import "server-only";

import {
	GetObjectCommand,
	HeadObjectCommand,
	PutObjectCommand,
	type S3Client,
} from "@aws-sdk/client-s3";
import { mediaClient, mediaConnectionConfig } from "@/integrations/r2/server";
import {
	WORLD_ENTITY_MEDIA_MAX_BYTES,
	WORLD_ENTITY_MEDIA_PRIVATE_BUCKET,
	WORLD_ENTITY_MEDIA_PREVIEW_BUCKET,
	WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
	WORLD_ENTITY_MEDIA_PUBLIC_ORIGIN,
	WORLD_ENTITY_MEDIA_UPLOAD_EXPIRES_SECONDS,
	type WorldEntityMediaMime,
	worldEntityPortraitObjectKey,
	worldEntityPortraitPendingObjectKey,
} from "./world-entity-media";
import {
	inspectWorldEntityImage,
	type WorldEntityImageInfo,
	worldEntityMediaSha256,
} from "./world-entity-media-image";
import { presignR2PutObject, type R2PresignedPut } from "./world-entity-media-presign";

export type VerifiedWorldEntityUpload = WorldEntityImageInfo &
	Readonly<{
		bucket: string;
		objectKey: string;
		readBackVerified: true;
	}>;

export type PresignedWorldEntityUpload = R2PresignedPut &
	Readonly<{
		bucket: string;
		pendingObjectKey: string;
	}>;

type S3ResponseError = Readonly<{
	name?: string;
	$metadata?: Readonly<{ httpStatusCode?: number }>;
}>;

function failure(code: string): never {
	throw new Error(`WORLD_ENTITY_MEDIA_${code}`);
}

function s3ResponseError(error: unknown): S3ResponseError {
	return error as S3ResponseError;
}

function isNotFound(error: unknown): boolean {
	const response = s3ResponseError(error);
	return (
		response.$metadata?.httpStatusCode === 404 ||
		response.name === "NotFound" ||
		response.name === "NoSuchKey"
	);
}

function isPreconditionFailed(error: unknown): boolean {
	const response = s3ResponseError(error);
	return response.$metadata?.httpStatusCode === 412 || response.name === "PreconditionFailed";
}

export function worldEntityMediaEnabled(): boolean {
	return process.env.TDA_WORLD_ENTITY_MEDIA_ENABLED === "true";
}

export function worldEntityMediaStagingBucket(): string {
	const production = process.env.VERCEL_ENV === "production";
	const expected = production
		? WORLD_ENTITY_MEDIA_PRIVATE_BUCKET
		: WORLD_ENTITY_MEDIA_PREVIEW_BUCKET;
	const configured = production ? process.env.R2_PRIVATE_BUCKET : process.env.R2_PREVIEW_BUCKET;
	if (configured !== expected) failure("STAGING_BUCKET_MISMATCH");
	return configured;
}

function publicBucket(): string {
	if (process.env.R2_PUBLIC_BUCKET !== WORLD_ENTITY_MEDIA_PUBLIC_BUCKET) {
		failure("PUBLIC_BUCKET_MISMATCH");
	}
	return WORLD_ENTITY_MEDIA_PUBLIC_BUCKET;
}

async function objectBytes(
	client: S3Client,
	bucket: string,
	objectKey: string,
): Promise<Uint8Array> {
	const head = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: objectKey }));
	if (
		typeof head.ContentLength !== "number" ||
		head.ContentLength < 24 ||
		head.ContentLength > WORLD_ENTITY_MEDIA_MAX_BYTES
	) {
		failure("R2_INVALID_SIZE");
	}
	const result = await client.send(new GetObjectCommand({ Bucket: bucket, Key: objectKey }));
	if (!result.Body) failure("R2_EMPTY_BODY");
	if (
		typeof result.ContentLength !== "number" ||
		result.ContentLength < 24 ||
		result.ContentLength > WORLD_ENTITY_MEDIA_MAX_BYTES ||
		result.ContentLength !== head.ContentLength
	) {
		failure("R2_LENGTH_MISMATCH");
	}
	const bytes = Uint8Array.from(await result.Body.transformToByteArray());
	if (bytes.length !== result.ContentLength) failure("R2_LENGTH_MISMATCH");
	return bytes;
}

