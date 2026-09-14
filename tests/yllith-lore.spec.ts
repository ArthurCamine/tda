import { expect, test } from "@playwright/test";

const SOCIAL =
	"https://media.dnd.faysk.dev/lore/yllith/b9858046c31ddc338fafe822b8c6132d4b4a4383c5f11b7b6e536943f8509f48/social-yllith.jpg";

test("Yllith is a direct-only standalone lore with cinematic and reading modes", async ({ page, request }) => {
	test.setTimeout(120000);
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));

	const response = await request.get("/lore/yllith");
	expect(response.ok()).toBeTruthy();
	expect(response.headers()["x-robots-tag"]).toContain("noindex");

	await page.goto("/lore/yllith");
	await expect(page.locator("h1").first()).toContainText("conquistar");
	await expect(page.locator('link[rel~="icon"]')).toHaveAttribute("href", "favicon.svg");
	await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
		"content",
		"noindex,nofollow,noarchive,noimageindex",
	);
	await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
		"href",
		"https://dnd.faysk.dev/lore/yllith",
	);
	await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", SOCIAL);

	const hero = page.locator(".hero-character");
	await expect(hero).toBeVisible();
	await expect.poll(() => hero.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(1000);

	const toggle = page.locator("#loreModeToggle");
	await expect(toggle).toHaveAttribute("aria-checked", "false");
	await toggle.click();
	await expect(toggle).toHaveAttribute("aria-checked", "true");
	await expect(page.locator("#reading-view")).toBeVisible();
	await expect(page.locator("[data-reading-chapter]")).toHaveCount(10);
	await expect(page.locator("#read-sequoia-vermelha-fica-para-tras")).toContainText("Sequoia Vermelha");
	await expect(page.locator("#read-yllith")).toContainText("Yllith");
	expect(new URL(page.url()).pathname).toBe("/lore/yllith");

	await toggle.click();
	await expect(toggle).toHaveAttribute("aria-checked", "false");
	expect(errors).toEqual([]);
});

test("Yllith remains absent from the curated lore catalog", async ({ page }) => {
	await page.goto("/lore");
	await expect(page.locator('a[href="/lore/yllith"]')).toHaveCount(0);
	await expect(page.getByText("Yllith", { exact: true })).toHaveCount(0);
});

test("Yllith exposes the approved full reading source and favicon", async ({ request }) => {
	const story = await request.get("/lore/yllith/historia.md");
	expect(story.ok()).toBeTruthy();
	expect(story.headers()["content-type"]).toContain("text/markdown");
	const text = await story.text();
	expect(text).toContain("# Nascida para conquistar");
	expect(text).toContain("Sequoia Vermelha fica para trás");
	expect(text).toContain("Uma matilha não nasce quando alguém manda");

	const favicon = await request.get("/lore/yllith/favicon.svg");
	expect(favicon.ok()).toBeTruthy();
	expect(await favicon.text()).toContain('aria-label="Yllith"');
});
