import { describe, expect, it } from "vitest";
import type { LocalReview, LocalReviewSegment } from "./protocol";
import { prepareReviewRebase, resolveReviewRebase } from "./review-rebase";

function segment(id: string): LocalReviewSegment {
	return {
		trackNumber: 1,
		segmentId: id,
		start: 0,
		end: 1,
		text: "Base",
		speaker: "Alex",
		reviewed: false,
	};
}
function review(
	segments: readonly LocalReviewSegment[],
	revision = 1,
): LocalReview {
	return {
		sourceId: "source",
		runId: "run",
		baseTranscriptSha256: "a".repeat(64),
		snapshotContract: "tda_local_review_cas_v1",
		status: "draft",
		segments,
		draftRevision: revision,
		draftSha256: String(revision).repeat(64),
	} as LocalReview;
}

describe("three-way local review recovery", () => {
	it("merges by field and identity even when array order differs", () => {
		const base = review([segment("a"), segment("b")]);
		const working = [
			{ ...base.segments[0], speaker: "Novo" },
			base.segments[1],
		];
		const latest = review(
			[base.segments[1], { ...base.segments[0], text: "Remote" }],
			2,
		);
		const plan = prepareReviewRebase(base, working, "draft", latest);
		expect(plan.collisions).toHaveLength(0);
		const resolved = resolveReviewRebase(plan, {});
		expect(resolved.segments[0]).toEqual({
			...base.segments[0],
			text: "Remote",
			speaker: "Novo",
		});
		expect(resolved.segments[1]).toEqual(base.segments[1]);
		expect(plan.latest.draftRevision).toBe(2);
	});
	it("accepts convergent edits and requires a decision for only true collisions", () => {
		const base = review([segment("a"), segment("b")]);
		const working = base.segments.map((item) => ({ ...item, text: "Local" }));
		const latest = review(
			[
				{ ...base.segments[0], text: "Local" },
				{ ...base.segments[1], text: "Remote" },
			],
			2,
		);
		const plan = prepareReviewRebase(base, working, "approved_local", latest);
		expect(plan.collisions).toHaveLength(1);
		expect(() => resolveReviewRebase(plan, {})).toThrow("REBASE_UNRESOLVED");
		const result = resolveReviewRebase(plan, {
			[plan.collisions[0].id]: "local",
		});
		expect(result.segments[1].text).toBe("Local");
		expect(result.status).toBe("reviewed");
	});
	it("does not inherit approval from the remote draft", () => {
		const base = review([segment("a")]);
		const latest = {
			...review(base.segments, 2),
			status: "approved_local" as const,
		};
		const plan = prepareReviewRebase(
			base,
			[{ ...base.segments[0], reviewed: true }],
			"draft",
			latest,
		);
		expect(resolveReviewRebase(plan, {}).status).toBe("reviewed");
		expect(resolveReviewRebase(plan, {}).segments[0].reviewed).toBe(true);
	});
	it("fails closed on missing, extra, duplicate, moved or foreign segments", () => {
		const base = review([segment("a")]);
		for (const segments of [
			[],
			[segment("b")],
			[segment("a"), segment("b")],
			[segment("a"), segment("a")],
			[{ ...segment("a"), start: 0.5 }],
		])
			expect(() =>
				prepareReviewRebase(base, base.segments, "draft", review(segments, 2)),
			).toThrow("REBASE_IDENTITY_MISMATCH");
		expect(() =>
			prepareReviewRebase(base, base.segments, "draft", {
				...base,
				runId: "other",
			}),
		).toThrow("REBASE_IDENTITY_MISMATCH");
	});
	it.each([7531, 100000])(
		"bounds collision output for %i segments",
		(count) => {
			const base = review(
				Array.from({ length: count }, (_, i) => segment(`${i}`)),
			);
			const working = base.segments.map((item, i) =>
				i < 3000 ? { ...item, speaker: "Local" } : item,
			);
			const latest = review(
				base.segments.map((item, i) =>
					i < 3 ? { ...item, speaker: "Remote" } : item,
				),
				2,
			);
			const plan = prepareReviewRebase(base, working, "draft", latest);
			expect(plan.localChanges).toBe(3000);
			expect(plan.collisions).toHaveLength(3);
			const result = resolveReviewRebase(
				plan,
				Object.fromEntries(plan.collisions.map((item) => [item.id, "remote"])),
			);
			expect(
				result.segments.filter((item) => item.speaker === "Local"),
			).toHaveLength(2997);
		},
	);
});
