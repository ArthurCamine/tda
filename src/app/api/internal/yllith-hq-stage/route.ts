import { createHash } from "node:crypto";
import {
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PUBLIC_BUCKET = "tda-media-public";
const PUBLIC_ORIGIN = "https://media.dnd.faysk.dev";
const MIGRATION = "yllith-hq-20260915";
const MAX_CARRIER_BYTES = 2 * 1024 * 1024;

const assets = {
  "yllith-hq.avif": { bytes: 270660, sha256: "80f34c65d49c46eea9abc77b689dbc3a35db6169833942023cc77a3b2e2b732c" },
  "yllith-jornada-hq.avif": { bytes: 145395, sha256: "696815188f4bf602c1b288b7b8f7f2741373e52055fbe06ba7cccb44b591784c" },
  "despedida-pais-hq.avif": { bytes: 206324, sha256: "15eed32a0da97d8303e3390d7792293b51af11cce6a98338f59f85f360605036" },
  "despedida-tios-hq.avif": { bytes: 232976, sha256: "1640491d2fe6dc6d90636f0e05d013bfae013f39b2fd3449e96e24c77ff4baec" },
  "sonho-hq.avif": { bytes: 76358, sha256: "c5899e7ee7b1154c5db8bd3d6b58b8a120d5527317dc101ef613139fbe902d70" },
  "mapa-hq.avif": { bytes: 329394, sha256: "4516fd1fcaa6d97f56369007bfb5ddd320427e5a53bb850a8e9a267b7051e73a" },
  "jornada-hq.avif": { bytes: 244263, sha256: "febe6350fb80ea3c7a84b76ee5673f44365d231d7729ccdae57c0fedaaebd834" },
  "horizonte-hq.avif": { bytes: 238231, sha256: "95c30d52b452ef0560a755fdbcb1138b5e9066cd3dfa2496b03d30d350681197" },
} as const;

type AssetName = keyof typeof assets;

function isAssetName(value: string | null): value is AssetName {
  return Boolean(value && value in assets);
}

function configured() {
  return Boolean(
    process.env.R2_PUBLIC_BUCKET === PUBLIC_BUCKET &&
      process.env.R2_ACCOUNT_ID &&
      process.env.R2_ACCESS_KEY_ID &&
      process.env.R2_SECRET_ACCESS_KEY,
  );
}

function client() {
  return new S3Client({
    region: "auto",
    endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: process.env.R2_ACCESS_KEY_ID!,
      secretAccessKey: process.env.R2_SECRET_ACCESS_KEY!,
    },
    requestChecksumCalculation: "WHEN_REQUIRED",
  });
}

function sha256(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function objectKey(name: AssetName) {
  return `lore/yllith/${assets[name].sha256}/${name}`;
}

function trustedSource(value: string) {
  const url = new URL(value);
  return (
    url.protocol === "https:" &&
    url.hostname.startsWith("oaisdmntpr") &&
    url.hostname.endsWith(".blob.core.windows.net") &&
    url.pathname.startsWith("/files/") &&
    url.pathname.endsWith("/raw")
  );
}

function extractCarrierPayload(carrier: Buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (carrier.length < 20 || !carrier.subarray(0, 8).equals(signature)) throw new Error("carrier is not PNG");
  let offset = 8;
  let payload: Buffer | null = null;
  while (offset + 12 <= carrier.length) {
    const length = carrier.readUInt32BE(offset);
    const typeStart = offset + 4;
    const dataStart = typeStart + 4;
    const dataEnd = dataStart + length;
    const chunkEnd = dataEnd + 4;
    if (chunkEnd > carrier.length) throw new Error("truncated PNG carrier");
    const type = carrier.toString("ascii", typeStart, dataStart);
    if (type === "raVF") {
      if (payload) throw new Error("duplicate carrier payload");
      payload = Buffer.from(carrier.subarray(dataStart, dataEnd));
    }
    offset = chunkEnd;
    if (type === "IEND") break;
  }
  if (!payload) throw new Error("carrier payload missing");
  return payload;
}

async function bodyBytes(body: unknown) {
  const stream = body as { transformToByteArray?: () => Promise<Uint8Array> } | undefined;
  if (!stream?.transformToByteArray) throw new Error("R2 body is not byte-readable");
  return Buffer.from(await stream.transformToByteArray());
}

function json(data: unknown, status = 200) {
  return Response.json(data, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const name = url.searchParams.get("asset");
  const source = url.searchParams.get("source");
  const migration = url.searchParams.get("migration");

  if (!name && !source) {
    return json({ environment: process.env.APP_ENV ?? null, configured: configured(), fixedAssets: Object.keys(assets).length });
  }
  if (process.env.APP_ENV !== "production") return json({ error: "production migration only" }, 404);
  if (!configured()) return json({ error: "R2 configuration unavailable" }, 503);
  if (migration !== MIGRATION) return json({ error: "migration mismatch" }, 404);
  if (!isAssetName(name) || !source) return json({ error: "asset and source are required" }, 400);

  let sourceAllowed = false;
  try { sourceAllowed = trustedSource(source); } catch { sourceAllowed = false; }
  if (!sourceAllowed) return json({ error: "untrusted carrier source" }, 400);

  const fetched = await fetch(source, { cache: "no-store", redirect: "follow" });
  if (!fetched.ok) return json({ error: "carrier fetch failed", status: fetched.status }, 502);
  const carrier = Buffer.from(await fetched.arrayBuffer());
  if (carrier.length > MAX_CARRIER_BYTES) return json({ error: "carrier too large" }, 413);

  let payload: Buffer;
  try { payload = extractCarrierPayload(carrier); }
  catch (error) { return json({ error: error instanceof Error ? error.message : "invalid carrier" }, 422); }

  const spec = assets[name];
  const digest = sha256(payload);
  if (payload.length !== spec.bytes || digest !== spec.sha256) {
    return json({ error: "AVIF integrity mismatch", expectedBytes: spec.bytes, actualBytes: payload.length, expectedSha256: spec.sha256, actualSha256: digest }, 422);
  }

  const s3 = client();
  const key = objectKey(name);
  let state = "reused";
  try {
    const head = await s3.send(new HeadObjectCommand({ Bucket: PUBLIC_BUCKET, Key: key }));
    if (head.ContentLength !== spec.bytes || head.ContentType !== "image/avif") throw new Error("immutable metadata mismatch");
  } catch (error) {
    const code = (error as { $metadata?: { httpStatusCode?: number }; name?: string })?.$metadata?.httpStatusCode;
    const errorName = (error as { name?: string })?.name;
    if (code !== 404 && errorName !== "NotFound" && errorName !== "NoSuchKey") throw error;
    await s3.send(new PutObjectCommand({
      Bucket: PUBLIC_BUCKET,
      Key: key,
      Body: payload,
      ContentType: "image/avif",
      CacheControl: "public, max-age=31536000, immutable",
      IfNoneMatch: "*",
    }));
    state = "published";
  }

  const readback = await s3.send(new GetObjectCommand({ Bucket: PUBLIC_BUCKET, Key: key }));
  const readbackBytes = await bodyBytes(readback.Body);
  if (readbackBytes.length !== spec.bytes || sha256(readbackBytes) !== spec.sha256 || readback.ContentType !== "image/avif") {
    return json({ error: "R2 read-back integrity mismatch" }, 502);
  }

  return json({
    ok: true,
    state,
    asset: name,
    bytes: spec.bytes,
    sha256: spec.sha256,
    key,
    url: `${PUBLIC_ORIGIN}/${key}`,
  });
}
