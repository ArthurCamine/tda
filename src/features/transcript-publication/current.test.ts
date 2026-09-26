import { describe, expect, it, vi } from "vitest";
import { createCurrentPublicationHandler } from "./current";
import { deniedPublicationDependencies } from "./consumer";
const actor = {
	authUserId: "auth",
	profileId: "33333333-3333-4333-8333-333333333333",
	campaignId: "campaign",
	sessionId: "session",
};
const request = (
	body: unknown = { campaignSlug: "campaign", sourceSessionId: "session" },
	origin = "https://tda.test",
) =>
	new Request("https://tda.test/api/transcript-publications/current", {
		method: "POST",
		headers: { origin, "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
describe("current publication metadata", () => {
	it("denies scope before reading any session metadata", async () => {
		const read = vi.fn();
		const handler = createCurrentPublicationHandler({
			origin: () => "https://tda.test",
			identity: async () => ({ ok: true, authUserId: "auth" }),
			publication: { ...deniedPublicationDependencies, authorize: async () => ({ ok: false as const, reason: "forbidden" as const }) },
			read,
		});
		expect((await handler(request())).status).toBe(403);
		expect(read).not.toHaveBeenCalled();
	});
	it("returns only authorized current metadata and disables caching", async () => {
		const read = vi.fn(async () => ({
			ok: true as const,
			current: { actorProfileId: actor.profileId, revisionId: null },
		}));
		const handler = createCurrentPublicationHandler({
			origin: () => "https://tda.test",
			identity: async () => ({ ok: true, authUserId: "auth" }),
			publication: {
				...deniedPublicationDependencies,
				authorize: async () => ({ ok: true, actor }),
			},
			read,
		});
		const response = await handler(request());
		expect(response.status).toBe(200);
		expect(response.headers.get("Cache-Control")).toBe("no-store");
		expect(await response.json()).toEqual({
			ok: true,
			current: { actorProfileId: actor.profileId, revisionId: null },
		});
		expect(read).toHaveBeenCalledWith(actor);
	});
	it("rejects wrong origin, oversized metadata and malformed target before lookup", async () => {
		const authorize = vi.fn();
		const read = vi.fn();
		const handler = createCurrentPublicationHandler({
			origin: () => "https://tda.test",
			identity: async () => ({ ok: true, authUserId: "auth" }),
			publication: { ...deniedPublicationDependencies, authorize },
			read,
		});
		expect((await handler(request({}, "https://other.test"))).status).toBe(403);
		expect(
			(
				await handler(
					request({
						campaignSlug: "x".repeat(2000),
						sourceSessionId: "session",
					}),
				)
			).status,
		).toBe(400);
		expect(
			(
				await handler(
					request({
						campaignSlug: "campaign",
						sourceSessionId: "session",
						extra: true,
					}),
				)
			).status,
		).toBe(400);
		expect(authorize).not.toHaveBeenCalled();
		expect(read).not.toHaveBeenCalled();
	});
});

