"use server";

import { randomUUID } from "node:crypto";
import type { SupabaseClient } from "@supabase/supabase-js";
import { authorizeCampaignCapabilityServer } from "@/features/auth/server";
import { EDIT_CAPABILITIES } from "@/features/edit/access/policy";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import { editDataClient } from "@/integrations/supabase/server";
import { sanitizeWorldGraphDraft } from "./graph-contract";
import {
	WORLD_ENTITY_MEDIA_MAX_BYTES,
	type WorldEntityMediaMime,
	isWorldEntityMediaAssetId,
	isWorldEntityMediaMime,
	isWorldEntityMediaSha256,
} from "./world-entity-media";
import {
	finalizeWorldEntityPortraitPendingUpload,
	presignWorldEntityPortraitPendingUpload,
	type VerifiedWorldEntityUpload,
	worldEntityMediaEnabled,
} from "./world-entity-media-server";

export type WorldEntityMediaUploadFailure =
	| "unauthenticated"
	| "profile_unresolved"
	| "forbidden"
	| "dependency_unavailable"
	| "media_unavailable"
	| "invalid_payload"
	| "lease_lost";

export type WorldEntityPortraitUploadIntent = Readonly<{
	sha256: string;
	mimeType: WorldEntityMediaMime;
	bytes: number;
}>;

export type RequestWorldEntityPortraitUploadResult =
	| Readonly<{
			ok: true;
			uploadId: string;
			uploadUrl: string;
			expiresAt: string;
			method: "PUT";
			headers: Readonly<{ "Content-Type": WorldEntityMediaMime }>;
	  }>
	| Readonly<{ ok: false; reason: WorldEntityMediaUploadFailure }>;

export type FinalizeWorldEntityPortraitUploadResult =
	| Readonly<{
			ok: true;
			assetId: string;
			sha256: string;
			mimeType: WorldEntityMediaMime;
			bytes: number;
			width: number;
			height: number;
	  }>
	| Readonly<{ ok: false; reason: WorldEntityMediaUploadFailure }>;

type AuthorizedMediaEditor = Readonly<{
	authUserId: string;
	profileId: string;
}>;

type MediaAssetRow = Readonly<{
	id: string;
	status: "staged" | "verified_public" | "retired";
	role_hint: string;
	staged_bucket: string;
	object_key: string;
	sha256: string;
	mime_type: string;
	byte_size: number | string;
	width: number;
	height: number;
	read_back_verified: boolean;
}>;

function validIntent(intent: WorldEntityPortraitUploadIntent): boolean {
	return (
		isWorldEntityMediaSha256(intent.sha256) &&
		isWorldEntityMediaMime(intent.mimeType) &&
		Number.isSafeInteger(intent.bytes) &&
		intent.bytes >= 24 &&
		intent.bytes <= WORLD_ENTITY_MEDIA_MAX_BYTES
	);
}

async function authorizedMediaEditor(): Promise<
	| Readonly<{ ok: true; access: AuthorizedMediaEditor }>
	| Readonly<{ ok: false; reason: WorldEntityMediaUploadFailure }>
