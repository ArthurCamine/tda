import { createHash } from "node:crypto";
import {
	WORLD_ENTITY_MEDIA_MAX_BYTES,
	WORLD_ENTITY_MEDIA_MAX_DIMENSION,
	type WorldEntityMediaMime,
} from "./world-entity-media";

export type WorldEntityImageInfo = Readonly<{
	sha256: string;
	mimeType: WorldEntityMediaMime;
	extension: "png" | "webp";
	bytes: number;
	width: number;
	height: number;
}>;

function failure(code: string): never {
	throw new Error(`WORLD_ENTITY_MEDIA_${code}`);
}

export function worldEntityMediaSha256(bytes: Uint8Array): string {
	return createHash("sha256").update(bytes).digest("hex");
}

function readUint24LE(bytes: Uint8Array, offset: number): number {
	return bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16);
}

function webpDimensions(bytes: Uint8Array): { width: number; height: number } | null {
	let offset = 12;
	while (offset + 8 <= bytes.length) {
		const chunk = Buffer.from(bytes.subarray(offset, offset + 4)).toString("ascii");
		const size = Buffer.from(bytes.subarray(offset + 4, offset + 8)).readUInt32LE(0);
		const data = offset + 8;
		if (data + size > bytes.length) return null;

		if (chunk === "VP8X" && size >= 10) {
			return {
				width: readUint24LE(bytes, data + 4) + 1,
				height: readUint24LE(bytes, data + 7) + 1,
			};
		}
		if (
			chunk === "VP8 " &&
			size >= 10 &&
			bytes[data + 3] === 0x9d &&
			bytes[data + 4] === 0x01 &&
			bytes[data + 5] === 0x2a
		) {
			return {
				width: (bytes[data + 6] | (bytes[data + 7] << 8)) & 0x3fff,
				height: (bytes[data + 8] | (bytes[data + 9] << 8)) & 0x3fff,
			};
		}
		if (chunk === "VP8L" && size >= 5 && bytes[data] === 0x2f) {
			const b1 = bytes[data + 1];
			const b2 = bytes[data + 2];
			const b3 = bytes[data + 3];
			const b4 = bytes[data + 4];
			return {
				width: 1 + (((b2 & 0x3f) << 8) | b1),
				height: 1 + (((b4 & 0x0f) << 10) | (b3 << 2) | ((b2 & 0xc0) >> 6)),
			};
		}

		offset = data + size + (size % 2);
	}
	return null;
}

function validDimensions(width: number, height: number): boolean {
	return (
		Number.isSafeInteger(width) &&
		Number.isSafeInteger(height) &&
		width >= 1 &&
		height >= 1 &&
		width <= WORLD_ENTITY_MEDIA_MAX_DIMENSION &&
		height <= WORLD_ENTITY_MEDIA_MAX_DIMENSION
	);
}

/**
 * Validates the bytes themselves rather than trusting filename or HTTP MIME.
 * This module intentionally imports node:crypto so accidental Client Component
 * imports fail at build time instead of weakening the upload boundary.
 */
export function inspectWorldEntityImage(bytes: Uint8Array): WorldEntityImageInfo {
	if (bytes.length < 24 || bytes.length > WORLD_ENTITY_MEDIA_MAX_BYTES) {
		failure("INVALID_SIZE");
	}

	const pngSignature = Buffer.from("89504e470d0a1a0a", "hex");
	const isPng = Buffer.from(bytes.subarray(0, 8)).equals(pngSignature);
	if (isPng) {
		if (
			Buffer.from(bytes.subarray(12, 16)).toString("ascii") !== "IHDR" ||
			Buffer.from(bytes.subarray(8, 12)).readUInt32BE(0) !== 13
		) {
			failure("INVALID_PNG");
		}
		const width = Buffer.from(bytes.subarray(16, 20)).readUInt32BE(0);
		const height = Buffer.from(bytes.subarray(20, 24)).readUInt32BE(0);
		if (!validDimensions(width, height)) failure("INVALID_DIMENSIONS");
		return {
			sha256: worldEntityMediaSha256(bytes),
			mimeType: "image/png",
			extension: "png",
			bytes: bytes.length,
			width,
			height,
		};
	}

	const isWebp =
		Buffer.from(bytes.subarray(0, 4)).toString("ascii") === "RIFF" &&
		Buffer.from(bytes.subarray(8, 12)).toString("ascii") === "WEBP";
	if (!isWebp) failure("UNSUPPORTED_IMAGE");

	const declaredSize = Buffer.from(bytes.subarray(4, 8)).readUInt32LE(0) + 8;
	if (declaredSize !== bytes.length) failure("INVALID_WEBP");
	const dimensions = webpDimensions(bytes);
	if (!dimensions || !validDimensions(dimensions.width, dimensions.height)) {
		failure("INVALID_DIMENSIONS");
	}
	return {
		sha256: worldEntityMediaSha256(bytes),
		mimeType: "image/webp",
		extension: "webp",
		bytes: bytes.length,
		width: dimensions.width,
		height: dimensions.height,
	};
}
