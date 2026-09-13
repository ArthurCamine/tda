import fs from "node:fs";
import path from "node:path";

const output = "docs/documentation/catalog.md";
function walk(dir) {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
		const file = `${dir}/${entry.name}`;
		return entry.isDirectory()
			? walk(file)
			: entry.name.endsWith(".md") && file !== output
				? [file]
				: [];
	});
}
const clean = (value) =>
	value.replaceAll("|", " / ").replaceAll("\n", " ").trim();
const files = walk("docs").sort();
let result =
	"# Catálogo documental gerado\n\nGerado por `pnpm docs:generate`; não editar manualmente. O [índice editorial](../README.md) continua sendo a entrada canônica. Este catálogo localiza páginas e lacunas de metadados sem duplicar contratos.\n\nDatas e estados são extraídos do cabeçalho, não inferidos do Git. `Não declarado` é lacuna de metadados, não ausência de implementação. O catálogo não concede aprovação nem substitui evidências.\n\n";
let missingOwner = 0;
let missingReview = 0;
for (const dir of [...new Set(files.map((file) => path.posix.dirname(file)))]) {
	result += `## ${dir}\n\n| Documento | Owner declarado | Estado declarado | Revisão declarada |\n| --- | --- | --- | --- |\n`;
	for (const file of files.filter((f) => path.posix.dirname(f) === dir)) {
		const text = fs.readFileSync(file, "utf8").split(/^```/m)[0];
		const title = text.match(/^#\s+(.+)$/m)?.[1] || file;
		const field = (name) =>
			text.match(new RegExp(`^>\\s*${name}:\\s*(.+)$`, "mi"))?.[1];
		const owner = field("Owner");
		const status = field("Status");
		const review = field("Última revisão");
		if (!owner) missingOwner++;
		if (!review) missingReview++;
		result += `| [${clean(title)}](${path.posix.relative("docs/documentation", file)}) | ${clean(owner || "Não declarado")} | ${clean(status || "Não declarado")} | ${clean(review || "Não declarado")} |\n`;
	}
	result += "\n";
}
result += `## Cobertura\n\n${files.length} páginas inventariadas, além deste catálogo gerado. ${missingOwner} sem Owner e ${missingReview} sem Última revisão no cabeçalho. Corrigir durante revisão real; não preencher datas automaticamente.\n`;
if (process.argv.includes("--write")) {
	fs.writeFileSync(output, result);
} else {
	const current = fs.existsSync(output)
		? fs.readFileSync(output, "utf8").replaceAll("\r\n", "\n")
		: "";
	if (current !== result) {
		const currentLines = current.split("\n");
		const expectedLines = result.split("\n");
		const maxLines = Math.max(currentLines.length, expectedLines.length);
		let firstDifference = 0;
		while (
			firstDifference < maxLines &&
			currentLines[firstDifference] === expectedLines[firstDifference]
		) {
			firstDifference++;
		}
		console.error(
			`Documentation catalog first mismatch at line ${firstDifference + 1}:\n` +
				`actual:   ${JSON.stringify(currentLines[firstDifference] ?? "<EOF>")}\n` +
				`expected: ${JSON.stringify(expectedLines[firstDifference] ?? "<EOF>")}`,
		);
		throw new Error("Documentation catalog stale: run pnpm docs:generate");
	}
}
console.log(`DOC_CATALOG_OK documents=${files.length}`);