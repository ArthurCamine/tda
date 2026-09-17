import { describe, expect, it } from "vitest";
import { selectLatestCompanionRcRelease } from "./companion-rc-release";

function release(tag: string, prerelease = true) {
	return {
		tag_name: tag,
		draft: false,
		prerelease,
		assets: [
			{
				name: "TDACompanion-x64.msi",
				browser_download_url: `https://github.com/Faysk/tda/releases/download/${tag}/TDACompanion-x64.msi`,
				digest: `sha256:${"b".repeat(64)}`,
				size: 16_000_000,
			},
		],
	};
}

describe("selectLatestCompanionRcRelease", () => {
	it("selects the newest valid RC without exposing stable releases", () => {
		expect(
			selectLatestCompanionRcRelease([
				release("companion-v0.4.0", false),
				release("companion-rc-v0.3.7-111111111111"),
				release("companion-rc-v0.3.8-222222222222"),
			]),
		).toMatchObject({
			channel: "rc",
			tag: "companion-rc-v0.3.8-222222222222",
			version: "0.3.8",
		});
	});

	it("keeps the newest release-list entry when two RCs share a version", () => {
		const newest = release("companion-rc-v0.3.8-333333333333");
		const older = release("companion-rc-v0.3.8-222222222222");
		expect(selectLatestCompanionRcRelease([newest, older])?.tag).toBe(
			"companion-rc-v0.3.8-333333333333",
		);
	});

	it("fails closed for stable-only or malformed inputs", () => {
		expect(
			selectLatestCompanionRcRelease([
				release("companion-v0.3.8", false),
				release("companion-rc-v0.3.8-notasha"),
			]),
		).toBeNull();
	});
});
