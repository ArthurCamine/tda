import { describe, expect, it } from "vitest";
import { inspectWorldEntityImage } from "./world-entity-media-image";

function png(width: number, height: number): Uint8Array {
	const bytes = Buffer.alloc(24);
	Buffer.from("89504e470d0a1a0a", "hex").copy(bytes, 0);
	bytes.writeUInt32BE(13, 8);
	bytes.write("IHDR", 12, "ascii");
	bytes.writeUInt32BE(width, 16);
	bytes.writeUInt32BE(height, 20);
	return bytes;
}

function writeUint24LE(bytes: Buffer, offset: number, value: number) {
	bytes[offset] = value & 0xff;
	bytes[offset + 1] = (value >> 8) & 0xff;
	bytes[offset + 2] = (value >> 16) & 0xff;
}

function webpVp8x(width: number, height: number): Uint8Array {
	const bytes = Buffer.alloc(30);
	bytes.write("RIFF", 0, "ascii");
	bytes.writeUInt32LE(bytes.length - 8, 4);
	bytes.write("WEBP", 8, "ascii");
	bytes.write("VP8X", 12, "ascii");
	bytes.writeUInt32LE(10, 16);
	writeUint24LE(bytes, 24, width - 1);
	writeUint24LE(bytes, 27, height - 1);
	return bytes;
}

describe("World entity media byte inspection", () => {
	it("identifies PNG by bytes and extracts dimensions", () => {
		const result = inspectWorldEntityImage(png(640, 960));
		expect(result).toMatchObject({
			mimeType: "image/png",
			extension: "png",
			bytes: 24,
			width: 640,
			height: 960,
		});
		expect(result.sha256).toMatch(/^[a-f0-9]{64}$/u);
	});

	it("identifies VP8X WebP and does not trust a filename or HTTP MIME", () => {
		const result = inspectWorldEntityImage(webpVp8x(1024, 1024));
		expect(result).toMatchObject({
			mimeType: "image/webp",
			extension: "webp",
			bytes: 30,
			width: 1024,
			height: 1024,
		});
	});

	it("rejects unsupported bytes and invalid WebP container lengths", () => {
		expect(() => inspectWorldEntityImage(Buffer.alloc(24, 0x3c))).toThrow(
			"WORLD_ENTITY_MEDIA_UNSUPPORTED_IMAGE",
		);
		const badWebp = Buffer.from(webpVp8x(512, 512));
		badWebp.writeUInt32LE(999, 4);
		expect(() => inspectWorldEntityImage(badWebp)).toThrow(
			"WORLD_ENTITY_MEDIA_INVALID_WEBP",
		);
	});

	it("rejects dimensions beyond the media contract", () => {
		expect(() => inspectWorldEntityImage(png(16_385, 512))).toThrow(
			"WORLD_ENTITY_MEDIA_INVALID_DIMENSIONS",
		);
		expect(() => inspectWorldEntityImage(webpVp8x(512, 16_385))).toThrow(
			"WORLD_ENTITY_MEDIA_INVALID_DIMENSIONS",
		);
	});
});
