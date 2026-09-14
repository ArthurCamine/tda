import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import { sha256 } from "./pipeline.mjs";
import { verifyPublicAll } from "./verify-public.mjs";

async function fixture() {
	const root = await mkdtemp(join(tmpdir(), "tda-media-public-verify-"));
	await mkdir(join(root, "media/manifests"), { recursive: true });
	await mkdir(join(root, "media/sources/example"), { recursive: true });
	const bytes = Buffer.from("immutable-public-media\n");
	const digest = sha256(bytes);
	const source = "media/sources/example/art.webp";
	await writeFile(join(root, source), bytes);
	await writeFile(join(root, "media/manifests/example.json"), JSON.stringify({
		schemaVersion: 1,
		project: "example-project",
		namespace: "lore/example",
		bucket: "tda-media-public",
		publicOrigin: "https://media.dnd.faysk.dev",
		assets: [{ file: "art.webp", source, encoding: "binary", bytes: bytes.length, sha256: digest, contentType: "image/webp" }],
	}, null, 2));
	return { root, bytes, digest };
}

test("public verification succeeds without storage credentials", async () => {
	const { root, bytes, digest } = await fixture();
	const receipt = await verifyPublicAll({
		repoRoot: root,
		receiptPath: ".local/public.json",
		attempts: 1,
		fetchImpl: async () => new Response(bytes, { status: 200, headers: { "content-type": "image/webp" } }),
	});
	assert.deepEqual(receipt.summary, { projects: 1, assets: 1, verified: 1 });
	assert.equal(receipt.assets[0].sha256, digest);
	const persisted = JSON.parse(await readFile(join(root, ".local/public.json"), "utf8"));
	assert.equal(persisted.summary.verified, 1);
});
