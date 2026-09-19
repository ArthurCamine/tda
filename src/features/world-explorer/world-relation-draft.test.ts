import { describe, expect, it } from "vitest";
import type { WorldGraphDraft } from "./model";
import {
	appendWorldDraftRelation,
	changeWorldDraftRelationType,
	reconnectWorldDraftRelation,
} from "./world-relation-draft";

const draft: WorldGraphDraft = {
	schemaVersion: 1,
	revision: 4,
	nodes: ["a", "b", "c"].map((id) => ({
		id,
		name: id.toUpperCase(),
		slug: id,
		entityType: "npc" as const,
		status: "active",
		visibility: "private_players" as const,
		summary: "",
		aliases: [],
	})),
	edges: [],
	relationTypes: [
		{
			slug: "friend",
			label: "Amizade",
			direction: "symmetric",
			family: "affinity",
			description: "",
			isActive: true,
			color: "#65c98a",
			lineStyle: "solid",
			lineWidth: 3,
		},
		{
			slug: "mentor",
			label: "Mentoria",
			direction: "directed",
			family: "authority",
			description: "",
			isActive: true,
			color: "#8f9aa8",
			lineStyle: "solid",
			lineWidth: 3,
		},
	],
};

function edge(
	id: string,
	source: string,
	target: string,
	relationType: "friend" | "mentor",
): WorldGraphDraft["edges"][number] {
	return {
		id,
		source,
		target,
		relationType,
		labelOverride: null,
		status: "active",
		visibility: "private_players",
		colorOverride: null,
		lineStyleOverride: null,
		lineWidthOverride: null,
	};
}

describe("World relation draft authoring", () => {
	it("creates a private relation without mutating the input draft", () => {
		const next = appendWorldDraftRelation(draft, {
			id: "edge-1",
			sourceId: "a",
			targetId: "b",
			relationType: "friend",
		});

		expect(next?.edges).toHaveLength(1);
		expect(next?.edges[0]).toMatchObject({
			id: "edge-1",
			source: "a",
			target: "b",
			relationType: "friend",
			status: "active",
			visibility: "private_players",
		});
		expect(draft.edges).toHaveLength(0);
	});

	it("blocks self-links and equivalent symmetric duplicates on create", () => {
		expect(
			appendWorldDraftRelation(draft, {
				id: "self",
				sourceId: "a",
				targetId: "a",
				relationType: "friend",
			}),
		).toBeNull();

		const first = appendWorldDraftRelation(draft, {
			id: "edge-1",
			sourceId: "a",
			targetId: "b",
			relationType: "friend",
		});
		expect(first).not.toBeNull();
		expect(
			appendWorldDraftRelation(first as WorldGraphDraft, {
				id: "edge-2",
				sourceId: "b",
				targetId: "a",
				relationType: "friend",
			}),
		).toBeNull();
	});

	it("lets the explicitly edited relation win when a type change collides", () => {
		const withRelations: WorldGraphDraft = {
			...draft,
			edges: [edge("edge-1", "a", "b", "mentor"), edge("edge-2", "a", "b", "friend")],
		};

		const next = changeWorldDraftRelationType(withRelations, "edge-1", "friend");

		expect(next?.edges.find((item) => item.id === "edge-1")).toMatchObject({
			relationType: "friend",
			status: "active",
		});
		expect(next?.edges.find((item) => item.id === "edge-2")).toMatchObject({
			status: "archived",
		});
	});

	it("reconnects an existing edge and archives an equivalent relation it replaces", () => {
		const withMentors: WorldGraphDraft = {
			...draft,
			edges: [edge("edge-1", "a", "b", "mentor"), edge("edge-2", "a", "c", "mentor")],
		};

		const moved = reconnectWorldDraftRelation(withMentors, "edge-1", "a", "c");

		expect(moved?.edges.find((item) => item.id === "edge-1")).toMatchObject({
			source: "a",
			target: "c",
			status: "active",
		});
		expect(moved?.edges.find((item) => item.id === "edge-2")).toMatchObject({
			status: "archived",
		});
	});

	it("still reconnects to a non-conflicting destination", () => {
		const withMentors: WorldGraphDraft = {
			...draft,
			edges: [edge("edge-1", "a", "b", "mentor"), edge("edge-2", "a", "c", "mentor")],
		};

		const moved = reconnectWorldDraftRelation(withMentors, "edge-1", "b", "c");

		expect(moved?.edges.find((item) => item.id === "edge-1")).toMatchObject({
			source: "b",
			target: "c",
		});
		expect(moved?.edges.find((item) => item.id === "edge-2")?.status).toBe("active");
	});
});
