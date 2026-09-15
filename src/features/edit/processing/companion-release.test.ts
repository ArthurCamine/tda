import { describe, expect, it } from "vitest";
import {
	isCompanionInstallableTag,
	selectCompanionAsset,
	selectCompanionAssetInfo,
	selectCompanionInstallableAssetInfo,
	selectLatestCompanionInstallableRelease,
	selectLatestCompanionTag,
	selectLatestWhisperRuntimeTag,
	selectWhisperRuntimeAsset,
	selectWhisperRuntimeAssetInfo,
} from "./companion-release";

function release(
	tag: string,
	options: {
		draft?: boolean;
		prerelease?: boolean;
		url?: string;
		digest?: string;
		size?: number;
	} = {},
) {
	return {
		tag_name: tag,
		draft: options.draft ?? false,
		prerelease: options.prerelease ?? false,
		assets: [
			{
				name: "TDACompanion-x64.msi",
				browser_download_url:
					options.url ??
					`https://github.com/Faysk/tda/releases/download/${tag}/TDACompanion-x64.msi`,
				digest: options.digest ?? `sha256:${"a".repeat(64)}`,
				size: options.size ?? 16_000_000,
			},
		],
	};
}

function whisperRelease(
	version: string,
	options: {
		draft?: boolean;
		prerelease?: boolean;
		url?: string;
		digest?: string;
		size?: number;
	} = {},
) {
	const tag = `companion-whisper-runtime-v${version}`;
	const name = `TDAWhisperRuntime-${version}-windows-x64.zip`;
	return {
		tag_name: tag,
		draft: options.draft ?? false,
		prerelease: options.prerelease ?? false,
		assets: [
			{
				name,
				browser_download_url:
					options.url ?? `https://github.com/Faysk/tda/releases/download/${tag}/${name}`,
				digest: options.digest ?? `sha256:${"b".repeat(64)}`,
				size: options.size ?? 1_500_000_000,
			},
		],
	};
}

describe("selectLatestCompanionTag", () => {
	it("selects the greatest companion semantic version from matching refs", () => {
		expect(
			selectLatestCompanionTag([
				{ ref: "refs/tags/companion-v0.2.0" },
				{ ref: "refs/tags/companion-v1.0.0" },
				{ ref: "refs/tags/companion-v0.12.4" },
				{ ref: "refs/tags/prod-abcdef123456" },
			]),
		).toBe("companion-v1.0.0");
	});

	it("ignores malformed, prerelease-shaped and RC tags", () => {
		expect(
			selectLatestCompanionTag([
				{ ref: "refs/tags/companion-v1.0" },
				{ ref: "refs/tags/companion-v1.0.0-beta" },
				{ ref: "refs/tags/companion-rc-v9.9.9-abcdef123456" },
				{ ref: "refs/heads/companion-v9.0.0" },
			]),
		).toBeNull();
	});
});

describe("selectCompanionAsset", () => {
	it("accepts the official MSI asset for the selected release", () => {
		expect(
			selectCompanionAsset(release("companion-v0.2.0"), "companion-v0.2.0"),
		).toBe(
			"https://github.com/Faysk/tda/releases/download/companion-v0.2.0/TDACompanion-x64.msi",
		);
	});

	it("rejects a draft, prerelease or mismatched release", () => {
		expect(
			selectCompanionAsset(
				release("companion-v0.2.0", { draft: true }),
				"companion-v0.2.0",
			),
		).toBeNull();
		expect(
			selectCompanionAsset(
				release("companion-v0.2.0", { prerelease: true }),
				"companion-v0.2.0",
			),
		).toBeNull();
		expect(
			selectCompanionAsset(release("companion-v0.2.0"), "companion-v0.3.0"),
		).toBeNull();
	});

	it("rejects assets outside the exact official release path", () => {
		expect(
			selectCompanionAsset(
				release("companion-v0.2.0", {
					url: "https://example.com/TDACompanion-x64.msi",
				}),
				"companion-v0.2.0",
			),
		).toBeNull();
	});
});

describe("selectCompanionAssetInfo", () => {
	it("returns the version, size and sha256 only for a validated asset", () => {
		expect(
			selectCompanionAssetInfo(release("companion-v0.3.0"), "companion-v0.3.0"),
		).toEqual({
			tag: "companion-v0.3.0",
			version: "0.3.0",
			url: "https://github.com/Faysk/tda/releases/download/companion-v0.3.0/TDACompanion-x64.msi",
			sha256: "a".repeat(64),
			size: 16_000_000,
		});
	});

	it("fails closed when digest or size metadata is missing or malformed", () => {
		expect(
			selectCompanionAssetInfo(
				release("companion-v0.3.0", { digest: "md5:deadbeef" }),
				"companion-v0.3.0",
			),
		).toBeNull();
		expect(
			selectCompanionAssetInfo(
				release("companion-v0.3.0", { size: 0 }),
				"companion-v0.3.0",
			),
		).toBeNull();
	});
});

