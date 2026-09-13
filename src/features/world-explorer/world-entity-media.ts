import type { WorldVisibility } from "./model";

export const WORLD_ENTITY_MEDIA_ROLE = "portrait" as const;
export const WORLD_ENTITY_MEDIA_PUBLIC_BUCKET = "tda-media-public" as const;
export const WORLD_ENTITY_MEDIA_PREVIEW_BUCKET = "tda-media-preview" as const;
export const WORLD_ENTITY_MEDIA_PRIVATE_BUCKET = "tda-media-private" as const;
export const WORLD_ENTITY_MEDIA_PUBLIC_ORIGIN = "https://media.dnd.faysk.dev" as const;
export const WORLD_ENTITY_MEDIA_MAX_BYTES = 8 * 1024 * 1024;
export const WORLD_ENTITY_MEDIA_MAX_DIMENSION = 16_384;
export const WORLD_ENTITY_MEDIA_UPLOAD_EXPIRES_SECONDS = 300;

const UUID_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const CAMPAIGN_SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,95}$/u;

export type WorldEntityMediaMime = "image/png" | "image/webp";
export type WorldEntityMediaStatus = "staged" | "verified_public" | "retired";

export type WorldEntityMediaAssetRecord = Readonly<{
	id: string;
	campaignId: string;
	stagedBucket: string;
	objectKey: string;
	sha256: string;
	mimeType: WorldEntityMediaMime;
	bytes: number;
	width: number;
	height: number;
	status: WorldEntityMediaStatus;
	publicBucket: string | null;
	publicObjectKey: string | null;
	readBackVerified: boolean;
	publicDeliveryVerified: boolean;
	publicVerifiedAt: string | null;
}>;

export type WorldEntityPortraitBinding = Readonly<{
	entityId: string;
	assetId: string;
	focalX: number;
	focalY: number;
}>;

export function isWorldEntityMediaAssetId(value: unknown): value is string {
	return typeof value === "string" && UUID_PATTERN.test(value);
}

export function isWorldEntityMediaSha256(value: unknown): value is string {
	return typeof value === "string" && SHA256_PATTERN.test(value);
}

export function isWorldEntityMediaMime(value: unknown): value is WorldEntityMediaMime {
	return value === "image/png" || value === "image/webp";
}

export function worldEntityMediaPreviewUrl(assetId: string): string | undefined {
	if (!isWorldEntityMediaAssetId(assetId)) return undefined;
	return `/api/world/entity-media/${encodeURIComponent(assetId.toLowerCase())}`;
}

/**
 * Next/Image does not forward request headers to authenticated source URLs.
 * Draft portraits therefore bypass the optimizer while the public immutable R2
 * URL continues through the normal optimized path.
 */
export function worldEntityMediaShouldBypassImageOptimization(imageUrl: string): boolean {
	const prefix = "/api/world/entity-media/";
	if (!imageUrl.startsWith(prefix)) return false;
	return isWorldEntityMediaAssetId(imageUrl.slice(prefix.length));
}

export function worldEntityPortraitObjectKey({
	campaignSlug,
	entityId,
	sha256,
	extension,
}: {
	campaignSlug: string;
	entityId: string;
	sha256: string;
	extension: "png" | "webp";
}): string | null {
	if (!CAMPAIGN_SLUG_PATTERN.test(campaignSlug)) return null;
	if (!isWorldEntityMediaAssetId(entityId) || !SHA256_PATTERN.test(sha256)) return null;
	return `campaigns/${campaignSlug}/entities/${entityId.toLowerCase()}/portrait/${sha256}.${extension}`;
}

export function worldEntityPortraitPendingObjectKey({
	campaignSlug,
	entityId,
	uploadId,
	sha256,
	extension,
}: {
	campaignSlug: string;
	entityId: string;
	uploadId: string;
	sha256: string;
	extension: "png" | "webp";
}): string | null {
	if (!CAMPAIGN_SLUG_PATTERN.test(campaignSlug)) return null;
	if (
		!isWorldEntityMediaAssetId(entityId) ||
		!isWorldEntityMediaAssetId(uploadId) ||
		!SHA256_PATTERN.test(sha256)
	) {
		return null;
	}
	return `uploads/pending/world-entity/${campaignSlug}/${entityId.toLowerCase()}/${uploadId.toLowerCase()}/${sha256}.${extension}`;
}

export function worldEntityPublicMediaUrl(
	asset: Pick<
		WorldEntityMediaAssetRecord,
		| "status"
		| "publicBucket"
		| "publicObjectKey"
		| "sha256"
		| "readBackVerified"
		| "publicDeliveryVerified"
		| "publicVerifiedAt"
	>,
	options: { campaignSlug: string; entityId?: string },
): string | undefined {
	if (
		asset.status !== "verified_public" ||
		asset.publicBucket !== WORLD_ENTITY_MEDIA_PUBLIC_BUCKET ||
		!asset.publicObjectKey ||
		!asset.readBackVerified ||
		!asset.publicDeliveryVerified ||
		!asset.publicVerifiedAt ||
		Number.isNaN(Date.parse(asset.publicVerifiedAt)) ||
		!SHA256_PATTERN.test(asset.sha256) ||
		!CAMPAIGN_SLUG_PATTERN.test(options.campaignSlug)
	) {
		return undefined;
	}

	// Campaign slugs are restricted to [a-z0-9-], so they are safe to interpolate
	// into this anchored expression without generic regex escaping.
	const pattern = new RegExp(
		`^campaigns/${options.campaignSlug}/entities/([0-9a-f-]{36})/portrait/([a-f0-9]{64})\\.(png|webp)$`,
		"u",
	);
	const match = pattern.exec(asset.publicObjectKey);
	if (!match || !isWorldEntityMediaAssetId(match[1]) || match[2] !== asset.sha256) {
		return undefined;
	}
	if (
		options.entityId &&
		(!isWorldEntityMediaAssetId(options.entityId) || match[1] !== options.entityId.toLowerCase())
	) {
		return undefined;
	}
	return `${WORLD_ENTITY_MEDIA_PUBLIC_ORIGIN}/${asset.publicObjectKey}`;
}

export function worldEntityMediaCanBecomePublic(visibility: WorldVisibility): boolean {
	return visibility === "public_web";
}

export function clampWorldEntityMediaFocalPoint(value: number): number {
	if (!Number.isFinite(value)) return 0.5;
	return Math.min(1, Math.max(0, value));
}

export function worldEntityMediaObjectPosition(
	focalPoint?: Readonly<{ x: number; y: number }>,
): string {
	const x = clampWorldEntityMediaFocalPoint(focalPoint?.x ?? 0.5);
	const y = clampWorldEntityMediaFocalPoint(focalPoint?.y ?? 0.5);
	return `${x * 100}% ${y * 100}%`;
}
