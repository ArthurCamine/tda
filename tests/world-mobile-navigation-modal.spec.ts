import { expect, test } from "@playwright/test";

test("mobile navigation is modal, touch-safe and restores focus when closed by its control", async ({
	page,
}, testInfo) => {
	test.skip(testInfo.project.name !== "mobile", "Mobile modal semantics contract.");

	await page.goto("/mundo");
	const trigger = page.getByRole("button", { name: "Explorar universo" });
	const stage = page.getByTestId("world-workspace-stage");

	await trigger.click();

	const navigation = page.getByRole("dialog", { name: "Navegação do mundo" });
	const close = page.getByRole("button", { name: "Fechar navegação do mundo" });
	await expect(navigation).toBeVisible();
	await expect(navigation).toHaveAttribute("aria-modal", "true");
	await expect(stage).toHaveAttribute("aria-hidden", "true");
	await expect(stage).toHaveAttribute("inert", "");
	await expect(close).toBeFocused();

	const closeBox = await close.boundingBox();
	expect(closeBox).not.toBeNull();
	expect(closeBox?.width).toBeGreaterThanOrEqual(44);
	expect(closeBox?.height).toBeGreaterThanOrEqual(44);

	await close.click();

	await expect(page.getByTestId("world-workspace-navigation")).not.toHaveAttribute("role", "dialog");
	await expect(stage).not.toHaveAttribute("aria-hidden", "true");
	await expect(stage).not.toHaveAttribute("inert", "");
	await expect(trigger).toBeVisible();
	await expect(trigger).toBeFocused();
});

test("mobile focus containment releases when viewport crosses to desktop", async ({
	page,
}, testInfo) => {
	test.skip(testInfo.project.name !== "mobile", "Responsive focus lifecycle contract.");

	await page.goto("/mundo");
	const trigger = page.getByRole("button", { name: "Explorar universo" });
	await trigger.click();

	const navigation = page.getByTestId("world-workspace-navigation");
	await expect(page.getByRole("dialog", { name: "Navegação do mundo" })).toBeVisible();
	await expect(page.getByRole("button", { name: "Fechar navegação do mundo" })).toBeFocused();

	await page.setViewportSize({ width: 1280, height: 800 });
	await expect(navigation).not.toHaveAttribute("role", "dialog");

	const stage = page.getByTestId("world-workspace-stage");
	await expect(stage).not.toHaveAttribute("inert", "");
	const stageButton = stage.locator("button").first();
	await stageButton.focus();
	await page.keyboard.press("Tab");

	await expect
		.poll(() =>
			navigation.evaluate((panel) =>
				Boolean(document.activeElement && panel.contains(document.activeElement)),
			),
		)
		.toBe(false);
});

test("desktop navigation remains non-modal", async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === "mobile", "Desktop navigation semantics contract.");

	await page.goto("/mundo");
	const navigation = page.getByTestId("world-workspace-navigation");
	const stage = page.getByTestId("world-workspace-stage");

	await expect(navigation).toBeVisible();
	await expect(navigation).not.toHaveAttribute("role", "dialog");
	await expect(navigation).not.toHaveAttribute("aria-modal", "true");
	await expect(stage).not.toHaveAttribute("aria-hidden", "true");
	await expect(stage).not.toHaveAttribute("inert", "");
});
