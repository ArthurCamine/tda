import { expect, test } from "@playwright/test";

test("World Explorer exposes the graph immediately while desktop chrome overlays a stable canvas", async ({
	page,
}) => {
	await page.setViewportSize({ width: 1366, height: 768 });
	await page.goto("/mundo");

	await expect(
		page.getByRole("heading", { level: 1, name: "Ecos da Jornada", exact: true }),
	).toBeVisible();
	const canvas = page.getByTestId("world-canvas");
	await expect(canvas).toBeVisible();

	const initialCanvas = await canvas.boundingBox();
	expect(initialCanvas).not.toBeNull();
	expect(initialCanvas?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(310);
	expect(initialCanvas?.height ?? 0).toBeGreaterThanOrEqual(430);
	const initialTransform = await page.locator(".react-flow__viewport").getAttribute("style");

	const workspace = page.getByTestId("world-workspace");
	const navigation = page.getByTestId("world-workspace-navigation");
	await expect(workspace).toHaveAttribute("data-world-navigation", "open");
	await page.getByRole("button", { name: "Recolher navegação do mundo" }).first().click();
	await expect(workspace).toHaveAttribute("data-world-navigation", "closed");
	await expect(navigation).toBeHidden();
	await expect(page.getByRole("button", { name: "Explorar universo" })).toBeVisible();

	const afterNavigation = await canvas.boundingBox();
	expect(afterNavigation).not.toBeNull();
	expect(Math.abs((afterNavigation?.width ?? 0) - (initialCanvas?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((afterNavigation?.x ?? 0) - (initialCanvas?.x ?? 0))).toBeLessThan(2);
	expect(await page.locator(".react-flow__viewport").getAttribute("style")).toBe(initialTransform);

	const beforeInspectorCollapse = await canvas.boundingBox();
	const detailCollapse = page.getByRole("button", {
		name: "Recolher painel de detalhes",
	});
	await expect(detailCollapse).toBeVisible();
	await detailCollapse.click();
	const detailOpen = page.getByRole("button", { name: "Abrir painel de detalhes" });
	await expect(detailOpen).toBeVisible();
	const afterInspectorCollapse = await canvas.boundingBox();
	expect(afterInspectorCollapse).not.toBeNull();
	expect(Math.abs((afterInspectorCollapse?.width ?? 0) - (beforeInspectorCollapse?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((afterInspectorCollapse?.x ?? 0) - (beforeInspectorCollapse?.x ?? 0))).toBeLessThan(2);
	expect(await page.locator(".react-flow__viewport").getAttribute("style")).toBe(initialTransform);

	expect(
		await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
	).toBeTruthy();
});

test("World Explorer keeps mobile navigation, controls and inspector sheet touch-safe", async ({
	page,
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto("/mundo");

	const workspace = page.getByTestId("world-workspace");
	await expect(workspace).toHaveAttribute("data-world-navigation", "closed");
	const exploreUniverse = page.getByRole("button", { name: "Explorar universo" });
	await expect(exploreUniverse).toBeVisible();
	const navigationTriggerBox = await exploreUniverse.boundingBox();
	expect(navigationTriggerBox?.height ?? 0).toBeGreaterThanOrEqual(44);

	const canvas = page.getByTestId("world-canvas");
	await expect(canvas).toBeVisible();
	const mobileCanvas = await canvas.boundingBox();
	expect(mobileCanvas?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(350);
	expect(mobileCanvas?.height ?? 0).toBeGreaterThanOrEqual(430);

	const reset = page.getByTestId("world-layout-reset");
	await expect(reset).toBeVisible();
	await expect(reset).toHaveAccessibleName(/Reorganizar|Restaurar posições/u);
	const resetBox = await reset.boundingBox();
	expect(resetBox?.width ?? 0).toBeGreaterThanOrEqual(44);
	expect(resetBox?.width ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(46);
	expect(resetBox?.height ?? 0).toBeGreaterThanOrEqual(44);

	const detailToggle = page.getByRole("button", { name: "Recolher painel de detalhes" });
	await expect(detailToggle).toBeVisible();
	const detailToggleBox = await detailToggle.boundingBox();
	expect(detailToggleBox?.width ?? 0).toBeGreaterThanOrEqual(44);
	expect(detailToggleBox?.height ?? 0).toBeGreaterThanOrEqual(44);

	const flowControl = page.locator(".react-flow__controls-button").first();
	await expect(flowControl).toBeVisible();
	const flowControlBox = await flowControl.boundingBox();
	expect(flowControlBox?.width ?? 0).toBeGreaterThanOrEqual(44);
	expect(flowControlBox?.height ?? 0).toBeGreaterThanOrEqual(44);
	await expect(page.locator(".react-flow__minimap")).toBeHidden();

	await detailToggle.click();
	const detailOpen = page.getByRole("button", { name: "Abrir painel de detalhes" });
	await expect(detailOpen).toBeVisible();
	await expect
		.poll(
			async () =>
				await detailOpen.evaluate(
					(button) =>
						button.parentElement?.getBoundingClientRect().height ??
						Number.POSITIVE_INFINITY,
				),
		)
		.toBeLessThanOrEqual(1);
	const reopenBox = await detailOpen.boundingBox();
	expect(reopenBox?.width ?? 0).toBeGreaterThanOrEqual(44);
	expect(reopenBox?.height ?? 0).toBeGreaterThanOrEqual(44);

	expect(
		await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
	).toBeTruthy();
});
