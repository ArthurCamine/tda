import assert from "node:assert/strict";
import test from "node:test";
import {
	WORLD_ENTITY_MEDIA_PENDING_LIFECYCLE_RULE_ID,
	WORLD_ENTITY_MEDIA_PENDING_PREFIX,
	WORLD_ENTITY_MEDIA_PREVIEW_CORS_RULE_ID,
	normalizeWorldEntityMediaPreviewOrigin,
	replaceManagedRule,
	worldEntityMediaCorsRuleMatches,
	worldEntityMediaLifecycleRuleMatches,
	worldEntityMediaPendingLifecycleRule,
	worldEntityMediaPreviewCorsRule,
} from "./world-entity-media-r2-policy.mjs";

test("preview origin must be one exact HTTPS Vercel origin", () => {
	assert.equal(
		normalizeWorldEntityMediaPreviewOrigin("https://tda-example.vercel.app"),
		"https://tda-example.vercel.app",
	);
	for (const invalid of [
		"http://tda-example.vercel.app",
		"https://tda-example.vercel.app/path",
		"https://*.vercel.app",
		"https://dnd.faysk.dev",
		"not-an-origin",
	]) {
		assert.throws(() => normalizeWorldEntityMediaPreviewOrigin(invalid));
	}
});

test("CORS rule allows only PUT with Content-Type from the exact preview origin", () => {
	const rule = worldEntityMediaPreviewCorsRule("https://tda-example.vercel.app");
	assert.equal(rule.ID, WORLD_ENTITY_MEDIA_PREVIEW_CORS_RULE_ID);
	assert.deepEqual(rule.AllowedOrigins, ["https://tda-example.vercel.app"]);
	assert.deepEqual(rule.AllowedMethods, ["PUT"]);
	assert.deepEqual(rule.AllowedHeaders, ["Content-Type"]);
	assert.deepEqual(rule.ExposeHeaders, ["ETag"]);
	assert.equal(rule.MaxAgeSeconds, 600);
	assert.equal(worldEntityMediaCorsRuleMatches(rule, rule), true);
});

test("pending lifecycle expires only the World entity pending prefix", () => {
	const rule = worldEntityMediaPendingLifecycleRule();
	assert.equal(rule.ID, WORLD_ENTITY_MEDIA_PENDING_LIFECYCLE_RULE_ID);
	assert.equal(rule.Filter.Prefix, WORLD_ENTITY_MEDIA_PENDING_PREFIX);
	assert.equal(rule.Expiration.Days, 1);
	assert.equal(rule.Status, "Enabled");
	assert.equal(worldEntityMediaLifecycleRuleMatches(rule, rule), true);
});

test("managed rule replacement preserves unrelated bucket policy", () => {
	const desired = worldEntityMediaPendingLifecycleRule();
	const result = replaceManagedRule(
		[
			{ ID: "keep-me", Status: "Enabled" },
			{ ID: desired.ID, Status: "Disabled", Filter: { Prefix: "wrong/" } },
		],
		desired,
	);
	assert.deepEqual(result, [{ ID: "keep-me", Status: "Enabled" }, desired]);
});
