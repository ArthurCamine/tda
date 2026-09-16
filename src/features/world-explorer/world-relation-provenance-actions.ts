"use server";

import { revalidatePath } from "next/cache";
import { authorizeCampaignCapabilityServer } from "@/features/auth/server";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { editDataClient } from "@/integrations/supabase/server";

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_RELATION_CANON_SOURCES = 50;

export type WorldRelationCanonOption = Readonly<{
	id: string;
	title: string;
	entryType: string;
	visibility: string;
	updatedAt: string | null;
}>;

export type WorldRelationProvenanceFailure =
	| "unauthenticated"
	| "profile_unresolved"
	| "forbidden"
	| "dependency_unavailable"
	| "invalid_payload"
	| "not_persisted"
	| "review_required";

export type LoadWorldRelationProvenanceResult =
	| Readonly<{
			ok: true;
			persisted: false;
			selectedCanonEntryIds: readonly string[];
			options: readonly WorldRelationCanonOption[];
	  }>
	| Readonly<{
			ok: true;
			persisted: true;
			relationStatus: string;
			relationVisibility: string;
			selectedCanonEntryIds: readonly string[];
			options: readonly WorldRelationCanonOption[];
	  }>
	| Readonly<{ ok: false; reason: WorldRelationProvenanceFailure }>;

export type ReplaceWorldRelationProvenanceResult =
	| Readonly<{ ok: true; status: "saved" | "unchanged"; sourceCount: number }>
	| Readonly<{ ok: false; reason: WorldRelationProvenanceFailure }>;

type RpcPayload = Readonly<Record<string, unknown>>;

function safeSourceCount(value: unknown): number | undefined {
	return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
		? value
		: undefined;
}

async function provenanceManager() {
	const [contentAccess, canonAccess] = await Promise.all([
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.contentEdit,
			campaignSlug: CAMPAIGN_SLUG,
		}),
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.canonApprove,
			campaignSlug: CAMPAIGN_SLUG,
		}),
	]);
	if (!contentAccess.ok) return contentAccess;
	if (!canonAccess.ok) return canonAccess;
	if (
		contentAccess.authUserId !== canonAccess.authUserId ||
		contentAccess.profileId !== canonAccess.profileId
	) {
		return { ok: false, reason: "forbidden" } as const;
	}
	return {
		ok: true,
		authUserId: contentAccess.authUserId,
		profileId: contentAccess.profileId,
	} as const;
}

export async function loadWorldRelationProvenanceAction(
	relationId: string,
): Promise<LoadWorldRelationProvenanceResult> {
	if (!UUID_PATTERN.test(relationId)) return { ok: false, reason: "invalid_payload" };
	const access = await provenanceManager();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", CAMPAIGN_SLUG)
		.maybeSingle();
	if (campaignError || !campaign?.id) {
		if (campaignError) console.error("World relation provenance campaign lookup failed", campaignError.message);
		return { ok: false, reason: "dependency_unavailable" };
	}

	const { data: relation, error: relationError } = await client
		.from("entity_relations")
		.select("id,status,visibility")
		.eq("campaign_id", campaign.id)
		.eq("id", relationId)
		.maybeSingle();
	if (relationError) {
		console.error("World relation provenance relation lookup failed", relationError.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	if (!relation) {
		return { ok: true, persisted: false, selectedCanonEntryIds: [], options: [] };
	}

	const [sourcesResult, canonResult] = await Promise.all([
		client
			.from("entity_relation_sources")
			.select("canon_entry_id")
			.eq("relation_id", relationId),
		client
			.from("canon_entries")
			.select("id,title,entry_type,visibility,updated_at")
			.eq("campaign_id", campaign.id)
			.eq("status", "active")
			.order("updated_at", { ascending: false })
			.limit(500),
	]);
	if (sourcesResult.error) {
		console.error("World relation provenance source lookup failed", sourcesResult.error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	if (canonResult.error) {
		console.error("World relation provenance canon lookup failed", canonResult.error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}

	return {
		ok: true,
		persisted: true,
		relationStatus: relation.status,
		relationVisibility: relation.visibility,
		selectedCanonEntryIds: (sourcesResult.data ?? []).map((source) => source.canon_entry_id),
		options: (canonResult.data ?? []).map((entry) => ({
			id: entry.id,
			title: entry.title,
			entryType: entry.entry_type,
			visibility: entry.visibility,
			updatedAt: entry.updated_at,
		})),
	};
}

export async function replaceWorldRelationProvenanceAction(
	relationId: string,
	canonEntryIds: readonly string[],
): Promise<ReplaceWorldRelationProvenanceResult> {
	if (
		!UUID_PATTERN.test(relationId) ||
		!Array.isArray(canonEntryIds) ||
		canonEntryIds.length > MAX_RELATION_CANON_SOURCES ||
		canonEntryIds.some((id) => !UUID_PATTERN.test(id))
	) {
		return { ok: false, reason: "invalid_payload" };
	}
	const uniqueCanonEntryIds = [...new Set(canonEntryIds)];
	const access = await provenanceManager();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("replace_world_relation_sources_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_relation_id: relationId,
		p_canon_entry_ids: uniqueCanonEntryIds,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World relation provenance replacement failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}

	const payload = data as RpcPayload;
	if (payload.ok === true && (payload.status === "saved" || payload.status === "unchanged")) {
		const sourceCount = safeSourceCount(payload.sourceCount);
		if (sourceCount === undefined) return { ok: false, reason: "dependency_unavailable" };
		revalidatePath("/mundo");
		return { ok: true, status: payload.status, sourceCount };
	}
	if (payload.reason === "not_found") return { ok: false, reason: "not_persisted" };
	if (
		payload.reason === "forbidden" ||
		payload.reason === "invalid_payload" ||
		payload.reason === "review_required"
	) {
		return { ok: false, reason: payload.reason };
	}
	return { ok: false, reason: "dependency_unavailable" };
}
