import { LocalReviewWorkspace } from "../../src/features/edit/processing/local-review";
import type { LocalReview } from "../../src/features/edit/processing/protocol";
import { useState } from "react";

// Synthetic browser data; the product never imports this isolated harness.
export function ReviewFixture() {
	const legacy = new URLSearchParams(location.search).has("legacy");
	const ephemeral = new URLSearchParams(location.search).has("ephemeral");
	const oldAgent = new URLSearchParams(location.search).has("old-agent");
	const [review, setReview] = useState<LocalReview>({
		sourceId: `craig-${"a".repeat(64)}`,
		runId: "run-synthetic-a1",
		baseTranscriptSha256: "b".repeat(64),
		draftSha256: ephemeral ? null : "c".repeat(64),
		draftRevision: ephemeral ? null : 1,
		persistence: ephemeral ? "ephemeral_base" : "persisted",
		...(oldAgent ? {} : { snapshotContract: "tda_local_review_cas_v1" }),
		status: "draft",
		approvalCurrent: false,
		approvedAt: null,
		createdAt: ephemeral ? null : "2026-09-26T12:00:00Z",
		updatedAt: ephemeral ? null : "2026-09-26T12:00:00Z",
		lineage: {
			profileId: "whisper-detailed",
			engine: "faster-whisper",
			model: "large-v3",
			modelRevision: null,
			device: "cpu",
			computeType: "int8",
			alignment: "native",
			executionLineage: null,
			completedAt: "2026-09-26T12:00:00Z",
		},
		stats: {
			audioWorkSeconds: 60,
			processingSeconds: 30,
			sessionDurationSeconds: 60,
			rtf: 0.5,
			wordCount: 2,
			segmentCount: 1,
			trackCount: 1,
		},
		warnings: Array.from(
			{ length: 1000 },
			(_, index) => `SYNTHETIC_WARNING_${index % 75}`,
		),
		...(legacy
			? {}
			: {
					warningSummary: {
						totalCount: 5000,
						displayedCount: 1000,
						truncated: true,
					},
				}),
		publicationTarget: null,
		review: {
			reviewedSegments: 0,
			totalSegments: 1,
			reviewPercent: 0,
			editedSegments: 0,
			wordCount: 2,
			warningCount: legacy ? 1000 : 5000,
		},
		segments: [
			{
				trackNumber: 1,
				segmentId: "1-0",
				start: 0,
				end: 1,
				text: "Olá\u0085mundo",
				speaker: "Participante sintético",
				reviewed: false,
			},
		],
		sync: { status: "not_configured" },
	});
	return (
		<LocalReviewWorkspace
			runs={[]}
			review={review}
			busy={false}
			error={null}
			publicationEnabled={false}
			onOpen={() => {}}
			onSave={(baseline, status, segments) => setReview({ ...baseline, status, segments,
				approvalCurrent: status === "approved_local",
				approvedAt: status === "approved_local" ? "2026-09-26T12:00:01Z" : null,
				persistence: "persisted", draftRevision: (baseline.draftRevision ?? 0) + 1,
				draftSha256: "e".repeat(64), createdAt: "2026-09-26T12:00:00Z", updatedAt: "2026-09-26T12:00:00Z" })}
			onClose={() => {}}
			onPublish={async () => {
				throw new Error("Synthetic fixture cannot publish");
			}}
		/>
	);
}
