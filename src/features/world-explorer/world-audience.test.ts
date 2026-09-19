import { describe, expect, it } from "vitest";
import {
	worldAudienceFromMembership,
	worldRelationRequiresReviewedProvenance,
	worldVisibilityIsAllowed,
	worldVisibleVisibilities,
} from "./world-audience";

describe("World audience projection", () => {
	it("prefers the full editor audience over campaign membership", () => {
		expect(
			worldAudienceFromMembership({ fullWorldEditor: true, campaignRole: "player" }),
		).toBe("editor");
	});

	it("resolves player and master memberships without treating them as public visitors", () => {
		expect(
			worldAudienceFromMembership({ fullWorldEditor: false, campaignRole: "player" }),
		).toBe("player");
		expect(
			worldAudienceFromMembership({ fullWorldEditor: false, campaignRole: "master" }),
		).toBe("master");
		expect(
			worldAudienceFromMembership({ fullWorldEditor: false, campaignRole: null }),
		).toBe("public");
	});

	it("keeps private and review-only data out of weaker audiences", () => {
		expect(worldVisibleVisibilities("public")).toEqual(["public_web"]);
		expect(worldVisibilityIsAllowed("player", "private_players")).toBe(true);
		expect(worldVisibilityIsAllowed("player", "private_master")).toBe(false);
		expect(worldVisibilityIsAllowed("player", "review_only")).toBe(false);
		expect(worldVisibilityIsAllowed("master", "private_master")).toBe(true);
		expect(worldVisibilityIsAllowed("master", "review_only")).toBe(false);
		expect(worldVisibilityIsAllowed("editor", "review_only")).toBe(true);
	});

	it("requires reviewed provenance only for campaign/web published relation facts", () => {
		expect(worldRelationRequiresReviewedProvenance("private_players")).toBe(false);
		expect(worldRelationRequiresReviewedProvenance("private_master")).toBe(false);
		expect(worldRelationRequiresReviewedProvenance("review_only")).toBe(false);
		expect(worldRelationRequiresReviewedProvenance("public_campaign")).toBe(true);
		expect(worldRelationRequiresReviewedProvenance("public_web")).toBe(true);
	});
});
