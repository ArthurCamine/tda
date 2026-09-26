import type {
	LocalReview,
	LocalReviewSegment,
	LocalReviewStatus,
} from "./protocol";

const fields = ["text", "speaker", "reviewed"] as const;
type Field = (typeof fields)[number];
export type ReviewCollision = {
	id: string;
	segmentKey: string;
	field: Field | "status";
	local: string | boolean;
	remote: string | boolean;
	start: number | null;
};
export type ReviewRebase = {
	latest: LocalReview;
	working: readonly LocalReviewSegment[];
	segments: readonly LocalReviewSegment[];
	status: LocalReviewStatus;
	collisions: readonly ReviewCollision[];
	localChanges: number;
};
const keyOf = (segment: LocalReviewSegment) =>
	JSON.stringify([segment.trackNumber, segment.segmentId]);
function index(segments: readonly LocalReviewSegment[]) {
	const map = new Map(segments.map((segment) => [keyOf(segment), segment]));
	if (map.size !== segments.length) throw new Error("REBASE_IDENTITY_MISMATCH");
	return map;
}
const unapproved = (status: LocalReviewStatus): LocalReviewStatus =>
	status === "approved_local" ? "reviewed" : status;

export function prepareReviewRebase(
	base: LocalReview,
	working: readonly LocalReviewSegment[],
	status: LocalReviewStatus,
	latest: LocalReview,
): ReviewRebase {
	if (
		base.sourceId !== latest.sourceId ||
		base.runId !== latest.runId ||
		base.baseTranscriptSha256 !== latest.baseTranscriptSha256 ||
		latest.snapshotContract !== "tda_local_review_cas_v1"
	)
		throw new Error("REBASE_IDENTITY_MISMATCH");
	const baseline = index(base.segments);
	const local = index(working);
	const remote = index(latest.segments);
	if (baseline.size !== local.size || baseline.size !== remote.size)
		throw new Error("REBASE_IDENTITY_MISMATCH");
	const collisions: ReviewCollision[] = [];
	let localChanges = 0;
	const segments = working.map((original) => {
		const key = keyOf(original),
			before = baseline.get(key),
			saved = remote.get(key);
		if (
			!before ||
			!saved ||
			original.start !== before.start ||
			original.end !== before.end ||
			saved.start !== before.start ||
			saved.end !== before.end
		)
			throw new Error("REBASE_IDENTITY_MISMATCH");
		const result = { ...saved };
		for (const field of fields) {
			if (original[field] === before[field]) continue;
			localChanges++;
			if (saved[field] !== before[field] && saved[field] !== original[field]) {
				collisions.push({
					id: JSON.stringify([key, field]),
					segmentKey: key,
					field,
					local: original[field],
					remote: saved[field],
					start: original.start,
				});
			} else if (field === "reviewed") result.reviewed = original.reviewed;
			else result[field] = original[field];
		}
		return result;
	});
	const baseStatus = unapproved(base.status),
		localStatus = unapproved(status),
		remoteStatus = unapproved(latest.status);
	let mergedStatus = remoteStatus;
	if (localStatus !== baseStatus) {
		localChanges++;
		if (remoteStatus !== baseStatus && remoteStatus !== localStatus)
			collisions.push({
				id: "status",
				segmentKey: "",
				field: "status",
				local: localStatus,
				remote: remoteStatus,
				start: null,
			});
		else mergedStatus = localStatus;
	}
	return {
		latest,
		working,
		segments,
		status: mergedStatus,
		collisions,
		localChanges,
	};
}

export function resolveReviewRebase(
	plan: ReviewRebase,
	choices: Readonly<Record<string, "local" | "remote">>,
) {
	let status = plan.status;
	const changes = new Map<string, Partial<LocalReviewSegment>>();
	for (const collision of plan.collisions) {
		const choice = choices[collision.id];
		if (choice !== "local" && choice !== "remote")
			throw new Error("REBASE_UNRESOLVED");
		const value = collision[choice];
		if (collision.field === "status") {
			status = unapproved(value as LocalReviewStatus);
			continue;
		}
		const patch = changes.get(collision.segmentKey) ?? {};
		if (collision.field === "reviewed") patch.reviewed = value as boolean;
		else patch[collision.field] = value as string;
		changes.set(collision.segmentKey, patch);
	}
	return {
		status: unapproved(status),
		segments: plan.segments.map((segment) => {
			const patch = changes.get(keyOf(segment));
			return patch ? { ...segment, ...patch } : segment;
		}),
	};
}
