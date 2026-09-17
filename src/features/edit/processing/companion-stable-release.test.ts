import { describe, expect, it } from "vitest";
import { selectLatestCompanionStableRelease } from "./companion-stable-release";

function release(tag: string, prerelease = false) {
	return {
		tag_name: tag,
		draft: false,
		prerelease,
		assets: [
			{
				name: "TDACompanion-x64.msi",
				browser_download_url: `https://github.com/Faysk/tda/releases/download/${tag}/TDACompanion-x64.msi`,
				digest: `sha256:${"a".repeat(64)}`,
				size: 16_000_000,
			},
		],
	};
}

describe("selectLatestCompanionStableRelease", () => {
	it("never promotes a newer RC through the stable surface", () => {
		const stable = release("companion-v0.3.7");
		const newerRc = release("companion-rc-v0.3.8-abcdef123456", true);

		expect(selectLatestCompanionStableRelease([newerRc, stable])).toMatchObject({
			channel: "stable",
			tag: "companion-v0.3.7",
			version: "0.3.7",
		});
	});

	it("selects the newest valid stable release", () => {
		expect(
			selectLatestCompanionStableRelease([
				release("companion-v0.3.4"),
				release("companion-v0.3.7"),
				release("companion-v0.3.6"),
			]),
		).toMatchObject({ tag: "companion-v0.3.7", channel: "stable" });
	});

	it("fails closed when only RC or malformed releases exist", () => {
		expect(
			selectLatestCompanionStableRelease([
				release("companion-rc-v9.9.9-abcdef123456", true),
				release("companion-v9.9"),
			]),
		).toBeNull();
	});
});
