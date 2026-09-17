import {
	selectLatestCompanionInstallableRelease,
	type CompanionInstallableRelease,
} from "./companion-release";

const STABLE_TAG_PATTERN = /^companion-v\d+\.\d+\.\d+$/;

type GithubReleaseLike = {
	tag_name?: unknown;
};

/**
 * Stable product surfaces must never advance onto an RC merely because its
 * semantic version is newer. Explicit RC downloads still go through the
 * installable-release helpers, but the normal manifest/default download path
 * is intentionally stable-only.
 */
export function selectLatestCompanionStableRelease(
	value: unknown,
): CompanionInstallableRelease | null {
	if (!Array.isArray(value)) return null;
	const stableOnly = value.filter((entry) => {
		if (!entry || typeof entry !== "object") return false;
		const tag = (entry as GithubReleaseLike).tag_name;
		return typeof tag === "string" && STABLE_TAG_PATTERN.test(tag);
	});
	const selected = selectLatestCompanionInstallableRelease(stableOnly);
	return selected?.channel === "stable" ? selected : null;
}
