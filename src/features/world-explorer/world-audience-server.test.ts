import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	getIdentity: vi.fn(),
	profileMaybeSingle: vi.fn(),
	campaignMaybeSingle: vi.fn(),
	membershipMaybeSingle: vi.fn(),
	publishedDataClient: vi.fn(),
	editDataClient: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("@/features/auth/server", () => ({
	getVerifiedServerIdentity: mocks.getIdentity,
}));
vi.mock("@/integrations/supabase/server", () => ({
	publishedDataClient: mocks.publishedDataClient,
	editDataClient: mocks.editDataClient,
}));

function queryWith(maybeSingle: ReturnType<typeof vi.fn>) {
	const query = {
		select: vi.fn(),
		eq: vi.fn(),
		maybeSingle,
	};
	query.select.mockReturnValue(query);
	query.eq.mockReturnValue(query);
	return query;
}

import { resolveWorldAudienceServer } from "./world-audience-server";

describe("resolveWorldAudienceServer", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mocks.getIdentity.mockResolvedValue({
			ok: true,
			authUserId: "auth-player",
		});
		mocks.profileMaybeSingle.mockResolvedValue({
			data: { id: "profile-player" },
			error: null,
		});
		mocks.campaignMaybeSingle.mockResolvedValue({
			data: { id: "campaign-yuhara" },
			error: null,
		});
		mocks.membershipMaybeSingle.mockResolvedValue({
			data: { role: "player" },
			error: null,
		});

		const client = {
			from: vi.fn((table: string) => {
				switch (table) {
					case "profiles":
						return queryWith(mocks.profileMaybeSingle);
					case "campaigns":
						return queryWith(mocks.campaignMaybeSingle);
					case "campaign_members":
						return queryWith(mocks.membershipMaybeSingle);
					default:
						throw new Error(`unexpected table ${table}`);
				}
			}),
		};
		mocks.publishedDataClient.mockReturnValue(client);
		mocks.editDataClient.mockReturnValue(null);
	});

	it("short-circuits full editors without consulting membership", async () => {
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: true,
				campaignSlug: "yuhara-main",
			}),
		).toBe("editor");
		expect(mocks.getIdentity).not.toHaveBeenCalled();
		expect(mocks.publishedDataClient).not.toHaveBeenCalled();
	});

	it("returns public for anonymous or unavailable identity", async () => {
		mocks.getIdentity.mockResolvedValueOnce({
			ok: false,
			reason: "unauthenticated",
		});
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: false,
				campaignSlug: "yuhara-main",
			}),
		).toBe("public");
		expect(mocks.publishedDataClient).not.toHaveBeenCalled();
	});

	it("resolves a campaign player to the player audience", async () => {
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: false,
				campaignSlug: "yuhara-main",
			}),
		).toBe("player");
		expect(mocks.profileMaybeSingle).toHaveBeenCalledTimes(1);
		expect(mocks.campaignMaybeSingle).toHaveBeenCalledTimes(1);
		expect(mocks.membershipMaybeSingle).toHaveBeenCalledTimes(1);
	});

	it("resolves a campaign master to the master audience", async () => {
		mocks.membershipMaybeSingle.mockResolvedValueOnce({
			data: { role: "master" },
			error: null,
		});
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: false,
				campaignSlug: "yuhara-main",
			}),
		).toBe("master");
	});

	it("does not promote an authenticated non-member", async () => {
		mocks.membershipMaybeSingle.mockResolvedValueOnce({
			data: null,
			error: null,
		});
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: false,
				campaignSlug: "yuhara-main",
			}),
		).toBe("public");
	});

	it("fails closed to public when membership lookup errors", async () => {
		mocks.membershipMaybeSingle.mockResolvedValueOnce({
			data: null,
			error: { message: "synthetic lookup failure" },
		});
		expect(
			await resolveWorldAudienceServer({
				fullWorldEditor: false,
				campaignSlug: "yuhara-main",
			}),
		).toBe("public");
	});
});
