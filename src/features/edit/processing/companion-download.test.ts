import { describe, expect, it } from "vitest";
import { parseCompanionDownloadManifest } from "./companion-download";

describe("parseCompanionDownloadManifest", () => {
	it("binds the displayed version to the exact pinned download URL", () => {
		expect(
			parseCompanionDownloadManifest({
				version: "0.3.2",
				asset: { url: "/api/downloads/companion/windows?version=0.3.2" },
			}),
		).toEqual({
			version: "0.3.2",
			url: "/api/downloads/companion/windows?version=0.3.2",
		});
	});

	it("rejects a manifest whose URL does not match its version", () => {
		expect(
			parseCompanionDownloadManifest({
				version: "0.3.4",
				asset: { url: "/api/downloads/companion/windows?version=0.3.2" },
			}),
		).toBeNull();
		expect(
			parseCompanionDownloadManifest({
				version: "0.3.4",
				asset: { url: "https://example.invalid/TDACompanion-x64.msi" },
			}),
		).toBeNull();
	});
});
