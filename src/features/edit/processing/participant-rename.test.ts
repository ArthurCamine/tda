import { describe, expect, it } from "vitest";
import { applyParticipantRename, participantGroups, previewParticipantRename } from "./participant-rename";
import type { LocalReviewSegment } from "./protocol";

function segment(trackNumber: number, segmentId: string, speaker = "Alex"): LocalReviewSegment {
	return { trackNumber, segmentId, speaker, start: 1, end: 2, text: "Texto intacto", reviewed: true };
}

describe("participant rename", () => {
	it("preserves exceptions, other tracks and every non-speaker field", () => {
		const original = [segment(1, "a"), segment(1, "b"), segment(1, "c"), segment(1, "d", "Convidado"), segment(2, "a")];
		const bytes = JSON.stringify(original);
		const intent = previewParticipantRename(original, 1, "Alex", "Novo");
		const result = applyParticipantRename(original, intent);
		expect(intent.identities).toHaveLength(3);
		expect(result.map((item) => item.speaker)).toEqual(["Novo", "Novo", "Novo", "Convidado", "Alex"]);
		result.forEach((item, index) => { expect({ ...item, speaker: original[index].speaker }).toEqual(original[index]); });
		expect(result[3]).toBe(original[3]);
		expect(JSON.stringify(original)).toBe(bytes);
		expect(participantGroups(original)).toHaveLength(3);
	});
	it.each(["", "  \n", "a".repeat(161), "bad\u0000name"])("rejects invalid names", (name) => {
		const base = [segment(1, "a")];
		expect(() => applyParticipantRename(base, previewParticipantRename(base, 1, "Alex", name))).toThrow("PARTICIPANT_NAME_INVALID");
	});
	it("requires another preview when the affected identities changed", () => {
		const base = [segment(1, "a")];
		const intent = previewParticipantRename(base, 1, "Alex", "Novo");
		expect(() => applyParticipantRename([...base, segment(1, "b")], intent)).toThrow("PARTICIPANT_PREVIEW_STALE");
		expect(() => applyParticipantRename([segment(1, "a", "Exception")], intent)).toThrow("PARTICIPANT_PREVIEW_STALE");
	});
	it("transforms 3000 of 7500 segments in one snapshot", () => {
		const base = Array.from({ length: 7500 }, (_, i) => segment(i < 3000 ? 1 : 2, `${i}`));
		const result = applyParticipantRename(base, previewParticipantRename(base, 1, "Alex", "😀".repeat(160)));
		expect(result.filter((item, i) => item !== base[i])).toHaveLength(3000);
		expect(result).toHaveLength(7500);
	});
});
