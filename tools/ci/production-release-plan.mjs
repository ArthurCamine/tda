import { appendFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { changedFilesForRange, classifyPaths } from "./classify-changes.mjs";

export function planProductionPaths(releasePaths, currentPaths = releasePaths) {
	const accumulated = classifyPaths(releasePaths);
	const current = classifyPaths(currentPaths);
	const migrations = accumulated.files.some(
		(path) => path.startsWith("supabase/migrations/") && path.endsWith(".sql"),
	);
	const mediaPublish = current.files.some(
		(path) => path.startsWith("media/manifests/") && path.endsWith(".json"),
	);
	return {
		...accumulated,
		migrations,
		mediaPublish,
		currentFiles: current.files,
	};
}

function writeGithubOutputs(result) {
	if (!process.env.GITHUB_OUTPUT) return;
	for (const key of ["db", "media", "migrations"])
		appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${result[key]}\n`);
	appendFileSync(process.env.GITHUB_OUTPUT, `media_publish=${result.mediaPublish}\n`);
	appendFileSync(
		process.env.GITHUB_OUTPUT,
		`files_json=${JSON.stringify(result.files)}\n`,
	);
	appendFileSync(
		process.env.GITHUB_OUTPUT,
		`current_files_json=${JSON.stringify(result.currentFiles)}\n`,
	);
}

function writeSummary(releaseRange, currentRange, result) {
	if (!process.env.GITHUB_STEP_SUMMARY) return;
	appendFileSync(
		process.env.GITHUB_STEP_SUMMARY,
		[
			"## Production release plan",
			`- Unpublished range: \`${releaseRange}\``,
			`- Current merge range: \`${currentRange}\``,
			`- migrations pending: \`${result.migrations}\``,
			`- accumulated media relevance: \`${result.media}\``,
			`- publish media from current merge: \`${result.mediaPublish}\``,
			`- accumulated DB relevance: \`${result.db}\``,
			`- Unpublished files (${result.files.length}): ${result.files.map((file) => `\`${file}\``).join(", ") || "none"}`,
			`- Current files (${result.currentFiles.length}): ${result.currentFiles.map((file) => `\`${file}\``).join(", ") || "none"}`,
			"",
		].join("\n"),
	);
}

function main() {
	const releaseRange = process.argv[2];
	const currentRange = process.argv[3] ?? releaseRange;
	if (!releaseRange) throw new Error("An explicit unpublished git range is required");
	const result = planProductionPaths(
		changedFilesForRange(releaseRange),
		changedFilesForRange(currentRange),
	);
	writeGithubOutputs(result);
	writeSummary(releaseRange, currentRange, result);
	console.log(JSON.stringify({ releaseRange, currentRange, ...result }));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) main();
