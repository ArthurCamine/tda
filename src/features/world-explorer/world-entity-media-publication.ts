import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";
import { CAMPAIGN_SLUG } from "@/features/sessions/model";
import type { WorldGraphDraft } from "./model";
import {
	WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
	worldEntityMediaCanBecomePublic,
	worldEntityPortraitObjectKey,
	worldEntityPublicMediaUrl,
} from "./world-entity-media";
import {
	promoteWorldEntityPortrait,
	worldEntityMediaEnabled,
} from "./world-entity-media-server";

export type WorldEntityMediaPublishBinding = Readonly<{
	entityId: string;
	assetId: string | null;
	focalX: number;
	focalY: number;
}>;

export type PreparedWorldEntityMedia =
	| Readonly<{ status: "unchanged"; bindings: readonly WorldEntityMediaPublishBinding[] }>
	| Readonly<{ status: "ready"; bindings: readonly WorldEntityMediaPublishBinding[] }>
	| Readonly<{ status: "pending"; bindings: readonly WorldEntityMediaPublishBinding[] }>;

type AssetRow = Readonly<{
	id: string;
	campaign_id: string;
	status: "staged" | "verified_public" | "retired";
	staged_bucket: string;
	object_key: string;
	sha256: string;
	mime_type: "image/png" | "image/webp";
	byte_size: number | string;
	width: number;
	height: number;
	read_back_verified: boolean;
	public_bucket: string | null;
	public_object_key: string | null;
	public_delivery_verified: boolean;
	public_verified_at: string | null;
}>;

function extensionFor(mimeType: AssetRow["mime_type"]): "png" | "webp" {
	return mimeType === "image/png" ? "png" : "webp";
}

function safeAssetForEntity(
	asset: AssetRow,
	campaignSlug: string,
	entityId: string,
): boolean {
	const expected = worldEntityPortraitObjectKey({
		campaignSlug,
		entityId,
		sha256: asset.sha256,
		extension: extensionFor(asset.mime_type),
	});
	return Boolean(
		expected &&
		asset.object_key === expected &&
		asset.status !== "retired" &&
		asset.read_back_verified === true &&
		Number.isSafeInteger(Number(asset.byte_size)) &&
		Number(asset.byte_size) > 0 &&
		asset.width > 0 &&
		asset.height > 0,
	);
}

/**
 * Prepares external media BEFORE the atomic graph publication consumes the
 * lease. Public bytes may be copied to their immutable public key here, but no
 * entity binding changes until the combined PostgreSQL RPC succeeds.
 *
 * If public promotion/read-back fails, publication stays fail-closed and the
 * World lease/draft remains available for retry instead of losing media intent.
 */
export async function prepareWorldEntityMediaForPublish({
	client,
	draft,
}: {
	client: SupabaseClient;
	draft: WorldGraphDraft;
}): Promise<PreparedWorldEntityMedia> {
	if (!worldEntityMediaEnabled()) return { status: "unchanged", bindings: [] };

	const requested = draft.nodes
		.filter((node) => node.primaryMediaAssetId !== undefined)
		.map((node) => ({
			entityId: node.id,
			assetId: node.primaryMediaAssetId ?? null,
			visibility: node.visibility,
			focalX: node.primaryMediaFocalPoint?.x ?? 0.5,
			focalY: node.primaryMediaFocalPoint?.y ?? 0.5,
		}));
	const bindings = requested.map(({ entityId, assetId, focalX, focalY }) => ({
		entityId,
		assetId,
		focalX,
		focalY,
	}));
	if (!requested.length) return { status: "ready", bindings };

	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", CAMPAIGN_SLUG)
		.maybeSingle();
	if (campaignError || !campaign?.id) {
		console.error(
			"World entity media publication campaign lookup failed",
			campaignError?.message,
		);
		return { status: "pending", bindings };
	}

	const requestedAssetIds = [
		...new Set(requested.flatMap((binding) => (binding.assetId ? [binding.assetId] : []))),
	];
	let assetRows: AssetRow[] = [];
	if (requestedAssetIds.length) {
		const { data, error } = await client
			.from("media_assets")
			.select(
				"id,campaign_id,status,staged_bucket,object_key,sha256,mime_type,byte_size,width,height,read_back_verified,public_bucket,public_object_key,public_delivery_verified,public_verified_at",
			)
			.eq("campaign_id", campaign.id)
			.in("id", requestedAssetIds);
		if (error) {
			console.error("World entity media publication asset lookup failed", error.message);
			return { status: "pending", bindings };
		}
		assetRows = (data ?? []) as AssetRow[];
		if (assetRows.length !== requestedAssetIds.length) {
			return { status: "pending", bindings };
		}
	}

	const assetById = new Map(assetRows.map((asset) => [asset.id, asset]));
	for (const binding of requested) {
		if (!binding.assetId) continue;
		const asset = assetById.get(binding.assetId);
		if (!asset || !safeAssetForEntity(asset, CAMPAIGN_SLUG, binding.entityId)) {
			return { status: "pending", bindings };
		}
		if (!worldEntityMediaCanBecomePublic(binding.visibility)) continue;

		const alreadyVerified =
			asset.status === "verified_public" &&
			Boolean(
				worldEntityPublicMediaUrl(
					{
						status: asset.status,
						publicBucket: asset.public_bucket,
						publicObjectKey: asset.public_object_key,
						sha256: asset.sha256,
						readBackVerified: asset.read_back_verified,
						publicDeliveryVerified: asset.public_delivery_verified,
						publicVerifiedAt: asset.public_verified_at,
					},
					{ campaignSlug: CAMPAIGN_SLUG, entityId: binding.entityId },
				),
			);
		if (alreadyVerified) continue;
		if (asset.status !== "staged") return { status: "pending", bindings };

		try {
			const promoted = await promoteWorldEntityPortrait({
				campaignSlug: CAMPAIGN_SLUG,
				entityId: binding.entityId,
				stagedBucket: asset.staged_bucket,
				objectKey: asset.object_key,
				info: {
					sha256: asset.sha256,
					mimeType: asset.mime_type,
					extension: extensionFor(asset.mime_type),
					bytes: Number(asset.byte_size),
					width: asset.width,
					height: asset.height,
				},
			});
			const { error: updateError } = await client
				.from("media_assets")
				.update({
					status: "verified_public",
					public_bucket: WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
					public_object_key: promoted.publicObjectKey,
					public_delivery_verified: true,
					public_verified_at: promoted.verifiedAt,
					updated_at: promoted.verifiedAt,
				})
				.eq("id", asset.id)
				.eq("campaign_id", campaign.id)
				.eq("status", "staged");
			if (updateError) {
				console.error(
					"World entity media verification persistence failed",
					updateError.message,
				);
				return { status: "pending", bindings };
			}
		} catch (error) {
			console.error(
				"World entity media promotion failed",
				error instanceof Error ? error.message : "unknown_error",
			);
			return { status: "pending", bindings };
		}
	}

	return { status: "ready", bindings };
}
