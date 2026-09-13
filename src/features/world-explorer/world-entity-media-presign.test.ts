import { describe, expect, it } from "vitest";
import { presignR2PutObject } from "./world-entity-media-presign";

const ACCOUNT_ID = "0123456789abcdef0123456789abcdef";
const ACCESS_KEY_ID = "TESTACCESS1234567890";
const SECRET_ACCESS_KEY = "testsecretkey012345678901234567890123456";
const SHA256 = "a".repeat(64);
const OBJECT_KEY =
	`uploads/pending/world-entity/yuhara-main/11111111-1111-4111-8111-111111111111/` +
	`22222222-2222-4222-8222-222222222222/${SHA256}.webp`;

describe("World entity media R2 presigner", () => {
	it("matches the pinned S3 SigV4 query vector and signs Content-Type", () => {
		const signed = presignR2PutObject({
			accountId: ACCOUNT_ID,
			bucket: "tda-media-preview",
			objectKey: OBJECT_KEY,
			accessKeyId: ACCESS_KEY_ID,
			secretAccessKey: SECRET_ACCESS_KEY,
			contentType: "image/webp",
			expiresIn: 300,
			now: new Date("2026-09-12T21:00:00.000Z"),
		});
		const url = new URL(signed.url);

		expect(url.origin).toBe(`https://${ACCOUNT_ID}.r2.cloudflarestorage.com`);
		expect(url.pathname).toBe(`/tda-media-preview/${OBJECT_KEY}`);
		expect(url.searchParams.get("X-Amz-Algorithm")).toBe("AWS4-HMAC-SHA256");
		expect(url.searchParams.get("X-Amz-Date")).toBe("20260912T210000Z");
		expect(url.searchParams.get("X-Amz-Expires")).toBe("300");
		expect(url.searchParams.get("X-Amz-SignedHeaders")).toBe("content-type;host");
		expect(url.searchParams.get("X-Amz-Signature")).toBe(
			"34b859158ac70f9dcc5a6881181a50dd6c9b8c333fac0335899fea39ea04d15f",
		);
		expect(signed.headers).toEqual({ "Content-Type": "image/webp" });
		expect(signed.expiresAt).toBe("2026-09-12T21:05:00.000Z");
		expect(signed.url).not.toContain(SECRET_ACCESS_KEY);
	});

	it("binds the signature to MIME, object path and short expiry", () => {
		const base = {
			accountId: ACCOUNT_ID,
			bucket: "tda-media-preview",
			objectKey: OBJECT_KEY,
			accessKeyId: ACCESS_KEY_ID,
			secretAccessKey: SECRET_ACCESS_KEY,
			expiresIn: 300,
			now: new Date("2026-09-12T21:00:00.000Z"),
		} as const;
		const webp = presignR2PutObject({ ...base, contentType: "image/webp" });
		const png = presignR2PutObject({ ...base, contentType: "image/png" });
		const otherKey = presignR2PutObject({
			...base,
			objectKey: OBJECT_KEY.replace(SHA256, "b".repeat(64)),
			contentType: "image/webp",
		});

		expect(webp.url).not.toBe(png.url);
		expect(webp.url).not.toBe(otherKey.url);
		expect(() => presignR2PutObject({ ...base, contentType: "image/webp", expiresIn: 901 })).toThrow(
			"WORLD_ENTITY_MEDIA_INVALID_PRESIGN_EXPIRY",
		);
		expect(() =>
			presignR2PutObject({
				...base,
				objectKey: "uploads/pending/../escape.webp",
				contentType: "image/webp",
			}),
		).toThrow("WORLD_ENTITY_MEDIA_INVALID_PRESIGN_TARGET");
	});
});
