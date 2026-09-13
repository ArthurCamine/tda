const DEFAULT_ATTEMPTS = 18;
const DEFAULT_DELAY_MS = 5000;
const DEFAULT_REQUEST_TIMEOUT_MS = 10000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJson(fetchImpl, url, requestTimeoutMs) {
  const response = await fetchImpl(url, {
    headers: { accept: "application/json" },
    cache: "no-store",
    signal: AbortSignal.timeout(requestTimeoutMs),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} from ${url}`);
  }

  return response.json();
}

export async function verifyCanonicalProduction({
  origin,
  sourceSha,
  releaseId,
  fetchImpl = globalThis.fetch,
  attempts = DEFAULT_ATTEMPTS,
  delayMs = DEFAULT_DELAY_MS,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  sleepImpl = sleep,
  onAttempt = () => {},
}) {
  if (!origin || !sourceSha || !releaseId) {
    throw new Error("origin, sourceSha and releaseId are required");
  }
  if (typeof fetchImpl !== "function") {
    throw new Error("fetch implementation is required");
  }
  if (!Number.isInteger(attempts) || attempts < 1) {
    throw new Error("attempts must be a positive integer");
  }
  if (!Number.isInteger(requestTimeoutMs) || requestTimeoutMs < 1) {
    throw new Error("requestTimeoutMs must be a positive integer");
  }

  const base = origin.replace(/\/$/, "");
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const [health, version] = await Promise.all([
        readJson(fetchImpl, `${base}/api/health`, requestTimeoutMs),
        readJson(fetchImpl, `${base}/api/version`, requestTimeoutMs),
      ]);

      const mismatches = [];
      if (health.ok !== true) mismatches.push("health.ok is not true");
      if (health.environment !== "production") {
        mismatches.push(`health.environment=${health.environment ?? "<missing>"}`);
      }
      if (health.commit !== sourceSha) {
        mismatches.push(`health.commit=${health.commit ?? "<missing>"}`);
      }
      if (version.commit !== sourceSha) {
        mismatches.push(`version.commit=${version.commit ?? "<missing>"}`);
      }
      if (version.release !== releaseId) {
        mismatches.push(`version.release=${version.release ?? "<missing>"}`);
      }

      if (mismatches.length === 0) {
        onAttempt({ attempt, ok: true, health, version });
        return { attempt, health, version };
      }

      lastError = new Error(`canonical state has not converged: ${mismatches.join(", ")}`);
      onAttempt({ attempt, ok: false, error: lastError, health, version });
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      onAttempt({ attempt, ok: false, error: lastError });
    }

    if (attempt < attempts) {
      await sleepImpl(delayMs);
    }
  }

  throw new Error(
    `Canonical Production did not converge after ${attempts} attempts: ${lastError?.message ?? "unknown error"}`,
  );
}

async function main() {
  const origin = process.env.PRODUCTION_ORIGIN;
  const sourceSha = process.env.SOURCE_SHA;
  const releaseId = process.env.RELEASE_ID;
  const attempts = Number.parseInt(process.env.CANONICAL_VERIFY_ATTEMPTS ?? `${DEFAULT_ATTEMPTS}`, 10);
  const delayMs = Number.parseInt(process.env.CANONICAL_VERIFY_DELAY_MS ?? `${DEFAULT_DELAY_MS}`, 10);
  const requestTimeoutMs = Number.parseInt(
    process.env.CANONICAL_VERIFY_REQUEST_TIMEOUT_MS ?? `${DEFAULT_REQUEST_TIMEOUT_MS}`,
    10,
  );

  const result = await verifyCanonicalProduction({
    origin,
    sourceSha,
    releaseId,
    attempts,
    delayMs,
    requestTimeoutMs,
    onAttempt({ attempt, ok, error, health, version }) {
      if (ok) {
        console.log(
          `CANONICAL_PRODUCTION_OK attempt=${attempt} commit=${health.commit} release=${version.release}`,
        );
        return;
      }
      console.log(`Canonical verification attempt ${attempt}/${attempts} pending: ${error?.message}`);
    },
  });

  console.log(JSON.stringify({
    ok: true,
    attempt: result.attempt,
    commit: result.health.commit,
    release: result.version.release,
  }));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
