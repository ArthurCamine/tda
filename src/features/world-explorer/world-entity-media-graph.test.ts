import { describe, expect, it } from "vitest";
import { sanitizeWorldGraphDraft, worldDatasetFromDraft } from "./graph-contract";

const NODE_ID = "11111111-1111-4111-8111-111111111111";
const ASSET_ID = "22222222-2222-4222-8222-222222222222";

function draftNode(overrides: Record<string, unknown> = {}) {
	return {
		id: NODE_ID,
		name: "Astel",
		slug: "astel",
		entityType: "pc",
		status: "active",
		visibility: "public_web",
		summary: "",
		aliases: [],
		...overrides,
	};
}

function candidate(node: Record<string, unknown>) {
	return {
		schemaVersion: 1,
		revision: 3,
		nodes: [node],
		edges: [],
		relationTypes: [],
	};
}

describe("World graph entity media contract", () => {
	it("keeps an untouched node free of media fields", () => {
		const draft = sanitizeWorldGraphDraft(candidate(draftNode()));
		expect(draft?.nodes[0]?.primaryMediaAssetId).toBeUndefined();
		expect(draft?.nodes[0]?.primaryMediaFocalPoint).toBeUndefined();
	});

	it("accepts a stable asset id and defaults focal point to the center", () => {
		const draft = sanitizeWorldGraphDraft(
			candidate(draftNode({ primaryMediaAssetId: ASSET_ID })),
		);
		expect(draft?.nodes[0]?.primaryMediaAssetId).toBe(ASSET_ID);
		expect(draft?.nodes[0]?.primaryMediaFocalPoint).toEqual({ x: 0.5, y: 0.5 });

		if (!draft) throw new Error("draft was rejected");
		const dataset = worldDatasetFromDraft(draft);
		expect(dataset.nodes[0]?.imageUrl).toBe(`/api/world/entity-media/${ASSET_ID}`);
		expect(dataset.nodes[0]?.imageFocalPoint).toEqual({ x: 0.5, y: 0.5 });
	});

	it("preserves an explicit removal without a focal point", () => {
		const draft = sanitizeWorldGraphDraft(
			candidate(draftNode({ primaryMediaAssetId: null })),
		);
		expect(draft?.nodes[0]?.primaryMediaAssetId).toBeNull();
		expect(draft?.nodes[0]?.primaryMediaFocalPoint).toBeUndefined();
	});

	it("rejects malformed ids and out-of-range focal points", () => {
		expect(
			sanitizeWorldGraphDraft(
				candidate(draftNode({ primaryMediaAssetId: "https://example.com/a.webp" })),
			),
		).toBeNull();
		expect(
			sanitizeWorldGraphDraft(
				candidate(
					draftNode({
						primaryMediaAssetId: ASSET_ID,
						primaryMediaFocalPoint: { x: 1.2, y: 0.4 },
					}),
				),
			),
		).toBeNull();
	});
});
