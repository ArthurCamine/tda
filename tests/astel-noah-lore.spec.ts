import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

// Exercise the actual candidate bytes before publication. This is not R2 evidence.
// Set TDA_VERIFY_PUBLIC_MEDIA=true after CD to test the real public delivery instead.
async function candidateMedia(page: Page) {
	if (process.env.TDA_VERIFY_PUBLIC_MEDIA === "true") return;
	for (const slug of ["astel", "noah"]) {
		const manifest = JSON.parse(
			readFileSync(`media/manifests/${slug}.json`, "utf8"),
		);
		for (const asset of manifest.assets) {
			const url = `${manifest.publicOrigin}/${manifest.namespace}/${asset.sha256}/${asset.file}`;
			await page.route(url, (route) =>
				route.fulfill({
					body: readFileSync(asset.source),
					contentType: asset.contentType,
				}),
			);
		}
	}
}

for (const [slug, count] of [
	["astel", 15],
	["noah", 7],
] as const) {
	test(`${slug}: catalog, direct route, chapters, gallery and return`, async ({
		page,
	}, testInfo) => {
		test.setTimeout(120000);
		await candidateMedia(page);
		const errors: string[] = [];
		page.on("pageerror", (error) => errors.push(error.message));
		await page.goto("/lore");
		await expect(page.locator('a[href="/lore/pipipi"]')).toBeVisible();
		await expect(
			page.locator(
				'a[href="/lore/d"],a[href="/lore/seika"],a[href="/lore/yllith"]',
			),
		).toHaveCount(0);
		await page.locator(`a[href="/lore/${slug}"]`).click();
		await expect(page).toHaveURL(new RegExp(`/lore/${slug}$`));
		await expect(page.locator("h1")).toHaveText(slug.toUpperCase());
		await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
			"href",
			`https://dnd.faysk.dev/lore/${slug}`,
		);
		await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
			"content",
			/https:\/\/media\.dnd\.faysk\.dev\/lore\//,
		);
		await page
			.locator(".hero-bg img")
			.evaluate((img: HTMLImageElement) => img.decode());
		await page
			.locator(".hero-current img")
			.evaluate((img: HTMLImageElement) => img.decode());
		await page.screenshot({ path: testInfo.outputPath(`${slug}-hero.png`) });
		if (await page.locator("#menuToggle").isVisible()) {
			await page.locator("#menuToggle").click();
			await expect(page.locator("#menuToggle")).toHaveAttribute(
				"aria-expanded",
				"true",
			);
		}
		await page.locator(".chapter-nav a").first().click();
		await expect(page).toHaveURL(/#(shadowfell|familia)$/);
		await page.emulateMedia({ reducedMotion: "reduce" });
		for (const image of await page.locator("main img").all()) {
			await image.scrollIntoViewIfNeeded();
			await expect
				.poll(() =>
					image.evaluate(
						(img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
					),
				)
				.toBe(true);
		}
		const oversized = await page.locator("main img").evaluateAll((images) =>
			images
				.filter((element) => {
					const img = element as HTMLImageElement;
					const style = getComputedStyle(img);
					if (style.objectFit === "scale-down") return false;
					const width =
						img.clientWidth -
						Number.parseFloat(style.paddingLeft) -
						Number.parseFloat(style.paddingRight);
					const height =
						img.clientHeight -
						Number.parseFloat(style.paddingTop) -
						Number.parseFloat(style.paddingBottom);
					const ratios = [width / img.naturalWidth, height / img.naturalHeight];
					return (
						(style.objectFit === "cover"
							? Math.max(...ratios)
							: Math.min(...ratios)) > 1.15
					);
				})
				.map((img) => (img as HTMLImageElement).src),
		);
		expect(oversized).toEqual([]);
		await expect(page.locator(".archive-item")).toHaveCount(count);
		for (const item of await page.locator(".archive-item").all()) {
			await item.click();
			await expect(page.locator("#lightbox")).toBeVisible();
			await page
				.locator("#lightboxImage")
				.evaluate((img: HTMLImageElement) => img.decode());
			await expect(page.locator("#lightboxImage")).toHaveAttribute(
				"src",
				(await item.getAttribute("data-full")) as string,
			);
			await page.keyboard.press("Escape");
			await expect(page.locator("#lightbox")).toBeHidden();
		}
		await page.getByText("Perguntas sem resposta", { exact: false }).click();
		await expect(page.locator(".dm-vault")).toHaveAttribute("open", "");
		await page
			.locator(".dm-vault")
			.screenshot({ path: testInfo.outputPath(`${slug}-questions.png`) });
		expect(
			await page.evaluate(
				() => document.documentElement.scrollWidth <= innerWidth + 1,
			),
		).toBe(true);
		if (slug === "astel") {
			await page.getByRole("link", { name: "Ler o Diário de Astel" }).click();
			await expect(
				page.getByRole("button", { name: "Abrir Diário de Astel" }),
			).toBeVisible();
			await page.getByRole("link", { name: "Astel — Antes da Voz" }).click();
		}
		await page.getByRole("link", { name: "Explorar outras lores" }).click();
		await expect(page).toHaveURL(/\/lore$/);
		for (const suffix of ["/", "/index.html"]) {
			const response = await page.goto(`/lore/${slug}${suffix}`);
			expect(response?.status()).toBe(200);
			expect(response?.headers()["x-robots-tag"]).toBeUndefined();
			await expect(page.locator("h1")).toHaveText(slug.toUpperCase());
		}
		expect(errors).toEqual([]);
	});

	test(`${slug}: text remains readable without JavaScript or images`, async ({
		browser,
	}) => {
		const context = await browser.newContext({
			javaScriptEnabled: false,
			viewport: { width: 390, height: 844 },
		});
		const page = await context.newPage();
		await page.route("https://media.dnd.faysk.dev/**", (route) =>
			route.abort(),
		);
		await page.goto(
			`${test.info().project.use.baseURL || "http://127.0.0.1:3101"}/lore/${slug}`,
		);
		await expect(page.locator(".story-panel").first()).toBeVisible();
		await expect(page.locator(".story-panel").first()).toHaveCSS(
			"opacity",
			"1",
		);
		await page.getByText("Perguntas sem resposta", { exact: false }).click();
		await expect(page.locator(".dm-vault")).toHaveAttribute("open", "");
		await context.close();
	});
}
