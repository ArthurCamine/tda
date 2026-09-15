export const TRANSCRIPT_REVIEW_STATUSES = [
	"pending",
	"approved",
	"needs_review",
	"discarded",
] as const;

export type TranscriptReviewStatus = (typeof TRANSCRIPT_REVIEW_STATUSES)[number];

export const TRANSCRIPT_EDIT_LIMITS = {
	text: 10_000,
	speaker: 160,
} as const;

export type TranscriptEditInput = Readonly<{
	text: unknown;
	speaker: unknown;
	reviewStatus: unknown;
}>;

export type PreparedTranscriptEdit = Readonly<{
	text: string;
	speaker: string;
	reviewStatus: TranscriptReviewStatus;
	needsReview: boolean;
	textChars: number;
	textWords: number;
}>;

export type TranscriptEditIssue =
	| "text_required"
	| "text_too_long"
	| "speaker_required"
	| "speaker_too_long"
	| "review_status_invalid";

export type PrepareTranscriptEditResult =
	| Readonly<{ ok: true; value: PreparedTranscriptEdit }>
	| Readonly<{ ok: false; issues: readonly TranscriptEditIssue[] }>;

function cleanString(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

export function transcriptSpeakerIdentityChanged(
	previousSpeaker: unknown,
	nextSpeaker: unknown,
): boolean {
	return cleanString(previousSpeaker) !== cleanString(nextSpeaker);
}

export function normalizeTranscriptReviewStatus(
	value: unknown,
): TranscriptReviewStatus | null {
	const normalized = cleanString(value);
	const legacyCompatible = normalized === "unreviewed" ? "pending" : normalized;

	return TRANSCRIPT_REVIEW_STATUSES.includes(
		legacyCompatible as TranscriptReviewStatus,
	)
		? (legacyCompatible as TranscriptReviewStatus)
		: null;
}

/**
 * Compatibility projection for new writes only.
 * `review_status` is the canonical read state; historical `needs_review` values
 * are audit/compatibility data and must not be used to reconstruct that state.
 */
export function transcriptStatusNeedsReview(
	status: TranscriptReviewStatus,
): boolean {
	return status === "pending" || status === "needs_review";
}

export function countTranscriptCharacters(text: string): number {
	return Array.from(text).length;
}

export function countTranscriptWords(text: string): number {
	const normalized = text.trim();
	return normalized ? normalized.split(/\s+/u).length : 0;
}

export function prepareTranscriptEdit(
	input: TranscriptEditInput,
): PrepareTranscriptEditResult {
	const text = cleanString(input.text);
	const speaker = cleanString(input.speaker);
	const reviewStatus = normalizeTranscriptReviewStatus(input.reviewStatus);
	const textChars = countTranscriptCharacters(text);
	const speakerChars = countTranscriptCharacters(speaker);
	const issues: TranscriptEditIssue[] = [];

	if (!text) issues.push("text_required");
	if (textChars > TRANSCRIPT_EDIT_LIMITS.text) issues.push("text_too_long");
	if (!speaker) issues.push("speaker_required");
	if (speakerChars > TRANSCRIPT_EDIT_LIMITS.speaker) {
		issues.push("speaker_too_long");
	}
	if (!reviewStatus) issues.push("review_status_invalid");

	if (issues.length || !reviewStatus) {
		return { ok: false, issues };
	}

	return {
		ok: true,
		value: {
			text,
			speaker,
			reviewStatus,
			needsReview: transcriptStatusNeedsReview(reviewStatus),
			textChars,
			textWords: countTranscriptWords(text),
		},
	};
}