> {
	const [contentAccess, layoutAccess] = await Promise.all([
		authorizeCampaignCapabilityServer({
			action: EDIT_CAPABILITIES.contentEdit,
			campaignSlug: CAMPAIGN_SLUG,
		}),
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
	return {
		ok: true,
		access: {
			authUserId: contentAccess.authUserId,
			profileId: contentAccess.profileId,
		},
	};
}

async function campaignAndLeaseAllowEntity({
	client,
	profileId,
	leaseToken,
	entityId,
}: {
	client: SupabaseClient;
	profileId: string;
	leaseToken: string;
	entityId: string;
}): Promise<{ campaignId: string } | null> {
	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", CAMPAIGN_SLUG)
		.maybeSingle();
	if (campaignError) throw new Error(`campaign_lookup:${campaignError.message}`);
	if (!campaign?.id) return null;

	const { data: lease, error: leaseError } = await client
		.from("world_edit_leases")
		.select("draft_graph,expires_at,graph_draft_initialized")
		.eq("campaign_id", campaign.id)
		.eq("holder_profile_id", profileId)
		.eq("lease_token", leaseToken)
		.maybeSingle();
	if (leaseError) throw new Error(`lease_lookup:${leaseError.message}`);
	if (
		!lease ||
		lease.graph_draft_initialized !== true ||
		typeof lease.expires_at !== "string" ||
		Date.parse(lease.expires_at) <= Date.now()
	) {
		return null;
	}

	const draft = sanitizeWorldGraphDraft(lease.draft_graph);
	if (!draft) return null;
	const normalizedEntityId = entityId.toLowerCase();
	if (!draft.nodes.some((node) => node.id.toLowerCase() === normalizedEntityId)) return null;
	return { campaignId: campaign.id };
}

function sameVerifiedAsset(row: MediaAssetRow, upload: VerifiedWorldEntityUpload): boolean {
	return (
		row.status !== "retired" &&
		row.role_hint === "portrait" &&
		row.staged_bucket === upload.bucket &&
		row.object_key === upload.objectKey &&
		row.sha256 === upload.sha256 &&
		row.mime_type === upload.mimeType &&
		Number(row.byte_size) === upload.bytes &&
		row.width === upload.width &&
		row.height === upload.height &&
		row.read_back_verified === true
	);
}

async function existingAsset(
	client: SupabaseClient,
	campaignId: string,
	upload: VerifiedWorldEntityUpload,
): Promise<MediaAssetRow | null> {
	const { data, error } = await client
		.from("media_assets")
		.select(
			"id,status,role_hint,staged_bucket,object_key,sha256,mime_type,byte_size,width,height,read_back_verified",
		)
		.eq("campaign_id", campaignId)
		.eq("staged_bucket", upload.bucket)
		.eq("object_key", upload.objectKey)
		.maybeSingle();
	if (error) throw new Error(`asset_lookup:${error.message}`);
	return (data as MediaAssetRow | null) ?? null;
}

async function persistVerifiedAsset({
	client,
	campaignId,
	profileId,
	upload,
}: {
	client: SupabaseClient;
	campaignId: string;
	profileId: string;
	upload: VerifiedWorldEntityUpload;
}): Promise<string> {
	const current = await existingAsset(client, campaignId, upload);
	if (current) {
		if (!sameVerifiedAsset(current, upload)) {
			throw new Error("asset_identity_collision");
		}
		return current.id;
	}

	const { data, error } = await client
		.from("media_assets")
		.insert({
			campaign_id: campaignId,
			media_kind: "image",
			role_hint: "portrait",
			status: "staged",
			staged_bucket: upload.bucket,
			object_key: upload.objectKey,
			sha256: upload.sha256,
			mime_type: upload.mimeType,
			byte_size: upload.bytes,
			width: upload.width,
			height: upload.height,
			read_back_verified: true,
			created_by: profileId,
		})
		.select(
			"id,status,role_hint,staged_bucket,object_key,sha256,mime_type,byte_size,width,height,read_back_verified",
		)
		.maybeSingle();
	if (!error && data) {
		const inserted = data as MediaAssetRow;
		if (!sameVerifiedAsset(inserted, upload)) throw new Error("asset_insert_mismatch");
		return inserted.id;
	}

	// A concurrent finalizer can win the unique (campaign,bucket,key) insert.
	// Re-read the canonical identity instead of mutating an existing asset.
	const raced = await existingAsset(client, campaignId, upload);
	if (raced && sameVerifiedAsset(raced, upload)) return raced.id;
	throw new Error(`asset_insert:${error?.message ?? "unknown"}`);
}

export async function requestWorldEntityPortraitUploadAction(
	leaseToken: string,
	entityId: string,
	intent: WorldEntityPortraitUploadIntent,
): Promise<RequestWorldEntityPortraitUploadResult> {
	if (!worldEntityMediaEnabled()) return { ok: false, reason: "media_unavailable" };
	if (
		!isWorldEntityMediaAssetId(leaseToken) ||
		!isWorldEntityMediaAssetId(entityId) ||
		!validIntent(intent)
	) {
		return { ok: false, reason: "invalid_payload" };
	}

	const authorization = await authorizedMediaEditor();
	if (!authorization.ok) return authorization;
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	try {
		const scope = await campaignAndLeaseAllowEntity({
			client,
			profileId: authorization.access.profileId,
			leaseToken,
			entityId,
		});
		if (!scope) return { ok: false, reason: "lease_lost" };

		const uploadId = randomUUID();
		const signed = presignWorldEntityPortraitPendingUpload({
			campaignSlug: CAMPAIGN_SLUG,
			entityId,
			uploadId,
			sha256: intent.sha256,
			mimeType: intent.mimeType,
		});
		return {
			ok: true,
			uploadId,
			uploadUrl: signed.url,
			expiresAt: signed.expiresAt,
			method: "PUT",
			headers: signed.headers,
		};
	} catch (error) {
		console.error(
			"World entity portrait upload intent failed",
			error instanceof Error ? error.message : "unknown_error",
		);
		return { ok: false, reason: "dependency_unavailable" };
	}
}

export async function finalizeWorldEntityPortraitUploadAction(
	leaseToken: string,
	entityId: string,
	uploadId: string,
	intent: WorldEntityPortraitUploadIntent,
): Promise<FinalizeWorldEntityPortraitUploadResult> {
	if (!worldEntityMediaEnabled()) return { ok: false, reason: "media_unavailable" };
	if (
		!isWorldEntityMediaAssetId(leaseToken) ||
		!isWorldEntityMediaAssetId(entityId) ||
		!isWorldEntityMediaAssetId(uploadId) ||
		!validIntent(intent)
	) {
		return { ok: false, reason: "invalid_payload" };
	}

	const authorization = await authorizedMediaEditor();
	if (!authorization.ok) return authorization;
	const client = editDataClient();
	if (!client) return { ok: false, reason: "dependency_unavailable" };

	try {
		const scope = await campaignAndLeaseAllowEntity({
			client,
			profileId: authorization.access.profileId,
			leaseToken,
			entityId,
		});
		if (!scope) return { ok: false, reason: "lease_lost" };

		const upload = await finalizeWorldEntityPortraitPendingUpload({
			campaignSlug: CAMPAIGN_SLUG,
			entityId,
			uploadId,
			expectedSha256: intent.sha256,
			expectedMimeType: intent.mimeType,
			expectedBytes: intent.bytes,
		});
		const assetId = await persistVerifiedAsset({
			client,
			campaignId: scope.campaignId,
			profileId: authorization.access.profileId,
			upload,
		});
		return {
			ok: true,
			assetId,
			sha256: upload.sha256,
			mimeType: upload.mimeType,
			bytes: upload.bytes,
			width: upload.width,
			height: upload.height,
		};
	} catch (error) {
		console.error(
			"World entity portrait upload finalization failed",
			error instanceof Error ? error.message : "unknown_error",
		);
		return { ok: false, reason: "dependency_unavailable" };
	}
}
