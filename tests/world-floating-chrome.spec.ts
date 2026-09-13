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
