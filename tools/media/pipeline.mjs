import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
	GetObjectCommand,
	HeadObjectCommand,
	PutObjectCommand,
	S3Client,
} from "@aws-sdk/client-s3";

export const DEFAULT_MANIFEST_DIR = "media/manifests";
export const DEFAULT_PUBLIC_ORIGIN = "https://media.dnd.faysk.dev";
const PUBLIC_BUCKET = "tda-media-public";
const MAX_ASSET_BYTES = 128 * 1024 * 1024;
const ALLOWED_ENCODINGS = new Set(["binary", "base64"]);
const ALLOWED_MEDIA_TYPE =
	/^(?:image\/(?:avif|jpeg|png|webp)|audio\/[a-z0-9.+-]+|video\/[a-z0-9.+-]+|application\/pdf)$/;

export function sha256(bytes) {
	return createHash("sha256").update(bytes).digest("hex");
}

function normalizePublicOrigin(value) {
	const url = new URL(value);
	if (
		url.protocol !== "https:" ||
		url.username ||
		url.password ||
		url.search ||
		url.hash ||
		url.pathname !== "/"
	)
		throw new Error("publicOrigin must be a bare https origin");
	return url.origin;
}

function safeRepoPath(root, value, label) {
	if (typeof value !== "string" || !value || isAbsolute(value))
		throw new Error(`${label} must be a non-empty repository-relative path`);
	const absolute = resolve(root, value);
	const rel = relative(root, absolute);
	if (!rel || rel === ".." || rel.startsWith(`..${sep}`))
		throw new Error(`${label} escapes repository root`);
	return absolute;
}

export function validateManifest(
	manifest,
	{ repoRoot = process.cwd(), manifestPath = null } = {},
) {
	if (!manifest || manifest.schemaVersion !== 1)
		throw new Error("media manifest schemaVersion must be 1");
	if (
		typeof manifest.project !== "string" ||
		!/^[a-z0-9][a-z0-9-]{1,63}$/.test(manifest.project)
	)
		throw new Error("media manifest project is invalid");
	if (
		typeof manifest.namespace !== "string" ||
		!/^[a-z0-9][a-z0-9._/-]*[a-z0-9]$/.test(manifest.namespace) ||
		manifest.namespace.includes("..") ||
		manifest.namespace.startsWith("/") ||
		manifest.namespace.endsWith("/")
	)
		throw new Error("media manifest namespace is invalid");
	if (manifest.bucket !== PUBLIC_BUCKET)
		throw new Error(`media manifest bucket must be ${PUBLIC_BUCKET}`);
	const publicOrigin = normalizePublicOrigin(
		manifest.publicOrigin ?? DEFAULT_PUBLIC_ORIGIN,
	);
	if (publicOrigin !== DEFAULT_PUBLIC_ORIGIN)
		throw new Error("media manifest publicOrigin is not approved");
	if (!Array.isArray(manifest.assets) || manifest.assets.length === 0)
		throw new Error("media manifest must declare at least one asset");

	const seenFiles = new Set();
	const seenKeys = new Set();
	const assets = manifest.assets.map((asset) => {
		if (
			typeof asset.file !== "string" ||
			asset.file !== basename(asset.file) ||
			!asset.file ||
			asset.file === "." ||
			asset.file === ".."
		)
			throw new Error("asset file must be a plain filename");
		if (seenFiles.has(asset.file))
			throw new Error(`duplicate asset file: ${asset.file}`);
		seenFiles.add(asset.file);

		if (
			!Number.isSafeInteger(asset.bytes) ||
			asset.bytes <= 0 ||
			asset.bytes > MAX_ASSET_BYTES
		)
			throw new Error(`invalid byte size for ${asset.file}`);
		if (
			typeof asset.sha256 !== "string" ||
			!/^[a-f0-9]{64}$/.test(asset.sha256)
		)
			throw new Error(`invalid sha256 for ${asset.file}`);
		const encoding = asset.encoding ?? "binary";
		if (!ALLOWED_ENCODINGS.has(encoding))
			throw new Error(`invalid source encoding for ${asset.file}`);
		if (
			typeof asset.contentType !== "string" ||
			!ALLOWED_MEDIA_TYPE.test(asset.contentType)
		)
			throw new Error(`unsupported contentType for ${asset.file}`);

		const sourcePath = safeRepoPath(
			repoRoot,
			asset.source,
			`source for ${asset.file}`,
		);
		const sourceRelative = relative(repoRoot, sourcePath).split(sep).join("/");
		if (!sourceRelative.startsWith("media/sources/"))
			throw new Error(`source for ${asset.file} must live under media/sources`);

		const objectKey = `${manifest.namespace}/${asset.sha256}/${asset.file}`;
		if (seenKeys.has(objectKey))
			throw new Error(`duplicate object key: ${objectKey}`);
		seenKeys.add(objectKey);

		return {
			...asset,
			encoding,
			sourcePath,
			sourceRelative,
			objectKey,
			publicUrl: `${publicOrigin}/${objectKey}`,
		};
	});

	return {
		schemaVersion: 1,
		project: manifest.project,
		namespace: manifest.namespace,
		bucket: manifest.bucket,
		publicOrigin,
		manifestPath,
		assets,
	};
}

