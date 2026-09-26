import { expect, test } from "@playwright/test";

test("base remains unsaved until an explicit editorial action", async ({ page }) => {
	await page.goto("/?review-contracts&ephemeral");
	await expect(page.getByText("Visualização da base. Nenhuma revisão foi salva.")).toBeVisible();
	await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
	await page.getByLabel("Estado do draft").selectOption("approved_local");
	await page.getByRole("button", { name: "Salvar revisão" }).click();
	await expect(page.getByText("Draft salvo localmente.")).toBeVisible();
	await expect(page.getByText(/Run bruto imutável · draft r1/)).toBeVisible();
	await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
});

test("older Agent remains readable and requires an update before editing", async ({ page }) => {
	await page.goto("/?review-contracts&old-agent");
	await expect(page.getByText(/Atualize o Companion para salvar/)).toBeVisible();
	await expect(page.getByRole("textbox", { name: "Texto", exact: true })).toBeDisabled();
	await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
});

test("speaker limits count emoji as one scalar and reject excess ASCII before save", async ({ page }) => {
	await page.goto("/?review-contracts");
	const speaker = page.getByRole("textbox", { name: "Speaker", exact: true });
	await speaker.fill("😀".repeat(160));
	await expect(speaker).toHaveValue("😀".repeat(160));
	await expect(speaker).toHaveAttribute("aria-invalid", "false");
	await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeEnabled();
	await speaker.fill("a".repeat(161));
	await expect(speaker).toHaveAttribute("aria-invalid", "true");
	await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
	await expect(page.getByRole("alert")).toContainText("Corrija os campos");
});

test("review shows factual warning totals with bounded details and Unicode word count", async ({
	page,
}, testInfo) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto("/?review-contracts");
	await expect(
		page.getByRole("heading", { name: "whisper-detailed" }),
	).toBeVisible();
	await expect(
		page.getByText("Avisos", { exact: true }).locator("..").locator("strong"),
	).toHaveText("5000");
	await expect(
		page.getByText("Palavras", { exact: true }).locator("..").locator("strong"),
	).toHaveText("2");
	await page.locator("summary").filter({ hasText: "avisos do pipeline" }).click();
	await expect(page.locator("summary").filter({ hasText: "avisos do pipeline" })).toHaveText(
		"5000 avisos do pipeline · mostrando 50 tipos dos primeiros 1000 avisos",
	);
	await expect(page.locator("details li")).toHaveCount(50);
	expect(
		await page.evaluate(
			() =>
				document.documentElement.scrollWidth <=
				document.documentElement.clientWidth,
		),
	).toBe(true);
	await page.screenshot({
		path: testInfo.outputPath("review-warnings.png"),
		fullPage: true,
	});
	expect(errors).toEqual([]);
});

test("historical review does not claim a verified total", async ({ page }) => {
	await page.goto("/?review-contracts&legacy");
	await expect(page.getByText("total histórico não verificado")).toBeVisible();
	await expect(page.locator("summary").filter({ hasText: "avisos do pipeline" })).not.toContainText("primeiros");
});


test("target repair preserves edits and restores only the original destination", async ({ page }, testInfo) => {
    await page.goto("/?review-contracts&repair");
    const repair = page.getByRole("button", { name: "Reparar vínculo original" });
    await expect(page.getByText(/O vínculo de publicação está danificado/)).toBeVisible();
    await page.getByRole("textbox", { name: "Texto", exact: true }).fill("Texto preservado");
    await expect(repair).toBeDisabled();
    await page.getByRole("button", { name: "Salvar revisão" }).click();
    await expect(repair).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath("publication-target-repair.png"), fullPage: true });
    await repair.click();
    await expect(repair).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Texto", exact: true })).toHaveValue("Texto preservado");
    await expect(page.getByText(/Destino vinculado: yuhara-main/)).toBeVisible();
});


