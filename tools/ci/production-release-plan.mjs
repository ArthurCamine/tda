import { appendFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { changedFilesForRange, classifyPaths } from "./classify-changes.mjs";

export function planProductionPaths(inputPaths) {
	const classified = classifyPaths(inputPaths);
	const migrations = classified.files.some(
		(path) => path.startsWith("supabase/migrations/") && path.endsWith(".sql"),
	);
	const mediaPublish = classified.files.some(
		(path) => path.startsWith("media/manifests/") && path.endsWith(".json"),
	);
	return { ...classified, migrations, mediaPublish };
}

function writeGithubOutputs(result) {
	if (!process.env.GITHUB_OUTPUT) return;
	for (const key of ["db", "media", "migrations", "mediaPublish"])
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
			"## Production release plan",
			`- Range: \`${range}\``,
			`- migrations: \`${result.migrations}\``,
			`- media relevant: \`${result.media}\``,
			`- media publish: \`${result.mediaPublish}\``,
			`- DB-related code: \`${result.db}\``,
			`- Files (${result.files.length}): ${result.files.map((file) => `\`${file}\``).join(", ") || "none"}`,
			"",
		].join("\n"),
	);
}

function main() {
	const range = process.argv[2];
	if (!range) throw new Error("An explicit git range is required");
	const result = planProductionPaths(changedFilesForRange(range));
	writeGithubOutputs(result);
	writeSummary(range, result);
	console.log(JSON.stringify({ range, ...result }));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) main();
