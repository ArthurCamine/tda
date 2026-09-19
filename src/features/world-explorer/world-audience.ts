import type { WorldVisibility } from "./model";

export type WorldAudience = "public" | "player" | "master" | "editor";

const VISIBILITIES_BY_AUDIENCE: Readonly<Record<WorldAudience, readonly WorldVisibility[]>> = {
	public: ["public_web"],
	player: ["private_players", "public_campaign", "public_web"],
	master: ["private_master", "private_players", "public_campaign", "public_web"],
	editor: ["private_master", "private_players", "review_only", "public_campaign", "public_web"],
};

export function worldVisibleVisibilities(audience: WorldAudience): readonly WorldVisibility[] {
	return VISIBILITIES_BY_AUDIENCE[audience];
}

export function worldVisibilityIsAllowed(
	audience: WorldAudience,
	visibility: WorldVisibility,
): boolean {
	return VISIBILITIES_BY_AUDIENCE[audience].includes(visibility);
}

export function worldRelationRequiresReviewedProvenance(visibility: WorldVisibility): boolean {
	return visibility === "public_campaign" || visibility === "public_web";
}

export function worldAudienceFromMembership(input: {
	fullWorldEditor: boolean;
	campaignRole: string | null | undefined;
}): WorldAudience {
	if (input.fullWorldEditor) return "editor";
	if (input.campaignRole === "master") return "master";
	if (input.campaignRole === "player") return "player";
	return "public";
}
