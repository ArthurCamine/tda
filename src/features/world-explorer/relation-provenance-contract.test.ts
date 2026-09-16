import { describe, expect, it } from "vitest";
import {
	activeRelationCanonSourceIds,
	relationHasActiveCanonProvenance,
} from "./relation-provenance-contract";

describe("World relation provenance eligibility", () => {
	it("rejects a draft-only relation even when ids match", () => {
		expect(relationHasActiveCanonProvenance(false, ["canon-a"], ["canon-a"])).toBe(false);
	});

	it("rejects a stale selected canon entry", () => {
		expect(relationHasActiveCanonProvenance(true, ["canon-old"], ["canon-active"])).toBe(false);
	});

	it("accepts a persisted relation with at least one active selected canon entry", () => {
		expect(
			relationHasActiveCanonProvenance(
				true,
				["canon-old", "canon-active"],
				["canon-active", "canon-other"],
			),
		).toBe(true);
	});

	it("rejects empty provenance", () => {
		expect(relationHasActiveCanonProvenance(true, [], ["canon-active"])).toBe(false);
	});
});

describe("World relation provenance replacement payload", () => {
	it("keeps only unique canon ids that are still active", () => {
		expect(
			activeRelationCanonSourceIds(
				["canon-old", "canon-active", "canon-active", "canon-other-old"],
				["canon-active", "canon-other-active"],
			),
		).toEqual(["canon-active"]);
	});

	it("returns an empty payload when all selected sources are stale", () => {
		expect(activeRelationCanonSourceIds(["canon-old"], [])).toEqual([]);
	});
});