async function putImmutableObject({
	client,
	bucket,
	objectKey,
	bytes,
	info,
	cacheControl,
}: {
	client: S3Client;
	bucket: string;
	objectKey: string;
	bytes: Uint8Array;
	info: WorldEntityImageInfo;
	cacheControl: string;
}) {
	let exists = false;
	try {
		const head = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: objectKey }));
		exists = true;
		if (
			head.ContentLength !== info.bytes ||
			head.ContentType !== info.mimeType ||
			head.Metadata?.sha256 !== info.sha256
		) {
			failure("R2_COLLISION");
		}
	} catch (error) {
		if (!isNotFound(error)) throw error;
	}

	if (!exists) {
		try {
			await client.send(
				new PutObjectCommand({
					Bucket: bucket,
					Key: objectKey,
					Body: bytes,
					ContentType: info.mimeType,
					ContentLength: info.bytes,
					Metadata: { sha256: info.sha256 },
					CacheControl: cacheControl,
					IfNoneMatch: "*",
				}),
			);
		} catch (error) {
			// Another finalizer can materialize the same content-addressed key
			// after our HEAD and before this conditional PUT. A 412 is therefore
			// resolved by the mandatory read-back below, never by overwriting it.
			if (!isPreconditionFailed(error)) throw error;
		}
	}

	const readBack = await objectBytes(client, bucket, objectKey);
	if (readBack.length !== info.bytes || worldEntityMediaSha256(readBack) !== info.sha256) {
		failure("R2_READBACK_FAILED");
	}
}

/**
 * Creates a short-lived PUT bearer URL for a unique pending key. The browser
 * never receives R2 credentials and never writes the canonical content-addressed
 * portrait key directly. Finalization re-reads and validates the bytes first.
 */
export function presignWorldEntityPortraitPendingUpload({
	campaignSlug,
	entityId,
	uploadId,
	sha256,
	mimeType,
}: {
	campaignSlug: string;
	entityId: string;
	uploadId: string;
	sha256: string;
	mimeType: WorldEntityMediaMime;
}): PresignedWorldEntityUpload {
	const extension = mimeType === "image/png" ? "png" : "webp";
	const pendingObjectKey = worldEntityPortraitPendingObjectKey({
		campaignSlug,
		entityId,
		uploadId,
		sha256,
		extension,
	});
	if (!pendingObjectKey) failure("INVALID_PENDING_OBJECT_KEY");
	const bucket = worldEntityMediaStagingBucket();
	const { accountId, accessKeyId, secretAccessKey } = mediaConnectionConfig();
	return {
		...presignR2PutObject({
			accountId,
			bucket,
			objectKey: pendingObjectKey,
			accessKeyId,
			secretAccessKey,
			contentType: mimeType,
			expiresIn: WORLD_ENTITY_MEDIA_UPLOAD_EXPIRES_SECONDS,
		}),
		bucket,
		pendingObjectKey,
	};
}

/**
 * Reads the exact pending object authorized by an upload intent, validates the
 * real bytes and then materializes the immutable canonical portrait key.
 * Pending objects are intentionally left to the dedicated R2 lifecycle policy:
 * a still-valid presigned URL could otherwise recreate them after deletion.
 */
export async function finalizeWorldEntityPortraitPendingUpload({
	campaignSlug,
	entityId,
	uploadId,
	expectedSha256,
	expectedMimeType,
	expectedBytes,
}: {
	campaignSlug: string;
	entityId: string;
	uploadId: string;
	expectedSha256: string;
	expectedMimeType: WorldEntityMediaMime;
	expectedBytes: number;
}): Promise<VerifiedWorldEntityUpload> {
	const extension = expectedMimeType === "image/png" ? "png" : "webp";
	const pendingObjectKey = worldEntityPortraitPendingObjectKey({
		campaignSlug,
		entityId,
		uploadId,
		sha256: expectedSha256,
		extension,
	});
	if (!pendingObjectKey) failure("INVALID_PENDING_OBJECT_KEY");

	const bucket = worldEntityMediaStagingBucket();
	const client = mediaClient();
	const bytes = await objectBytes(client, bucket, pendingObjectKey);
	const info = inspectWorldEntityImage(bytes);
	if (
		info.sha256 !== expectedSha256 ||
		info.mimeType !== expectedMimeType ||
		info.bytes !== expectedBytes
	) {
		failure("UPLOAD_INTENT_MISMATCH");
	}

	const objectKey = worldEntityPortraitObjectKey({
		campaignSlug,
		entityId,
		sha256: info.sha256,
		extension: info.extension,
	});
	if (!objectKey) failure("INVALID_OBJECT_KEY");
	await putImmutableObject({
		client,
		bucket,
		objectKey,
		bytes,
		info,
		cacheControl: "private, no-store",
	});
	return { ...info, bucket, objectKey, readBackVerified: true };
}

/**
 * Server-side fallback upload for trusted application code. Browser direct
 * upload uses the pending-key presign/finalize flow above.
 */
export async function uploadWorldEntityPortrait({
	campaignSlug,
	entityId,
	bytes,
}: {
	campaignSlug: string;
	entityId: string;
	bytes: Uint8Array;
}): Promise<VerifiedWorldEntityUpload> {
	const info = inspectWorldEntityImage(bytes);
	const objectKey = worldEntityPortraitObjectKey({
		campaignSlug,
		entityId,
		sha256: info.sha256,
		extension: info.extension,
	});
	if (!objectKey) failure("INVALID_OBJECT_KEY");
	const bucket = worldEntityMediaStagingBucket();
	const client = mediaClient();
	await putImmutableObject({
		client,
		bucket,
		objectKey,
		bytes,
		info,
		cacheControl: "private, no-store",
	});
	return { ...info, bucket, objectKey, readBackVerified: true };
}

