import { expect, test, type Page } from "@playwright/test";

async function closeWorkspaceOverlays(page: Page) {
	const navigationClose = page.getByRole("button", { name: "Recolher navegação do mundo" });
	if (await navigationClose.isVisible().catch(() => false)) await navigationClose.click();
	const inspectorClose = page.getByRole("button", { name: "Recolher painel de detalhes" });
	if (await inspectorClose.isVisible().catch(() => false)) await inspectorClose.click();
}

test("World Explorer opens as a multi-hub overview and keeps selection separate from focus", async ({ page }) => {
	await page.goto("/mundo");
	await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ecos da Jornada");
	await expect(page.getByText("Demo · não canônico")).toBeVisible();
	await expect(page.getByRole("heading", { level: 2, name: "Visão geral", exact: true })).toBeVisible();

	const allRelationLabels = page.locator("[data-world-edge-label]");
	await expect.poll(async () => allRelationLabels.count()).toBeGreaterThan(1);
	const labelCountBeforeSelection = await allRelationLabels.count();

	await page.locator('[data-world-node="astel"]').click();
	await expect(page.getByRole("heading", { level: 2, name: "Astel", exact: true })).toBeVisible();
	await expect(
		page.locator('[data-world-node="astel"] [data-node-state]'),
	).toHaveText("Selecionado");
	await expect(page).toHaveURL(/\/mundo$/);

	await expect.poll(async () => allRelationLabels.count()).toBeLessThan(labelCountBeforeSelection);
	const labelCountAfterSelection = await allRelationLabels.count();
	expect(labelCountAfterSelection).toBeGreaterThan(0);

	await page.getByRole("link", { name: "Explorar conexões de Astel" }).click();
	await expect(page).toHaveURL(/\/mundo\?foco=astel$/);
	await expect(page.getByText("Foco exploratório atual.")).toBeVisible();
	await expect(
		page.locator('[data-world-node="astel"] [data-node-state]'),
	).toHaveText("Foco · selecionado");
	await expect(page.locator('[data-world-node="raven-queen"]')).toBeVisible();
});

test("World Explorer paints relation strokes in the same visible layer as edge labels", async ({ page }) => {
	await page.goto("/mundo");
	await expect(page.locator('[data-world-node="dandelion"]')).toBeVisible();

	const labelLayer = page.locator(".react-flow__edgelabel-renderer");
	await expect(labelLayer).toBeVisible();
	const edges = labelLayer.locator("[data-world-edge]");
	await expect(edges.first()).toBeVisible();
	expect(await edges.count()).toBeGreaterThan(0);

	const paint = await edges.first().evaluate((element) => {
		const style = getComputedStyle(element);
		const path = element as SVGPathElement;
		const svg = element.closest("svg");
		if (!svg) throw new Error("Independent world edge SVG not found");
		const svgStyle = getComputedStyle(svg);
		const rect = svg.getBoundingClientRect();
		return {
			stroke: style.stroke,
			strokeWidth: Number.parseFloat(style.strokeWidth),
			strokeOpacity: Number.parseFloat(style.strokeOpacity),
			vectorEffect: style.vectorEffect,
			length: path.getTotalLength(),
			d: path.getAttribute("d"),
			svgPosition: svgStyle.position,
			svgOverflow: svgStyle.overflow,
			width: rect.width,
			height: rect.height,
			insideNativeEdgeLayer: Boolean(element.closest(".react-flow__edges")),
		};
	});

	expect(paint.d).toBeTruthy();
	expect(paint.length).toBeGreaterThan(20);
	expect(paint.stroke).not.toBe("none");
	expect(paint.stroke).not.toBe("rgba(0, 0, 0, 0)");
	expect(paint.strokeWidth).toBeGreaterThanOrEqual(3);
	expect(paint.strokeOpacity).toBeGreaterThanOrEqual(0.9);
	expect(paint.vectorEffect).toBe("non-scaling-stroke");
	expect(paint.svgPosition).toBe("absolute");
	expect(paint.svgOverflow).not.toBe("hidden");
	expect(paint.width).toBeGreaterThan(20);
	expect(paint.height).toBeGreaterThan(20);
	expect(paint.insideNativeEdgeLayer).toBe(false);
});

test("World Explorer inspector traverses visible connections without changing focus", async ({ page }) => {
	await page.goto("/mundo");
	await page.locator('[data-world-node="astel"]').click();

	await page.getByRole("tab", { name: /Laços/ }).click();
	await expect(page.getByRole("heading", { level: 3, name: "Conexões de Astel" })).toBeVisible();
	const ravenConnection = page.getByRole("button", { name: "Selecionar Raven Queen; relação Vínculo místico" });
	await expect(ravenConnection).toBeVisible();
	await ravenConnection.click();

	await expect(page.getByRole("heading", { level: 2, name: "Raven Queen", exact: true })).toBeVisible();
	await expect(page.getByRole("button", { name: "Selecionar Astel; relação Vínculo místico" })).toBeVisible();
	await expect(page).toHaveURL(/\/mundo$/);
});

