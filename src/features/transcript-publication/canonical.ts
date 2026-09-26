import { countWordsV1, isReviewStringV1 } from "../transcript-review/text-contract";

export const PUBLICATION_REQUEST_VERSION =
	"tda_transcript_publication_request_v1" as const;
export const PUBLICATION_PAYLOAD_VERSION =
	"tda_transcript_publication_v1" as const;
export const PUBLICATION_RECEIPT_VERSION =
	"tda_transcript_publication_receipt_v1" as const;
export const MAX_PUBLICATION_REQUEST_BYTES = 34 * 1024 * 1024;
export const MAX_PUBLICATION_PAYLOAD_BYTES = 32 * 1024 * 1024;
export const MAX_PUBLICATION_SEGMENTS = 100_000;

export const UUID =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
export const SHA256 = /^[0-9a-f]{64}$/u;
const IDENTIFIER = /^[A-Za-z0-9_-]{1,160}$/u;
const SOURCE_ID = /^craig-[0-9a-f]{64}$/u;
const RUN_ID = /^[A-Za-z0-9_-]{1,196}$/u;

export type PublicationFailure =
	| "unauthenticated"
	| "forbidden"
	| "publish_capability_undefined"
	| "invalid_payload"
	| "approved_review_required"
	| "too_large"
	| "not_found"
	| "conflict"
	| "stale_current"
	| "dependency_unavailable";

export type PublicationTarget = Readonly<{
	campaignSlug: string;
	sourceSessionId: string;
}>;

export type CanonicalPreparedPublication = Readonly<{
	operationId: string;
	expectedCurrentRevisionId: string | null;
	expectedActorProfileId?: string;
	target: PublicationTarget;
	sourceId: string;
	runId: string;
	baseTranscriptSha256: string;
	draftSha256: string;
	payloadJson: string;
	payloadBytes: number;
	segmentCount: number;
}>;

export type PublicationReceipt = Readonly<{
	schemaVersion: typeof PUBLICATION_RECEIPT_VERSION;
	status: "committed";
	receiptId: string;
	campaignId: string;
	sessionId: string;
	revisionId: string;
	revisionNumber: number;
	operationId: string;
	sourceId: string;
	runId: string;
	baseTranscriptSha256: string;
	draftSha256: string;
	payloadSha256: string;
	segmentCount: number;
	wordCount: number;
	committedAt: string;
}>;

export type PublicationResult =
	| Readonly<{ ok: true; receipt: PublicationReceipt }>
	| Readonly<{ ok: false; reason: PublicationFailure }>;

export type CanonicalPreparePublicationResult =
	| Readonly<{ ok: true; value: CanonicalPreparedPublication }>
	| Readonly<{
			ok: false;
			reason: PublicationFailure;
			payloadBytes?: number;
	  }>;

