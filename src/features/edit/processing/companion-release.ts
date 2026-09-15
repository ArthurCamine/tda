const ASSET_NAME = "TDACompanion-x64.msi";
const TAG_PATTERN = /^companion-v(\d+)\.(\d+)\.(\d+)$/;
const REF_PATTERN = /^refs\/tags\/(companion-v(\d+)\.(\d+)\.(\d+))$/;
const COMPANION_RC_TAG_PATTERN =
	/^companion-rc-v(\d+)\.(\d+)\.(\d+)-([a-f0-9]{12})$/;
const DOWNLOAD_PREFIX = "https://github.com/Faysk/tda/releases/download/";

const WHISPER_TAG_PATTERN = /^companion-whisper-runtime-v(\d+)\.(\d+)\.(\d+)$/;
const WHISPER_REF_PATTERN =
	/^refs\/tags\/(companion-whisper-runtime-v(\d+)\.(\d+)\.(\d+))$/;
const QWEN_TAG_PATTERN = /^companion-qwen-runtime-v(\d+)\.(\d+)\.(\d+)$/;
const QWEN_REF_PATTERN =
	/^refs\/tags\/(companion-qwen-runtime-v(\d+)\.(\d+)\.(\d+))$/;

type GithubRef = {
	ref?: unknown;
};

type ReleaseAsset = {
	name?: unknown;
	browser_download_url?: unknown;
	digest?: unknown;
	size?: unknown;
};

type GithubRelease = {
	tag_name?: unknown;
	draft?: unknown;
	prerelease?: unknown;
	assets?: unknown;
};

type TagCandidate = {
	tag: string;
	version: readonly [number, number, number];
};

export type CompanionAssetInfo = {
	tag: string;
	version: string;
	url: string;
	sha256: string;
	size: number;
};

export type CompanionChannel = "stable" | "rc";

export type CompanionInstallableRelease = CompanionAssetInfo & {
	channel: CompanionChannel;
};

export type WhisperRuntimeAssetInfo = CompanionAssetInfo;
export type QwenRuntimeAssetInfo = CompanionAssetInfo;

function isNewer(
	left: readonly [number, number, number],
	right: readonly [number, number, number],
): boolean {
	for (let index = 0; index < 3; index += 1) {
		if (left[index] !== right[index]) return left[index] > right[index];
	}
	return false;
}

function versionTuple(version: string): readonly [number, number, number] {
	const [major, minor, patch] = version.split(".").map(Number);
	return [major, minor, patch];
}

function selectLatestTag(refs: unknown, pattern: RegExp): string | null {
	if (!Array.isArray(refs)) return null;
	let latest: TagCandidate | null = null;

	for (const value of refs) {
		if (!value || typeof value !== "object") continue;
		const ref = (value as GithubRef).ref;
		if (typeof ref !== "string") continue;
		const match = pattern.exec(ref);
		if (!match) continue;

		const candidate: TagCandidate = {
			tag: match[1],
			version: [Number(match[2]), Number(match[3]), Number(match[4])],
		};
		if (!latest || isNewer(candidate.version, latest.version)) latest = candidate;
	}

	return latest?.tag ?? null;
}

export function selectLatestCompanionTag(refs: unknown): string | null {
	return selectLatestTag(refs, REF_PATTERN);
}

export function selectLatestWhisperRuntimeTag(refs: unknown): string | null {
	return selectLatestTag(refs, WHISPER_REF_PATTERN);
}

export function selectLatestQwenRuntimeTag(refs: unknown): string | null {
	return selectLatestTag(refs, QWEN_REF_PATTERN);
}

function releaseAsset(
	value: unknown,
	expectedTag: string,
	tagPattern: RegExp,
	assetName: string,
	expectedPrerelease = false,
): ReleaseAsset | null {
	if (!tagPattern.test(expectedTag) || !value || typeof value !== "object") return null;
	const release = value as GithubRelease;
	if (
		release.draft !== false ||
		release.prerelease !== expectedPrerelease ||
		release.tag_name !== expectedTag ||
		!Array.isArray(release.assets)
	) {
		return null;
	}
	return (
		(release.assets.find((entry) => {
			if (!entry || typeof entry !== "object") return false;
			return (entry as ReleaseAsset).name === assetName;
		}) as ReleaseAsset | undefined) ?? null
	);
}

function selectAsset(
	value: unknown,
	expectedTag: string,
	tagPattern: RegExp,
	assetName: string,
	expectedPrerelease = false,
): string | null {
	const asset = releaseAsset(
		value,
		expectedTag,
		tagPattern,
		assetName,
		expectedPrerelease,
	);
	if (!asset || typeof asset.browser_download_url !== "string") return null;
	const expectedUrl = `${DOWNLOAD_PREFIX}${expectedTag}/${assetName}`;
	return asset.browser_download_url === expectedUrl ? expectedUrl : null;
}

