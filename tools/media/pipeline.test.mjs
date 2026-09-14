import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import {
	discoverManifests,
	readAssetBytes,
	sha256,
	validateAll,
	validateManifest,
} from "./pipeline.mjs";

async function fixture({ encoding = "binary", namespace = "lore/example" } = {}) {
	const root = await mkdtemp(join(tmpdir(), "tda-media-"));
	await mkdir(join(root, "media/manifests"), { recursive: true });
	await mkdir(join(root, "media/sources/example"), { recursive: true });
	const bytes = Buffer.from("tda-media-pipeline\n");
	const digest = sha256(bytes);
	const source = `media/sources/example/art.bin${encoding === "base64" ? ".b64" : ""}`;
	await writeFile(
		join(root, source),
		encoding === "base64" ? bytes.toString("base64") : bytes,
	);
	const manifest = {
		schemaVersion: 1,
		project: "example-project",
		namespace,
		bucket: "tda-media-public",
		publicOrigin: "https://media.dnd.faysk.dev",
		assets: [
			{
				file: "art.webp",
				source,
				encoding,
				bytes: bytes.length,
				sha256: digest,
				contentType: "image/webp",
			},
		],
	};
	await writeFile(
		join(root, "media/manifests/example.json"),
		`${JSON.stringify(manifest, null, 2)}\n`,
	);
	return { root, manifest, bytes, digest };
}

test("discovers a manifest and derives immutable content-addressed keys", async () => {
	const { root, digest } = await fixture();
	const [manifest] = await discoverManifests({ repoRoot: root });
	assert.equal(manifest.assets[0].objectKey, `lore/example/${digest}/art.webp`);
	assert.equal(
		manifest.assets[0].publicUrl,
		`https://media.dnd.faysk.dev/lore/example/${digest}/art.webp`,
	);
});

test("validates binary and base64 transport sources by exact bytes and sha256", async () => {
	for (const encoding of ["binary", "base64"]) {
		const { root, bytes } = await fixture({ encoding });
		const result = await validateAll({ repoRoot: root });
		assert.equal(result.assets, 1);
		assert.equal(result.bytes, bytes.length);
	}
});

test("rejects source path traversal and mutable/unsafe manifest identities", async () => {
	const { root, manifest } = await fixture();
	assert.throws(
		() =>
			validateManifest(
				{
					...manifest,
					assets: [{ ...manifest.assets[0], source: "../secret.webp" }],
				},
				{ repoRoot: root },
			),
		/escapes repository root/,
	);
	assert.throws(
		() => validateManifest({ ...manifest, namespace: "../bad" }, { repoRoot: root }),
		/namespace is invalid/,
	);
});

test("rejects local integrity drift before publication", async () => {
	const { root } = await fixture({ encoding: "base64" });
	const manifests = await discoverManifests({ repoRoot: root });
	await writeFile(manifests[0].assets[0].sourcePath, Buffer.from("dGFtcGVyZWQ="));
	await assert.rejects(() => readAssetBytes(manifests[0].assets[0]), /mismatch/);
});
