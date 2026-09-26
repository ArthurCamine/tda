import { isReviewStringV1 } from "../../transcript-review/text-contract";
import type { LocalReviewSegment } from "./protocol";

export type ParticipantRename = Readonly<{
	trackNumber: number;
	expectedSpeaker: string;
	newSpeaker: string;
	identities: readonly string[];
}>;

export function participantGroups(segments: readonly LocalReviewSegment[]) {
	const groups = new Map<string, { trackNumber: number; speaker: string; count: number }>();
	for (const segment of segments) {
		const key = JSON.stringify([segment.trackNumber, segment.speaker]);
		const group = groups.get(key);
		if (group) group.count++;
		else groups.set(key, { trackNumber: segment.trackNumber, speaker: segment.speaker, count: 1 });
	}
	return [...groups.entries()].map(([key, group]) => ({ key, ...group }));
}

export function previewParticipantRename(
	segments: readonly LocalReviewSegment[], trackNumber: number,
	expectedSpeaker: string, newSpeaker: string,
): ParticipantRename {
	return { trackNumber, expectedSpeaker, newSpeaker,
		identities: segments.filter((segment) => segment.trackNumber === trackNumber && segment.speaker === expectedSpeaker)
			.map((segment) => JSON.stringify([segment.trackNumber, segment.segmentId])),
	};
}

export function applyParticipantRename(segments: readonly LocalReviewSegment[], intent: ParticipantRename) {
	if (!isReviewStringV1(intent.newSpeaker, "speaker")) throw new Error("PARTICIPANT_NAME_INVALID");
	const current = previewParticipantRename(segments, intent.trackNumber, intent.expectedSpeaker, intent.newSpeaker);
	if (current.identities.length !== intent.identities.length || current.identities.some((id, index) => id !== intent.identities[index]))
		throw new Error("PARTICIPANT_PREVIEW_STALE");
	if (!current.identities.length || intent.newSpeaker === intent.expectedSpeaker) return segments;
	return segments.map((segment) => segment.trackNumber === intent.trackNumber && segment.speaker === intent.expectedSpeaker
		? { ...segment, speaker: intent.newSpeaker } : segment);
}
