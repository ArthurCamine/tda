import {
	selectLatestCompanionInstallableRelease,
	type CompanionInstallableRelease,
} from "./companion-release";

const RC_TAG_PATTERN = /^companion-rc-v\d+\.\d+\.\d+-[a-f0-9]{12}$/;

type GithubReleaseLike = {
	tag_name?: unknown;
};

/**
 * RCs are opt-in only. This selector exists for explicit test surfaces and must
 * never be used by the default/stable download path.
 */
export function selectLatestCompanionRcRelease(
	value: unknown,
): CompanionInstallableRelease | null {
	if (!Array.isArray(value)) return null;
	const rcOnly = value.filter((entry) => {
		if (!entry || typeof entry !== "object") return false;
		const tag = (entry as GithubReleaseLike).tag_name;
		return typeof tag === "string" && RC_TAG_PATTERN.test(tag);
	});
	const selected = selectLatestCompanionInstallableRelease(rcOnly);
	return selected?.channel === "rc" ? selected : null;
}