function decodeBase64Strict(text, label) {
	const compact = text.replace(/\s+/g, "");
	if (
		!compact ||
		compact.length % 4 === 1 ||
		!/^[A-Za-z0-9+/]*={0,2}$/.test(compact)
	)
		throw new Error(`invalid base64 source for ${label}`);
	const bytes = Buffer.from(compact, "base64");
	const canonical = bytes.toString("base64").replace(/=+$/, "");
	if (canonical !== compact.replace(/=+$/, ""))
		throw new Error(`non-canonical base64 source for ${label}`);
	return bytes;
}

export async function readAssetBytes(asset) {
	const raw = await readFile(asset.sourcePath);
	const bytes =
		asset.encoding === "base64"
			? decodeBase64Strict(raw.toString("ascii"), asset.file)
			: raw;
	const digest = sha256(bytes);
	if (bytes.length !== asset.bytes)
		throw new Error(
			`local media size mismatch for ${asset.file}: expected ${asset.bytes}, got ${bytes.length}`,
		);
	if (digest !== asset.sha256)
		throw new Error(
			`local media sha256 mismatch for ${asset.file}: expected ${asset.sha256}, got ${digest}`,
		);
	return bytes;
}

export async function discoverManifests({
	repoRoot = process.cwd(),
	manifestDir = DEFAULT_MANIFEST_DIR,
} = {}) {
	const absoluteDir = safeRepoPath(repoRoot, manifestDir, "manifest directory");
	let names;
	try {
		names = (await readdir(absoluteDir))
			.filter((name) => name.endsWith(".json"))
			.sort();
	} catch (error) {
		if (error?.code === "ENOENT") return [];
		throw error;
	}
	if (names.length === 0) return [];

	const manifests = [];
	const projects = new Set();
	const objectKeys = new Set();
	for (const name of names) {
		const manifestPath = join(absoluteDir, name);
		const parsed = JSON.parse(await readFile(manifestPath, "utf8"));
		const manifest = validateManifest(parsed, { repoRoot, manifestPath });
		if (projects.has(manifest.project))
			throw new Error(`duplicate media project: ${manifest.project}`);
		projects.add(manifest.project);
		for (const asset of manifest.assets) {
			if (objectKeys.has(asset.objectKey))
				throw new Error(`duplicate media object across manifests: ${asset.objectKey}`);
			objectKeys.add(asset.objectKey);
		}
		manifests.push(manifest);
	}
	return manifests;
}

export async function validateAll(options = {}) {
	const manifests = await discoverManifests(options);
	let assets = 0;
	let bytes = 0;
	for (const manifest of manifests) {
		for (const asset of manifest.assets) {
			const payload = await readAssetBytes(asset);
			assets += 1;
			bytes += payload.length;
		}
	}
	return {
		manifests: manifests.length,
		assets,
		bytes,
		projects: manifests.map((manifest) => manifest.project),
	};
}