describe("newest installable Companion release", () => {
	it("accepts stable and immutable RC tag shapes only", () => {
		expect(isCompanionInstallableTag("companion-v0.3.4")).toBe(true);
		expect(isCompanionInstallableTag("companion-rc-v0.3.4-abcdef123456")).toBe(true);
		expect(isCompanionInstallableTag("companion-rc-v0.3.4-latest")).toBe(false);
		expect(isCompanionInstallableTag("companion-v0.3.4-beta")).toBe(false);
	});

	it("selects a newer RC over an older stable release", () => {
		const stable = release("companion-v0.3.2");
		const rc = release("companion-rc-v0.3.4-abcdef123456", { prerelease: true });
		expect(selectLatestCompanionInstallableRelease([stable, rc])).toEqual({
			channel: "rc",
			tag: "companion-rc-v0.3.4-abcdef123456",
			version: "0.3.4",
			url: "https://github.com/Faysk/tda/releases/download/companion-rc-v0.3.4-abcdef123456/TDACompanion-x64.msi",
			sha256: "a".repeat(64),
			size: 16_000_000,
		});
	});

	it("prefers stable when RC and stable have the same semantic version", () => {
		const rc = release("companion-rc-v0.3.4-abcdef123456", { prerelease: true });
		const stable = release("companion-v0.3.4");
		expect(selectLatestCompanionInstallableRelease([rc, stable])?.channel).toBe("stable");
		expect(selectLatestCompanionInstallableRelease([rc, stable])?.tag).toBe(
			"companion-v0.3.4",
		);
	});

	it("fails closed when the release channel state does not match its tag", () => {
		const rcTag = "companion-rc-v0.3.4-abcdef123456";
		expect(selectCompanionInstallableAssetInfo(release(rcTag), rcTag)).toBeNull();
		expect(
			selectCompanionInstallableAssetInfo(
				release("companion-v0.3.4", { prerelease: true }),
				"companion-v0.3.4",
			),
		).toBeNull();
	});

	it("ignores drafts and malformed Companion-like releases", () => {
		const valid = release("companion-v0.3.2");
		const draftNewer = release("companion-rc-v9.9.9-abcdef123456", {
			draft: true,
			prerelease: true,
		});
		const malformed = release("companion-rc-v9.9.9-notasha", { prerelease: true });
		expect(selectLatestCompanionInstallableRelease([draftNewer, malformed, valid])?.tag).toBe(
			"companion-v0.3.2",
		);
	});
});

describe("Whisper runtime release selection", () => {
	it("keeps the runtime release namespace separate from Companion and production tags", () => {
		expect(
			selectLatestWhisperRuntimeTag([
				{ ref: "refs/tags/companion-v9.0.0" },
				{ ref: "refs/tags/prod-deadbeef" },
				{ ref: "refs/tags/companion-whisper-runtime-v1.0.0" },
				{ ref: "refs/tags/companion-whisper-runtime-v1.2.0" },
			]),
		).toBe("companion-whisper-runtime-v1.2.0");
	});

	it("accepts only the exact immutable GitHub runtime asset", () => {
		const tag = "companion-whisper-runtime-v1.0.0";
		expect(selectWhisperRuntimeAsset(whisperRelease("1.0.0"), tag)).toBe(
			"https://github.com/Faysk/tda/releases/download/companion-whisper-runtime-v1.0.0/TDAWhisperRuntime-1.0.0-windows-x64.zip",
		);
		expect(
			selectWhisperRuntimeAsset(
				whisperRelease("1.0.0", { url: "https://example.com/runtime.zip" }),
				tag,
			),
		).toBeNull();
	});

	it("returns only runtime assets with GitHub sha256 and positive size metadata", () => {
		const tag = "companion-whisper-runtime-v1.0.0";
		expect(selectWhisperRuntimeAssetInfo(whisperRelease("1.0.0"), tag)).toEqual({
			tag,
			version: "1.0.0",
			url: "https://github.com/Faysk/tda/releases/download/companion-whisper-runtime-v1.0.0/TDAWhisperRuntime-1.0.0-windows-x64.zip",
			sha256: "b".repeat(64),
			size: 1_500_000_000,
		});
		expect(
			selectWhisperRuntimeAssetInfo(
				whisperRelease("1.0.0", { digest: "sha1:bad" }),
				tag,
			),
		).toBeNull();
	});
});
