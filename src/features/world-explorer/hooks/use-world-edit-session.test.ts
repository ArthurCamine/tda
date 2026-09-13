import { describe, expect, it } from "vitest";
import {
	worldEditFailureMessage,
	worldLayoutPositionsEqual,
} from "./world-edit-session-model";

describe("World edit session helpers", () => {
	it("compares layout positions independent of object key order", () => {
		expect(
			worldLayoutPositionsEqual(
				{ astel: { x: 10, y: 20 }, dandelion: { x: 30, y: 40 } },
				{ dandelion: { x: 30, y: 40 }, astel: { x: 10, y: 20 } },
			),
		).toBe(true);
		expect(
			worldLayoutPositionsEqual(
				{ astel: { x: 10, y: 20 } },
				{ astel: { x: 11, y: 20 } },
			),
		).toBe(false);
	});

	it("keeps user-facing failure messages stable", () => {
		expect(worldEditFailureMessage("lease_lost")).toContain("sessão exclusiva");
		expect(worldEditFailureMessage("conflict")).toContain("rascunho foi preservado");
		expect(worldEditFailureMessage("media_pending")).toContain("imagem");
		expect(worldEditFailureMessage("media_pending")).toContain("foram preservados");
		expect(worldEditFailureMessage("unknown")).toContain("Nenhuma alteração foi publicada");
	});
});