test("bulk rename isolates a track, preserves exceptions and saves one snapshot", async ({ page }, testInfo) => {
    await page.goto("/?review-contracts&bulk");
    await page.getByText(/Gerenciar participantes/).click();
    await page.getByLabel("Participante de origem").selectOption(JSON.stringify([1, "Alex"]));
    await page.getByLabel("Novo nome").fill("Nome normalizado");
    await expect(page.getByText("3 falas serão alteradas; 1 com nomes diferentes serão preservadas.")).toBeVisible();
    await page.getByRole("button", { name: "Revisar renomeio" }).click();
    await page.getByRole("button", { name: "Cancelar renomeio" }).click();
    await expect(page.getByTestId("save-count")).toHaveText("0");
    await page.getByLabel("Novo nome").fill("Nome normalizado");
    await page.getByRole("button", { name: "Revisar renomeio" }).click();
    await page.getByRole("button", { name: "Aplicar ao draft" }).click();
    await expect(page.getByLabel("Participante de origem")).toBeFocused();
    await expect(page.getByLabel("Estado do draft")).toHaveValue("reviewed");
    await expect(page.getByTestId("save-count")).toHaveText("0");
    const speakers = page.getByRole("textbox", { name: "Speaker", exact: true });
    expect(await speakers.evaluateAll((nodes) => nodes.map((node) => (node as HTMLInputElement).value))).toEqual(["Nome normalizado", "Nome normalizado", "Nome normalizado", "Convidado", "Alex"]);
    await page.screenshot({ path: testInfo.outputPath("participant-rename.png"), fullPage: true });
    await page.getByRole("button", { name: "Salvar revisão" }).click();
    await expect(page.getByTestId("save-count")).toHaveText("1");
    await expect(speakers.first()).toHaveValue("Nome normalizado");
});

test("bulk rename survives a save conflict", async ({ page }) => {
    await page.goto("/?review-contracts&bulk&conflict");
    await page.getByText(/Gerenciar participantes/).click();
    await page.getByLabel("Participante de origem").selectOption(JSON.stringify([1, "Alex"]));
    await page.getByLabel("Novo nome").fill("Novo");
    await page.getByRole("button", { name: "Revisar renomeio" }).click();
    await page.getByRole("button", { name: "Aplicar ao draft" }).click();
    await page.getByRole("button", { name: "Salvar revisão" }).click();
    await expect(page.getByRole("alert")).toContainText("mudou em outra aba");
    await expect(page.getByRole("textbox", { name: "Speaker", exact: true }).first()).toHaveValue("Novo");
    await expect(page.getByText("Alterações não salvas neste draft.")).toBeVisible();
});


test("concurrent bulk edits reconcile by field without closing or losing the working copy", async ({ page }, testInfo) => {
    await page.goto("/?review-contracts&bulk&conflict");
    await page.getByText(/Gerenciar participantes/).click();
    await page.getByLabel("Participante de origem").selectOption(JSON.stringify([1, "Alex"]));
    await page.getByLabel("Novo nome").fill("Novo");
    await page.getByRole("button", { name: "Revisar renomeio" }).click();
    await page.getByRole("button", { name: "Aplicar ao draft" }).click();
    await page.getByLabel("Filtrar falas").fill("Fala");
    await page.getByRole("button", { name: "Salvar revisão" }).click();
    await page.getByRole("button", { name: "Comparar com versão mais recente" }).click();
    await expect(page.getByText(/3 mudanças locais · 1 colisões/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Salvar revisão" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Reconciliar no draft" })).toBeDisabled();
    await page.getByLabel("Manter minha alteração").check();
    await page.screenshot({ path: testInfo.outputPath("review-conflict.png"), fullPage: true });
    await page.getByRole("button", { name: "Reconciliar no draft" }).click();
    await expect(page.getByLabel("Filtrar falas")).toHaveValue("Fala");
    await expect(page.getByText(/Reconciliado sobre a revisão 2/)).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Speaker", exact: true }).first()).toHaveValue("Novo");
    await expect(page.getByRole("textbox", { name: "Texto", exact: true }).nth(1)).toHaveValue("Fala remota");
    await expect(page.getByLabel("Estado do draft")).toHaveValue("reviewed");
    await page.getByRole("button", { name: "Salvar revisão" }).click();
    await expect(page.getByText(/Run bruto imutável · draft r3/)).toBeVisible();
    await expect(page.getByTestId("save-count")).toHaveText("2");
});


