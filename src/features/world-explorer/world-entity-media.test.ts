import { describe, expect, it } from "vitest";
import {
	WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
	clampWorldEntityMediaFocalPoint,
	isWorldEntityMediaAssetId,
	worldEntityMediaObjectPosition,
	worldEntityMediaPreviewUrl,
	worldEntityMediaShouldBypassImageOptimization,
	worldEntityPortraitObjectKey,
	worldEntityPortraitPendingObjectKey,
	worldEntityPublicMediaUrl,
} from "./world-entity-media";

const CAMPAIGN_SLUG = "yuhara-main";
const ENTITY_ID = "11111111-1111-4111-8111-111111111111";
const ASSET_ID = "22222222-2222-4222-8222-222222222222";
const UPLOAD_ID = "33333333-3333-4333-8333-333333333333";
const SHA256 = "a".repeat(64);
const OBJECT_KEY = `campaigns/${CAMPAIGN_SLUG}/entities/${ENTITY_ID}/portrait/${SHA256}.webp`;

describe("World entity media contract", () => {
	it("uses stable asset ids for private preview URLs", () => {
		expect(isWorldEntityMediaAssetId(ASSET_ID)).toBe(true);
		expect(worldEntityMediaPreviewUrl(ASSET_ID)).toBe(`/api/world/entity-media/${ASSET_ID}`);
		expect(worldEntityMediaPreviewUrl("https://example.com/image.webp")).toBeUndefined();
	});

	it("bypasses Next image optimization only for authenticated private media previews", () => {
		expect(
			worldEntityMediaShouldBypassImageOptimization(`/api/world/entity-media/${ASSET_ID}`),
		).toBe(true);
		expect(
			worldEntityMediaShouldBypassImageOptimization(
				`https://media.dnd.faysk.dev/${OBJECT_KEY}`,
			),
		).toBe(false);
		expect(worldEntityMediaShouldBypassImageOptimization("/api/world/entity-media/not-a-uuid")).toBe(
			false,
		);
	});

	it("builds immutable portrait keys from campaign, canonical entity identity and content hash", () => {
		expect(
			worldEntityPortraitObjectKey({
				campaignSlug: CAMPAIGN_SLUG,
				entityId: ENTITY_ID,
				sha256: SHA256,
				extension: "webp",
			}),
		).toBe(OBJECT_KEY);
		expect(
			worldEntityPortraitObjectKey({
				campaignSlug: "../escape",
				entityId: ENTITY_ID,
				sha256: SHA256,
				extension: "webp",
			}),
		).toBeNull();
	});

	it("keeps browser uploads on unique pending keys instead of canonical portrait keys", () => {
		expect(
			worldEntityPortraitPendingObjectKey({
				campaignSlug: CAMPAIGN_SLUG,
				entityId: ENTITY_ID,
				uploadId: UPLOAD_ID,
				sha256: SHA256,
				extension: "webp",
			}),
		).toBe(
			`uploads/pending/world-entity/${CAMPAIGN_SLUG}/${ENTITY_ID}/${UPLOAD_ID}/${SHA256}.webp`,
		);
		expect(
			worldEntityPortraitPendingObjectKey({
				campaignSlug: CAMPAIGN_SLUG,
				entityId: ENTITY_ID,
				uploadId: "not-a-uuid",
				sha256: SHA256,
				extension: "webp",
			}),
		).toBeNull();
	});

	it("only exposes verified public R2 assets for the matching campaign and entity", () => {
		const verified = {
			status: "verified_public" as const,
			publicBucket: WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
			publicObjectKey: OBJECT_KEY,
			sha256: SHA256,
			readBackVerified: true,
			publicDeliveryVerified: true,
			publicVerifiedAt: "2026-09-12T19:00:00.000Z",
		};
		expect(
			worldEntityPublicMediaUrl(verified, {
				campaignSlug: CAMPAIGN_SLUG,
				entityId: ENTITY_ID,
			}),
		).toBe(`https://media.dnd.faysk.dev/${OBJECT_KEY}`);
		expect(
			worldEntityPublicMediaUrl(verified, {
				campaignSlug: CAMPAIGN_SLUG,
				entityId: "44444444-4444-4444-8444-444444444444",
			}),
		).toBeUndefined();
		expect(
			worldEntityPublicMediaUrl(verified, {
				campaignSlug: "outra-campanha",
				entityId: ENTITY_ID,
			}),
		).toBeUndefined();
		expect(
			worldEntityPublicMediaUrl(
				{ ...verified, publicDeliveryVerified: false },
				{ campaignSlug: CAMPAIGN_SLUG, entityId: ENTITY_ID },
			),
		).toBeUndefined();
		expect(
			worldEntityPublicMediaUrl(
				{
					...verified,
					publicObjectKey: `campaigns/${CAMPAIGN_SLUG}/entities/------------------------------------/portrait/${SHA256}.webp`,
				},
				{ campaignSlug: CAMPAIGN_SLUG },
			),
		).toBeUndefined();
	});

	it("keeps focal points normalized", () => {
		expect(clampWorldEntityMediaFocalPoint(-0.4)).toBe(0);
		expect(clampWorldEntityMediaFocalPoint(0.42)).toBe(0.42);
		expect(clampWorldEntityMediaFocalPoint(2)).toBe(1);
		expect(clampWorldEntityMediaFocalPoint(Number.NaN)).toBe(0.5);
		expect(worldEntityMediaObjectPosition()).toBe("50% 50%");
		expect(worldEntityMediaObjectPosition({ x: 0.2, y: 0.75 })).toBe("20% 75%");
		expect(worldEntityMediaObjectPosition({ x: -2, y: 4 })).toBe("0% 100%");
	});
});
