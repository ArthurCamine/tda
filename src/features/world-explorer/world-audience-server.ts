import "server-only";
import { getVerifiedServerIdentity } from "@/features/auth/server";
import { editDataClient, publishedDataClient } from "@/integrations/supabase/server";
import { worldAudienceFromMembership, type WorldAudience } from "./world-audience";

export async function resolveWorldAudienceServer(input: {
	fullWorldEditor: boolean;
	campaignSlug: string;
}): Promise<WorldAudience> {
	if (input.fullWorldEditor) return "editor";

	const identity = await getVerifiedServerIdentity();
	if (!identity.ok) return "public";

	const client = publishedDataClient() ?? editDataClient();
	if (!client) return "public";

	try {
		const { data: profile, error: profileError } = await client
			.from("profiles")
			.select("id")
			.eq("auth_user_id", identity.authUserId)
			.maybeSingle();
		if (profileError || !profile?.id) return "public";

		const { data: campaign, error: campaignError } = await client
			.from("campaigns")
			.select("id")
			.eq("slug", input.campaignSlug)
			.maybeSingle();
		if (campaignError || !campaign?.id) return "public";

		const { data: membership, error: membershipError } = await client
			.from("campaign_members")
			.select("role")
			.eq("campaign_id", campaign.id)
			.eq("profile_id", profile.id)
			.maybeSingle();
		if (membershipError) {
			console.error("World audience membership lookup failed", membershipError.message);
			return "public";
		}

		return worldAudienceFromMembership({
			fullWorldEditor: false,
			campaignRole: membership?.role,
		});
	} catch (error) {
		console.error(
			"World audience resolution failed",
			error instanceof Error ? error.message : "unknown_error",
		);
		return "public";
	}
}
