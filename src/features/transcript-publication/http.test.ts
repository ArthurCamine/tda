import { describe, expect, it, vi } from "vitest";
import type { PublicationDependencies } from "./consumer";
import { createPublicationHandler } from "./http";
import { preparePublication } from "./contract";

const ORIGIN = "https://dnd.faysk.dev";
const AUTH_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROFILE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CAMPAIGN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const SESSION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const sourceId = `craig-${"a".repeat(64)}`;

function rawRequest() {
	return JSON.stringify({
		schemaVersion: "tda_transcript_publication_request_v1",
		expectedCurrentRevisionId: null,
		operationId: "11111111-1111-4111-8111-111111111111",
		binding: {
			schemaVersion: "tda_publication_target_v1",
			campaignSlug: "yuhara-main",
			sourceSessionId: "sessao-00001",
			sourceId,
			runId: "run-job-a1",
			jobId: "job-a",
			attempt: 1,
			transcriptSha256: "b".repeat(64),
		},
		review: {
			sourceId,
			runId: "run-job-a1",
			baseTranscriptSha256: "b".repeat(64),
			draftRevision: 1,
			draftSha256: "c".repeat(64),
			status: "approved_local",
			lineage: {
				profileId: "whisper-detailed",
				engine: "faster-whisper",
				model: "large-v3",
				modelRevision: null,
				device: "cuda",
				computeType: "float16",
				alignment: "native",
				completedAt: "2026-09-21T12:00:00Z",
			},
			warnings: [],
			review: {
				reviewedSegments: 1,
				totalSegments: 1,
				reviewPercent: 100,
				editedSegments: 0,
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
		},
	});
}

function dependencies() {
	const raw = rawRequest();
	const parsed = preparePublication(raw);
	if (!parsed.ok) throw new Error(parsed.reason);
	const receipt = {
		schemaVersion: "tda_transcript_publication_receipt_v1" as const,
		status: "committed" as const,
		receiptId: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
		campaignId: CAMPAIGN,
		sessionId: SESSION,
		revisionId: "ffffffff-ffff-4fff-8fff-ffffffffffff",
		revisionNumber: 1,
		operationId: parsed.value.operationId,
		sourceId: parsed.value.sourceId,
		runId: parsed.value.runId,
		baseTranscriptSha256: parsed.value.baseTranscriptSha256,
		draftSha256: parsed.value.draftSha256,
		payloadSha256: parsed.value.payloadSha256,
		segmentCount: parsed.value.segmentCount,
		wordCount: 2,
		committedAt: "2026-09-21T12:01:00Z",
	};
	const publication: PublicationDependencies = {
		authorize: vi.fn(async (authUserId) => ({
			ok: true as const,
			actor: {
				authUserId,
				profileId: PROFILE,
				campaignId: CAMPAIGN,
				sessionId: SESSION,
			},
		})),
		commit: vi.fn(async () => ({ ok: true as const, receipt })),
		lookup: vi.fn(async () => ({ ok: true as const, receipt })),
	};
	return { raw, publication };
}

function request(raw: string, origin = ORIGIN) {
	return new Request(`${ORIGIN}/api/transcript-publications`, {
		method: "POST",
		headers: {
			Origin: origin,
			"Content-Type": "application/json",
		},
		body: raw,
	});
}

describe("transcript publication HTTP boundary", () => {
	it("authenticates same-origin requests and confirms the exact receipt", async () => {
		const { raw, publication } = dependencies();
		const handler = createPublicationHandler({
			origin: () => ORIGIN,
			identity: async () => ({ ok: true, authUserId: AUTH_USER }),
			publication,
		});
		const response = await handler(request(raw));
		expect(response.status).toBe(200);
		expect(await response.json()).toMatchObject({
			ok: true,
			receipt: {
				campaignId: CAMPAIGN,
				sessionId: SESSION,
				revisionNumber: 1,
			},
		});
		expect(publication.authorize).toHaveBeenCalledWith(AUTH_USER, {
			campaignSlug: "yuhara-main",
			sourceSessionId: "sessao-00001",
		});
		expect(publication.commit).toHaveBeenCalledTimes(1);
	});

	it("rejects foreign origin before identity or target work", async () => {
		const { raw, publication } = dependencies();
		const identity = vi.fn(async () => ({ ok: true as const, authUserId: AUTH_USER }));
		const handler = createPublicationHandler({
			origin: () => ORIGIN,
			identity,
			publication,
		});
		const response = await handler(request(raw, "https://evil.invalid"));
		expect(response.status).toBe(403);
		expect(identity).not.toHaveBeenCalled();
		expect(publication.authorize).not.toHaveBeenCalled();
	});

	it("keeps the production-style deny explicit instead of calling commit", async () => {
		const raw = rawRequest();
		const commit = vi.fn<PublicationDependencies["commit"]>();
		const publication: PublicationDependencies = {
			authorize: async () => ({
				ok: false,
				reason: "publish_capability_undefined",
			}),
			commit,
			lookup: vi.fn<PublicationDependencies["lookup"]>(),
		};
		const handler = createPublicationHandler({
			origin: () => ORIGIN,
			identity: async () => ({ ok: true, authUserId: AUTH_USER }),
			publication,
		});
		const response = await handler(request(raw));
		expect(response.status).toBe(503);
		expect(await response.json()).toEqual({
			ok: false,
			reason: "publish_capability_undefined",
		});
		expect(commit).not.toHaveBeenCalled();
	});

	it("uses readback lookup without a second commit", async () => {
		const { raw, publication } = dependencies();
		const handler = createPublicationHandler(
			{
				origin: () => ORIGIN,
				identity: async () => ({ ok: true, authUserId: AUTH_USER }),
				publication,
			},
			true,
		);
		const response = await handler(request(raw));
		expect(response.status).toBe(200);
		expect(publication.lookup).toHaveBeenCalledTimes(1);
		expect(publication.commit).not.toHaveBeenCalled();
	});

	it("rejects a mismatched receipt rather than claiming publication", async () => {
		const { raw, publication: valid } = dependencies();
		const publication: PublicationDependencies = {
			...valid,
			commit: vi.fn(async (actor, input) => {
				const result = await valid.commit(actor, input);
				if (!result.ok) return result;
				return {
					ok: true as const,
					receipt: { ...result.receipt, sessionId: CAMPAIGN },
				};
			}),
		};
		const handler = createPublicationHandler({
			origin: () => ORIGIN,
			identity: async () => ({ ok: true, authUserId: AUTH_USER }),
			publication,
		});
		const response = await handler(request(raw));
		expect(response.status).toBe(503);
		expect(await response.json()).toEqual({
			ok: false,
			reason: "dependency_unavailable",
		});
	});
});

it.each([false, true])("rejects profile changes between confirmation and receipt/write (lookup=%s)", async lookup => {
 const { raw, publication } = dependencies();
 const handler = createPublicationHandler({ origin: () => ORIGIN, identity: async () => ({ ok: true, authUserId: AUTH_USER }), publication }, lookup);
 const changed = { ...JSON.parse(raw), expectedActorProfileId: "99999999-9999-4999-8999-999999999999" };
 const response = await handler(request(JSON.stringify(changed)));
 expect(response.status).toBe(403); expect(publication.commit).not.toHaveBeenCalled(); expect(publication.lookup).not.toHaveBeenCalled();
});
