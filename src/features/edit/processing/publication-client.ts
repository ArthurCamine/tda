"use client";

import type { LocalReview } from "./protocol";
import {
	MAX_PUBLICATION_PAYLOAD_BYTES,
	prepareCanonicalPublication,
	type PublicationFailure,
} from "../../transcript-publication/canonical";

export type PublicationReceiptView = Readonly<{
	receiptId: string;
	revisionId: string;
	revisionNumber: number;
	committedAt: string;
}>;

export type PublicationPreflight = Readonly<{
	eligible: boolean;
	reason: PublicationFailure | null;
	payloadBytes: number | null;
	maxPayloadBytes: number;
}>;

const PREFLIGHT_OPERATION_ID = "00000000-0000-4000-8000-000000000000";

export class PublicationClientError extends Error {
	constructor(
		readonly code:
			| "unauthenticated"
			| "forbidden"
			| "publish_capability_undefined"
			| "invalid_payload"
			| "approved_review_required"
			| "too_large"
			| "not_found"
			| "conflict"
			| "stale_current"
			| "dependency_unavailable"
			| "unconfirmed",
	) {
		super(code);
		this.name = "PublicationClientError";
	}
}

type Transport = (
	input: string | URL | Request,
	init?: RequestInit,
) => Promise<Response>;

export function publicationRequestBody(review: LocalReview, operationId: string, expectedCurrentRevisionId: string | null, expectedActorProfileId?: string) {
	const target = review.publicationTarget;
	if (!target) throw new PublicationClientError("invalid_payload");
	if (review.persistence === "ephemeral_base" || review.draftSha256 === null || review.draftRevision === null)
		throw new PublicationClientError("approved_review_required");
	if (review.status !== "approved_local")
		throw new PublicationClientError("approved_review_required");
	return {
		schemaVersion: "tda_transcript_publication_request_v1",
		operationId,
		expectedCurrentRevisionId,
		...(expectedActorProfileId === undefined ? {} : { expectedActorProfileId }),
		binding: {
			schemaVersion: "tda_publication_target_v1",
			campaignSlug: target.campaignSlug,
			sourceSessionId: target.sourceSessionId,
			sourceId: review.sourceId,
			runId: review.runId,
			jobId: target.jobId,
			attempt: target.attempt,
			transcriptSha256: review.baseTranscriptSha256,
		},
		review: {
			sourceId: review.sourceId,
			runId: review.runId,
			baseTranscriptSha256: review.baseTranscriptSha256,
			draftRevision: review.draftRevision,
			draftSha256: review.draftSha256,
			status: review.status,
			lineage: {
				profileId: review.lineage.profileId,
				engine: review.lineage.engine,
				model: review.lineage.model,
				modelRevision: review.lineage.modelRevision,
				device: review.lineage.device,
				computeType: review.lineage.computeType,
				alignment: review.lineage.alignment,
				completedAt: review.lineage.completedAt,
			},
			warnings: review.warnings,
			...(review.warningSummary
				? { warningSummary: review.warningSummary }
				: {}),
			review: review.review,
			segments: review.segments,
		},
	};
}

export function preflightApprovedLocalReview(
	review: LocalReview,
): PublicationPreflight {
	let raw: string;
	try {
		raw = JSON.stringify(publicationRequestBody(review, PREFLIGHT_OPERATION_ID, null));
	} catch (cause) {
		const reason =
			cause instanceof PublicationClientError
				? cause.code === "approved_review_required"
					? "approved_review_required"
					: "invalid_payload"
				: "invalid_payload";
		return {
			eligible: false,
			reason,
			payloadBytes: null,
			maxPayloadBytes: MAX_PUBLICATION_PAYLOAD_BYTES,
		};
	}
	const prepared = prepareCanonicalPublication(raw);
	if (!prepared.ok) {
		return {
			eligible: false,
			reason: prepared.reason,
			payloadBytes: prepared.payloadBytes ?? null,
			maxPayloadBytes: MAX_PUBLICATION_PAYLOAD_BYTES,
		};
	}
	return {
		eligible: true,
		reason: null,
		payloadBytes: prepared.value.payloadBytes,
		maxPayloadBytes: MAX_PUBLICATION_PAYLOAD_BYTES,
	};
}

function parseFailure(value: unknown): PublicationClientError["code"] {
	if (!value || typeof value !== "object") return "dependency_unavailable";
	const reason = (value as { reason?: unknown }).reason;
	return typeof reason === "string" &&
		[
			"unauthenticated",
			"forbidden",
			"publish_capability_undefined",
			"invalid_payload",
			"approved_review_required",
			"too_large",
			"not_found",
			"conflict",
			"stale_current",
			"dependency_unavailable",
		].includes(reason)
		? (reason as PublicationClientError["code"])
		: "dependency_unavailable";
}