function selectAssetInfo(
	value: unknown,
	expectedTag: string,
	tagPattern: RegExp,
	assetName: string,
	expectedPrerelease = false,
): CompanionAssetInfo | null {
	const url = selectAsset(
		value,
		expectedTag,
		tagPattern,
		assetName,
		expectedPrerelease,
	);
	const asset = releaseAsset(
		value,
		expectedTag,
		tagPattern,
		assetName,
		expectedPrerelease,
	);
	const tagMatch = tagPattern.exec(expectedTag);
	if (!url || !asset || !tagMatch) return null;
	if (typeof asset.digest !== "string" || !/^sha256:[a-f0-9]{64}$/.test(asset.digest)) {
		return null;
	}
	if (typeof asset.size !== "number" || !Number.isSafeInteger(asset.size) || asset.size <= 0) {
		return null;
	}
	return {
		tag: expectedTag,
		version: `${tagMatch[1]}.${tagMatch[2]}.${tagMatch[3]}`,
		url,
		sha256: asset.digest.slice("sha256:".length),
		size: asset.size,
	};
}

function companionChannel(tag: string): CompanionChannel | null {
	if (TAG_PATTERN.test(tag)) return "stable";
	if (COMPANION_RC_TAG_PATTERN.test(tag)) return "rc";
	return null;
}

export function isCompanionInstallableTag(tag: string): boolean {
	return companionChannel(tag) !== null;
}

export function selectCompanionInstallableAssetInfo(
	value: unknown,
	expectedTag: string,
): CompanionInstallableRelease | null {
	const channel = companionChannel(expectedTag);
	if (!channel) return null;
	const info =
		channel === "stable"
			? selectAssetInfo(value, expectedTag, TAG_PATTERN, ASSET_NAME, false)
			: selectAssetInfo(
					value,
					expectedTag,
					COMPANION_RC_TAG_PATTERN,
					ASSET_NAME,
					true,
				);
	return info ? { ...info, channel } : null;
}

export function selectLatestCompanionInstallableRelease(
	value: unknown,
): CompanionInstallableRelease | null {
	if (!Array.isArray(value)) return null;
	let latest: CompanionInstallableRelease | null = null;

	for (const entry of value) {
		if (!entry || typeof entry !== "object") continue;
		const tag = (entry as GithubRelease).tag_name;
		if (typeof tag !== "string") continue;
		const candidate = selectCompanionInstallableAssetInfo(entry, tag);
		if (!candidate) continue;
		if (!latest) {
			latest = candidate;
			continue;
		}

		const candidateVersion = versionTuple(candidate.version);
		const latestVersion = versionTuple(latest.version);
		if (isNewer(candidateVersion, latestVersion)) {
			latest = candidate;
			continue;
		}
		const sameVersion = candidateVersion.every(
			(part, index) => part === latestVersion[index],
		);
		if (sameVersion && candidate.channel === "stable" && latest.channel === "rc") {
			latest = candidate;
		}
	}

	return latest;
}

export function selectCompanionAsset(
	value: unknown,
	expectedTag: string,
): string | null {
	return selectAsset(value, expectedTag, TAG_PATTERN, ASSET_NAME);
}

export function selectCompanionAssetInfo(
	value: unknown,
	expectedTag: string,
): CompanionAssetInfo | null {
	return selectAssetInfo(value, expectedTag, TAG_PATTERN, ASSET_NAME);
}

function whisperAssetName(tag: string): string | null {
	const match = WHISPER_TAG_PATTERN.exec(tag);
	if (!match) return null;
	return `TDAWhisperRuntime-${match[1]}.${match[2]}.${match[3]}-windows-x64.zip`;
}

export function selectWhisperRuntimeAsset(
	value: unknown,
	expectedTag: string,
): string | null {
	const assetName = whisperAssetName(expectedTag);
	return assetName
		? selectAsset(value, expectedTag, WHISPER_TAG_PATTERN, assetName)
		: null;
}

export function selectWhisperRuntimeAssetInfo(
	value: unknown,
	expectedTag: string,
): WhisperRuntimeAssetInfo | null {
	const assetName = whisperAssetName(expectedTag);
	return assetName
		? selectAssetInfo(value, expectedTag, WHISPER_TAG_PATTERN, assetName)
		: null;
}

function qwenVersion(tag: string): string | null {
	const match = QWEN_TAG_PATTERN.exec(tag);
	return match ? `${match[1]}.${match[2]}.${match[3]}` : null;
}

export function qwenRuntimeBundleManifestName(tag: string): string | null {
	const version = qwenVersion(tag);
	return version ? `TDAQwenRuntimeBundle-${version}-windows-x64.json` : null;
}

export function selectQwenRuntimeBundleManifestAssetInfo(
	value: unknown,
	expectedTag: string,
): QwenRuntimeAssetInfo | null {
	const name = qwenRuntimeBundleManifestName(expectedTag);
	return name ? selectAssetInfo(value, expectedTag, QWEN_TAG_PATTERN, name) : null;
}

export function selectQwenRuntimePartAssetInfo(
	value: unknown,
	expectedTag: string,
	assetName: string,
): QwenRuntimeAssetInfo | null {
	const version = qwenVersion(expectedTag);
	if (!version) return null;
	const match = /^TDAQwenRuntime-(\d+\.\d+\.\d+)-windows-x64\.zip\.part(\d{3})$/.exec(
		assetName,
	);
	if (!match || match[1] !== version || Number(match[2]) < 1 || Number(match[2]) > 16) {
		return null;
	}
	return selectAssetInfo(value, expectedTag, QWEN_TAG_PATTERN, assetName);
}
