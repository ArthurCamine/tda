import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import type { LocalReview } from "./protocol";
import {
	PublicationClientError,
	type PublicationReceiptView,
} from "./publication-client";
import {
	createPublicationRecovery,
	PENDING_MAX_AGE_MS,
} from "./publication-recovery";
const sourceId = `craig-${"a".repeat(64)}`;
const review: LocalReview = {
	sourceId,
	runId: "run-job-a1",
	baseTranscriptSha256: "b".repeat(64),
	draftRevision: 2,
	draftSha256: "c".repeat(64),
	status: "approved_local",
	approvalCurrent: true,
	approvedAt: "2026-09-21T12:01:00Z",
	createdAt: "2026-09-21T12:00:00Z",
	updatedAt: "2026-09-21T12:01:00Z",
	lineage: {
		profileId: "whisper-detailed",
		engine: "faster-whisper",
		model: "large-v3",
		modelRevision: null,
		device: "cuda",
		computeType: "float16",
		alignment: "native",
		executionLineage: {
			schemaVersion: "tda_execution_lineage_v1",
			companionVersion: "0.3.14",
			runtimeFamily: "whisper",
			runtimeVersion: "1.1.5",
			device: "cuda",
			computeType: "float16",
			gpu: {
				vendor: "NVIDIA",
				index: 0,
				model: "NVIDIA Test GPU",
				vramTotalBytes: 8 * 1024 ** 3,
				computeCapability: "8.9",
				driverVersion: "600.12",
			},
		},
		completedAt: "2026-09-21T11:59:00Z",
	},
	stats: {
		audioWorkSeconds: 60,
		processingSeconds: 12,
		sessionDurationSeconds: 60,
		rtf: 0.2,
		wordCount: 2,
		segmentCount: 1,
		trackCount: 1,
	},
	warnings: [],
	publicationTarget: {
		campaignSlug: "yuhara-main",
		sourceSessionId: "sessao-00001",
		jobId: "job-a",
		attempt: 1,
	},
	review: {
		reviewedSegments: 1,
		totalSegments: 1,
		reviewPercent: 100,
		editedSegments: 1,
		wordCount: 2,
		warningCount: 0,
	},
	segments: [
		{
			trackNumber: 1,
			segmentId: "1-0",
			start: 0,
			end: 1,
			text: "Olá mundo",
			speaker: "Alice",
			reviewed: true,
		},
	],
	sync: { status: "not_configured" },
};

