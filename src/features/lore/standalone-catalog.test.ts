import { describe, expect, it } from "vitest";
import { standaloneLoreForEntity } from "./standalone-catalog";

describe("editorial lore links", () => {
	it("uses exact character slugs without matching names or other entity types", () => {
		expect(standaloneLoreForEntity("pc", "astel")?.slug).toBe("astel");
		expect(standaloneLoreForEntity("pc", "noah")?.slug).toBe("noah");
		for (const [type, slug] of [
			["npc", "astel"],
			["location", "noah"],
			["pc", "Noah Wood"],
			["pc", "astel-nightshade"],
			["pc", null],
			[undefined, "astel"],
		]) {
			expect(
				standaloneLoreForEntity(type ?? undefined, slug ?? null),
			).toBeNull();
		}
	});
});