function record(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function exactKeys(
	value: Record<string, unknown>,
	keys: readonly string[],
): boolean {
	const actual = Object.keys(value);
	return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

function text(
	value: unknown,
	max: number,
	pattern?: RegExp,
): string | null {
	if (typeof value !== "string" || value.length < 1 || value.length > max)
		return null;
	if (pattern && !pattern.test(value)) return null;
	return value;
}

function nullableText(value: unknown, max: number): string | null | undefined {
	if (value === null) return null;
	if (typeof value !== "string" || value.length > max) return undefined;
	return value;
}

function integer(value: unknown, min: number, max: number): number | null {
	return Number.isSafeInteger(value) &&
		(value as number) >= min &&
		(value as number) <= max
		? (value as number)
		: null;
}

function finite(value: unknown, min: number, max: number): number | null {
	return typeof value === "number" &&
		Number.isFinite(value) &&
		value >= min &&
		value <= max
		? value
		: null;
}

function utf8Bytes(value: string): number {
	return new TextEncoder().encode(value).byteLength;
}

export function prepareCanonicalPublication(raw: string): CanonicalPreparePublicationResult {
	if (utf8Bytes(raw) > MAX_PUBLICATION_REQUEST_BYTES)
		return { ok: false, reason: "too_large" };
	let input: unknown;
	try {
		input = JSON.parse(raw);
	} catch {
		return { ok: false, reason: "invalid_payload" };
	}
	const root = record(input);
	if (
		!root ||
		!exactKeys(root, ["schemaVersion", "operationId", "expectedCurrentRevisionId", "binding", "review", ...(root.expectedActorProfileId === undefined ? [] : ["expectedActorProfileId"])]) ||
		root.schemaVersion !== PUBLICATION_REQUEST_VERSION
	)
		return { ok: false, reason: "invalid_payload" };

	const operationId = text(root.operationId, 36, UUID);
	if (root.expectedActorProfileId !== undefined && !text(root.expectedActorProfileId, 36, UUID)) return { ok: false, reason: "invalid_payload" };
	const expectedCurrentRevisionId = root.expectedCurrentRevisionId === null ? null : text(root.expectedCurrentRevisionId, 36, UUID);
	if (root.expectedCurrentRevisionId !== null && expectedCurrentRevisionId === null) return { ok: false, reason: "invalid_payload" };
	const binding = record(root.binding);
	const review = record(root.review);
	if (
		!operationId ||
		!binding ||
		!review ||
		!exactKeys(binding, [
			"schemaVersion",
			"campaignSlug",
			"sourceSessionId",
			"sourceId",
			"runId",
			"jobId",
			"attempt",
			"transcriptSha256",
		]) ||
		binding.schemaVersion !== "tda_publication_target_v1"
	)
		return { ok: false, reason: "invalid_payload" };

	const campaignSlug = text(binding.campaignSlug, 128, IDENTIFIER);
	const sourceSessionId = text(binding.sourceSessionId, 160, IDENTIFIER);
	const sourceId = text(binding.sourceId, 70, SOURCE_ID);
	const runId = text(binding.runId, 196, RUN_ID);
	const jobId = text(binding.jobId, 128, IDENTIFIER);
	const attempt = integer(binding.attempt, 1, 1_000_000);
	const bindingTranscriptSha = text(binding.transcriptSha256, 64, SHA256);
	if (
		!campaignSlug ||
		!sourceSessionId ||
		!sourceId ||
		!runId ||
		!jobId ||
		attempt === null ||
		!bindingTranscriptSha
	)
		return { ok: false, reason: "invalid_payload" };

	if (
		!exactKeys(review, [
			"sourceId",
			"runId",
			"baseTranscriptSha256",
			"draftRevision",
			"draftSha256",
			"status",
			"lineage",
			"warnings",
			"review",
			"segments",
			...(review.warningSummary === undefined ? [] : ["warningSummary"]),
		])
	)
		return { ok: false, reason: "invalid_payload" };

	if (review.status !== "approved_local")
		return { ok: false, reason: "approved_review_required" };

	const reviewSourceId = text(review.sourceId, 70, SOURCE_ID);
	const reviewRunId = text(review.runId, 196, RUN_ID);
	const baseTranscriptSha256 = text(review.baseTranscriptSha256, 64, SHA256);
	const draftSha256 = text(review.draftSha256, 64, SHA256);
	const draftRevision = integer(review.draftRevision, 0, 999_999_999_999);
	if (
		!reviewSourceId ||
		!reviewRunId ||
		!baseTranscriptSha256 ||
		!draftSha256 ||
		draftRevision === null ||
		reviewSourceId !== sourceId ||
		reviewRunId !== runId ||
		baseTranscriptSha256 !== bindingTranscriptSha
	)
		return { ok: false, reason: "invalid_payload" };

	const lineage = record(review.lineage);
	const summary = record(review.review);
	const warnings = Array.isArray(review.warnings) ? review.warnings : null;
	const segments = Array.isArray(review.segments) ? review.segments : null;
	if (
		!lineage ||
		!summary ||
		!warnings ||
		!segments ||
		segments.length < 1 ||
		segments.length > MAX_PUBLICATION_SEGMENTS
	)
		return { ok: false, reason: "invalid_payload" };

	if (
		!exactKeys(lineage, [
			"profileId",
			"engine",
			"model",
			"modelRevision",
			"device",
			"computeType",
			"alignment",
			"completedAt",
		])
	)
		return { ok: false, reason: "invalid_payload" };
	const profileId = text(lineage.profileId, 64);
	const engine = nullableText(lineage.engine, 64);
	const model = nullableText(lineage.model, 256);
	const modelRevision = nullableText(lineage.modelRevision, 256);
	const device = nullableText(lineage.device, 64);
	const computeType = nullableText(lineage.computeType, 64);
	const alignment = nullableText(lineage.alignment, 64);
	const completedAt = nullableText(lineage.completedAt, 128);
	if (
		!profileId ||
		engine === undefined ||
		model === undefined ||
		modelRevision === undefined ||
		device === undefined ||
		computeType === undefined ||
		alignment === undefined ||
		completedAt === undefined
	)
		return { ok: false, reason: "invalid_payload" };

	if (
		!exactKeys(summary, [
			"reviewedSegments",
			"totalSegments",
			"reviewPercent",
			"editedSegments",
			"wordCount",
			"warningCount",
		])
	)
		return { ok: false, reason: "invalid_payload" };
	const reviewedSegments = integer(
		summary.reviewedSegments,
		0,
		MAX_PUBLICATION_SEGMENTS,
	);
	const totalSegments = integer(
		summary.totalSegments,
		1,
		MAX_PUBLICATION_SEGMENTS,
	);
	const wordCount = integer(summary.wordCount, 0, 999_999_999);
	const warningCount = integer(summary.warningCount, 0, 999_999_999);
	if (
		reviewedSegments === null ||
		totalSegments === null ||
		wordCount === null ||
		warningCount === null ||
		totalSegments !== segments.length ||
		reviewedSegments > totalSegments
	)
		return { ok: false, reason: "invalid_payload" };

	const warningSummary = review.warningSummary === undefined ? null : record(review.warningSummary);
	if (review.warningSummary !== undefined && (!warningSummary ||
		!exactKeys(warningSummary, ["totalCount", "displayedCount", "truncated"]) ||
		warningSummary.totalCount !== warningCount || warningSummary.displayedCount !== warnings.length ||
		warningSummary.displayedCount !== Math.min(warningCount, 1000) ||
		warningSummary.truncated !== (warningCount > warnings.length)))
		return { ok: false, reason: "invalid_payload" };
	if (
		(!warningSummary && warnings.length !== warningCount) || warnings.length > 1000 ||
		warnings.some(
			(value) => typeof value !== "string" || value.length > 1024,
		)
	)
		return { ok: false, reason: "invalid_payload" };

	const seen = new Set<string>();
	let computedReviewed = 0;
	let computedWords = 0;
	const canonicalSegments: Array<{
		track_number: number; segment_id: string; start: number; end: number;
		text: string; speaker: string; reviewed: boolean;
	}> = [];
	for (const rawSegment of segments) {
		const segment = record(rawSegment);
		if (
			!segment ||
			!exactKeys(segment, [
				"trackNumber",
				"segmentId",
				"start",
				"end",
				"text",
				"speaker",
				"reviewed",
			])
		)
			return { ok: false, reason: "invalid_payload" };
		const trackNumber = integer(segment.trackNumber, 1, 9999);
		const segmentId = text(segment.segmentId, 256);
		const start = finite(segment.start, 0, 604800);
		const end = finite(segment.end, 0, 604800);
		const segmentText = isReviewStringV1(segment.text, "text") ? segment.text : null;
		const speaker = isReviewStringV1(segment.speaker, "speaker") ? segment.speaker : null;
		if (
			trackNumber === null ||
			!segmentId ||
			start === null ||
			end === null ||
			end < start ||
			segmentText === null ||
			speaker === null ||
			typeof segment.reviewed !== "boolean"
		)
			return { ok: false, reason: "invalid_payload" };
		const identity = `${trackNumber}\u0000${segmentId}`;
		if (seen.has(identity)) return { ok: false, reason: "invalid_payload" };
		seen.add(identity);
		if (segment.reviewed) computedReviewed += 1;
		computedWords += countWordsV1(segmentText);
		canonicalSegments.push({
			track_number: trackNumber,
			segment_id: segmentId,
			start,
			end,
			text: segmentText,
			speaker,
			reviewed: segment.reviewed,
		});
	}
	if (
		computedReviewed !== reviewedSegments ||
		computedWords !== wordCount
	)
		return { ok: false, reason: "invalid_payload" };

	// Total order over immutable fields; independent of presentation and locale.
	canonicalSegments.sort((a, b) => a.track_number - b.track_number || a.start - b.start || a.end - b.end ||
		(a.segment_id < b.segment_id ? -1 : a.segment_id > b.segment_id ? 1 : 0));
	const payload = {
		schema_version: PUBLICATION_PAYLOAD_VERSION,
		source_id: sourceId,
		run_id: runId,
		base_transcript_sha256: baseTranscriptSha256,
		draft_sha256: draftSha256,
		lineage: {
			profile_id: profileId,
			engine,
			model,
			model_revision: modelRevision,
			device,
			compute_type: computeType,
			alignment,
			completed_at: completedAt,
		},
		review: {
			status: "approved_local",
			draft_revision: draftRevision,
			reviewed_segments: reviewedSegments,
			total_segments: totalSegments,
			warning_count: warningCount,
			word_count: wordCount,
		},
		segments: canonicalSegments,
	};
	const payloadJson = JSON.stringify(payload);
	const payloadBytes = utf8Bytes(payloadJson);
	if (payloadBytes > MAX_PUBLICATION_PAYLOAD_BYTES)
		return { ok: false, reason: "too_large", payloadBytes };

	return {
		ok: true,
		value: {
			operationId,
			expectedCurrentRevisionId,
			...(root.expectedActorProfileId === undefined ? {} : { expectedActorProfileId: root.expectedActorProfileId as string }),
			target: { campaignSlug, sourceSessionId },
			sourceId,
			runId,
			baseTranscriptSha256,
			draftSha256,
			payloadJson,
			payloadBytes,
			segmentCount: canonicalSegments.length,
		},
	};
}
