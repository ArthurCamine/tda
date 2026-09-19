"use server";

import { authorizeCampaignCapabilityServer, getVerifiedServerIdentity } from "@/features/auth/server";
import { loadEditAccessContext } from "@/features/edit/access/repository";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { editDataClient } from "@/integrations/supabase/server";
import type { WorldLayoutProjection } from "./model";

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const POSITION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;
type RpcPayload = Readonly<Record<string, unknown>>;

export type WorldLayoutSessionFailure =
	| "unauthenticated"
	| "profile_unresolved"
	| "forbidden"
	| "dependency_unavailable"
	| "invalid_payload"
	| "lease_lost"
	| "conflict";

export type AcquireWorldLayoutSessionResult =
	| Readonly<{
			ok: true;
			status: "acquired" | "resumed" | "recovered";
			draft: WorldLayoutProjection;
			expiresAt: string;
			recoverySource?: "lease" | "durable";
			staleRecovery?: boolean;
			previousPublishConfirmed?: boolean;
			previousPublishedGraphRevision?: number;
			previousPublishedLayoutRevision?: number;
	  }>
	| Readonly<{
			ok: false;
			reason: "busy";
			holderLabel: string;
			sameActor: boolean;
			expiresAt?: string;
	  }>
	| Readonly<{ ok: false; reason: WorldLayoutSessionFailure }>;

export type WorldLayoutSessionResult =
	| Readonly<{
			ok: true;
			status: "renewed" | "draft_saved" | "released" | "discarded";
			expiresAt?: string;
	  }>
	| Readonly<{ ok: false; reason: WorldLayoutSessionFailure; revision?: number }>;

function safeString(value: unknown): string | undefined {
	return typeof value === "string" && value.length ? value : undefined;
}

function safeRevision(value: unknown): number | undefined {
	return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

function sanitizeLoosePositions(value: unknown): WorldLayoutProjection["positions"] | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) return null;
	const entries = Object.entries(value as Record<string, unknown>);
	if (entries.length > 1000) return null;
	const positions: WorldLayoutProjection["positions"] = {};
	for (const [id, raw] of entries) {
		if (!POSITION_ID_PATTERN.test(id) || !raw || typeof raw !== "object" || Array.isArray(raw)) return null;
		const row = raw as Record<string, unknown>;
		if (Object.keys(row).some((key) => key !== "x" && key !== "y")) return null;
		if (typeof row.x !== "number" || typeof row.y !== "number") return null;
		if (!Number.isFinite(row.x) || !Number.isFinite(row.y) || Math.abs(row.x) > 5000 || Math.abs(row.y) > 5000) {
			return null;
		}
		positions[id] = { x: row.x, y: row.y };
	}
	return positions;
}

async function layoutEditor() {
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
		return { ok: true, authUserId: identity.authUserId, profileId: context.profileId } as const;
	} catch {
		return { ok: false, reason: "dependency_unavailable" } as const;
	}
}

export async function acquireWorldLayoutSessionAction(
	leaseToken: string,
): Promise<AcquireWorldLayoutSessionResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const access = await layoutEditor();
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
		if (error) console.error("World layout lease acquisition failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true) {
		const status = payload.status;
		const revision = safeRevision(payload.baseRevision);
		const positions = sanitizeLoosePositions(payload.draftPositions);
		const expiresAt = safeString(payload.expiresAt);
		if (
			(status === "acquired" || status === "resumed" || status === "recovered") &&
			revision !== undefined && positions && expiresAt
		) {
			const recoverySource =
				payload.recoverySource === "lease" || payload.recoverySource === "durable"
					? payload.recoverySource
					: undefined;
			return {
				ok: true,
				status,
				expiresAt,
				draft: { schemaVersion: 1, view: "overview", revision, positions },
				recoverySource,
				staleRecovery: payload.staleRecovery === true,
				previousPublishConfirmed: payload.previousPublishConfirmed === true,
				previousPublishedGraphRevision: safeRevision(payload.previousPublishedGraphRevision),
				previousPublishedLayoutRevision: safeRevision(payload.previousPublishedLayoutRevision),
			};
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
	if (payload.reason === "forbidden") return { ok: false, reason: "forbidden" };
	return { ok: false, reason: "dependency_unavailable" };
}

export async function renewWorldLayoutSessionAction(
	leaseToken: string,
): Promise<WorldLayoutSessionResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const access = await layoutEditor();
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
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "renewed") {
		return { ok: true, status: "renewed", expiresAt: safeString(payload.expiresAt) };
	}
	if (payload.reason === "lease_lost" || payload.reason === "forbidden") {
		return { ok: false, reason: payload.reason };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function saveWorldLayoutSessionDraftAction(
	leaseToken: string,
	candidate: WorldLayoutProjection,
): Promise<WorldLayoutSessionResult> {
	if (!UUID_PATTERN.test(leaseToken) || candidate.schemaVersion !== 1 || candidate.view !== "overview") {
		return { ok: false, reason: "invalid_payload" };
	}
	const positions = sanitizeLoosePositions(candidate.positions);
	if (!positions) return { ok: false, reason: "invalid_payload" };
	const access = await layoutEditor();
	if (!access.ok) return { ok: false, reason: access.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };
	const { data, error } = await client.rpc("save_world_edit_layout_draft_atomic", {
		p_auth_user_id: access.authUserId,
		p_actor_profile_id: access.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
		p_positions: positions,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "draft_saved") {
		return { ok: true, status: "draft_saved", expiresAt: safeString(payload.expiresAt) };
	}
	if (payload.reason === "conflict") {
		return { ok: false, reason: "conflict", revision: safeRevision(payload.revision) };
	}
	if (
		payload.reason === "lease_lost" ||
		payload.reason === "forbidden" ||
		payload.reason === "invalid_payload"
	) {
		return { ok: false, reason: payload.reason };
	}
	return { ok: false, reason: "dependency_unavailable" };
}

export async function releaseWorldLayoutSessionAction(
	leaseToken: string,
): Promise<WorldLayoutSessionResult> {
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
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	return payload.ok === true && payload.status === "released"
		? { ok: true, status: "released" }
		: { ok: false, reason: "dependency_unavailable" };
}


export async function discardWorldLayoutSessionAction(
	leaseToken: string,
): Promise<WorldLayoutSessionResult> {
	if (!UUID_PATTERN.test(leaseToken)) return { ok: false, reason: "invalid_payload" };
	const profile = await verifiedProfile();
	if (!profile.ok) return { ok: false, reason: profile.reason };
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };
	const { data, error } = await client.rpc("discard_world_edit_lease_atomic", {
		p_auth_user_id: profile.authUserId,
		p_actor_profile_id: profile.profileId,
		p_campaign_slug: CAMPAIGN_SLUG,
		p_lease_token: leaseToken,
	});
	if (error || !data || typeof data !== "object" || Array.isArray(data)) {
		if (error) console.error("World draft discard failed", error.message);
		return { ok: false, reason: "dependency_unavailable" };
	}
	const payload = data as RpcPayload;
	if (payload.ok === true && payload.status === "discarded") {
		return { ok: true, status: "discarded" };
	}
	if (payload.reason === "lease_lost" || payload.reason === "forbidden") {
		return { ok: false, reason: payload.reason };
	}
	return { ok: false, reason: "dependency_unavailable" };
}