test("World Explorer exposes honest SSR metadata through the central public contract", async ({ page }) => {
	await page.goto("/mundo");
	await expect(page).toHaveTitle(/Ecos da Jornada — demonstração/);
	await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /Demonstração multi-hub.*não são canon/);
	await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", "https://dnd.faysk.dev/mundo");
	await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", "https://dnd.faysk.dev/mundo");

	await page.goto("/mundo?foco=astel");
	await expect(page).toHaveTitle(/Astel · Ecos da Jornada — demonstração/);
	await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", "https://dnd.faysk.dev/mundo?foco=astel");

	await page.goto("/mundo?foco=segredo-inexistente");
	await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", "Ecos da Jornada — demonstração");
	await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", "https://dnd.faysk.dev/mundo");
});

test("World Explorer can switch to the textual view and filter relations with the DS select", async ({ page }) => {
	await page.goto("/mundo");
	await closeWorkspaceOverlays(page);
	await page.getByRole("button", { name: "Lista" }).click();
	const relations = page.locator('section[aria-labelledby="world-relations-title"]');
	await expect(relations.getByRole("heading", { name: "Relações em lista" })).toBeVisible();
	await expect(page.getByTestId("world-canvas")).toHaveCount(0);

	const relationTrigger = page.getByRole("button", { name: "Filtrar por relação" });
	await relationTrigger.click();
	await page.getByRole("option", { name: "Conflito" }).click();
	await expect(relationTrigger).toContainText("Conflito");
	await expect(relations.getByText("Conflito", { exact: true })).toBeVisible();
	await expect(relations.getByText("Rivalidade", { exact: true })).toBeVisible();
});

test("World Explorer explains an empty search and recovers when the query is cleared", async ({ page }) => {
	await page.goto("/mundo");
	const search = page.getByRole("searchbox", { name: "Buscar no mundo" });
	const canvas = page.getByTestId("world-canvas");

	await search.fill("memoria-que-nao-existe");
	await expect(page.getByText("Nenhuma relação visível para os filtros atuais.")).toBeHidden();
	await expect.poll(() =>
		canvas.evaluate((element) => getComputedStyle(element, "::after").content),
	).toContain("Nenhum resultado visível");

	await search.fill("");
	await expect(page.locator('[data-world-node="dandelion"]')).toBeVisible();
	await expect.poll(() =>
		canvas.evaluate((element) => getComputedStyle(element, "::after").content),
	).not.toContain("Nenhum resultado visível");
});

test("World Explorer relation select follows the real theme toggle and never falls back to native chrome", async ({ page }) => {
	await page.goto("/mundo");
	await closeWorkspaceOverlays(page);
	const relationTrigger = page.getByRole("button", { name: "Filtrar por relação" });
	const listbox = page.getByRole("listbox", { name: "Filtrar por relação" });

	await relationTrigger.click();
	await expect(listbox).toBeVisible();
	const firstPaint = await listbox.evaluate((element) => {
		const style = getComputedStyle(element);
		return {
			background: style.backgroundColor,
			borderWidth: style.borderTopWidth,
			borderRadius: style.borderTopLeftRadius,
		};
	});
	expect(firstPaint.background).not.toBe("rgba(0, 0, 0, 0)");
	expect(firstPaint.borderWidth).not.toBe("0px");
	expect(firstPaint.borderRadius).not.toBe("0px");
	await page.keyboard.press("Escape");
	await expect(listbox).toBeHidden();

	await page.getByRole("button", { name: "Mostrar menu principal" }).click();
	const themeToggle = page.getByRole("switch", { name: "Modo escuro" });
	await expect(themeToggle).toBeVisible();
	const wasDark = await themeToggle.getAttribute("aria-checked");
	await themeToggle.click();
	await expect(themeToggle).toHaveAttribute("aria-checked", wasDark === "true" ? "false" : "true");
	await page.waitForTimeout(800);
	await page.getByRole("button", { name: "Ocultar menu principal" }).click();
	await expect(page.locator(".site-header")).toBeHidden();

	await relationTrigger.click();
	await expect(listbox).toBeVisible();
	await expect.poll(() => listbox.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(firstPaint.background);

	const nativeRelationSelect = await page.locator("select").evaluateAll((selects) =>
		selects.some((select) =>
			Array.from((select as HTMLSelectElement).options).some((option) => option.text === "Conflito"),
		),
	);
	expect(nativeRelationSelect).toBe(false);
});

test("World Explorer nodes are movable without changing the URL", async ({ page }) => {
	await page.goto("/mundo");
	const astel = page.locator('[data-world-node="astel"]').locator("..");
	const before = await astel.getAttribute("style");
	const box = await astel.boundingBox();
	expect(box).not.toBeNull();
	if (box) {
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
		await page.mouse.down();
		await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 30, { steps: 6 });
		await page.mouse.up();
	}
	await expect.poll(() => astel.getAttribute("style")).not.toBe(before);
	await expect(page).toHaveURL(/\/mundo$/);
});

test("World Explorer collapses the side inspector before it can squeeze intermediate widths", async ({ page }) => {
	await page.setViewportSize({ width: 1024, height: 900 });
	await page.goto("/mundo");
	await expect(page.getByTestId("world-canvas")).toBeVisible();
	await expect(page.getByLabel("Ajustar largura do painel")).toBeHidden();
	await expect(page.getByRole("button", { name: "Filtrar por relação" })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("World Explorer stays inside the viewport including the 320px minimum", async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 800 });
	await page.goto("/mundo");
	await expect(page.getByTestId("world-canvas")).toBeVisible();
	await expect(page.getByRole("button", { name: "Todos" })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
