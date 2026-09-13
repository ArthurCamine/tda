"use server";

import { revalidatePath } from "next/cache";
import { authorizeCampaignCapabilityServer } from "@/features/auth/server";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { editDataClient } from "@/integrations/supabase/server";
import { sanitizeWorldGraphDraft } from "./graph-contract";
import type { WorldGraphDraft } from "./model";
import { worldEntityMediaDraftHasIntent } from "./world-entity-media-intent";
import { prepareWorldEntityMediaForPublish } from "./world-entity-media-publication";
import { hydrateWorldGraphDraftMedia } from "./world-entity-media-repository";
import { worldEntityMediaEnabled } from "./world-entity-media-server";

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

type RpcPayload = Readonly<Record<string, unknown>>;

export type WorldGraphFailure =
	| "unauthenticated"
	| "profile_unresolved"
	| "forbidden"
	| "dependency_unavailable"
	| "invalid_payload"
	| "duplicate"
	| "review_required"
	| "media_pending"
	| "lease_lost"
	| "conflict";

export type AcquireWorldGraphDraftResult =
	| Readonly<{
			ok: true;
			draft: WorldGraphDraft;
			expiresAt?: string;
	  }>
	| Readonly<{ ok: false; reason: WorldGraphFailure; revision?: number }>;

export type WorldGraphMutationResult =
	| Readonly<{
			ok: true;
			status: "draft_saved" | "saved" | "unchanged";
			graphRevision?: number;
			layoutRevision?: number;
			expiresAt?: string;
			mediaStatus?: "saved" | "unchanged";
	  }>
	| Readonly<{ ok: false; reason: WorldGraphFailure; revision?: number }>;

function safeNumber(value: unknown): number | undefined {
	return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
		? value
		: undefined;
}

function safeString(value: unknown): string | undefined {
	return typeof value === "string" && value.length ? value : undefined;
}

function safeMediaStatus(value: unknown): "saved" | "unchanged" | undefined {
	return value === "saved" || value === "unchanged" ? value : undefined;
}

async function contentEditor() {
	return authorizeCampaignCapabilityServer({
		action: EDIT_CAPABILITIES.contentEdit,
		campaignSlug: CAMPAIGN_SLUG,
	});
}

