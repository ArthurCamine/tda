import { describe, expect, it } from "vitest";
import { evidenceBackedRelationIds } from "./canonical-publication-contract";

const relations = [{ id: "relation-a" }, { id: "relation-b" }, { id: "relation-c" }];

describe("World canonical publication provenance", () => {
	it("excludes a relation with no source", () => {
		expect(evidenceBackedRelationIds(relations, [], ["canon-a"])).toEqual(new Set());
	});

	it("excludes a source that points to a canon entry outside the reviewed campaign set", () => {
		const backed = evidenceBackedRelationIds(
			relations,
			[{ relation_id: "relation-a", canon_entry_id: "canon-other" }],
			["canon-a"],
		);
		expect(backed).toEqual(new Set());
	});

	it("includes a relation backed by an existing reviewed canon entry", () => {
		const backed = evidenceBackedRelationIds(
			relations,
			[{ relation_id: "relation-a", canon_entry_id: "canon-a" }],
			["canon-a"],
		);
		expect(backed).toEqual(new Set(["relation-a"]));
	});

	it("accepts any valid source while ignoring stale sources for the same relation", () => {
		const backed = evidenceBackedRelationIds(
			relations,
			[
				{ relation_id: "relation-b", canon_entry_id: "canon-missing" },
				{ relation_id: "relation-b", canon_entry_id: "canon-b" },
			],
			["canon-b"],
		);
		expect(backed).toEqual(new Set(["relation-b"]));
	});

	it("does not let a source for an unknown relation authorize another edge", () => {
		const backed = evidenceBackedRelationIds(
			relations,
			[{ relation_id: "relation-unknown", canon_entry_id: "canon-a" }],
			["canon-a"],
		);
		expect(backed).toEqual(new Set());
	});
});
