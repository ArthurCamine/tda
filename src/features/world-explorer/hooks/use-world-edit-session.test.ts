import { describe, expect, it } from "vitest";
import {
	worldDraftSaveFailureMessage,
	worldEditFailureMessage,
	worldLayoutPositionsEqual,
	worldPublishFailureMessage,
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

	it("keeps user-facing failure messages explicit about durability and publication", () => {
		expect(worldEditFailureMessage("lease_lost")).toContain("preservado");
		expect(worldEditFailureMessage("conflict")).toContain("preservado");
		expect(worldDraftSaveFailureMessage("dependency_unavailable")).toContain("Mantenha esta aba aberta");
		expect(worldPublishFailureMessage("media_pending")).toContain("publicação não aconteceu");
		expect(worldPublishFailureMessage("review_required")).toContain("fonte canônica");
		expect(worldPublishFailureMessage("dependency_unavailable")).toContain("Não foi possível confirmar");
		expect(worldPublishFailureMessage("dependency_unavailable")).toContain("rascunho continua preservado");
	});
});
