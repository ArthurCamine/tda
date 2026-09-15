import { notFound } from "next/navigation";
import { WorldCommandPaletteE2EFixture } from "@/features/world-explorer/components/world-command-palette-e2e-fixture";

export const dynamic = "force-dynamic";

export default function WorldCommandPaletteE2EPage() {
	if (process.env.TDA_E2E_FIXTURES !== "true") notFound();

	return (
		<main>
			<h1>World Command Palette E2E</h1>
			<WorldCommandPaletteE2EFixture />
		</main>
	);
}
