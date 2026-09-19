"use server";

import { revalidatePath } from "next/cache";
import {
	authorizeCampaignCapabilityServer,
	getVerifiedServerIdentity,
} from "@/features/auth/server";
import { loadEditAccessContext } from "@/features/edit/access/repository";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { editDataClient } from "@/integrations/supabase/server";
import { DANDELION_WORLD_DEMO } from "./fixtures/dandelion";
import {
	WORLD_LAYOUT_SCHEMA_VERSION,
	sanitizeWorldLayoutProjection,
} from "./layout-contract";
import type { WorldLayoutProjection } from "./model";
import { buildWorldProjection } from "./projection";

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export type WorldEditLeaseFailure =
	| "unauthenticated"
	| "profile_unresolved"
	| "forbidden"
	| "dependency_unavailable"
	| "invalid_payload"
	| "lease_lost"
	| "conflict";

export type AcquireWorldEditLeaseResult =
	| Readonly<{
			ok: true;
			status: "acquired" | "resumed" | "recovered";
			expiresAt: string;
			draft: WorldLayoutProjection;
	  }>
	| Readonly<{
			ok: false;
			reason: "busy";
			holderLabel: string;
			sameActor: boolean;
			expiresAt?: string;
	  }>
	| Readonly<{ ok: false; reason: WorldEditLeaseFailure }>;

export type WorldEditMutationResult =
	| Readonly<{
			ok: true;
			status: "renewed" | "draft_saved" | "saved" | "unchanged" | "released";
			revision?: number;
			expiresAt?: string;
	  }>
	| Readonly<{
			ok: false;
			reason: WorldEditLeaseFailure;
			revision?: number;
	  }>;

type RpcPayload = Readonly<Record<string, unknown>>;

