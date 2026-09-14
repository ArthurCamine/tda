import { mkdir, writeFile } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
	DEFAULT_MANIFEST_DIR,
	discoverManifests,
	publicVerificationUrl,
	readAssetBytes,
	sha256,
} from "./pipeline.mjs";

const DEFAULT_RECEIPT = ".local/media-public-verification-receipt.json";

function safeRepoPath(root, value, label) {
	if (typeof value !== "string" || !value)
		throw new Error(`${label} must be a non-empty repository-relative path`);
	const absolute = resolve(root, value);
	const rel = relative(root, absolute);
	if (!rel || rel === ".." || rel.startsWith(`..${sep}`))
		throw new Error(`${label} escapes repository root`);
	return absolute;
}

async function verifyPublicDelivery(asset, { fetchImpl = fetch, attempts = 8 } = {}) {
	let lastError;
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		try {
			const response = await fetchImpl(publicVerificationUrl(asset.publicUrl, attempt), {
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

function manifestSetSha256(manifests) {
	const lines = manifests.flatMap((manifest) =>
		manifest.assets.map(
			(asset) =>
				`${manifest.project}\t${asset.objectKey}\t${asset.bytes}\t${asset.contentType}`,
		),
	);
	return sha256(Buffer.from(lines.sort().join("\n"), "utf8"));
}

export async function verifyPublicAll({
	repoRoot = process.cwd(),
	manifestDir = DEFAULT_MANIFEST_DIR,
	receiptPath = DEFAULT_RECEIPT,
	fetchImpl = fetch,
	attempts = 8,
} = {}) {
	const manifests = await discoverManifests({ repoRoot, manifestDir });
	const receipt = {
		schemaVersion: 1,
		kind: "tda-media-public-verification-receipt",
		createdAt: new Date().toISOString(),
		publicOrigin: "https://media.dnd.faysk.dev",
		manifestSetSha256: manifestSetSha256(manifests),
		manifests: manifests.length,
		assets: [],
	};

	for (const manifest of manifests) {
		for (const asset of manifest.assets) {
			await readAssetBytes(asset);
			const delivery = await verifyPublicDelivery(asset, { fetchImpl, attempts });
			receipt.assets.push({
				project: manifest.project,
				file: asset.file,
				objectKey: asset.objectKey,
				publicUrl: asset.publicUrl,
				bytes: asset.bytes,
				sha256: asset.sha256,
				contentType: asset.contentType,
				publicDeliveryVerified: true,
				httpStatus: delivery.httpStatus,
			});
			console.log(`MEDIA_PUBLIC_VERIFIED ${manifest.project} ${asset.file}`);
		}
	}

	receipt.summary = {
		projects: manifests.length,
		assets: receipt.assets.length,
		verified: receipt.assets.filter((asset) => asset.publicDeliveryVerified).length,
	};
	await writeReceipt(repoRoot, receiptPath, receipt);
	console.log(
		`MEDIA_PUBLIC_VERIFY_OK ${receipt.summary.assets} assets; verified=${receipt.summary.verified}`,
	);
	return receipt;
}

export async function main(args = process.argv.slice(2)) {
	const { values } = parseArgs({
		args,
		strict: true,
		options: {
			"manifest-dir": { type: "string", default: DEFAULT_MANIFEST_DIR },
			receipt: { type: "string", default: DEFAULT_RECEIPT },
		},
	});
	return verifyPublicAll({
		manifestDir: values["manifest-dir"],
		receiptPath: values.receipt,
	});
}

if (
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
	main().catch((error) => {
		console.error(
			`MEDIA_PUBLIC_VERIFY_FAILED ${error instanceof Error ? error.message : String(error)}`,
		);
		process.exitCode = 1;
	});
}
