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
const MIGRATION = "yllith-hq-png-20260915";
const MAX_SOURCE_BYTES = 4 * 1024 * 1024;

const assets = {
  "yllith-hq.png": { bytes: 2117077, sha256: "384d17c645ce923a5fc1bb6526bb213d50f9e5c4ea0a6e90e8320d6aa33cc73f" },
  "yllith-jornada-hq.png": { bytes: 1083459, sha256: "2c810a111ee7b946d95aad965366c85bce1ce0880bf81e771d4f0a2ea063a1ec" },
  "despedida-pais-hq.png": { bytes: 2148131, sha256: "99041fe8c1a46cb5be28e02e4a9f801ebe2835dd961a9b8be432cfddcee8d363" },
  "despedida-tios-hq.png": { bytes: 2323189, sha256: "be6afe09d0092661d9e14374548bad5a28e31693a7dceae173e3ae1068c064ee" },
  "sonho-hq.png": { bytes: 994654, sha256: "c128f9446018b979aaa2080c3a068d21ede2426946c0ee7608c31385104ceb9b" },
  "mapa-hq.png": { bytes: 2748924, sha256: "2b06647874d9fe8ac121979ad1336ef935ad79022d36629d72de286b65eea4b6" },
  "jornada-hq.png": { bytes: 2362952, sha256: "803e8e16fa7042dc4cb71a0708f22243e369f35981f86c0a50fba06edfe14c67" },
  "horizonte-hq.png": { bytes: 2299532, sha256: "c302db65accd8a3ddf46ac3f7e1c4b9444f71de589e89c9d4dc12d9390ec1df4" },
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

function isPng(bytes: Buffer) {
  return bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
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
  if (!sourceAllowed) return json({ error: "untrusted source" }, 400);

  const fetched = await fetch(source, { cache: "no-store", redirect: "follow" });
  if (!fetched.ok) return json({ error: "source fetch failed", status: fetched.status }, 502);
  const declared = Number(fetched.headers.get("content-length") ?? "0");
  if (declared > MAX_SOURCE_BYTES) return json({ error: "source too large" }, 413);
  const payload = Buffer.from(await fetched.arrayBuffer());
  if (payload.length > MAX_SOURCE_BYTES) return json({ error: "source too large" }, 413);
  if (!isPng(payload)) return json({ error: "source is not PNG" }, 422);

  const spec = assets[name];
  const digest = sha256(payload);
  if (payload.length !== spec.bytes || digest !== spec.sha256) {
    return json({ error: "PNG integrity mismatch", expectedBytes: spec.bytes, actualBytes: payload.length, expectedSha256: spec.sha256, actualSha256: digest }, 422);
  }

  const s3 = client();
  const key = objectKey(name);
  let state = "reused";
  try {
    const head = await s3.send(new HeadObjectCommand({ Bucket: PUBLIC_BUCKET, Key: key }));
    if (head.ContentLength !== spec.bytes || head.ContentType !== "image/png") throw new Error("immutable metadata mismatch");
  } catch (error) {
    const code = (error as { $metadata?: { httpStatusCode?: number }; name?: string })?.$metadata?.httpStatusCode;
    const errorName = (error as { name?: string })?.name;
    if (code !== 404 && errorName !== "NotFound" && errorName !== "NoSuchKey") throw error;
    await s3.send(new PutObjectCommand({
      Bucket: PUBLIC_BUCKET,
      Key: key,
      Body: payload,
      ContentType: "image/png",
      CacheControl: "public, max-age=31536000, immutable",
      IfNoneMatch: "*",
    }));
    state = "published";
  }

  const readback = await s3.send(new GetObjectCommand({ Bucket: PUBLIC_BUCKET, Key: key }));
  const readbackBytes = await bodyBytes(readback.Body);
  if (readbackBytes.length !== spec.bytes || sha256(readbackBytes) !== spec.sha256 || readback.ContentType !== "image/png") {
    return json({ error: "R2 read-back integrity mismatch" }, 502);
  }

  return json({ ok: true, state, asset: name, bytes: spec.bytes, sha256: spec.sha256, key, url: `${PUBLIC_ORIGIN}/${key}` });
}
