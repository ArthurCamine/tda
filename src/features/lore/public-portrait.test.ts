import { describe, expect, it } from "vitest";
import { buildPublishedLoreProfile } from "./public-projection";
import { withPublishedLorePortraitFallback } from "./public-portrait";

function baseProfile() {
	const profile = buildPublishedLoreProfile({
		id: "11111111-1111-4111-8111-111111111111",
		name: "Dandelion",
		slug: "dandelion",
		entity_type: "pc",
		status: "active",
		visibility: "public_web",
		summary: "Uma memória publicada.",
		aliases: [],
	});
	if (!profile) throw new Error("profile fixture unavailable");
	return profile;
}

describe("public lore portrait fallback", () => {
	it("uses the verified World portrait when the generic profile has no authored hero media", () => {
		const profile = withPublishedLorePortraitFallback(baseProfile(), {
			imageUrl:
				"https://media.dnd.faysk.dev/campaigns/yuhara-main/entities/11111111-1111-4111-8111-111111111111/portrait/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.webp",
			focalPoint: { x: 0.2, y: 0.75 },
		});
		expect(profile.presentation.hero.poster).toEqual({
			src: expect.stringContaining("/portrait/"),
			alt: "Retrato de Dandelion",
		});
		expect(profile.presentation.hero.focalPoint).toEqual({ x: 20, y: 75 });
	});

	it("clamps malformed focal values instead of leaking invalid object-position percentages", () => {
		const profile = withPublishedLorePortraitFallback(baseProfile(), {
			imageUrl: "https://media.dnd.faysk.dev/portrait.webp",
			focalPoint: { x: -4, y: Number.NaN },
		});
		expect(profile.presentation.hero.focalPoint).toEqual({ x: 0, y: 50 });
	});

	it("never overrides authored lore hero media", () => {
		const base = baseProfile();
		const authored = {
			...base,
			presentation: {
				...base.presentation,
				hero: {
					...base.presentation.hero,
					poster: { src: "/authored.webp", alt: "Arte autoral" },
				},
			},
		};
		const result = withPublishedLorePortraitFallback(authored, {
			imageUrl: "https://media.dnd.faysk.dev/world.webp",
			focalPoint: { x: 0.5, y: 0.5 },
		});
		expect(result).toBe(authored);
		expect(result.presentation.hero.poster?.src).toBe("/authored.webp");
	});
});
