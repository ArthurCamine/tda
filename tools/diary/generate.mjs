import { readFile, readdir, writeFile } from "node:fs/promises";

const root = new URL("../../", import.meta.url);
const read = async (path) =>
	(await readFile(new URL(path, root), "utf8")).replace(/\r\n/g, "\n");
const escapeHtml = (text) =>
	text.replace(
		/[&<>"']/g,
		(char) =>
			({
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&#39;",
			})[char],
	);
const check = process.argv.includes("--check");
const diaries = JSON.parse(await read("src/features/diary/catalog.json"));
const seen = new Set();

async function emit(path, content) {
	if (check) {
		if ((await read(path)) !== content)
			throw new Error(`${path} desatualizado; execute pnpm diary:generate.`);
	} else await writeFile(new URL(path, root), content, "utf8");
}

for (const diary of diaries) {
	const { slug, title, author, description } = diary;
	if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || seen.has(slug))
		throw new Error("Slug inválido ou duplicado.");
	seen.add(slug);
	const source = `content/diaries/${slug}/`;
	const target = `public/diario/${slug}/`;
	const files = (await readdir(new URL(source, root)))
		.filter((file) => /^\d+_.+\.md$/.test(file))
		.sort((a, b) => Number.parseInt(a, 10) - Number.parseInt(b, 10));
	if (!files.length) throw new Error(`${slug}: nenhum capítulo encontrado.`);
	const chapters = [];
	for (const file of files) {
		const text = (await read(source + file))
			.replace(/^\uFEFF/, "")
			.replace(/\r\n/g, "\n")
			.trim();
		const [heading, ...lines] = text.split("\n");
		const match = heading.match(/^# Capítulo (\d+):\s*(.+)$/);
		if (
			!match ||
			Number(match[1]) !== chapters.length + 1 ||
			Number.parseInt(file, 10) !== Number(match[1])
		)
			throw new Error(`${file}: numeração ou título inválido.`);
		const body = lines.join("\n").trim();
		if (!body) throw new Error(`${file}: capítulo vazio.`);
		chapters.push({
			id: file.replace(/\.md$/, ""),
			number: Number(match[1]),
			title: match[2],
			paragraphs: body.split(/\n\s*\n/).map((p) => p.trim()),
		});
	}
	await emit(
		`${target}capitulos.js`,
		`// Gerado por pnpm diary:generate. Fonte: ${source}\nwindow.DIARY_CHAPTERS = ${JSON.stringify(chapters, null, 2).replace(/</g, "\\u003c")};\n`,
	);
	const canonical = `https://dnd.faysk.dev/diario/${slug}`;
	const metadata = `<title>${escapeHtml(title)}</title>
  <meta name="description" content="${escapeHtml(description)}">
  <meta name="author" content="${escapeHtml(author)}">
  <link rel="canonical" href="${canonical}">
  <meta property="og:type" content="article">
  <meta property="og:locale" content="pt_BR">
  <meta property="og:site_name" content="TDA — Tem Dado Aqui">
  <meta property="og:title" content="${escapeHtml(title)}">
  <meta property="og:description" content="${escapeHtml(description)}">
  <meta property="og:url" content="${canonical}">
  <meta property="og:image" content="https://dnd.faysk.dev/og/default">
  <meta property="og:image:alt" content="TDA — Tem Dado Aqui">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="${escapeHtml(title)}">
  <meta name="twitter:description" content="${escapeHtml(description)}">
  <meta name="twitter:image" content="https://dnd.faysk.dev/og/default">`;
	const index = await read(`${target}index.html`);
	if (
		!index.includes("<!-- diary:metadata -->") ||
		!index.includes("<!-- /diary:metadata -->")
	)
		throw new Error(`${slug}: bloco de metadata ausente.`);
	await emit(
		`${target}index.html`,
		index.replace(
			/<!-- diary:metadata -->[\s\S]*?<!-- \/diary:metadata -->/,
			`<!-- diary:metadata -->\n  ${metadata}\n  <!-- /diary:metadata -->`,
		),
	);
	await emit(
		`${target}leitura.html`,
		`<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  ${metadata}
  <link rel="icon" href="/diario/${slug}/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/diario/${slug}/reading.css">
</head>
<body>
  <header><nav aria-label="Navegação do diário"><a href="/diario">Todos os diários</a><a href="/diario/${slug}">Abrir versão em livro</a></nav><h1>${escapeHtml(title)}</h1><p>${escapeHtml(author)}</p></header>
  <main>
    <nav id="sumario" aria-label="Capítulos"><h2>Sumário</h2><ol>${chapters.map((c) => `<li><a href="#${c.id}">${escapeHtml(c.title)}</a></li>`).join("")}</ol></nav>
    ${chapters.map((c) => `<section id="${c.id}" aria-labelledby="title-${c.id}"><p class="chapter-number">Capítulo ${c.number}</p><h2 id="title-${c.id}">${escapeHtml(c.title)}</h2>${c.paragraphs.map((p) => (p === "***" ? "<hr>" : `<p>${escapeHtml(p)}</p>`)).join("\n")}<a class="back" href="#sumario">Voltar ao sumário</a></section>`).join("\n")}
  </main>
  <footer><a href="/diario">Todos os diários</a></footer>
</body>
</html>
`,
	);
	console.log(
		`${slug}: ${chapters.length} capítulos ${check ? "verificados" : "gerados"}.`,
	);
}
