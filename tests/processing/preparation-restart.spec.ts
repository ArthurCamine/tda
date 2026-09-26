import { expect, test } from "@playwright/test";
import { installCompanionFixture, LOCAL_API } from "./companion-fixture";

test("interrupted preparation resumes without another Craig upload", async ({ page }, testInfo) => {
	await installCompanionFixture(page, { profileReady: false });
	let resumed = false;
	await page.route(`${LOCAL_API}/preparation`, async route => {
		if (route.request().method() === "OPTIONS") return route.fallback();
		if (route.request().method() === "POST") {
			expect(route.request().postDataJSON()).toEqual({ source_id: `craig-${"b".repeat(64)}`, profile_id: "qwen-quality" });
			resumed = true;
		}
		await route.fulfill({ json: {
			schema: "tda_profile_preparation_v1", state: resumed ? "running" : "interrupted", active: resumed,
			operation_id: (resumed ? "b" : "a").repeat(32), source_id: `craig-${"b".repeat(64)}`,
			profile_id: "qwen-quality", engine: "qwen3", stage: "runtime", title: "Preparando runtime",
			detail: "Verificando arquivos locais", sequence: resumed ? 1 : 4, elapsed_seconds: 0,
			error_code: resumed ? null : "TRANSCRIPTION_PREPARATION_INTERRUPTED",
		}, headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:3102" } });
	});
	await page.goto("/");
	await expect(page.getByText("Preparação interrompida pelo reinício do Companion.")).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath("preparation-interrupted.png"), fullPage: true });
	await page.getByRole("button", { name: "Retomar preparação" }).click();
	await expect(page.getByText("Retomando preparação após reinício. Os arquivos locais serão verificados novamente.")).toBeVisible();
	expect(resumed).toBe(true);
	await expect(page.getByRole("button", { name: "Retomar preparação" })).toHaveCount(0);
});
