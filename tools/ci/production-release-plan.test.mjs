import assert from "node:assert/strict";
import test from "node:test";
import { planProductionPaths } from "./production-release-plan.mjs";

test("docs-only does not require migrations or media publication", () => {
	const plan = planProductionPaths(["docs/operations/ci-cd.md"]);
	assert.equal(plan.migrations, false);
	assert.equal(plan.media, false);
	assert.equal(plan.mediaPublish, false);
});

test("database code without a migration does not mutate Production schema", () => {
	const plan = planProductionPaths(["src/features/transcript-sync/service.ts"]);
	assert.equal(plan.db, true);
	assert.equal(plan.migrations, false);
});

test("pending Supabase migration remains cumulative until Production catches up", () => {
	const plan = planProductionPaths(
		["supabase/migrations/20260914123456_example.sql"],
		["docs/operations/ci-cd.md"],
	);
	assert.equal(plan.db, true);
	assert.equal(plan.migrations, true);
	assert.equal(plan.mediaPublish, false);
});

test("current canonical manifest requires Production media publication", () => {
	const plan = planProductionPaths(
		["media/manifests/yllith.json"],
		["media/manifests/yllith.json"],
	);
	assert.equal(plan.media, true);
	assert.equal(plan.mediaPublish, true);
	assert.equal(plan.migrations, false);
});

test("historical manifest does not make a later unrelated web release demand R2 credentials", () => {
	const plan = planProductionPaths(
		["media/manifests/yllith.json", ".github/workflows/production.yml"],
		[".github/workflows/production.yml"],
	);
	assert.equal(plan.media, true);
	assert.equal(plan.mediaPublish, false);
});

test("media tooling change is relevant but does not republish old manifests", () => {
	const plan = planProductionPaths(["tools/media/pipeline.mjs"]);
	assert.equal(plan.media, true);
	assert.equal(plan.mediaPublish, false);
});