function manifestSetSha256(manifests) {
	const lines = manifests.flatMap((manifest) =>
		manifest.assets.map(
			(asset) =>
				`${manifest.project}\t${asset.objectKey}\t${asset.bytes}\t${asset.contentType}`,
		),
	);
	return sha256(Buffer.from(lines.sort().join("\n"), "utf8"));
}

function r2Config() {
	const accountId = process.env.R2_ACCOUNT_ID?.trim();
	const accessKeyId = process.env.R2_ACCESS_KEY_ID?.trim();
	const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY?.trim();
	const bucket = process.env.R2_PUBLIC_BUCKET?.trim();
	if (bucket !== PUBLIC_BUCKET || !accountId || !accessKeyId || !secretAccessKey)
		throw new Error("R2 public media configuration is incomplete");
	return { accountId, accessKeyId, secretAccessKey, bucket };
}

function r2Client(config) {
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

async function bodyBytes(body) {
	if (!body?.transformToByteArray)
		throw new Error("R2 response body is not byte-readable");
	return Buffer.from(await body.transformToByteArray());
}

function isNotFound(error) {
	return (
		error?.$metadata?.httpStatusCode === 404 ||
		error?.name === "NotFound" ||
		error?.name === "NoSuchKey"
	);
}

async function inspectRemote(client, manifest, asset) {
	try {
		const head = await client.send(
			new HeadObjectCommand({ Bucket: manifest.bucket, Key: asset.objectKey }),
		);
		if (head.ContentLength !== asset.bytes)
			throw new Error(
				`immutable R2 object size mismatch for ${asset.objectKey}; refusing overwrite`,
			);
		const result = await client.send(
			new GetObjectCommand({ Bucket: manifest.bucket, Key: asset.objectKey }),
		);
		if (!result.Body) throw new Error(`R2 object has no body: ${asset.objectKey}`);
		const bytes = await bodyBytes(result.Body);
		if (sha256(bytes) !== asset.sha256)
			throw new Error(
				`immutable R2 object sha256 mismatch for ${asset.objectKey}; refusing overwrite`,
			);
		if (result.ContentType !== asset.contentType)
			throw new Error(
				`immutable R2 object content-type mismatch for ${asset.objectKey}; refusing overwrite`,
			);
		return { exists: true };
	} catch (error) {
		if (isNotFound(error)) return { exists: false };
		throw error;
	}
}

async function verifyPublicDelivery(asset, attempts = 8) {
	let lastError;
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		try {
			const response = await fetch(asset.publicUrl, {
				cache: "no-store",
				headers: { "cache-control": "no-cache" },
			});
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const actualType = response.headers
				.get("content-type")
				?.split(";")[0]
				?.trim();
			if (actualType !== asset.contentType)
				throw new Error(
					`content-type ${actualType ?? "missing"} != ${asset.contentType}`,
				);
			const bytes = Buffer.from(await response.arrayBuffer());
			if (bytes.length !== asset.bytes)
				throw new Error(`bytes ${bytes.length} != ${asset.bytes}`);
			if (sha256(bytes) !== asset.sha256)
				throw new Error(`sha256 mismatch for ${asset.publicUrl}`);
			return { httpStatus: response.status, contentType: actualType };
		} catch (error) {
			lastError = error;
			if (attempt < attempts)
				await new Promise((resolveDelay) =>
					setTimeout(resolveDelay, attempt * 750),
				);
		}
	}
	throw new Error(
		`public media verification failed for ${asset.publicUrl}: ${lastError?.message}`,
	);
}

async function writeReceipt(repoRoot, receiptPath, receipt) {
	const absoluteReceipt = safeRepoPath(repoRoot, receiptPath, "receipt path");
	await mkdir(dirname(absoluteReceipt), { recursive: true });
	await writeFile(absoluteReceipt, `${JSON.stringify(receipt, null, 2)}\n`);
}

