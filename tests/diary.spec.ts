import { readFileSync, readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("diary archive opens the standalone book and remembers reading", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto("/diario");
	await expect(
		page.getByRole("heading", { name: "Diários", exact: true }),
	).toBeVisible();
	await page
		.getByRole("link", { name: /Astel Nightshade.*Diário de Astel/ })
		.click();
	await expect(page).toHaveURL(/\/diario\/astel$/);
	await expect(page.locator(".site-header")).toHaveCount(0);
	await page.getByRole("button", { name: "Abrir Diário de Astel" }).click();
	await expect(page.locator("#left-page")).toContainText("Coisas Pequenas");
	await page.getByRole("button", { name: "Próxima", exact: true }).click();
	const position = await page.locator("#page-status").innerText();
	const paragraph = await page
		.locator("#left-page .page-body p")
		.first()
		.innerText();
	await page.reload();
	await page.getByRole("button", { name: "Continuar de onde parei" }).click();
	await expect(page.locator("#page-status")).toHaveText(position);
	await expect(page.locator("#left-page .page-body p").first()).toHaveText(
		paragraph,
	);
	await page.getByRole("button", { name: "Aumentar tamanho do texto" }).click();
	await expect(page.locator("#left-page .page-body")).toHaveCSS(
		"font-size",
		"20px",
	);
	await page.getByRole("button", { name: "Sumário" }).click();
	await expect(page.locator("#chapter-list li")).toHaveCount(11);
	await page.getByRole("button", { name: /XI Uma Resposta/ }).click();
	await expect(page.locator("#book")).toContainText("Uma Resposta");
	await expect(page.locator("#reader-error")).toBeHidden();
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
	expect(errors).toEqual([]);
	await page.emulateMedia({ reducedMotion: "reduce" });
	await page.getByRole("button", { name: "Voltar à capa" }).click();
	await page.getByRole("button", { name: "Abrir Diário de Astel" }).click();
	await page.keyboard.press("ArrowRight");
	await expect(page.locator("#turning-page")).toBeHidden();
	await expect(page.locator("#previous")).toBeEnabled();
	await page.setViewportSize({ width: 320, height: 740 });
	await page.getByRole("button", { name: "Voltar à capa" }).click();
	expect(
		await page.evaluate(
			() =>
				document.documentElement.scrollWidth <=
				document.documentElement.clientWidth,
		),
	).toBe(true);
	await page.getByRole("button", { name: "Abrir Diário de Astel" }).click();
	expect(
		await page.evaluate(
			() =>
				document.documentElement.scrollWidth <=
				document.documentElement.clientWidth,
		),
	).toBe(true);
});

test("direct URLs, chapter sources, and metadata stay separate from lore", async ({
	page,
	request,
}) => {
	for (const path of [
		"/diario/astel",
		"/diario/astel/",
		"/diario/astel/index.html",
	]) {
		await page.goto(path);
		await expect(
			page.getByRole("button", { name: "Abrir Diário de Astel" }),
		).toBeVisible();
		await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
			"href",
			"https://dnd.faysk.dev/diario/astel",
		);
		await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
			"content",
			"Diário de Astel",
		);
		await page.getByRole("button", { name: "Abrir Diário de Astel" }).click();
		await expect(page.locator("#page-status")).toContainText(/de \d+/);
	}
	for (const path of [
		"/diario/nao-existe",
		"/diario/astel/planejamento.md",
		"/diario/astel/continuidade.md",
	]) {
		expect((await request.get(path)).status()).toBe(404);
	}
	await page.goto("/lore");
	await expect(page.locator('a[href="/diario/astel"]')).toHaveCount(0);
});

test("continuous reading works without JavaScript and retains all paragraphs", async ({
	browser,
	baseURL,
	viewport,
}) => {
	const context = await browser.newContext({
		javaScriptEnabled: false,
		baseURL,
		viewport,
	});
	const page = await context.newPage();
	await page.goto("/diario/astel");
	await page.getByRole("link", { name: "versão de leitura contínua" }).click();
	await expect(
		page.getByRole("heading", { name: "Diário de Astel", exact: true }),
	).toBeVisible();
	await expect(page.locator("main section")).toHaveCount(11);
	await page.locator('#sumario a[href="#11_uma_resposta"]').click();
	await expect(page).toHaveURL(/#11_uma_resposta$/);
	await expect(page.locator('[id="11_uma_resposta"] h2')).toHaveText(
		"Uma Resposta",
	);
	const originals = readdirSync("content/diaries/astel").sort();
	for (const [index, file] of originals.entries()) {
		const original = readFileSync(`content/diaries/astel/${file}`, "utf8")
			.replace(/^\uFEFF/, "")
			.replace(/\r\n/g, "\n")
			.trim()
			.split("\n")
			.slice(1)
			.join("\n")
			.trim();
		const paragraphs = original
			.split(/\n\s*\n/)
			.map((p) => p.trim())
			.filter((p) => p !== "***");
		expect(
			await page
				.locator("main section")
				.nth(index)
				.locator("p:not(.chapter-number)")
				.allTextContents(),
		).toEqual(paragraphs);
	}
	await context.close();
});
