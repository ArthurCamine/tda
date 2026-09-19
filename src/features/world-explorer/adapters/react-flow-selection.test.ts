import { describe, expect, it } from "vitest";
import type { WorldGraphProjection } from "../model";
import {
	applyWorldFlowSelection,
	preserveWorldFlowNodeMeasurements,
	toReactFlowStructure,
} from "./react-flow";

const PROJECTION: WorldGraphProjection = {
	demo: true,
	mode: "overview",
	focusId: null,
	heroIds: ["hero"],
	nodes: [
		{
			id: "hero",
			slug: "hero",
			kind: "entity",
			entityType: "pc",
			label: "Hero",
		},
		{
			id: "friend",
			slug: "friend",
			kind: "entity",
			entityType: "npc",
			label: "Friend",
		},
		{
			id: "isolated",
			slug: "isolated",
			kind: "entity",
			entityType: "location",
			label: "Isolated",
		},
	],
	edges: [
		{
			id: "hero-friend",
			source: "hero",
			target: "friend",
			relationType: "friend_of",
			label: "Friend",
			direction: "symmetric",
			family: "affinity",
		},
	],
	relationTypes: [],
};

describe("World React Flow selection decoration", () => {
	it("reuses layout and routing while only decorating transient selection state", () => {
		const structure = toReactFlowStructure(PROJECTION);
		const heroPosition = structure.nodes.find((node) => node.id === "hero")?.position;
		const route = structure.edges[0];

		const selected = applyWorldFlowSelection(structure, "hero");
		expect(selected.nodes.find((node) => node.id === "hero")).toMatchObject({
			selected: true,
			zIndex: 5,
			data: { isDimmed: false },
		});
		expect(selected.nodes.find((node) => node.id === "friend")?.data.isDimmed).toBe(false);
		expect(selected.nodes.find((node) => node.id === "isolated")?.data.isDimmed).toBe(true);
		expect(selected.edges[0].data).toMatchObject({
			isHighlighted: true,
			isDimmed: false,
		});
		expect(selected.nodes.find((node) => node.id === "hero")?.position).toBe(heroPosition);
		expect(selected.edges[0].sourceHandle).toBe(route.sourceHandle);
		expect(selected.edges[0].targetHandle).toBe(route.targetHandle);

		// The cached structure itself stays selection-neutral and can be reused.
		expect(structure.nodes.every((node) => node.selected === false)).toBe(true);
		expect(structure.nodes.every((node) => node.data.isDimmed === false)).toBe(true);
		expect(structure.edges[0].data).toMatchObject({
			isHighlighted: false,
			isDimmed: false,
		});
	});

	it("clears dimming without rebuilding the structural graph", () => {
		const structure = toReactFlowStructure(PROJECTION);
		const selected = applyWorldFlowSelection(structure, "hero");
		const cleared = applyWorldFlowSelection(structure, null);

		expect(selected).not.toBe(structure);
		expect(cleared.nodes.every((node) => node.selected === false)).toBe(true);
		expect(cleared.nodes.every((node) => node.data.isDimmed === false)).toBe(true);
		expect(cleared.edges.every((edge) => edge.data?.isDimmed === false)).toBe(true);
	});

	it("preserves React Flow measurements when domain-driven graph data refreshes", () => {
		const structure = toReactFlowStructure(PROJECTION);
		const current = structure.nodes.map((node) =>
			node.id === "hero"
				? { ...node, measured: { width: 240, height: 144 } }
				: node,
		);
		const next = structure.nodes.map((node) =>
			node.id === "hero"
				? { ...node, data: { ...node.data, isDimmed: true } }
				: node,
		);

		const reconciled = preserveWorldFlowNodeMeasurements(current, next);
		const hero = reconciled.find((node) => node.id === "hero");

		expect(hero?.measured).toEqual({ width: 240, height: 144 });
		expect(hero?.data.isDimmed).toBe(true);
		expect(reconciled.find((node) => node.id === "friend")?.measured).toBeUndefined();
	});
});