test("publication freezes current and requires a fresh confirmation after stale_current", async ({ page }, testInfo) => {
 const first = "11111111-1111-4111-8111-111111111111";
 const second = "22222222-2222-4222-8222-222222222222";
 let reads = 0; const sent: Array<{ operationId: string; expectedCurrentRevisionId: string }> = [];
 await page.route("**/api/transcript-publications/current", route => route.fulfill({ json: { ok: true, current: { actorProfileId: "33333333-3333-4333-8333-333333333333", revisionId: (++reads, sent.length === 0 ? first : second) } } }));
 await page.route(/\/api\/transcript-publications$/, async route => {
  sent.push(route.request().postDataJSON());
  await route.fulfill({ status: 409, json: { ok: false, reason: "stale_current" } });
 });
 await page.goto("/?review-contracts&publication");
 await page.getByRole("button", { name: "Publicar no TDA" }).click();
 await expect(page.getByRole("alertdialog")).toContainText(first);
 expect(sent).toHaveLength(0);
 await page.screenshot({ path: testInfo.outputPath("publication-current-confirmation.png"), fullPage: true });
 await page.getByRole("button", { name: "Confirmar publicação" }).click();
 await expect(page.getByRole("alert")).toContainText("A revisão publicada mudou");
 expect(sent).toHaveLength(1); expect(sent[0].expectedCurrentRevisionId).toBe(first); expect(reads).toBeGreaterThanOrEqual(2);
 await page.getByRole("button", { name: "Publicar no TDA" }).click();
 await expect(page.getByRole("alertdialog")).toContainText(second);
 expect(sent).toHaveLength(1);
 await page.getByRole("button", { name: "Confirmar publicação" }).click();
 await expect(page.getByRole("alert")).toContainText("A revisão publicada mudou");
 expect(sent).toHaveLength(2); expect(sent[1].expectedCurrentRevisionId).toBe(second); expect(sent[1].operationId).not.toBe(sent[0].operationId);
});

test("lost publication recovers after reload without a second write or transcript storage", async ({ page }, testInfo) => {
 let posts = 0; let readable = false; let committed: Record<string, unknown> | null = null;
 await page.route("**/api/transcript-publications/current", route => route.fulfill({ json: { ok: true, current: { actorProfileId: "33333333-3333-4333-8333-333333333333", revisionId: committed ? "44444444-4444-4444-8444-444444444444" : null } } }));
 await page.route(/\/api\/transcript-publications$/, async route => {
  const body = route.request().postDataJSON(); posts++;
  committed = { schemaVersion: "tda_transcript_publication_receipt_v1", status: "committed", receiptId: "55555555-5555-4555-8555-555555555555", revisionId: "44444444-4444-4444-8444-444444444444", revisionNumber: 1, committedAt: "2026-09-26T12:00:00Z", operationId: body.operationId, sourceId: body.review.sourceId, runId: body.review.runId, baseTranscriptSha256: body.review.baseTranscriptSha256, draftSha256: body.review.draftSha256, segmentCount: body.review.segments.length, wordCount: body.review.review.wordCount };
  await route.abort();
 });
 await page.route("**/api/transcript-publications/receipt", async route => {
  if (!readable) { await route.fulfill({ status: 503, json: { ok: false, reason: "dependency_unavailable" } }); return; }
  const body = route.request().postDataJSON(); expect(body.operationId).toBe(committed?.operationId); expect(body.expectedCurrentRevisionId).toBeNull();
  await route.fulfill({ json: { ok: true, receipt: committed } });
 });
 await page.goto("/?review-contracts&publication");
 await page.getByRole("button", { name: "Publicar no TDA" }).click();
 await page.getByRole("button", { name: "Confirmar publicação" }).click();
 await expect(page.getByRole("alert")).toContainText("A resposta foi perdida");
 const stored = await page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith("tda.publication.pending.v1:")));
 expect(stored).toHaveLength(1); expect(stored[0][1]).not.toContain("Olá"); expect(stored[0][1]).not.toContain("Participante sintético"); expect(JSON.parse(stored[0][1]).operationId).toBe((committed as Record<string, unknown> | null)?.operationId);
 readable = true;
 await page.reload();
 await expect(page.getByText(/Publicação confirmada · revisão cloud 1/)).toBeVisible();
 expect(posts).toBe(1);
 expect(await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith("tda.publication.pending.v1:")))).toHaveLength(0);
 await page.screenshot({ path: testInfo.outputPath("publication-recovered.png"), fullPage: true });
});
