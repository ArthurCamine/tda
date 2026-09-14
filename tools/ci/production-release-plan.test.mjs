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

test("Supabase migration requires Production migration lifecycle", () => {
	const plan = planProductionPaths([
		"supabase/migrations/20260914123456_example.sql",
	]);
	assert.equal(plan.db, true);
	assert.equal(plan.migrations, true);
});

test("changed canonical manifest requires Production media publication", () => {
	const plan = planProductionPaths(["media/manifests/yllith.json"]);
	assert.equal(plan.media, true);
	assert.equal(plan.mediaPublish, true);
	assert.equal(plan.migrations, false);
});

test("media tooling change is relevant but does not republish old manifests", () => {
	const plan = planProductionPaths(["tools/media/pipeline.mjs"]);
	assert.equal(plan.media, true);
	assert.equal(plan.mediaPublish, false);
});
