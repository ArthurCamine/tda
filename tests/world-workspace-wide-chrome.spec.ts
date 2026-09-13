import { expect, test, type Page } from "@playwright/test";

async function closeWorkspaceOverlays(page: Page) {
	const navigationClose = page.getByRole("button", { name: "Recolher navegação do mundo" });
	if (await navigationClose.isVisible().catch(() => false)) await navigationClose.click();
	const inspectorClose = page.getByRole("button", { name: "Recolher painel de detalhes" });
	if (await inspectorClose.isVisible().catch(() => false)) await inspectorClose.click();
}

test("wide World workspace uses one control row and floats filters over the canvas", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === "mobile", "Wide workspace contract.");
	await page.goto("/mundo");
	const viewport = page.viewportSize();
	if (!viewport || viewport.width < 1920) test.skip();

	const heading = page.getByRole("heading", { level: 1, name: "Ecos da Jornada" });
	await expect(heading).toHaveCount(1);

	const search = page.locator("[data-world-search]");
	const relation = page.locator("[data-world-relation-filter]");
	const reset = page.locator("[data-world-layout-action]");
	const viewToggle = page.locator("[data-world-view-toggle]");
	const rowBoxes = await Promise.all([
		search.boundingBox(),
		relation.boundingBox(),
		reset.boundingBox(),
		viewToggle.boundingBox(),
	]);
	for (const box of rowBoxes) expect(box).not.toBeNull();
	const rowY = rowBoxes[0]?.y ?? 0;
	for (const box of rowBoxes.slice(1)) {
		expect(Math.abs((box?.y ?? rowY) - rowY)).toBeLessThan(3);
	}

	const conductor = page.getByTestId("world-conductor");
	if (await conductor.count()) {
		const conductorBox = await conductor.boundingBox();
		expect(conductorBox).not.toBeNull();
		expect(Math.abs((conductorBox?.y ?? rowY) - rowY)).toBeLessThan(3);
	}

	const canvas = page.getByTestId("world-canvas");
	const filters = page.getByRole("group", { name: "Filtrar o grafo" });
	const canvasBox = await canvas.boundingBox();
	const filterBox = await filters.boundingBox();
	expect(canvasBox).not.toBeNull();
	expect(filterBox).not.toBeNull();
	expect((filterBox?.y ?? 0) + (filterBox?.height ?? 0)).toBeGreaterThan(canvasBox?.y ?? 0);
	expect(filterBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan((canvasBox?.y ?? 0) + 100);

	await closeWorkspaceOverlays(page);
	const all = page.getByRole("button", { name: "Todos", exact: true });
	const characters = page.getByRole("button", { name: "Personagens", exact: true });
	await expect(all).toHaveAttribute("aria-pressed", "true");
	await characters.click();
	await expect(characters).toHaveAttribute("aria-pressed", "true");
	await expect(all).toHaveAttribute("aria-pressed", "false");

	expect(await page.evaluate(() => window.scrollY)).toBe(0);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
