import {
	prepareCanonicalPublication,
	UUID,
	SHA256,
} from "../../transcript-publication/canonical";
import type { LocalReview } from "./protocol";
import {
	PublicationClientError,
	publicationRequestBody,
	readApprovedPublicationReceipt,
	readCurrentPublication,
	type PublicationReceiptView,
} from "./publication-client";

const PREFIX = "tda.publication.pending.v1:";
export const PENDING_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
const LIMIT = 20;
export type PendingPublication = Readonly<{
	schemaVersion: 1;
	state: "unresolved";
	profileScope: string;
	campaignSlug: string;
	sourceSessionId: string;
	sourceId: string;
	runId: string;
	draftRevision: number;
	draftSha256: string;
	payloadSha256: string;
	operationId: string;
	expectedCurrentRevisionId: string | null;
	createdAt: number;
}>;
export type PublicationConfirmation = Readonly<{
	current: { actorProfileId: string; revisionId: string | null };
	pending: PendingPublication | null;
	blocked: "mismatch" | "expired" | null;
	receipt: PublicationReceiptView | null;
}>;
export class PublicationRecoveryError extends Error {
	constructor(
		readonly code:
			| "storage_unavailable"
			| "pending_mismatch"
			| "pending_expired"
			| "profile_changed",
	) {
		super(code);
	}
}
type StoragePort = Pick<
	Storage,
	"getItem" | "setItem" | "removeItem" | "key" | "length"
>;
type Dependencies = {
	storage: StoragePort;
	now: () => number;
	uuid: () => string;
	digest: (value: string) => Promise<string>;
	current: typeof readCurrentPublication;
	receipt: (
		review: LocalReview,
		operationId: string,
		expected: string | null,
		profileScope: string,
	) => Promise<PublicationReceiptView>;
	lock: <T>(key: string, action: () => Promise<T>) => Promise<T>;
};
const fields = [
	"schemaVersion",
	"state",
	"profileScope",
	"campaignSlug",
	"sourceSessionId",
	"sourceId",
	"runId",
	"draftRevision",
	"draftSha256",
	"payloadSha256",
	"operationId",
	"expectedCurrentRevisionId",
	"createdAt",
];

