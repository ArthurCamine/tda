import { expect, test } from "@playwright/test";

test("normalized timing distinguishes recovery from fresh throughput", async ({ page }, testInfo) => {
	await page.goto("/?review-contracts&metrics");
	await page.getByText("Tempo comparável e reaproveitamento", { exact: true }).click();
	await expect(page.getByText(/1 faixas com ASR novo/)).toBeVisible();
	await expect(page.getByText(/não usar como throughput de ASR integral/)).toBeVisible();
	await expect(page.getByText("Preparação dos modelos", { exact: true })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath("engine-metrics.png"), fullPage: true });
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
	await page.goto("/?review-contracts&metrics&legacy");
	await expect(page.getByText("Tempo histórico sem medição comparável entre engines.")).toBeVisible();
});
