import { expect, test } from "@playwright/test";

test("desktop navigation overlays without resizing the workspace", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === "mobile", "Desktop overlay contract.");
	await page.goto("/mundo");

	const workspace = page.getByTestId("world-workspace");
	const stage = page.getByTestId("world-workspace-stage");
	const canvas = page.getByTestId("world-canvas");
	const navigation = page.getByTestId("world-workspace-navigation");
	await expect(workspace).toHaveAttribute("data-world-navigation", "open");
	await expect(navigation).toBeVisible();

	const stageBefore = await stage.boundingBox();
	const canvasBefore = await canvas.boundingBox();
	const transformBefore = await page.locator(".react-flow__viewport").getAttribute("style");
	const collapse = page.getByRole("button", { name: "Recolher navegação do mundo" }).first();
	const tabBefore = await collapse.boundingBox();
	expect(tabBefore?.width ?? 0).toBeGreaterThanOrEqual(38);
	expect(tabBefore?.height ?? 0).toBeGreaterThanOrEqual(54);

	await collapse.click();
	await expect(workspace).toHaveAttribute("data-world-navigation", "closed");
	await expect(navigation).toBeHidden();
	const stageAfter = await stage.boundingBox();
	const canvasAfter = await canvas.boundingBox();
	expect(Math.abs((stageAfter?.width ?? 0) - (stageBefore?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((canvasAfter?.width ?? 0) - (canvasBefore?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((canvasAfter?.x ?? 0) - (canvasBefore?.x ?? 0))).toBeLessThan(2);
	expect(await page.locator(".react-flow__viewport").getAttribute("style")).toBe(transformBefore);

	const reopen = page.getByRole("button", { name: "Explorar universo" });
	const tabAfter = await reopen.boundingBox();
	expect(tabAfter?.width ?? 0).toBeGreaterThanOrEqual(38);
	expect(tabAfter?.height ?? 0).toBeGreaterThanOrEqual(54);
});

test("desktop inspector overlays without resizing the canvas", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === "mobile", "Desktop overlay contract.");
	await page.goto("/mundo");

	const canvas = page.getByTestId("world-canvas");
	const inspector = page.locator('aside[aria-live="polite"]');
	const before = await canvas.boundingBox();
	const transformBefore = await page.locator(".react-flow__viewport").getAttribute("style");
	await page.getByRole("button", { name: "Recolher painel de detalhes" }).click();
	const reopen = page.getByRole("button", { name: "Abrir painel de detalhes" });
	await expect(reopen).toBeVisible();
	await expect.poll(async () => (await inspector.boundingBox())?.width ?? -1).toBeLessThan(2);

	const after = await canvas.boundingBox();
	expect(Math.abs((after?.width ?? 0) - (before?.width ?? 0))).toBeLessThan(2);
	expect(Math.abs((after?.x ?? 0) - (before?.x ?? 0))).toBeLessThan(2);
	expect(await page.locator(".react-flow__viewport").getAttribute("style")).toBe(transformBefore);
	const tab = await reopen.boundingBox();
	expect(tab?.width ?? 0).toBeGreaterThanOrEqual(38);
	expect(tab?.height ?? 0).toBeGreaterThanOrEqual(54);
	expect(Math.abs((tab?.x ?? 0) + (tab?.width ?? 0) - (await page.evaluate(() => innerWidth)))).toBeLessThan(3);
});

test("mobile inspector still collapses to a bottom-sheet reopen control", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name !== "mobile", "Mobile inspector contract.");
	await page.goto("/mundo");
	const inspector = page.locator('aside[aria-live="polite"]');
	await page.getByRole("button", { name: "Recolher painel de detalhes" }).click();
	const reopen = page.getByRole("button", { name: "Abrir painel de detalhes" });
	await expect(reopen).toBeVisible();
	await expect.poll(async () => (await inspector.boundingBox())?.height ?? -1).toBeLessThan(2);
	const box = await reopen.boundingBox();
	expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
	expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test("mobile navigation remains a non-reserving modal overlay", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name !== "mobile", "Mobile navigation contract.");
	await page.goto("/mundo");
	const workspace = page.getByTestId("world-workspace");
	const stage = page.getByTestId("world-workspace-stage");
	const before = await stage.boundingBox();
	await page.getByRole("button", { name: "Explorar universo" }).click();
	await expect(workspace).toHaveAttribute("data-world-navigation", "open");
	const open = await stage.boundingBox();
	expect(Math.abs((open?.width ?? 0) - (before?.width ?? 0))).toBeLessThan(2);
	await page.getByRole("button", { name: "Fechar navegação do mundo" }).click();
	await expect(workspace).toHaveAttribute("data-world-navigation", "closed");
});