function key(profile: string, campaign: string) {
	return `${PREFIX}${profile}:${campaign}`;
}
function read(storage: StoragePort, scope: string): PendingPublication | null {
	try {
		const raw = storage.getItem(scope);
		if (raw === null) return null;
		if (raw.length > 2048) throw new Error();
		const value = JSON.parse(raw);
		if (
			!value ||
			typeof value !== "object" ||
			Array.isArray(value) ||
			Object.keys(value).length !== fields.length ||
			Object.keys(value).some((k) => !fields.includes(k)) ||
			fields
				.filter(
					(field) =>
						![
							"schemaVersion",
							"draftRevision",
							"createdAt",
							"expectedCurrentRevisionId",
						].includes(field),
				)
				.some((field) => typeof value[field] !== "string") ||
			value.schemaVersion !== 1 ||
			value.state !== "unresolved" ||
			!UUID.test(value.profileScope) ||
			!UUID.test(value.operationId) ||
			!/^[A-Za-z0-9_-]{1,128}$/u.test(value.campaignSlug) ||
			!/^[A-Za-z0-9_-]{1,160}$/u.test(value.sourceSessionId) ||
			!/^craig-[0-9a-f]{64}$/u.test(value.sourceId) ||
			!/^[A-Za-z0-9_-]{1,196}$/u.test(value.runId) ||
			!Number.isSafeInteger(value.draftRevision) ||
			value.draftRevision < 0 ||
			!SHA256.test(value.draftSha256) ||
			!SHA256.test(value.payloadSha256) ||
			(value.expectedCurrentRevisionId !== null &&
				!UUID.test(value.expectedCurrentRevisionId)) ||
			!Number.isSafeInteger(value.createdAt) ||
			value.createdAt < 0 ||
			key(value.profileScope, value.campaignSlug) !== scope
		)
			throw new Error();
		return value as PendingPublication;
	} catch {
		throw new PublicationRecoveryError("storage_unavailable");
	}
}
function write(
	storage: StoragePort,
	scope: string,
	pending: PendingPublication,
) {
	try {
		let count = 0;
		for (let i = 0; i < storage.length; i++)
			if (storage.key(i)?.startsWith(PREFIX)) count++;
		if (count >= LIMIT && storage.getItem(scope) === null) throw new Error();
		const raw = JSON.stringify(pending);
		if (raw.length > 2048) throw new Error();
		storage.setItem(scope, raw);
		if (storage.getItem(scope) !== raw) throw new Error();
	} catch {
		throw new PublicationRecoveryError("storage_unavailable");
	}
}
function remove(storage: StoragePort, scope: string, operationId: string) {
	try {
		if (read(storage, scope)?.operationId === operationId)
			storage.removeItem(scope);
	} catch {
		throw new PublicationRecoveryError("storage_unavailable");
	}
}
function same(
	pending: PendingPublication,
	identity: Awaited<ReturnType<typeof identityOf>>,
) {
	return (
		pending.sourceId === identity.sourceId &&
		pending.runId === identity.runId &&
		pending.sourceSessionId === identity.sourceSessionId &&
		pending.campaignSlug === identity.campaignSlug &&
		pending.draftRevision === identity.draftRevision &&
		pending.draftSha256 === identity.draftSha256 &&
		pending.payloadSha256 === identity.payloadSha256
	);
}
async function identityOf(review: LocalReview, digest: Dependencies["digest"]) {
	const parsed = prepareCanonicalPublication(
		JSON.stringify(
			publicationRequestBody(
				review,
				"00000000-0000-4000-8000-000000000000",
				null,
			),
		),
	);
	if (!parsed.ok || review.draftRevision === null)
		throw new PublicationClientError("invalid_payload");
	return {
		sourceId: review.sourceId,
		runId: review.runId,
		...parsed.value.target,
		draftRevision: review.draftRevision,
		draftSha256: parsed.value.draftSha256,
		payloadSha256: await digest(parsed.value.payloadJson),
	};
}
export function createPublicationRecovery(deps: Dependencies) {
	return {
		async inspect(review: LocalReview): Promise<PublicationConfirmation> {
			const current = await deps.current(review);
			const identity = await identityOf(review, deps.digest);
			const scope = key(current.actorProfileId, identity.campaignSlug);
			return deps.lock(scope, async () => {
				const pending = read(deps.storage, scope);
				if (!pending)
					return { current, pending: null, blocked: null, receipt: null };
				if (!same(pending, identity))
					return { current, pending, blocked: "mismatch", receipt: null };
				const expired =
					deps.now() - pending.createdAt > PENDING_MAX_AGE_MS ||
					pending.createdAt > deps.now();
				try {
					const receipt = await deps.receipt(
						review,
						pending.operationId,
						pending.expectedCurrentRevisionId,
						current.actorProfileId,
					);
					remove(deps.storage, scope, pending.operationId);
					return { current, pending: null, blocked: null, receipt };
				} catch (cause) {
					if (
						cause instanceof PublicationClientError &&
						["unauthenticated", "forbidden"].includes(cause.code)
					)
						throw cause;
					return {
						current: {
							...current,
							revisionId: pending.expectedCurrentRevisionId,
						},
						pending,
						blocked: expired ? "expired" : null,
						receipt: null,
					};
				}
			});
		},
		async execute(
			review: LocalReview,
			confirmation: PublicationConfirmation,
			publish: (
				review: LocalReview,
				operationId: string,
				expected: string | null,
				profileScope: string,
			) => Promise<PublicationReceiptView>,
		): Promise<PublicationReceiptView> {
			// Reauthorize immediately before every CTA, including retries after account changes.
			const current = await deps.current(review);
			if (current.actorProfileId !== confirmation.current.actorProfileId)
				throw new PublicationRecoveryError("profile_changed");
			const identity = await identityOf(review, deps.digest);
			const scope = key(current.actorProfileId, identity.campaignSlug);
			return deps.lock(scope, async () => {
				let pending = read(deps.storage, scope);
				if (pending && !same(pending, identity))
					throw new PublicationRecoveryError("pending_mismatch");
				if (
					pending &&
					(deps.now() - pending.createdAt > PENDING_MAX_AGE_MS ||
						pending.createdAt > deps.now())
				)
					throw new PublicationRecoveryError("pending_expired");
				if (
					confirmation.pending &&
					(!pending || pending.operationId !== confirmation.pending.operationId)
				)
					throw new PublicationRecoveryError("pending_mismatch");
				if (!pending && current.revisionId !== confirmation.current.revisionId)
					throw new PublicationClientError("stale_current");
				if (pending) {
					try {
						const receipt = await deps.receipt(
							review,
							pending.operationId,
							pending.expectedCurrentRevisionId,
							current.actorProfileId,
						);
						remove(deps.storage, scope, pending.operationId);
						return receipt;
					} catch (cause) {
						if (
							!(cause instanceof PublicationClientError) ||
							cause.code !== "not_found"
						)
							throw new PublicationClientError("unconfirmed");
					}
				} else {
					pending = {
						schemaVersion: 1,
						state: "unresolved",
						profileScope: current.actorProfileId,
						...identity,
						operationId: deps.uuid(),
						expectedCurrentRevisionId: confirmation.current.revisionId,
						createdAt: deps.now(),
					};
					write(deps.storage, scope, pending); // Durability must succeed before the network write.
				}
				try {
					const receipt = await publish(
						review,
						pending.operationId,
						pending.expectedCurrentRevisionId,
						current.actorProfileId,
					);
					remove(deps.storage, scope, pending.operationId);
					return receipt;
				} catch (cause) {
					// Auth/network/conflicting identity cannot prove an earlier request did not commit.
					if (
						cause instanceof PublicationClientError &&
						[
							"stale_current",
							"invalid_payload",
							"approved_review_required",
							"too_large",
						].includes(cause.code)
					)
						remove(deps.storage, scope, pending.operationId);
					throw cause;
				}
			});
		},
		async abandon(review: LocalReview, confirmation: PublicationConfirmation) {
			const current = await deps.current(review);
			if (current.actorProfileId !== confirmation.current.actorProfileId)
				throw new PublicationRecoveryError("profile_changed");
			if (!confirmation.pending || !review.publicationTarget) return;
			const scope = key(
				current.actorProfileId,
				review.publicationTarget.campaignSlug,
			);
			await deps.lock(scope, async () =>
				remove(deps.storage, scope, confirmation.pending!.operationId),
			);
		},
	};
}

export function browserPublicationRecovery() {
	try {
		if (!navigator.locks) throw new Error();
		return createPublicationRecovery({
			storage: window.localStorage,
			now: Date.now,
			uuid: () => crypto.randomUUID(),
			digest: async (value) =>
				Array.from(
					new Uint8Array(
						await crypto.subtle.digest(
							"SHA-256",
							new TextEncoder().encode(value),
						),
					),
					(b) => b.toString(16).padStart(2, "0"),
				).join(""),
			current: readCurrentPublication,
			receipt: (review, id, expected, profile) =>
				readApprovedPublicationReceipt(review, id, expected, fetch, profile),
			lock: (scope, action) => navigator.locks.request(scope, action),
		});
	} catch {
		throw new PublicationRecoveryError("storage_unavailable");
	}
}
