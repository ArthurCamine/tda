import { describe, expect, it } from "vitest";
import type { WorldGraphDraft } from "./model";
import { worldEntityMediaDraftHasIntent } from "./world-entity-media-intent";

const BASE_NODE = {
	id: "11111111-1111-4111-8111-111111111111",
	name: "Astel",
	slug: "astel",
	entityType: "pc" as const,
	status: "active",
	visibility: "public_web" as const,
	summary: "",
	aliases: [],
};

function draft(node: WorldGraphDraft["nodes"][number]): WorldGraphDraft {
	return {
		schemaVersion: 1,
		revision: 0,
		nodes: [node],
		edges: [],
		relationTypes: [],
	};
}

describe("World entity media draft intent", () => {
	it("does not treat an untouched node as media intent", () => {
		expect(worldEntityMediaDraftHasIntent(draft(BASE_NODE))).toBe(false);
	});

	it("treats both a portrait assignment and explicit removal as media intent", () => {
		expect(
			worldEntityMediaDraftHasIntent(
				draft({
					...BASE_NODE,
					primaryMediaAssetId: "22222222-2222-4222-8222-222222222222",
				}),
			),
		).toBe(true);
		expect(
			worldEntityMediaDraftHasIntent(draft({ ...BASE_NODE, primaryMediaAssetId: null })),
		).toBe(true);
	});
});