/**
 * Verifies a canonical staged object for trusted server-side recovery/import
 * flows. Browser direct upload does not receive a presign for canonical keys.
 */
export async function verifyWorldEntityPortraitObject({
	campaignSlug,
	entityId,
	expectedSha256,
	expectedMimeType,
	expectedBytes,
}: {
	campaignSlug: string;
	entityId: string;
	expectedSha256: string;
	expectedMimeType: WorldEntityMediaMime;
	expectedBytes?: number;
}): Promise<VerifiedWorldEntityUpload> {
	const extension = expectedMimeType === "image/png" ? "png" : "webp";
	const objectKey = worldEntityPortraitObjectKey({
		campaignSlug,
		entityId,
		sha256: expectedSha256,
		extension,
	});
	if (!objectKey) failure("INVALID_OBJECT_KEY");
	const bucket = worldEntityMediaStagingBucket();
	const bytes = await objectBytes(mediaClient(), bucket, objectKey);
	const info = inspectWorldEntityImage(bytes);
	if (
		info.sha256 !== expectedSha256 ||
		info.mimeType !== expectedMimeType ||
		(expectedBytes !== undefined && info.bytes !== expectedBytes)
	) {
		failure("UPLOAD_INTENT_MISMATCH");
	}
	return { ...info, bucket, objectKey, readBackVerified: true };
}

export async function readWorldEntityMediaObject({
	bucket,
	objectKey,
}: {
	bucket: string;
	objectKey: string;
}): Promise<Uint8Array> {
	const allowed = new Set<string>([
		WORLD_ENTITY_MEDIA_PREVIEW_BUCKET,
		WORLD_ENTITY_MEDIA_PRIVATE_BUCKET,
		WORLD_ENTITY_MEDIA_PUBLIC_BUCKET,
	]);
	if (!allowed.has(bucket)) failure("BUCKET_NOT_ALLOWED");
	return objectBytes(mediaClient(), bucket, objectKey);
}

export async function promoteWorldEntityPortrait({
	campaignSlug,
	entityId,
	stagedBucket,
	objectKey,
	info,
}: {
	campaignSlug: string;
	entityId: string;
	stagedBucket: string;
	objectKey: string;
	info: WorldEntityImageInfo;
}): Promise<{ publicBucket: string; publicObjectKey: string; verifiedAt: string }> {
	if (
		stagedBucket !== WORLD_ENTITY_MEDIA_PREVIEW_BUCKET &&
		stagedBucket !== WORLD_ENTITY_MEDIA_PRIVATE_BUCKET
	) {
		failure("STAGING_BUCKET_NOT_ALLOWED");
	}
	const expectedObjectKey = worldEntityPortraitObjectKey({
		campaignSlug,
		entityId,
		sha256: info.sha256,
		extension: info.extension,
	});
	if (!expectedObjectKey || objectKey !== expectedObjectKey) failure("OBJECT_SCOPE_MISMATCH");

	const client = mediaClient();
	const bytes = await objectBytes(client, stagedBucket, objectKey);
	const inspected = inspectWorldEntityImage(bytes);
	if (
		inspected.sha256 !== info.sha256 ||
		inspected.mimeType !== info.mimeType ||
		inspected.bytes !== info.bytes ||
		inspected.width !== info.width ||
		inspected.height !== info.height
	) {
		failure("STAGED_INTEGRITY_FAILED");
	}

	const bucket = publicBucket();
	await putImmutableObject({
		client,
		bucket,
		objectKey,
		bytes,
		info,
		cacheControl: "public, max-age=31536000, immutable",
	});

	const url = `${WORLD_ENTITY_MEDIA_PUBLIC_ORIGIN}/${objectKey}`;
	const response = await fetch(url, {
		cache: "no-store",
		redirect: "error",
		signal: AbortSignal.timeout(15_000),
	});
	if (!response.ok) failure("PUBLIC_DELIVERY_FAILED");
	const contentLength = Number(response.headers.get("content-length"));
	if (Number.isFinite(contentLength) && contentLength > WORLD_ENTITY_MEDIA_MAX_BYTES) {
		failure("PUBLIC_DELIVERY_TOO_LARGE");
	}
	const delivered = new Uint8Array(await response.arrayBuffer());
	const mime = response.headers.get("content-type")?.split(";", 1)[0]?.trim();
	if (
		mime !== info.mimeType ||
		delivered.length !== info.bytes ||
		worldEntityMediaSha256(delivered) !== info.sha256
	) {
		failure("PUBLIC_DELIVERY_MISMATCH");
	}
	return {
		publicBucket: bucket,
		publicObjectKey: objectKey,
		verifiedAt: new Date().toISOString(),
	};
}
