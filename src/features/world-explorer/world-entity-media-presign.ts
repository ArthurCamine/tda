import { createHash, createHmac } from "node:crypto";
import type { WorldEntityMediaMime } from "./world-entity-media";

const R2_ACCOUNT_PATTERN = /^[a-f0-9]{32}$/u;
const BUCKET_PATTERN = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/u;
const MAX_PRESIGN_SECONDS = 900;

export type R2PresignedPut = Readonly<{
	url: string;
	expiresAt: string;
	headers: Readonly<{ "Content-Type": WorldEntityMediaMime }>;
}>;

function rfc3986(value: string): string {
	return encodeURIComponent(value).replace(/[!'()*]/gu, (character) =>
		`%${character.charCodeAt(0).toString(16).toUpperCase()}`,
	);
}

function canonicalObjectPath(bucket: string, objectKey: string): string {
	if (
		!BUCKET_PATTERN.test(bucket) ||
		!objectKey ||
		objectKey.startsWith("/") ||
		objectKey.split("/").some((segment) => !segment || segment === "." || segment === "..")
	) {
		throw new Error("WORLD_ENTITY_MEDIA_INVALID_PRESIGN_TARGET");
	}
	return `/${rfc3986(bucket)}/${objectKey.split("/").map(rfc3986).join("/")}`;
}

function sha256(value: string): string {
	return createHash("sha256").update(value, "utf8").digest("hex");
}

function hmac(key: string | Uint8Array, value: string): Buffer {
	return createHmac("sha256", key).update(value, "utf8").digest();
}

function signingKey(secretAccessKey: string, dateStamp: string): Buffer {
	const dateKey = hmac(`AWS4${secretAccessKey}`, dateStamp);
	const regionKey = hmac(dateKey, "auto");
	const serviceKey = hmac(regionKey, "s3");
	return hmac(serviceKey, "aws4_request");
}

function amzTimestamp(date: Date): string {
	if (!Number.isFinite(date.getTime())) throw new Error("WORLD_ENTITY_MEDIA_INVALID_PRESIGN_DATE");
	return date.toISOString().replace(/[:-]|\.\d{3}/gu, "");
}

function compareEncodedQueryEntry(
	[leftKey, leftValue]: readonly [string, string],
	[rightKey, rightValue]: readonly [string, string],
): number {
	if (leftKey < rightKey) return -1;
	if (leftKey > rightKey) return 1;
	if (leftValue < rightValue) return -1;
	if (leftValue > rightValue) return 1;
	return 0;
}

/**
 * Produces the same S3 SigV4 query contract used by R2 presigned PUT URLs.
 * The browser receives only the bearer URL plus the signed Content-Type;
 * R2 credentials never leave this server-side call chain.
 */
export function presignR2PutObject({
	accountId,
	bucket,
	objectKey,
	accessKeyId,
	secretAccessKey,
	contentType,
	expiresIn,
	now = new Date(),
}: {
	accountId: string;
	bucket: string;
	objectKey: string;
	accessKeyId: string;
	secretAccessKey: string;
	contentType: WorldEntityMediaMime;
	expiresIn: number;
	now?: Date;
}): R2PresignedPut {
	if (!R2_ACCOUNT_PATTERN.test(accountId)) {
		throw new Error("WORLD_ENTITY_MEDIA_INVALID_R2_ACCOUNT");
	}
	if (!accessKeyId || /\s/u.test(accessKeyId) || !secretAccessKey) {
		throw new Error("WORLD_ENTITY_MEDIA_INVALID_R2_CREDENTIALS");
	}
	if (!Number.isSafeInteger(expiresIn) || expiresIn < 1 || expiresIn > MAX_PRESIGN_SECONDS) {
		throw new Error("WORLD_ENTITY_MEDIA_INVALID_PRESIGN_EXPIRY");
	}
	if (contentType !== "image/png" && contentType !== "image/webp") {
		throw new Error("WORLD_ENTITY_MEDIA_INVALID_PRESIGN_MIME");
	}

	const host = `${accountId}.r2.cloudflarestorage.com`;
	const canonicalUri = canonicalObjectPath(bucket, objectKey);
	const timestamp = amzTimestamp(now);
	const dateStamp = timestamp.slice(0, 8);
	const credentialScope = `${dateStamp}/auto/s3/aws4_request`;
	const signedHeaders = "content-type;host";
	const queryEntries = [
		["X-Amz-Algorithm", "AWS4-HMAC-SHA256"],
		["X-Amz-Credential", `${accessKeyId}/${credentialScope}`],
		["X-Amz-Date", timestamp],
		["X-Amz-Expires", String(expiresIn)],
		["X-Amz-SignedHeaders", signedHeaders],
	] as const;
	const canonicalQuery = queryEntries
		.map(([key, value]) => [rfc3986(key), rfc3986(value)] as const)
		.sort(compareEncodedQueryEntry)
		.map(([key, value]) => `${key}=${value}`)
		.join("&");
	const canonicalHeaders = `content-type:${contentType}\nhost:${host}\n`;
	const canonicalRequest = [
		"PUT",
		canonicalUri,
		canonicalQuery,
		canonicalHeaders,
		signedHeaders,
		"UNSIGNED-PAYLOAD",
	].join("\n");
	const stringToSign = [
		"AWS4-HMAC-SHA256",
		timestamp,
		credentialScope,
		sha256(canonicalRequest),
	].join("\n");
	const signature = createHmac("sha256", signingKey(secretAccessKey, dateStamp))
		.update(stringToSign, "utf8")
		.digest("hex");
	const url = `https://${host}${canonicalUri}?${canonicalQuery}&X-Amz-Signature=${signature}`;

	return {
		url,
		expiresAt: new Date(now.getTime() + expiresIn * 1000).toISOString(),
		headers: { "Content-Type": contentType },
	};
}
