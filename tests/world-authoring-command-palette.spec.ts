import { expect, test, type Page } from "@playwright/test";

const FIXTURE_PATH = "/e2e-fixtures/world-command-palette";

async function openPalette(page: Page) {
	const trigger = page.getByRole("button", { name: /Comandos do Mundo/i });
	await trigger.focus();
	await trigger.click();
	const dialog = page.getByRole("dialog", { name: "Comandos do Mundo" });
	const combobox = page.getByRole("combobox", { name: "Buscar comandos ou elementos" });
	await expect(dialog).toBeVisible();
	await expect(combobox).toBeFocused();
	return { trigger, dialog, combobox };
}

test("command palette stays out of the public World", async ({ page }) => {
	await page.goto("/mundo");

	await expect(page.getByTestId("world-canvas")).toBeVisible();
	await expect(page.getByRole("button", { name: /Comandos do Mundo/i })).toHaveCount(0);
	await page.keyboard.press("Control+K");
	await expect(page.getByRole("dialog", { name: "Comandos do Mundo" })).toHaveCount(0);
	await expect(page.locator("[data-world-command-palette-dialog]")).toHaveCount(0);
});

test("command palette keeps one virtual-focus combobox model", async ({ page }) => {
	await page.goto(FIXTURE_PATH);
	const { trigger, dialog, combobox } = await openPalette(page);

	await expect(combobox).toHaveAttribute("aria-expanded", "true");
	await expect(combobox).toHaveAttribute("aria-haspopup", "listbox");
	await expect(combobox).toHaveAttribute("aria-autocomplete", "list");
	await expect(combobox).toHaveAttribute("aria-controls", "world-command-palette-results");

	const options = page.getByRole("option");
	expect(await options.count()).toBeGreaterThan(2);
	for (let index = 0; index < (await options.count()); index += 1) {
		expect(await options.nth(index).evaluate((element) => (element as HTMLElement).tabIndex)).toBe(-1);
	}

	const firstActive = await combobox.getAttribute("aria-activedescendant");
	await combobox.press("ArrowDown");
	await expect(combobox).toBeFocused();
	const secondActive = await combobox.getAttribute("aria-activedescendant");
	expect(secondActive).not.toBe(firstActive);
	await combobox.press("ArrowUp");
	await expect(combobox).toHaveAttribute("aria-activedescendant", firstActive ?? "");

	await combobox.press("ArrowDown");
	await combobox.press("Enter");
	await expect(dialog).toHaveCount(0);
	await expect(page.getByTestId("world-command-palette-action")).toHaveText("command:world.fit");
	await expect(trigger).toBeFocused();

	await trigger.click();
	await expect(combobox).toBeFocused();
	await combobox.fill("Elemento Fixture");
	await expect(page.getByRole("option")).toHaveCount(1);
	await combobox.press("Enter");
	await expect(page.getByTestId("world-command-palette-action")).toHaveText("entity:fixture-entity");
	await expect(trigger).toBeFocused();

	await trigger.focus();
	await page.keyboard.press("Control+K");
	await expect(dialog).toBeVisible();
	await expect(combobox).toBeFocused();
	await page.keyboard.press("Escape");
	await expect(dialog).toHaveCount(0);
	await expect(trigger).toBeFocused();
});

test("command palette excludes virtual options from Tab order", async ({ page }) => {
	await page.goto(FIXTURE_PATH);
	const { combobox } = await openPalette(page);
	const closeButton = page.locator(
		'button[aria-label="Fechar comandos do Mundo"]:not([tabindex="-1"])',
	);

	await combobox.press("Tab");
	await expect(closeButton).toBeFocused();
	await closeButton.press("Tab");
	await expect(combobox).toBeFocused();
});

test("command palette remains usable at the frozen authoring viewports", async ({ page }) => {
	for (const viewport of [
		{ width: 1366, height: 768 },
		{ width: 390, height: 844 },
		{ width: 320, height: 800 },
	]) {
		await page.setViewportSize(viewport);
		await page.goto(FIXTURE_PATH);
		const { dialog, combobox } = await openPalette(page);
		await expect(dialog).toBeInViewport();
		await expect(combobox).toBeVisible();
		await expect(
			page.locator('button[aria-label="Fechar comandos do Mundo"]:not([tabindex="-1"])'),
		).toBeVisible();
		await page.keyboard.press("Escape");
		await expect(dialog).toHaveCount(0);
	}
});
