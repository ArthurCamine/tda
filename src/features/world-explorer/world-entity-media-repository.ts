import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";
import type { WorldGraphDraft, WorldMediaFocalPoint } from "./model";
import {
	clampWorldEntityMediaFocalPoint,
	worldEntityPublicMediaUrl,
	type WorldEntityMediaAssetRecord,
} from "./world-entity-media";

type MediaBindingRow = Readonly<{
	entity_id: string;
	asset_id: string;
	focal_x: number | string;
	focal_y: number | string;
}>;

type MediaAssetRow = Readonly<{
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

export type WorldEntityPortraitPresentation = Readonly<{
	imageUrl: string;
	focalPoint: WorldMediaFocalPoint;
}>;

export function worldEntityMediaEnabled(): boolean {
	return process.env.TDA_WORLD_ENTITY_MEDIA_ENABLED === "true";
}

function focalPoint(row: MediaBindingRow): WorldMediaFocalPoint {
	return {
		x: clampWorldEntityMediaFocalPoint(Number(row.focal_x)),
		y: clampWorldEntityMediaFocalPoint(Number(row.focal_y)),
	};
}

function toAssetRecord(row: MediaAssetRow): WorldEntityMediaAssetRecord | null {
	const bytes = Number(row.byte_size);
	if (!Number.isSafeInteger(bytes) || bytes <= 0) return null;
	if (!Number.isSafeInteger(row.width) || row.width <= 0) return null;
	if (!Number.isSafeInteger(row.height) || row.height <= 0) return null;
	return {
		id: row.id,
		campaignId: row.campaign_id,
		stagedBucket: row.staged_bucket,
		objectKey: row.object_key,
		sha256: row.sha256,
		mimeType: row.mime_type,
		bytes,
		width: row.width,
		height: row.height,
		status: row.status,
		publicBucket: row.public_bucket,
		publicObjectKey: row.public_object_key,
		readBackVerified: row.read_back_verified,
		publicDeliveryVerified: row.public_delivery_verified,
		publicVerifiedAt: row.public_verified_at,
	};
}

async function loadBindings(
	client: SupabaseClient,
	campaignId: string,
	entityIds: readonly string[],
): Promise<MediaBindingRow[]> {
	if (!worldEntityMediaEnabled() || entityIds.length === 0) return [];
	const { data, error } = await client
		.from("entity_media_bindings")
		.select("entity_id,asset_id,focal_x,focal_y")
		.eq("campaign_id", campaignId)
		.eq("role", "portrait")
		.in("entity_id", [...entityIds]);
	if (error) throw new Error(`World entity media binding lookup failed: ${error.message}`);
	return (data ?? []) as MediaBindingRow[];
}

export async function hydrateWorldGraphDraftMedia(
	client: SupabaseClient,
	campaignSlug: string,
	draft: WorldGraphDraft,
): Promise<WorldGraphDraft> {
	if (!worldEntityMediaEnabled() || draft.nodes.length === 0) return draft;
	const { data: campaign, error: campaignError } = await client
		.from("campaigns")
		.select("id")
		.eq("slug", campaignSlug)
		.maybeSingle();
	if (campaignError || !campaign?.id) {
		throw new Error(
			`World entity media campaign lookup failed: ${campaignError?.message ?? "campaign_not_found"}`,
		);
	}
	const bindings = await loadBindings(
		client,
		campaign.id,
		draft.nodes.map((node) => node.id),
	);
	const bindingByEntity = new Map(bindings.map((binding) => [binding.entity_id, binding]));
	return {
		...draft,
		nodes: draft.nodes.map((node) => {
			if (node.primaryMediaAssetId !== undefined) return node;
			const binding = bindingByEntity.get(node.id);
			return binding
				? {
						...node,
						primaryMediaAssetId: binding.asset_id,
						primaryMediaFocalPoint: focalPoint(binding),
					}
				: node;
		}),
	};
}

/**
 * Resolves only explicitly bound and verified public portraits.
 * Provider URLs are never read from entity metadata or accepted from callers.
 */
export async function loadWorldEntityPortraitPresentations(
	client: SupabaseClient,
	campaignId: string,
	campaignSlug: string,
	entityIds: readonly string[],
): Promise<Map<string, WorldEntityPortraitPresentation>> {
	const bindings = await loadBindings(client, campaignId, entityIds);
	if (!bindings.length) return new Map();

	const assetIds = [...new Set(bindings.map((binding) => binding.asset_id))];
	const { data: assetData, error: assetError } = await client
		.from("media_assets")
		.select(
			"id,campaign_id,status,staged_bucket,object_key,sha256,mime_type,byte_size,width,height,read_back_verified,public_bucket,public_object_key,public_delivery_verified,public_verified_at",
		)
		.eq("campaign_id", campaignId)
		.in("id", assetIds);
	if (assetError) throw new Error(`World entity media asset lookup failed: ${assetError.message}`);

	const byId = new Map(
		((assetData ?? []) as MediaAssetRow[])
			.map((row) => [row.id, toAssetRecord(row)] as const)
			.filter((entry): entry is readonly [string, WorldEntityMediaAssetRecord] => Boolean(entry[1])),
	);
	const presentations = new Map<string, WorldEntityPortraitPresentation>();
	for (const binding of bindings) {
		const asset = byId.get(binding.asset_id);
		if (!asset) continue;
		const imageUrl = worldEntityPublicMediaUrl(asset, {
			campaignSlug,
			entityId: binding.entity_id,
		});
		if (!imageUrl) continue;
		presentations.set(binding.entity_id, {
			imageUrl,
			focalPoint: focalPoint(binding),
		});
	}
	return presentations;
}
