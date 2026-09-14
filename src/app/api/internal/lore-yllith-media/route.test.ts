import { afterEach, describe, expect, it } from "vitest";
import { GET } from "./route";

const ENV_KEYS = [
  "APP_ENV",
  "TDA_LORE_STAGING_TOKEN",
  "R2_PUBLIC_BUCKET",
  "R2_ACCOUNT_ID",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
] as const;

const originalEnv = Object.fromEntries(
  ENV_KEYS.map((key) => [key, process.env[key]]),
) as Record<(typeof ENV_KEYS)[number], string | undefined>;

function clearR2() {
  delete process.env.R2_PUBLIC_BUCKET;
  delete process.env.R2_ACCOUNT_ID;
  delete process.env.R2_ACCESS_KEY_ID;
  delete process.env.R2_SECRET_ACCESS_KEY;
}

afterEach(() => {
  for (const key of ENV_KEYS) {
    const value = originalEnv[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe("Yllith production bootstrap authorization", () => {
  it("keeps the read-only manifest available without a token", async () => {
    process.env.APP_ENV = "production";
    delete process.env.TDA_LORE_STAGING_TOKEN;
    clearR2();

    const response = await GET(
      new Request("https://dnd.faysk.dev/api/internal/lore-yllith-media"),
    );

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.protocol).toBe("yllith-r2-bootstrap-v2");
    expect(body.configured).toBe(false);
  });

  it("hides verify when the Production secret is absent", async () => {
    process.env.APP_ENV = "production";
    delete process.env.TDA_LORE_STAGING_TOKEN;
    clearR2();

    const response = await GET(
      new Request(
        "https://dnd.faysk.dev/api/internal/lore-yllith-media?verify=yllith.webp",
      ),
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "production bootstrap only" });
  });

  it("rejects an incorrect bearer token before R2 access", async () => {
    process.env.APP_ENV = "production";
    process.env.TDA_LORE_STAGING_TOKEN = "expected-release-token";
    clearR2();

    const response = await GET(
      new Request(
        "https://dnd.faysk.dev/api/internal/lore-yllith-media?finalize=yllith.webp",
        { headers: { authorization: "Bearer wrong-release-token" } },
      ),
    );

    expect(response.status).toBe(404);
  });

  it("accepts the exact token then fails closed when R2 is unavailable", async () => {
    process.env.APP_ENV = "production";
    process.env.TDA_LORE_STAGING_TOKEN = "expected-release-token";
    clearR2();

    const response = await GET(
      new Request(
        "https://dnd.faysk.dev/api/internal/lore-yllith-media?verify=yllith.webp",
        { headers: { authorization: "Bearer expected-release-token" } },
      ),
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "R2 configuration unavailable" });
  });

  it("never enables bootstrap outside Production", async () => {
    process.env.APP_ENV = "preview";
    process.env.TDA_LORE_STAGING_TOKEN = "expected-release-token";
    clearR2();

    const response = await GET(
      new Request(
        "https://preview.example/api/internal/lore-yllith-media?verify=yllith.webp",
        { headers: { authorization: "Bearer expected-release-token" } },
      ),
    );

    expect(response.status).toBe(404);
  });
});
