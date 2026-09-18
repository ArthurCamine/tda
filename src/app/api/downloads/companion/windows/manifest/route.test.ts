import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

function release(tag: string, prerelease: boolean) {
  return {
    tag_name: tag,
    draft: false,
    prerelease,
    assets: [
      {
        name: "TDACompanion-x64.msi",
        browser_download_url:
          `https://github.com/Faysk/tda/releases/download/${tag}/TDACompanion-x64.msi`,
        digest: `sha256:${"a".repeat(64)}`,
        size: 83_000_000,
      },
    ],
  };
}

function catalog() {
  return [
    release("companion-rc-v0.3.10-0123456789ab", true),
    release("companion-v0.3.9", false),
  ];
}

function mockGithubReleases() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(catalog()), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Companion Windows manifest route", () => {
  it("defaults to Stable and never leaks a newer RC", async () => {
    mockGithubReleases();

    const response = await GET(
      new Request("https://dnd.faysk.dev/api/downloads/companion/windows/manifest"),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      channel: "stable",
      version: "0.3.9",
      tag: "companion-v0.3.9",
      minimum_api: "1",
      asset: {
        url: "/api/downloads/companion/windows?tag=companion-v0.3.9",
        sha256: "a".repeat(64),
        size: 83_000_000,
      },
    });
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0");
  });

  it("returns an immutable RC only after explicit channel=rc opt-in", async () => {
    mockGithubReleases();

    const response = await GET(
      new Request(
        "https://dnd.faysk.dev/api/downloads/companion/windows/manifest?channel=rc",
      ),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      channel: "rc",
      version: "0.3.10",
      tag: "companion-rc-v0.3.10-0123456789ab",
      asset: {
        url:
          "/api/downloads/companion/windows?tag=companion-rc-v0.3.10-0123456789ab",
      },
    });
  });

  it.each([
    "?channel=nightly",
    "?channel=rc&channel=stable",
    "?channel=rc&unexpected=1",
    "?unexpected=1",
  ])("rejects ambiguous or unsupported query %s before GitHub lookup", async (query) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request(
        `https://dnd.faysk.dev/api/downloads/companion/windows/manifest${query}`,
      ),
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "COMPANION_RELEASE_REQUEST_INVALID",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
