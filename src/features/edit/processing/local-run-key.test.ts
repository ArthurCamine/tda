import { describe, expect, it } from "vitest";
import {
	localRunKey,
	sameLocalRun,
	serializeLocalRunKey,
} from "./local-run-key";

describe("local run identity", () => {
	it("keeps identical legacy run ids distinct across sources", () => {
		const left = { sourceId: "source-a", runId: "legacy-same" };
		const right = { sourceId: "source-b", runId: "legacy-same" };

		expect(sameLocalRun(localRunKey(left), right)).toBe(false);
		expect(serializeLocalRunKey(localRunKey(left))).not.toBe(
			serializeLocalRunKey(localRunKey(right)),
		);
	});

	it("uses value identity instead of object reference", () => {
		const original = { sourceId: "source-a", runId: "run-1" };
		const reconstructed = JSON.parse(
			JSON.stringify(original),
		) as typeof original;

		expect(original).not.toBe(reconstructed);
		expect(sameLocalRun(localRunKey(original), reconstructed)).toBe(true);
		expect(serializeLocalRunKey(localRunKey(original))).toBe(
			serializeLocalRunKey(localRunKey(reconstructed)),
		);
	});

	it("serializes arbitrary bounded identifiers without delimiter ambiguity", () => {
		const first = { sourceId: "a:b", runId: "c" };
		const second = { sourceId: "a", runId: "b:c" };

		expect(serializeLocalRunKey(localRunKey(first))).not.toBe(
			serializeLocalRunKey(localRunKey(second)),
		);
	});
});
