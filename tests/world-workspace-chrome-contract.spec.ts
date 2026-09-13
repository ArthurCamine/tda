import { expect, test, type Page } from "@playwright/test";

async function expectWorkspaceChromeAvailable(page: Page) {
	await expect(
		page.getByRole("heading", { level: 1, name: "Ecos da Jornada", exact: true }),
	).toBeVisible();
	await expect(page.getByRole("button", { name: "Canvas", exact: true })).toBeVisible();
	await expect(page.getByRole("button", { name: "Lista", exact: true })).toBeVisible();
	await expect(page.getByRole("searchbox", { name: "Buscar no mundo" })).toBeVisible();
	await expect(page.getByLabel("Filtrar por relação")).toBeVisible();
	await expect(page.getByRole("group", { name: "Filtrar o grafo" })).toBeVisible();
	await expect(page.getByRole("button", { name: "Reorganizar", exact: true })).toBeVisible();
}

async function closeWorkspaceOverlays(page: Page) {
	const navigationClose = page.getByRole("button", { name: "Recolher navegação do mundo" });
	if (await navigationClose.isVisible().catch(() => false)) await navigationClose.click();
	const inspectorClose = page.getByRole("button", { name: "Recolher painel de detalhes" });
	if (await inspectorClose.isVisible().catch(() => false)) await inspectorClose.click();
}

test("World Workspace keeps primary chrome available while navigation overlays a stable canvas", async ({
	page,
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto("/mundo");

	const canvas = page.getByTestId("world-canvas");
	await expect(canvas).toBeVisible();
	await expectWorkspaceChromeAvailable(page);

	const initialCanvas = await canvas.boundingBox();
	const initialTransform = await page.locator(".react-flow__viewport").getAttribute("style");
	await page.getByRole("button", { name: "Recolher navegação do mundo" }).click();
	await expect(page.getByRole("button", { name: "Explorar universo" })).toBeVisible();
	await expectWorkspaceChromeAvailable(page);

	const closedCanvas = await canvas.boundingBox();
	expect(initialCanvas).not.toBeNull();
	expect(closedCanvas).not.toBeNull();
	expect(Math.abs((closedCanvas?.width ?? 0) - (initialCanvas?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((closedCanvas?.x ?? 0) - (initialCanvas?.x ?? 0))).toBeLessThan(2);
	expect(await page.locator(".react-flow__viewport").getAttribute("style")).toBe(initialTransform);
});

test("World Workspace chrome preserves transient view/filter state without creating explicit focus", async ({
	page,
}) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await page.goto("/mundo");

	await expectWorkspaceChromeAvailable(page);
	await closeWorkspaceOverlays(page);
	await page.getByRole("button", { name: "Personagens", exact: true }).click();
	await expect(page.getByRole("button", { name: "Personagens", exact: true })).toHaveAttribute(
		"aria-pressed",
		"true",
	);
	await page.getByRole("button", { name: "Lista", exact: true }).click();
	await expect(page.getByRole("button", { name: "Lista", exact: true })).toHaveAttribute(
		"aria-pressed",
		"true",
	);

	expect(new URL(page.url()).searchParams.has("foco")).toBeFalsy();
});