export async function publishAll({
	repoRoot = process.cwd(),
	manifestDir = DEFAULT_MANIFEST_DIR,
	receiptPath = ".local/media-publication-receipt.json",
} = {}) {
	const manifests = await discoverManifests({ repoRoot, manifestDir });
	const prepared = [];
	for (const manifest of manifests) {
		for (const asset of manifest.assets)
			prepared.push({ manifest, asset, bytes: await readAssetBytes(asset) });
	}

	const receipt = {
		schemaVersion: 1,
		kind: "tda-media-publication-receipt",
		createdAt: new Date().toISOString(),
		bucket: PUBLIC_BUCKET,
		publicOrigin: DEFAULT_PUBLIC_ORIGIN,
		manifestSetSha256: manifestSetSha256(manifests),
		manifests: manifests.length,
		assets: [],
	};

	if (prepared.length === 0) {
		receipt.summary = { projects: 0, assets: 0, published: 0, reused: 0, verified: 0 };
		await writeReceipt(repoRoot, receiptPath, receipt);
		console.log("MEDIA_PUBLISH_OK 0 assets; nothing to publish");
		return receipt;
	}

	const config = r2Config();
	const client = r2Client(config);
	for (const { manifest, asset, bytes } of prepared) {
		const state = await inspectRemote(client, manifest, asset);
		let action = "reused";
		if (!state.exists) {
			await client.send(
				new PutObjectCommand({
					Bucket: manifest.bucket,
					Key: asset.objectKey,
					Body: bytes,
					ContentType: asset.contentType,
					CacheControl: "public, max-age=31536000, immutable",
					Metadata: {
						sha256: asset.sha256,
						"tda-project": manifest.project,
					},
				}),
			);
			action = "published";
			const verified = await inspectRemote(client, manifest, asset);
			if (!verified.exists)
				throw new Error(`R2 write disappeared during verification: ${asset.objectKey}`);
		}
		const delivery = await verifyPublicDelivery(asset);
		receipt.assets.push({
			project: manifest.project,
			file: asset.file,
			objectKey: asset.objectKey,
			publicUrl: asset.publicUrl,
			bytes: asset.bytes,
			sha256: asset.sha256,
			contentType: asset.contentType,
			action,
			readBackVerified: true,
			publicDeliveryVerified: true,
			httpStatus: delivery.httpStatus,
		});
		console.log(`MEDIA_${action.toUpperCase()} ${manifest.project} ${asset.file}`);
	}

	receipt.summary = {
		projects: manifests.length,
		assets: receipt.assets.length,
		published: receipt.assets.filter((asset) => asset.action === "published").length,
		reused: receipt.assets.filter((asset) => asset.action === "reused").length,
		verified: receipt.assets.filter((asset) => asset.publicDeliveryVerified).length,
	};
	await writeReceipt(repoRoot, receiptPath, receipt);
	console.log(
		`MEDIA_PUBLISH_OK ${receipt.summary.assets} assets; published=${receipt.summary.published}; reused=${receipt.summary.reused}; verified=${receipt.summary.verified}`,
	);
	return receipt;
}

export async function main(args = process.argv.slice(2)) {
	const command = args[0] ?? "validate";
	const { values } = parseArgs({
		args: args.slice(1),
		strict: true,
		options: {
			"manifest-dir": { type: "string", default: DEFAULT_MANIFEST_DIR },
			receipt: {
				type: "string",
				default: ".local/media-publication-receipt.json",
			},
		},
	});
	if (command === "validate") {
		const result = await validateAll({ manifestDir: values["manifest-dir"] });
		console.log(
			`MEDIA_VALIDATE_OK ${result.manifests} manifests / ${result.assets} assets / ${result.bytes} bytes`,
		);
		return result;
	}
	if (command === "publish")
		return publishAll({
			manifestDir: values["manifest-dir"],
			receiptPath: values.receipt,
		});
	throw new Error(`unknown media pipeline command: ${command}`);
}

if (
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
	main().catch((error) => {
		console.error(
			`MEDIA_PIPELINE_FAILED ${error instanceof Error ? error.message : String(error)}`,
		);
		process.exitCode = 1;
	});
}
