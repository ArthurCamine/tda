import { hasRemoteMatch } from "next/dist/shared/lib/match-remote-pattern";
import { describe, expect, it } from "vitest";
import config from "../../../next.config";
import { toPublishedSession } from "./model";

const prefix = "https://media.dnd.faysk.dev/campaigns/yuhara-main/sessions/";
const key = `caeb376d-0a7d-5bf7-b18a-68c82557b61d/cover/${"a".repeat(64)}`;
const row = {
	source_session_id: "session-1",
	title: "Session",
	session_date: "2026-06-24",
	arc: "Arc",
	summary_short: "Summary",
	status: "published",
	campaigns: { slug: "yuhara-main" },
};

describe("R2 public session delivery", () => {
	it.each(["webp", "png"])(
		"accepts public %s in model and actual Next matcher",
		(ext) => {
			const url = `${prefix}${key}.${ext}`;
			expect(
				toPublishedSession({ ...row, cover_image_url: url })?.coverImage,
			).toBe(url);
			expect(
				hasRemoteMatch([], config.images?.remotePatterns ?? [], new URL(url)),
			).toBe(true);
		},
	);
	it.each([
		`${prefix}${key}.webp?token=synthetic`,
		`${prefix}${key}.webp`.replace("https:", "http:"),
		`${prefix}${key}.webp`.replace(
			"media.dnd.faysk.dev",
			"media.dnd.faysk.dev.evil.example",
		),
		`${prefix}${key}.webp`.replace(
			"media.dnd.faysk.dev",
			"media.dnd.faysk.dev:8443",
		),
		`${prefix}${key}.webp`.replace("yuhara-main", "another-campaign"),
		"https://media.dnd.faysk.dev/private/master.png",
		"https://tda-media-private.example/master.png",
		"https://tda-media-preview.example/image.png",
		"https://raw.githubusercontent.com/Faysk/dnd-scribe/48f8a43e8145e782d3bf4186a4a9b4218a92c643/web/assets/sessions/2026-07-25/card.webp",
	])("rejects out-of-scope image %s in both boundaries", (url) => {
		expect(
			toPublishedSession({ ...row, cover_image_url: url }),
		).not.toHaveProperty("coverImage");
		expect(
			hasRemoteMatch([], config.images?.remotePatterns ?? [], new URL(url)),
		).toBe(false);
	});
	it("rejects embedded credentials and fragments in the model", () => {
		for (const url of [
			`${prefix}${key}.webp#private`,
			`${prefix}${key}.webp`.replace("https://", "https://user:pass@"),
		]) {
			expect(
				toPublishedSession({ ...row, cover_image_url: url }),
			).not.toHaveProperty("coverImage");
		}
	});
});
