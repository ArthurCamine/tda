import { describe, expect, test } from "vitest";
import { verifyCanonicalProduction } from "./verify-production-canonical.mjs";

const goodHealth = { ok: true, environment: "production", commit: "sha" };
const goodVersion = { commit: "sha", release: "prod-sha" };

function fakeFetch(states: Array<{ health: object; version: object }>) {
	let call = 0;
	return async (input: string | URL | Request) => {
		const state = states[Math.min(Math.floor(call / 2), states.length - 1)];
		call += 1;
		const body = String(input).endsWith("/api/health") ? state.health : state.version;
		return new Response(JSON.stringify(body), { status: 200 });
	};
}

describe("verifyCanonicalProduction", () => {
	test("accepts matching canonical state", async () => {
		const result = await verifyCanonicalProduction({
			origin: "https://example.test",
			sourceSha: "sha",
			releaseId: "prod-sha",
			fetchImpl: fakeFetch([{ health: goodHealth, version: goodVersion }]),
			attempts: 1,
			delayMs: 0,
			sleepImpl: async () => {},
		});
		expect(result.attempt).toBe(1);
	});

	test("waits for a stale alias to converge", async () => {
		const stale = {
			health: { ok: true, environment: "production", commit: "old" },
			version: { commit: "old", release: "prod-old" },
		};
		const result = await verifyCanonicalProduction({
			origin: "https://example.test",
			sourceSha: "sha",
			releaseId: "prod-sha",
			fetchImpl: fakeFetch([stale, { health: goodHealth, version: goodVersion }]),
			attempts: 2,
			delayMs: 0,
			sleepImpl: async () => {},
		});
		expect(result.attempt).toBe(2);
	});
});
