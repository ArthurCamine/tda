export const EDIT_CAPABILITIES = {
	localProcess: "campaign.local.process",
	transcriptRead: "campaign.transcript.read",
	contentEdit: "campaign.content.edit",
	permissionsManage: "campaign.permissions.manage",
	transcriptImport: "campaign.transcript.import",
	worldLayoutEdit: "campaign.world.layout.edit",
	canonApprove: "narrative.canon.approve",
} as const;

export type EditCapability =
	(typeof EDIT_CAPABILITIES)[keyof typeof EDIT_CAPABILITIES];

export type EditGrant = Readonly<{
	action: string;
	scopeType: string;
	scopeId: string;
	status: string;
	startsAt: string;
	endsAt: string | null;
}>;

export type EditAccessContext = Readonly<{
	authUserId: string;
	profileId: string | null;
	grants: readonly EditGrant[];
}>;

export type EditAccessFailure =
	| "profile_unresolved"
	| "forbidden";

export type EditAccessResult =
	| Readonly<{ ok: true; profileId: string }>
	| Readonly<{ ok: false; reason: EditAccessFailure }>;

const PROJECT_SCOPE_ID = "tda";

function isGrantActive(grant: EditGrant, now: Date): boolean {
	if (grant.status !== "active") return false;

	const startsAt = Date.parse(grant.startsAt);
	if (!Number.isFinite(startsAt) || startsAt > now.getTime()) return false;

	if (!grant.endsAt) return true;
	const endsAt = Date.parse(grant.endsAt);
	return Number.isFinite(endsAt) && endsAt > now.getTime();
}

function grantCoversCampaign(grant: EditGrant, campaignSlug: string): boolean {
	return (
		(grant.scopeType === "campaign" && grant.scopeId === campaignSlug) ||
		(grant.scopeType === "project" && grant.scopeId === PROJECT_SCOPE_ID)
	);
}

export function authorizeCampaignCapability(
	context: EditAccessContext,
	capability: EditCapability,
	campaignSlug: string,
	now = new Date(),
): EditAccessResult {
	if (!context.profileId) {
		return { ok: false, reason: "profile_unresolved" };
	}

	const allowed = context.grants.some(
		(grant) =>
			grant.action === capability &&
			isEffectiveCampaignGrant(grant, campaignSlug, now),
	);

	return allowed
		? { ok: true, profileId: context.profileId }
		: { ok: false, reason: "forbidden" };
}

/** Shared scope/time predicate for authorization and its administrative projection. */
export function isEffectiveCampaignGrant(
	grant: EditGrant,
	campaignSlug: string,
	now: Date,
): boolean {
	return isGrantActive(grant, now) && grantCoversCampaign(grant, campaignSlug);
}