function safeRevision(value: unknown): number | undefined {
	const parsed =
		typeof value === "number"
			? value
			: typeof value === "string" && /^\\d+$/u.test(value)
				? Number(value)
				: Number.NaN;
	return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

function safeString(value: unknown): string | undefined {
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

function strictLayoutCandidate(
	candidate: WorldLayoutProjection,
): WorldLayoutProjection | undefined {
	if (
		candidate.schemaVersion !== WORLD_LAYOUT_SCHEMA_VERSION ||
		candidate.view !== "overview" ||
		!Number.isSafeInteger(candidate.revision) ||
		candidate.revision < 0 ||
		!candidate.positions ||
		typeof candidate.positions !== "object" ||
		Array.isArray(candidate.positions)
	) {
		return undefined;
	}

	const projection = buildWorldProjection(DANDELION_WORLD_DEMO);
	const sanitized = sanitizeWorldLayoutProjection(
		candidate,
		new Set(projection.nodes.map((node) => node.id)),
		"overview",
	);
	if (!sanitized) return undefined;

	const rawIds = Object.keys(candidate.positions).sort();
	const safeIds = Object.keys(sanitized.positions).sort();
	if (rawIds.length !== safeIds.length || rawIds.some((id, index) => id !== safeIds[index])) {
		return undefined;
	}
	return sanitized;
}

function draftFromRpc(payload: RpcPayload): WorldLayoutProjection | undefined {
	const revision = safeRevision(payload.baseRevision);
	if (revision === undefined) return undefined;
	if (
		!payload.draftPositions ||
		typeof payload.draftPositions !== "object" ||
		Array.isArray(payload.draftPositions)
	) {
		return undefined;
	}

	const projection = buildWorldProjection(DANDELION_WORLD_DEMO);
	return sanitizeWorldLayoutProjection(
		{
			schemaVersion: WORLD_LAYOUT_SCHEMA_VERSION,
			view: "overview",
			revision,
			positions: payload.draftPositions as WorldLayoutProjection["positions"],
		},
		new Set(projection.nodes.map((node) => node.id)),
		"overview",
	);
}

async function authorizedLayoutEditor() {
	return authorizeCampaignCapabilityServer({
		action: EDIT_CAPABILITIES.worldLayoutEdit,
		campaignSlug: CAMPAIGN_SLUG,
	});
}

async function verifiedProfile() {
	const identity = await getVerifiedServerIdentity();
	if (!identity.ok) return identity;
	try {
		const context = await loadEditAccessContext(identity.authUserId);
		if (!context) return { ok: false, reason: "dependency_unavailable" } as const;
		if (!context.profileId) return { ok: false, reason: "profile_unresolved" } as const;
		return {
			ok: true,
			authUserId: identity.authUserId,
			profileId: context.profileId,
		} as const;
	} catch {
		return { ok: false, reason: "dependency_unavailable" } as const;
	}
}

export async function acquireWorldEditLeaseAction(
	leaseToken: string,
): Promise<AcquireWorldEditLeaseResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };

	const access = await authorizedLayoutEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("acquire_world_edit_lease_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World edit lease acquisition failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}

	const payload = data as RpcPayload;
	if (payload.ok === true) {
		const status = payload.status;
		const expiresAt = safeString(payload.expiresAt);
		const draft = draftFromRpc(payload);
		if (
			(status === "acquired" || status === "resumed" || status === "recovered") &&
			expiresAt &&
			draft
		) {
			return { ok: true, status, expiresAt, draft };
		}
	}

	if (payload.ok === false && payload.reason === "busy") {
		return {
			ok: false,
			reason: "busy",
			holderLabel: safeString(payload.holderLabel) ?? "Outra pessoa",
			sameActor: payload.sameActor === true,
			expiresAt: safeString(payload.expiresAt),
		};
	}
	if (payload.ok === false && payload.reason === "forbidden") {
		return { ok: false, reason: "forbidden" };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function renewWorldEditLeaseAction(
	leaseToken: string,
): Promise<WorldEditMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const access = await authorizedLayoutEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("renew_world_edit_lease_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World edit lease renewal failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "renewed") {
		return {
			ok: true,
			status: "renewed",
			expiresAt: safeString(payload.expiresAt),
		};
	}
	if (payload.ok === false && payload.reason === "lease_lost") {
		return { ok: false, reason: "lease_lost" };
	}
	if (payload.ok === false && payload.reason === "forbidden") {
		return { ok: false, reason: "forbidden" };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function saveWorldEditDraftAction(
	leaseToken: string,
	candidate: WorldLayoutProjection,
): Promise<WorldEditMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const sanitized = strictLayoutCandidate(candidate);
	if (!sanitized) return { ok: false, reason: "invalid_payload" };

	const access = await authorizedLayoutEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("save_world_edit_layout_draft_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
		p_positions: sanitized.positions,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World edit draft save failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "draft_saved") {
		return {
			ok: true,
			status: "draft_saved",
			expiresAt: safeString(payload.expiresAt),
		};
	}
	if (payload.ok === false && payload.reason === "conflict") {
		return {
			ok: false,
			reason: "conflict",
			revision: safeRevision(payload.revision),
		};
	}
	if (payload.ok === false && payload.reason === "lease_lost") {
		return { ok: false, reason: "lease_lost" };
	}
	if (payload.ok === false && payload.reason === "forbidden") {
		return { ok: false, reason: "forbidden" };
	}
	if (payload.ok === false && payload.reason === "invalid_payload") {
		return { ok: false, reason: "invalid_payload" };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function publishWorldEditLayoutAction(
	leaseToken: string,
): Promise<WorldEditMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const access = await authorizedLayoutEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const confirmedReceipt = async (): Promise<WorldEditMutationResult | null> => {
		const { data: campaign, error: campaignError } = await client
			.from("campaigns")
			.select("id")
			.eq("slug", CAMPAIGN_SLUG)
			.maybeSingle();
		if (campaignError || !campaign?.id) {
			if (campaignError)
				console.error("World layout publish receipt campaign lookup failed", campaignError.message);
			return null;
		}
		const { data: receipt, error: receiptError } = await client
			.from("world_edit_drafts")
			.select("status,published_layout_revision")
			.eq("campaign_id", campaign.id)
			.eq("owner_profile_id", access.profileId)
			.eq("lease_token", leaseToken)
			.maybeSingle();
		if (receiptError) {
			console.error("World layout publish receipt lookup failed", receiptError.message);
			return null;
		}
		if (receipt?.status !== "published") return null;
		const revision = safeRevision(receipt.published_layout_revision);
		if (revision === undefined) return null;
		return { ok: true, status: "saved", revision };
	};

	const { data, error } = await client.rpc("publish_world_edit_layout_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World edit publish failed", error.message);
		const receipt = await confirmedReceipt();
		if (receipt?.ok) {
			revalidatePath("/mundo");
			return receipt;
		}
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && (payload.status === "saved" || payload.status === "unchanged")) {
		const revision = safeRevision(payload.revision);
		if (revision === undefined) return { ok: false, reason: "dependency_unavailable" };
		revalidatePath("/mundo");
		return { ok: true, status: payload.status, revision };
	}
	if (payload.ok === false && payload.reason === "conflict") {
		return {
			ok: false,
			reason: "conflict",
			revision: safeRevision(payload.revision),
		};
	}
	if (payload.ok === false && payload.reason === "lease_lost") {
		const receipt = await confirmedReceipt();
		if (receipt?.ok) {
			revalidatePath("/mundo");
			return receipt;
		}
		return { ok: false, reason: "lease_lost" };
	}
	if (payload.ok === false && payload.reason === "forbidden") {
		return { ok: false, reason: "forbidden" };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function releaseWorldEditLeaseAction(
	leaseToken: string,
): Promise<WorldEditMutationResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const profile = await verifiedProfile();
	if (!profile.ok) return { ok: false, reason: profile.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	const { data, error } = await client.rpc("release_world_edit_lease_atomic", {
		p_auth_user_id: profile.authUserId,
		p_actor_profile_id: profile.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World edit lease release failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	return payload.ok === true && payload.status === "released"
		? { ok: true, status: "released" }
		: { ok: false, reason: "dependency_unavailable" };
}
