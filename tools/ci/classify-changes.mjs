import { appendFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

const CLASSIFIER_CONTRACT = new Set([
	"tools/ci/classify-changes.mjs",
	"tools/ci/classify-changes.test.mjs",
]);

const EXACT = {
	db: new Set([
		"tools/transcript-sync-db.py",
		"tools/world-layout-db.py",
		"tools/world-entity-media-db.py",
		"tools/test_world_layout_db.py",
		"tools/test_world_entity_media_db.py",
		"tools/ci/check-migrations.mjs",
		"tools/check-migration-naming.py",
		"tools/check-relation-migration-safety.py",
	]),
	companion: new Set([".github/workflows/companion.yml"]),
	media: new Set([
		"tools/media-pipeline.py",
		"tools/check-canonical-media-usage.py",
		"tools/check-lore-assets.py",
		"tools/migrate-r2-keys.mjs",
		"tools/world-entity-media-r2-policy.test.mjs",
	]),
};

const PREFIX = {
	db: ["supabase/", "src/features/transcript-sync/"],
	companion: ["local-companion/"],
	media: ["media/", "tools/media/"],
};

function normalized(path) {
	return path.trim().replaceAll("\\", "/").replace(/^\.\//, "");
}

function matches(path, domain) {
	if (CLASSIFIER_CONTRACT.has(path)) return true;
	if (EXACT[domain].has(path)) return true;
	if (PREFIX[domain].some((prefix) => path.startsWith(prefix))) return true;
	if (domain === "companion" && /^tools\/check-companion-.*\.py$/u.test(path))
		return true;
	return false;
}

export function classifyPaths(inputPaths) {
	const files = [...new Set(inputPaths.map(normalized).filter(Boolean))].sort();
	const classes = {
		web: files.length > 0,
		db: files.some((path) => matches(path, "db")),
		companion: files.some((path) => matches(path, "companion")),
		media: files.some((path) => matches(path, "media")),
	};
	return { files, ...classes };
}

export function changedFilesForRange(range) {
	if (!range || typeof range !== "string")
		throw new Error("An explicit git range is required");
	const output = execFileSync(
		"git",
		["diff", "--name-only", "--diff-filter=ACMR", range],
		{ encoding: "utf8" },
	);
	return output.split(/\r?\n/u).filter(Boolean);
}

function writeGithubOutputs(result) {
	if (!process.env.GITHUB_OUTPUT) return;
	for (const key of ["web", "db", "companion", "media"])
		appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${result[key]}\n`);
	appendFileSync(
		process.env.GITHUB_OUTPUT,
		`files_json=${JSON.stringify(result.files)}\n`,
	);
}

function writeSummary(range, result) {
	if (!process.env.GITHUB_STEP_SUMMARY) return;
	appendFileSync(
		process.env.GITHUB_STEP_SUMMARY,
		[
			"## Change relevance",
			`- Range: \`${range}\``,
			`- web: \`${result.web}\``,
			`- db: \`${result.db}\``,
			`- companion: \`${result.companion}\``,
			`- media: \`${result.media}\``,
			`- Files (${result.files.length}): ${result.files.map((file) => `\`${file}\``).join(", ") || "none"}`,
			"",
		].join("\n"),
	);
}

function main() {
	const range = process.argv[2];
	const result = classifyPaths(changedFilesForRange(range));
	writeGithubOutputs(result);
	writeSummary(range, result);
	console.log(JSON.stringify({ range, ...result }));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) main();
