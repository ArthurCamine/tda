import assert from "node:assert/strict";
import test from "node:test";
import { classifyPaths } from "./classify-changes.mjs";

function flags(files) {
	const { web, db, companion, media } = classifyPaths(files);
	return { web, db, companion, media };
}

test("docs-only stays on fast CI only", () => {
	assert.deepEqual(flags(["docs/operations/cicd-simplification-plan.md"]), {
		web: true,
		db: false,
		companion: false,
		media: false,
	});
});

test("ordinary web and lore files do not activate heavy domains", () => {
	assert.deepEqual(
		flags(["src/app/page.tsx", "public/lore/yllith/yllith.css", "public/lore/yllith/historia.md"]),
		{ web: true, db: false, companion: false, media: false },
	);
});

test("Companion source and its generic workflow activate Companion", () => {
	assert.equal(flags(["local-companion/tda_companion/app.py"]).companion, true);
	assert.equal(flags([".github/workflows/companion.yml"]).companion, true);
	assert.equal(flags(["tools/check-companion-model-freshness.py"]).companion, true);
});

test("specialized runtime workflows do not build the generic MSI by themselves", () => {
	assert.equal(flags([".github/workflows/qwen-runtime-package.yml"]).companion, false);
	assert.equal(flags([".github/workflows/runtime-promote.yml"]).companion, false);
	assert.equal(flags([".github/workflows/whisper-runtime.yml"]).companion, false);
});

test("Supabase and transcript-sync changes activate PostgreSQL integration", () => {
	assert.equal(flags(["supabase/migrations/202609140001_example.sql"]).db, true);
	assert.equal(flags(["src/features/transcript-sync/client.ts"]).db, true);
	assert.equal(flags(["tools/world-layout-db.py"]).db, true);
});

test("database documentation alone does not start PostgreSQL", () => {
	assert.equal(flags(["docs/database/migrations.md"]).db, false);
});

test("media manifests and tooling activate media domain", () => {
	assert.equal(flags(["media/yllith/manifest.json"]).media, true);
	assert.equal(flags(["tools/media/verify-public.mjs"]).media, true);
	assert.equal(flags(["tools/world-entity-media-r2-policy.test.mjs"]).media, true);
});

test("mixed changes activate each relevant domain", () => {
	assert.deepEqual(
		flags([
			"src/app/page.tsx",
			"supabase/migrations/202609140002_example.sql",
			"local-companion/tda_companion/app.py",
			"media/yllith/manifest.json",
		]),
		{ web: true, db: true, companion: true, media: true },
	);
});

test("normalizes duplicate and Windows-style paths", () => {
	const result = classifyPaths([
		".\\local-companion\\tda_companion\\app.py",
		"local-companion/tda_companion/app.py",
	]);
	assert.deepEqual(result.files, ["local-companion/tda_companion/app.py"]);
	assert.equal(result.companion, true);
});