function harness() {
	const records = new Map<string, string>();
	const storage = {
		get length() {
			return records.size;
		},
		key: (i: number) => [...records.keys()][i] ?? null,
		getItem: (k: string) => records.get(k) ?? null,
		setItem: (k: string, v: string) => {
			records.set(k, v);
		},
		removeItem: (k: string) => {
			records.delete(k);
		},
	};
	const current = vi.fn(async () => ({
		actorProfileId: "33333333-3333-4333-8333-333333333333",
		revisionId: null as string | null,
	}));
	const receipt = vi.fn(
		async (
			_review: LocalReview,
			_id: string,
			_expected: string | null,
		): Promise<PublicationReceiptView> => {
			throw new PublicationClientError("not_found");
		},
	);
	const now = vi.fn(() => 100000);
	let count = 0;
	const deps = {
		storage,
		current,
		receipt,
		now,
		uuid: () => `55555555-5555-4555-8555-${String(++count).padStart(12, "0")}`,
		digest: async (value: string) =>
			createHash("sha256").update(value).digest("hex"),
		lock: async <T>(_key: string, fn: () => Promise<T>) => fn(),
	};
	return { records, deps, create: () => createPublicationRecovery(deps) };
}
const committed = {
	receiptId: "receipt",
	revisionId: "revision",
	revisionNumber: 1,
	committedAt: "2026-09-26T12:00:00Z",
};
describe("durable publication recovery", () => {
	it("recovers the exact operation after lost POST/readback and a new client instance", async () => {
		const h = harness();
		const first = h.create();
		const confirm = await first.inspect(review);
		const publish = vi.fn(async () => {
			throw new PublicationClientError("unconfirmed");
		});
		await expect(first.execute(review, confirm, publish)).rejects.toMatchObject(
			{ code: "unconfirmed" },
		);
		expect(h.records.size).toBe(1);
		const pending = JSON.parse([...h.records.values()][0]);
		expect(JSON.stringify(pending)).not.toContain("Olá");
		expect(JSON.stringify(pending)).not.toContain("Alice");
		expect(Object.keys(pending)).not.toContain("segments");
		h.deps.current.mockResolvedValue({
			actorProfileId: confirm.current.actorProfileId,
			revisionId: "11111111-1111-4111-8111-111111111111",
		});
		h.deps.receipt.mockImplementation(async () => committed);
		const afterReload = await h.create().inspect(review);
		expect(afterReload.receipt).toEqual(committed);
		expect(h.records.size).toBe(0);
		expect(publish).toHaveBeenCalledTimes(1);
		expect(h.deps.receipt).toHaveBeenLastCalledWith(
			review,
			pending.operationId,
			null,
			confirm.current.actorProfileId,
		);
	});
	it.each(["draft", "run", "session"])(
		"blocks %s mismatch and requires explicit abandonment",
		async (kind) => {
			const h = harness();
			const api = h.create();
			const c = await api.inspect(review);
			await expect(
				api.execute(review, c, async () => {
					throw new PublicationClientError("unconfirmed");
				}),
			).rejects.toThrow();
			const changed =
				kind === "draft"
					? { ...review, draftSha256: "f".repeat(64) }
					: kind === "run"
						? { ...review, runId: "another-run" }
						: {
								...review,
								publicationTarget: {
									...review.publicationTarget!,
									sourceSessionId: "another-session",
								},
							};
			const mismatch = await h.create().inspect(changed);
			expect(mismatch.blocked).toBe("mismatch");
			const publish = vi.fn();
			await expect(
				api.execute(changed, mismatch, publish),
			).rejects.toMatchObject({ code: "pending_mismatch" });
			expect(publish).not.toHaveBeenCalled();
			await api.abandon(changed, mismatch);
			const next = await api.inspect(changed);
			await api.execute(changed, next, async () => committed);
			expect(h.records.size).toBe(0);
		},
	);
	it("preserves original expected current during unresolved retries", async () => {
		const h = harness();
		const api = h.create();
		const c = await api.inspect(review);
		const send = vi.fn(async () => {
			throw new PublicationClientError("unconfirmed");
		});
		await expect(api.execute(review, c, send)).rejects.toThrow();
		h.deps.current.mockResolvedValue({
			...c.current,
			revisionId: "11111111-1111-4111-8111-111111111111",
		});
		const retry = await h.create().inspect(review);
		expect(retry.current.revisionId).toBe(null);
		await expect(api.execute(review, retry, send)).rejects.toThrow();
		expect(send.mock.calls[1]).toEqual(send.mock.calls[0]);
	});
	it("isolates profiles and campaigns and rejects an actor switch at confirmation", async () => {
		const h = harness();
		const api = h.create();
		const c = await api.inspect(review);
		await expect(
			api.execute(review, c, async () => {
				throw new PublicationClientError("unconfirmed");
			}),
		).rejects.toThrow();
		const otherCampaign = {
			...review,
			publicationTarget: {
				...review.publicationTarget!,
				campaignSlug: "other",
			},
		};
		expect((await api.inspect(otherCampaign)).pending).toBeNull();
		h.deps.current.mockResolvedValue({
			actorProfileId: "44444444-4444-4444-8444-444444444444",
			revisionId: null,
		});
		expect((await api.inspect(review)).pending).toBeNull();
		const publish = vi.fn();
		await expect(api.execute(review, c, publish)).rejects.toMatchObject({
			code: "profile_changed",
		});
		expect(publish).not.toHaveBeenCalled();
		expect(h.records.size).toBe(1);
	});
	it("expires retries without silently dropping an unresolved operation", async () => {
		const h = harness();
		const api = h.create();
		const c = await api.inspect(review);
		await expect(
			api.execute(review, c, async () => {
				throw new PublicationClientError("unconfirmed");
			}),
		).rejects.toThrow();
		h.deps.now.mockReturnValue(100001 + PENDING_MAX_AGE_MS);
		const expired = await api.inspect(review);
		expect(expired.blocked).toBe("expired");
		expect(h.records.size).toBe(1);
		await expect(api.execute(review, expired, vi.fn())).rejects.toMatchObject({
			code: "pending_expired",
		});
	});
	it("fails closed before POST if storage cannot preserve the operation", async () => {
		const h = harness();
		const api = h.create();
		const c = await api.inspect(review);
		h.deps.storage.setItem = () => {
			throw new Error("quota");
		};
		const publish = vi.fn();
		await expect(api.execute(review, c, publish)).rejects.toMatchObject({
			code: "storage_unavailable",
		});
		expect(publish).not.toHaveBeenCalled();
	});
});