export async function acquireWorldGraphDraftAction(
	leaseToken: string,
): Promise<AcquireWorldGraphDraftResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const access = await contentEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("acquire_world_graph_draft_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World graph draft acquisition failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true) {
		const draft = sanitizeWorldGraphDraft(payload.draftGraph);
		if (!draft) return { ok: false, reason: "dependency_unavailable" };
		try {
			const hydratedDraft = await hydrateWorldGraphDraftMedia(client, CAMPAIGN_SLUG, draft);
			return { ok: true, draft: hydratedDraft, expiresAt: safeString(payload.expiresAt) };
		} catch (mediaError) {
			console.error(
				"World graph media hydration failed",
				mediaError instanceof Error ? mediaError.message : "unknown_error",
			);
			return { ok: false, reason: "dependency_unavailable" };
		}
	}
	if (payload.reason === "forbidden" || payload.reason === "lease_lost") {
		return { ok: false, reason: payload.reason };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function saveWorldGraphDraftAction(
	leaseToken: string,
	draftCandidate: WorldGraphDraft,
): Promise<WorldGraphMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const draft = sanitizeWorldGraphDraft(draftCandidate);
	if (!draft) return { ok: false, reason: "invalid_payload" };
	const access = await contentEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("save_world_graph_draft_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
		p_draft: draft,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World graph draft save failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "draft_saved") {
		return { ok: true, status: "draft_saved", expiresAt: safeString(payload.expiresAt) };
	}
	if (
		payload.reason === "forbidden" ||
		payload.reason === "lease_lost" ||
		payload.reason === "invalid_payload" ||
		payload.reason === "duplicate"
	) {
		return { ok: false, reason: payload.reason };
	}
	if (payload.reason === "conflict") {
		return { ok: false, reason: "conflict", revision: safeNumber(payload.revision) };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function publishWorldEditStateAction(
	leaseToken: string,
): Promise<WorldGraphMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const [contentAccess, layoutAccess] = await Promise.all([
		contentEditor(),
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.worldLayoutEdit,
			campaignSlug: CAMPAIGN_SLUG,
		}),
	]);
	if (!contentAccess.ok) return { ok: false, reason: contentAccess.reason };
	if (!layoutAccess.ok) return { ok: false, reason: layoutAccess.reason };
	if (
		contentAccess.authUserId !== layoutAccess.authUserId ||
		contentAccess.profileId !== layoutAccess.profileId
	) {
		return { ok: false, reason: "forbidden" };
	}
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	// Public relation facts must remain behind the existing canon/review gate.
	// The World editor may persist private/review material, but it cannot promote
	// an active relation to a published audience until a canon source is attached.
	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", CAMPAIGN_SLUG)
		.maybeSingle();
	if (campaignError || !campaign?.id) {
		if (campaignError) console.error("World publication campaign lookup failed", campaignError.message);
		return { ok: false, reason: "dependency_unavailable" };
	}

	const { data: lease, error: leaseError } = await client
		.from("world_edit_leases")
		.select("draft_graph")
		.eq("campaign_id", campaign.id)
		.eq("holder_profile_id", contentAccess.profileId)
		.eq("lease_token", leaseToken)
		.maybeSingle();
	if (leaseError || !lease) {
		if (leaseError) console.error("World publication draft lookup failed", leaseError.message);
		return { ok: false, reason: leaseError ? "dependency_unavailable" : "lease_lost" };
	}

	const publicationDraft = sanitizeWorldGraphDraft(lease.draft_graph);
	if (!publicationDraft) return { ok: false, reason: "invalid_payload" };
	const publishedRelationIds = publicationDraft.edges
		.filter(
			(edge) =>
				edge.status === "active" &&
				(edge.visibility === "public_campaign" || edge.visibility === "public_web"),
		)
		.map((edge) => edge.id);

	if (publishedRelationIds.length) {
		const { data: sources, error: sourceError } = await client
			.from("entity_relation_sources")
			.select("relation_id")
			.in("relation_id", publishedRelationIds);
		if (sourceError) {
			console.error("World publication source lookup failed", sourceError.message);
			return { ok: false, reason: "dependency_unavailable" };
		}
		const sourcedRelationIds = new Set((sources ?? []).map((source) => source.relation_id));
		if (publishedRelationIds.some((relationId) => !sourcedRelationIds.has(relationId))) {
			return { ok: false, reason: "review_required" };
		}
	}

	const mediaEnabled = worldEntityMediaEnabled();
	if (!mediaEnabled && worldEntityMediaDraftHasIntent(publicationDraft)) {
		// A flag can be disabled while an editor still owns a draft created when
		// media was available. Never fall back to the legacy publisher in that
		// state: it would consume the lease while silently dropping media intent.
		return { ok: false, reason: "media_pending" };
	}
	const preparedMedia = await prepareWorldEntityMediaForPublish({
		client,
		draft: publicationDraft,
	});
	if (preparedMedia.status === "pending") {
		return { ok: false, reason: "media_pending" };
	}

	const rpcArgs = {
		p_auth_user_id: contentAccess.authUserId,
		p_actor_profile_id: contentAccess.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	};
	const { data, error } = mediaEnabled
		? await client.rpc("publish_world_edit_state_with_media_atomic", {
				...rpcArgs,
				p_bindings: preparedMedia.bindings,
			})
		: await client.rpc("publish_world_edit_state_atomic", rpcArgs);
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World combined publish failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && (payload.status === "saved" || payload.status === "unchanged")) {
		const graphRevision = safeNumber(payload.graphRevision);
		const layoutRevision = safeNumber(payload.layoutRevision);
		if (graphRevision === undefined || layoutRevision === undefined) {
			return { ok: false, reason: "dependency_unavailable" };
		}
		const mediaStatus = safeMediaStatus(payload.mediaStatus);
		revalidatePath("/mundo");
		return {
			ok: true,
			status: mediaStatus === "saved" ? "saved" : payload.status,
			graphRevision,
			layoutRevision,
			mediaStatus,
		};
	}
	if (payload.reason === "media_not_verified" || payload.reason === "media_invalid") {
		return { ok: false, reason: "media_pending" };
	}
	if (
		payload.reason === "forbidden" ||
		payload.reason === "lease_lost" ||
		payload.reason === "invalid_payload" ||
		payload.reason === "duplicate" ||
		payload.reason === "review_required"
	) {
		return { ok: false, reason: payload.reason };
	}
	if (payload.reason === "conflict") {
		return { ok: false, reason: "conflict", revision: safeNumber(payload.revision) };
	}
	return { ok: false, reason: "dependency_unavailable" };
}
