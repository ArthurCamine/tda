import { createHash, timingSafeEqual } from "node:crypto";
import {
  DeleteObjectsCommand,
  GetObjectCommand,
  type GetObjectCommandOutput,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PUBLIC_BUCKET = "tda-media-public";
const PUBLIC_ORIGIN = "https://media.dnd.faysk.dev";
const CHUNK_BYTES = 4096;

const assets = {
  "backgroud_jornada.avif": {
    bytes: 44678,
    sha256: "04ae4968021a938e8a8e738bbe84fea20f8e0900bba0be2b6cba70bc635e06b5",
    type: "image/avif",
    parts: 11,
  },
  "despedida_pais_background.avif": {
    bytes: 43481,
    sha256: "f096873034fe4cd14c1cfd24849dcf2fa127bcd65964dc9dd244846a7487421e",
    type: "image/avif",
    parts: 11,
  },
  "despedida_pais_destaque.webp": {
    bytes: 56612,
    sha256: "88c7ce480d435e1f565faa2a257ea645da65d54d8a066a506b0672345f45484f",
    type: "image/webp",
    parts: 14,
  },
  "despedida_tios_backgroud.avif": {
    bytes: 42002,
    sha256: "6e094723afb19b7be52115ecccfc291d699ead15e66bdea688befef07638c803",
    type: "image/avif",
    parts: 11,
  },
  "despedida_tios_destaque-personagem.webp": {
    bytes: 32900,
    sha256: "8f06c91fc38b1ab98f918d390632b7859068f39e7664cf33842f5296def7ba9d",
    type: "image/webp",
    parts: 9,
  },
  "maos_sobre_mapa_matilha.webp": {
    bytes: 20272,
    sha256: "4f76223c2b0b4065beb6457173bf8a3a684715c7fcf76a395ccc7e252c0734d4",
    type: "image/webp",
    parts: 5,
  },
  "mapa_matilha_sem_mao.avif": {
    bytes: 84082,
    sha256: "84e87577d93d06b69e9b5d9ff644e2d860cae32ee4542b8e0a7c523124c6850c",
    type: "image/avif",
    parts: 21,
  },
  "social-yllith.jpg": {
    bytes: 65609,
    sha256: "b9858046c31ddc338fafe822b8c6132d4b4a4383c5f11b7b6e536943f8509f48",
    type: "image/jpeg",
    parts: 17,
  },
  "sonho-paralax_personagem.webp": {
    bytes: 22930,
    sha256: "34a720045e7b9886d152e6b67cdb161c1f81194579cf693c4a0750ad2a055fab",
    type: "image/webp",
    parts: 6,
  },
  "sonho_paralax_backgroud.avif": {
    bytes: 16786,
    sha256: "bcf5985f7f43bb50e40d36fc40a6e35192343cf39d9159a479ad0a62f3bab655",
    type: "image/avif",
    parts: 5,
  },
  "sonho_paralax_espirito.webp": {
    bytes: 18090,
    sha256: "52dcd41179659ff80bb0b55bab50862a4d4449d726a5dd3a0b50af5db02800fd",
    type: "image/webp",
    parts: 5,
  },
  "sonho_paralax_nevoa.webp": {
    bytes: 22342,
    sha256: "1bc774679515e7524ed4db58738455554c8eeef298042a7cff365ca41ed05b2b",
    type: "image/webp",
    parts: 6,
  },
  "yllith.webp": {
    bytes: 98122,
    sha256: "77ec8886af074c15310ec9f078c530d24d9fbe29cb1ff12fe9ab27b8b031538f",
    type: "image/webp",
    parts: 24,
  },
  "yllith_jornada.webp": {
    bytes: 34612,
    sha256: "24f564be0e4a17610dc2d6eaec92dcbcff139440dcf64ead30c982e0b2c5f886",
    type: "image/webp",
    parts: 9,
  },
} as const;

type AssetName = keyof typeof assets;

type R2Config = Readonly<{
  accountId: string;
  accessKeyId: string;
  secretAccessKey: string;
}>;

function isAssetName(value: string | null): value is AssetName {
  return Boolean(value && value in assets);
}

function r2Config(): R2Config | null {
  const accountId = process.env.R2_ACCOUNT_ID?.trim();
  const accessKeyId = process.env.R2_ACCESS_KEY_ID?.trim();
  const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY?.trim();
  if (
    process.env.R2_PUBLIC_BUCKET !== PUBLIC_BUCKET ||
    !accountId ||
    !accessKeyId ||
    !secretAccessKey
  ) {
    return null;
  }
  return { accountId, accessKeyId, secretAccessKey };
}

function isConfigured() {
  return r2Config() !== null;
}

function authorizedProductionBootstrap(request: Request) {
  const expected = process.env.TDA_LORE_STAGING_TOKEN?.trim();
  const header = request.headers.get("authorization");
  if (!expected || !header?.startsWith("Bearer ")) return false;
  const supplied = header.slice("Bearer ".length);
  const expectedBytes = Buffer.from(expected);
  const suppliedBytes = Buffer.from(supplied);
  return (
    expectedBytes.length === suppliedBytes.length &&
    timingSafeEqual(expectedBytes, suppliedBytes)
  );
}

function client(config: R2Config) {
  return new S3Client({
    region: "auto",
    endpoint: `https://${config.accountId}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: config.accessKeyId,
      secretAccessKey: config.secretAccessKey,
    },
    requestChecksumCalculation: "WHEN_REQUIRED",
  });
}

function finalKey(name: AssetName) {
  return `lore/yllith/${assets[name].sha256}/${name}`;
}

function stagingKey(name: AssetName, part: number) {
  return `lore/yllith/.staging-v2/${assets[name].sha256}/${part}.part`;
}

function publicUrl(name: AssetName) {
  return `${PUBLIC_ORIGIN}/${finalKey(name)}`;
}

function sha256(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function decodeBase64Url(value: string) {
  return Buffer.from(value.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

async function bodyBytes(body: unknown) {
  const candidate = body as { transformToByteArray?: () => Promise<Uint8Array> };
  if (!candidate.transformToByteArray) throw new Error("R2 body is not byte-readable");
  return Buffer.from(await candidate.transformToByteArray());
}

function isMissingObject(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const candidate = error as {
    name?: unknown;
    Code?: unknown;
    $metadata?: { httpStatusCode?: unknown };
  };
  return (
    candidate.name === "NoSuchKey" ||
    candidate.Code === "NoSuchKey" ||
    candidate.$metadata?.httpStatusCode === 404
  );
}

function json(data: unknown, init?: ResponseInit) {
  const headers = new Headers(init?.headers);
  headers.set("Cache-Control", "no-store");
  return Response.json(data, { ...init, headers });
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const file = url.searchParams.get("file");
  const partParam = url.searchParams.get("part");
  const dataParam = url.searchParams.get("data");
  const finalize = url.searchParams.get("finalize");
  const verify = url.searchParams.get("verify");

  const writes = Boolean(finalize || (file && partParam !== null && dataParam !== null));
  const verifies = Boolean(verify);

  if (!writes && !verifies) {
    return json({
      environment: process.env.APP_ENV ?? null,
      configured: isConfigured(),
      protocol: "yllith-r2-bootstrap-v2",
      policy: "fixed immutable content-addressed media only",
      chunkBytes: CHUNK_BYTES,
      assets: (Object.keys(assets) as AssetName[]).map((name) => ({
        name,
        bytes: assets[name].bytes,
        sha256: assets[name].sha256,
        parts: assets[name].parts,
        url: publicUrl(name),
      })),
    });
  }

  if (
    process.env.APP_ENV !== "production" ||
    !authorizedProductionBootstrap(request)
  ) {
    return json({ error: "production bootstrap only" }, { status: 404 });
  }

  const config = r2Config();
  if (!config) {
    return json({ error: "R2 configuration unavailable" }, { status: 503 });
  }

  const s3 = client(config);

  if (verify) {
    if (!isAssetName(verify)) return json({ error: "unknown asset" }, { status: 400 });
    try {
      const head = await s3.send(
        new HeadObjectCommand({ Bucket: PUBLIC_BUCKET, Key: finalKey(verify) }),
      );
      return json({
        ok: head.ContentLength === assets[verify].bytes,
        name: verify,
        expectedBytes: assets[verify].bytes,
        remoteBytes: head.ContentLength ?? null,
        url: publicUrl(verify),
      });
    } catch {
      return json({ ok: false, name: verify }, { status: 404 });
    }
  }

  if (finalize) {
    if (!isAssetName(finalize)) return json({ error: "unknown asset" }, { status: 400 });
    const spec = assets[finalize];
    const pieces: Buffer[] = [];
    for (let part = 0; part < spec.parts; part += 1) {
      let result: GetObjectCommandOutput;
      try {
        result = await s3.send(
          new GetObjectCommand({ Bucket: PUBLIC_BUCKET, Key: stagingKey(finalize, part) }),
        );
      } catch (error) {
        if (isMissingObject(error)) {
          return json({ error: "missing part", name: finalize, part }, { status: 409 });
        }
        throw error;
      }
      if (!result.Body) return json({ error: "missing part", name: finalize, part }, { status: 409 });
      pieces.push(await bodyBytes(result.Body));
    }
    const bytes = Buffer.concat(pieces);
    const digest = sha256(bytes);
    if (bytes.length !== spec.bytes || digest !== spec.sha256) {
      return json(
        {
          error: "final integrity mismatch",
          name: finalize,
          expectedBytes: spec.bytes,
          actualBytes: bytes.length,
          expectedSha256: spec.sha256,
          actualSha256: digest,
        },
        { status: 409 },
      );
    }
    await s3.send(
      new PutObjectCommand({
        Bucket: PUBLIC_BUCKET,
        Key: finalKey(finalize),
        Body: bytes,
        ContentType: spec.type,
        CacheControl: "public, max-age=31536000, immutable",
      }),
    );
    await s3.send(
      new DeleteObjectsCommand({
        Bucket: PUBLIC_BUCKET,
        Delete: {
          Objects: Array.from({ length: spec.parts }, (_, part) => ({
            Key: stagingKey(finalize, part),
          })),
          Quiet: true,
        },
      }),
    );
    return json({
      ok: true,
      finalized: true,
      name: finalize,
      bytes: bytes.length,
      sha256: digest,
      url: publicUrl(finalize),
    });
  }

  if (!isAssetName(file)) return json({ error: "unknown asset" }, { status: 400 });
  const spec = assets[file];
  const part = Number(partParam);
  if (!Number.isSafeInteger(part) || part < 0 || part >= spec.parts) {
    return json({ error: "unknown part" }, { status: 400 });
  }
  if (!dataParam) return json({ error: "missing data" }, { status: 400 });

  const bytes = decodeBase64Url(dataParam);
  const expectedBytes =
    part === spec.parts - 1 ? spec.bytes - CHUNK_BYTES * (spec.parts - 1) : CHUNK_BYTES;
  if (bytes.length !== expectedBytes) {
    return json(
      { error: "part length mismatch", name: file, part, expectedBytes, actualBytes: bytes.length },
      { status: 422 },
    );
  }

  await s3.send(
    new PutObjectCommand({
      Bucket: PUBLIC_BUCKET,
      Key: stagingKey(file, part),
      Body: bytes,
      ContentType: "application/octet-stream",
      CacheControl: "no-store",
    }),
  );
  return json({ ok: true, staged: true, name: file, part, bytes: bytes.length });
}
