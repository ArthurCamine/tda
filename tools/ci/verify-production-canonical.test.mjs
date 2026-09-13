import assert from "node:assert/strict";
import test from "node:test";

import { verifyCanonicalProduction } from "./verify-production-canonical.mjs";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function fetchSequence(states) {
  let request = 0;
  return async (url) => {
    const attempt = Math.floor(request / 2);
    request += 1;
    const state = states[Math.min(attempt, states.length - 1)];
    if (url.endsWith("/api/health")) return jsonResponse(state.health);
    if (url.endsWith("/api/version")) return jsonResponse(state.version);
    throw new Error(`unexpected URL ${url}`);
  };
}

const expected = {
  health: { ok: true, environment: "production", commit: "expected-sha" },
  version: { commit: "expected-sha", release: "prod-expected" },
};

test("accepts canonical Production immediately when commit and release match", async () => {
  const result = await verifyCanonicalProduction({
    origin: "https://example.test",
    sourceSha: "expected-sha",
    releaseId: "prod-expected",
    fetchImpl: fetchSequence([expected]),
    attempts: 3,
    delayMs: 0,
    sleepImpl: async () => {},
  });
  assert.equal(result.attempt, 1);
});

test("retries state mismatch and succeeds after canonical convergence", async () => {
  const stale = {
    health: { ok: true, environment: "production", commit: "previous-sha" },
    version: { commit: "previous-sha", release: "prod-previous" },
  };
  const attempts = [];
  const result = await verifyCanonicalProduction({
    origin: "https://example.test/",
    sourceSha: "expected-sha",
    releaseId: "prod-expected",
    fetchImpl: fetchSequence([stale, expected]),
    attempts: 3,
    delayMs: 0,
    sleepImpl: async () => {},
    onAttempt(event) {
      attempts.push(event.ok);
    },
  });
  assert.equal(result.attempt, 2);
  assert.deepEqual(attempts, [false, true]);
});

test("fails closed when canonical state never converges", async () => {
  const stale = {
    health: { ok: true, environment: "production", commit: "previous-sha" },
    version: { commit: "previous-sha", release: "prod-previous" },
  };
  await assert.rejects(
    verifyCanonicalProduction({
      origin: "https://example.test",
      sourceSha: "expected-sha",
      releaseId: "prod-expected",
      fetchImpl: fetchSequence([stale]),
      attempts: 2,
      delayMs: 0,
      sleepImpl: async () => {},
    }),
    /did not converge after 2 attempts/,
  );
});

test("retries transient HTTP failures within the same bounded window", async () => {
  let request = 0;
  const fetchImpl = async (url) => {
    request += 1;
    if (request <= 2) return jsonResponse({ error: "temporary" }, 503);
    if (url.endsWith("/api/health")) return jsonResponse(expected.health);
    return jsonResponse(expected.version);
  };
  const result = await verifyCanonicalProduction({
    origin: "https://example.test",
    sourceSha: "expected-sha",
    releaseId: "prod-expected",
    fetchImpl,
    attempts: 2,
    delayMs: 0,
    sleepImpl: async () => {},
  });
  assert.equal(result.attempt, 2);
});
