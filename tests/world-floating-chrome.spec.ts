import { expect, test, type Page } from "@playwright/test";

async function closeWorkspaceOverlays(page: Page) {
	const navigationClose = page.getByRole("button", { name: "Recolher navegação do mundo" });
	if (await navigationClose.isVisible().catch(() => false)) await navigationClose.click();
	const inspectorClose = page.getByRole("button", { name: "Recolher painel de detalhes" });
	if (await inspectorClose.isVisible().catch(() => false)) await inspectorClose.click();
}

test("World floating chrome owns the canvas controls without changing their contracts", async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto("/mundo");

	const chrome = page.getByTestId("world-floating-chrome");
	await expect(chrome).toBeVisible();
	await expect(chrome.getByRole("searchbox", { name: "Buscar no mundo" })).toBeVisible();
	await expect(chrome.getByRole("button", { name: "Filtrar por relação" })).toBeVisible();
	await expect(chrome.getByRole("button", { name: "Reorganizar" })).toBeVisible();
	await expect(chrome.getByRole("button", { name: "Canvas" })).toHaveAttribute("aria-pressed", "true");
	await expect(chrome.getByRole("button", { name: "Lista" })).toHaveAttribute("aria-pressed", "false");

	const paint = await chrome.evaluate((element) => {
		const primary = element.firstElementChild as HTMLElement | null;
		if (!primary) throw new Error("Floating chrome primary surface not found");
		const style = getComputedStyle(primary);
		return {
			background: style.backgroundColor,
			borderWidth: style.borderTopWidth,
			borderRadius: style.borderTopLeftRadius,
			backdropFilter: style.backdropFilter,
		};
	});
	expect(paint.background).not.toBe("rgba(0, 0, 0, 0)");
	expect(paint.borderWidth).not.toBe("0px");
	expect(paint.borderRadius).not.toBe("0px");
	expect(paint.backdropFilter).not.toBe("none");

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

	const canvas = page.getByTestId("world-canvas");
	const filters = page.getByRole("group", { name: "Filtrar o grafo" });
	const [chromeBox, canvasBox, filterBox] = await Promise.all([
		chrome.boundingBox(),
		canvas.boundingBox(),
		filters.boundingBox(),
	]);
	expect(chromeBox).not.toBeNull();
	expect(canvasBox).not.toBeNull();
	expect(filterBox).not.toBeNull();
	expect(chromeBox?.height ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(52);
	expect((canvasBox?.y ?? 0) - ((chromeBox?.y ?? 0) + (chromeBox?.height ?? 0))).toBeLessThanOrEqual(8);
	expect((filterBox?.y ?? 0) + (filterBox?.height ?? 0)).toBeGreaterThan(canvasBox?.y ?? 0);
	expect(filterBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan((canvasBox?.y ?? 0) + 80);

	const segmentedPaint = await filters.evaluate((element) => {
		const active = element.querySelector("button[aria-pressed='true']") as HTMLElement | null;
		if (!active) throw new Error("Active World filter not found");
		const railStyle = getComputedStyle(element);
		const activeStyle = getComputedStyle(active);
		return {
			railBackground: railStyle.backgroundColor,
			railBorderWidth: railStyle.borderTopWidth,
			chipBorderWidth: activeStyle.borderTopWidth,
		};
	});
	expect(segmentedPaint.railBackground).not.toBe("rgba(0, 0, 0, 0)");
	expect(segmentedPaint.railBorderWidth).not.toBe("0px");
	expect(segmentedPaint.chipBorderWidth).toBe("0px");

	await closeWorkspaceOverlays(page);
	await chrome.getByRole("button", { name: "Lista" }).click();
	await expect(page.getByTestId("world-canvas")).toHaveCount(0);
	await expect(page.getByRole("heading", { name: "Relações em lista" })).toBeVisible();

	await chrome.getByRole("button", { name: "Canvas" }).click();
	await expect(page.getByTestId("world-canvas")).toBeVisible();
});

test("World floating chrome remains touch-safe and contained on mobile", async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/mundo");

	const chrome = page.getByTestId("world-floating-chrome");
	await expect(chrome).toBeVisible();

	for (const control of [
		chrome.getByRole("button", { name: "Filtrar por relação" }),
		chrome.getByRole("button", { name: "Canvas" }),
		chrome.getByRole("button", { name: "Lista" }),
		chrome.getByRole("button", { name: "Todos" }),
	]) {
		const box = await control.boundingBox();
		expect(box).not.toBeNull();
		expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
	}

	expect(
		await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
	).toBeTruthy();
});

test("World floating chrome stays usable at the 320x800 minimum viewport", async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 800 });
	await page.goto("/mundo");

	const chrome = page.getByTestId("world-floating-chrome");
	await expect(chrome).toBeVisible();
	await expect(chrome.getByRole("searchbox", { name: "Buscar no mundo" })).toBeVisible();

	for (const control of [
		chrome.getByRole("button", { name: "Filtrar por relação" }),
		chrome.getByRole("button", { name: "Reorganizar" }),
		chrome.getByRole("button", { name: "Canvas" }),
		chrome.getByRole("button", { name: "Lista" }),
		chrome.getByRole("button", { name: "Todos" }),
	]) {
		await expect(control).toBeVisible();
		const box = await control.boundingBox();
		expect(box).not.toBeNull();
		expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
	}

	expect(
		await page.evaluate(() => ({
			documentWidth: document.documentElement.scrollWidth,
			viewportWidth: innerWidth,
		})),
	).toEqual({ documentWidth: 320, viewportWidth: 320 });

	await closeWorkspaceOverlays(page);
	await chrome.getByRole("button", { name: "Lista" }).click();
	await expect(page.getByRole("heading", { name: "Relações em lista" })).toBeVisible();
	await chrome.getByRole("button", { name: "Canvas" }).click();
	await expect(page.getByTestId("world-canvas")).toBeVisible();
});