async function parseReceipt(
	response: Response,
	expected: LocalReview,
	operationId: string,
): Promise<PublicationReceiptView> {
	let body: unknown;
	try {
		body = await response.json();
	} catch {
		throw new PublicationClientError("dependency_unavailable");
	}
	if (!response.ok) throw new PublicationClientError(parseFailure(body));
	if (!body || typeof body !== "object")
		throw new PublicationClientError("dependency_unavailable");
	const receipt = (body as { receipt?: unknown }).receipt;
	if (!receipt || typeof receipt !== "object")
		throw new PublicationClientError("dependency_unavailable");
	const value = receipt as Record<string, unknown>;
	if (
		value.schemaVersion !== "tda_transcript_publication_receipt_v1" ||
		value.status !== "committed" ||
		!/^([0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/u.test(
			String(value.receiptId),
		) ||
		typeof value.receiptId !== "string" ||
		typeof value.revisionId !== "string" ||
		!Number.isSafeInteger(value.revisionNumber) ||
		(value.revisionNumber as number) < 1 ||
		typeof value.committedAt !== "string" ||
		!Number.isFinite(Date.parse(value.committedAt)) ||
		typeof value.operationId !== "string" ||
		typeof value.sourceId !== "string" ||
		typeof value.runId !== "string" ||
		typeof value.baseTranscriptSha256 !== "string" ||
		typeof value.draftSha256 !== "string" ||
		!Number.isSafeInteger(value.segmentCount) ||
		!Number.isSafeInteger(value.wordCount)
	)
		throw new PublicationClientError("dependency_unavailable");
	if (
		value.operationId !== operationId ||
		value.sourceId !== expected.sourceId ||
		value.runId !== expected.runId ||
		value.baseTranscriptSha256 !== expected.baseTranscriptSha256 ||
		value.draftSha256 !== expected.draftSha256 ||
		value.segmentCount !== expected.segments.length ||
		value.wordCount !== expected.review.wordCount
	)
		throw new PublicationClientError("conflict");
	return {
		receiptId: value.receiptId,
		revisionId: value.revisionId,
		revisionNumber: value.revisionNumber as number,
		committedAt: value.committedAt,
	};
}

async function post(
	path: string,
	body: string,
	transport: Transport,
): Promise<Response> {
	return transport(path, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		credentials: "same-origin",
		cache: "no-store",
		redirect: "error",
		body,
	});
}

export async function publishApprovedLocalReview(
	review: LocalReview,
	operationId: string,
	expectedCurrentRevisionId: string | null,
	transport: Transport = fetch,
	expectedActorProfileId?: string,
): Promise<PublicationReceiptView> {
	const body = JSON.stringify(publicationRequestBody(review, operationId, expectedCurrentRevisionId, expectedActorProfileId));
	try {
		return await parseReceipt(
			await post("/api/transcript-publications", body, transport),
			review,
			operationId,
		);
	} catch (cause) {
		if (
			cause instanceof PublicationClientError &&
			cause.code !== "dependency_unavailable"
		)
			throw cause;
	}

	// A network failure after the POST is ambiguous: the atomic commit may have
	// succeeded. Read back the same operation instead of creating a new revision.
	try {
		return await parseReceipt(
			await post("/api/transcript-publications/receipt", body, transport),
			review,
			operationId,
		);
	} catch (cause) {
		if (
			cause instanceof PublicationClientError &&
			cause.code !== "not_found" &&
			cause.code !== "dependency_unavailable"
		)
			throw cause;
		throw new PublicationClientError("unconfirmed");
	}
}

export async function readCurrentPublication(review: LocalReview, transport: Transport = fetch): Promise<{ actorProfileId: string; revisionId: string | null }> {
 const target = review.publicationTarget;
 if (!target) throw new PublicationClientError("invalid_payload");
 const response = await post("/api/transcript-publications/current", JSON.stringify({ campaignSlug: target.campaignSlug, sourceSessionId: target.sourceSessionId }), transport);
 const body = await response.json();
 if (!response.ok) throw new PublicationClientError(parseFailure(body));
 const current = body?.current;
 const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
 if (body?.ok !== true || !current || typeof current.actorProfileId !== "string" || !uuid.test(current.actorProfileId) || (current.revisionId !== null && (typeof current.revisionId !== "string" || !uuid.test(current.revisionId)))) throw new PublicationClientError("dependency_unavailable");
 return { actorProfileId: current.actorProfileId, revisionId: current.revisionId };
}

export async function readApprovedPublicationReceipt(review: LocalReview, operationId: string, expectedCurrentRevisionId: string | null, transport: Transport = fetch, expectedActorProfileId?: string): Promise<PublicationReceiptView> {
 return parseReceipt(await post("/api/transcript-publications/receipt", JSON.stringify(publicationRequestBody(review, operationId, expectedCurrentRevisionId, expectedActorProfileId)), transport), review, operationId);
}
