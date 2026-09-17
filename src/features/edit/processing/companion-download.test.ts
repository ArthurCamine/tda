import { describe, expect, it } from "vitest";
import {
	companionManifestUrl,
	parseCompanionDownloadManifest,
} from "./companion-download";

describe("companionManifestUrl", () => {
	it("keeps stable as the default surface and requires explicit RC opt-in", () => {
		expect(companionManifestUrl("stable")).toBe(
			"/api/downloads/companion/windows/manifest",
		);
		expect(companionManifestUrl("rc")).toBe(
			"/api/downloads/companion/windows/manifest?channel=rc",
		);
	});
});

describe("parseCompanionDownloadManifest", () => {
	it("binds a stable version to the exact pinned stable tag", () => {
		expect(
			parseCompanionDownloadManifest({
				channel: "stable",
				version: "0.3.2",
				tag: "companion-v0.3.2",
				asset: {
					url: "/api/downloads/companion/windows?tag=companion-v0.3.2",
				},
			}),
		).toEqual({
			version: "0.3.2",
			channel: "stable",
			tag: "companion-v0.3.2",
			url: "/api/downloads/companion/windows?tag=companion-v0.3.2",
		});
	});

	it("accepts an RC only when channel, version, tag and URL agree", () => {
		const tag = "companion-rc-v0.3.8-abcdef123456";
		expect(
			parseCompanionDownloadManifest({
				channel: "rc",
				version: "0.3.8",
				tag,
				asset: {
					url: `/api/downloads/companion/windows?tag=${tag}`,
				},
			}),
		).toEqual({
			version: "0.3.8",
			channel: "rc",
			tag,
			url: `/api/downloads/companion/windows?tag=${tag}`,
		});
	});

	it("rejects a manifest whose channel, tag, version or URL do not match", () => {
		expect(
			parseCompanionDownloadManifest({
				channel: "stable",
				version: "0.3.4",
				tag: "companion-v0.3.2",
				asset: {
					url: "/api/downloads/companion/windows?tag=companion-v0.3.2",
				},
			}),
		).toBeNull();
		expect(
			parseCompanionDownloadManifest({
				channel: "stable",
				version: "0.3.4",
				tag: "companion-rc-v0.3.4-abcdef123456",
				asset: {
					url: "/api/downloads/companion/windows?tag=companion-rc-v0.3.4-abcdef123456",
				},
			}),
		).toBeNull();
		expect(
			parseCompanionDownloadManifest({
				channel: "rc",
				version: "0.3.4",
				tag: "companion-rc-v0.3.4-abcdef123456",
				asset: { url: "https://example.invalid/TDACompanion-x64.msi" },
			}),
		).toBeNull();
	});
});
