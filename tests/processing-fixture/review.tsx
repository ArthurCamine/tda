import { LocalReviewWorkspace } from "../../src/features/edit/processing/local-review";
import type { LocalReview } from "../../src/features/edit/processing/protocol";
import { useState } from "react";

// Synthetic browser data; the product never imports this isolated harness.
export function ReviewFixture() {
	const legacy = new URLSearchParams(location.search).has("legacy");
	const ephemeral = new URLSearchParams(location.search).has("ephemeral");
	const oldAgent = new URLSearchParams(location.search).has("old-agent");
	const bulk = new URLSearchParams(location.search).has("bulk");
    const [saveCount, setSaveCount] = useState(0);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [review, setReview] = useState<LocalReview>({
		sourceId: `craig-${"a".repeat(64)}`,
		runId: "run-synthetic-a1",
		baseTranscriptSha256: "b".repeat(64),
		draftSha256: ephemeral ? null : "c".repeat(64),
		draftRevision: ephemeral ? null : 1,
		persistence: ephemeral ? "ephemeral_base" : "persisted",
		...(oldAgent ? {} : { snapshotContract: "tda_local_review_cas_v1" }),
		status: bulk ? "approved_local" : "draft",
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
		publicationTargetState: "invalid",
		review: {
			reviewedSegments: 0,
			totalSegments: 1,
			reviewPercent: 0,
			editedSegments: 0,
			wordCount: 2,
			warningCount: legacy ? 1000 : 5000,
		},
		segments: bulk ? Array.from({ length: 5 }, (_, index) => ({
            trackNumber: index === 4 ? 2 : 1, segmentId: `s-${index}`, start: index, end: index + 1,
            text: `Fala ${index}`, speaker: index === 3 ? "Convidado" : "Alex", reviewed: true,
        })) : [
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
		<>
        <span data-testid="save-count">{saveCount}</span>
        <LocalReviewWorkspace
			runs={[]}
			review={review}
			busy={false}
			error={saveError}
			publicationEnabled={false}
			onOpen={() => {}}
			onSave={(baseline, status, segments) => {
                setSaveCount((count) => count + 1);
                setSaveError(null);
                if (new URLSearchParams(location.search).has("conflict") && baseline.draftRevision !== 2) { setSaveError("LOCAL_REVIEW_DRAFT_CONFLICT"); return; }
                setReview({ ...baseline, status, segments,
				approvalCurrent: status === "approved_local",
				approvedAt: status === "approved_local" ? "2026-09-26T12:00:01Z" : null,
				persistence: "persisted", draftRevision: (baseline.draftRevision ?? 0) + 1,
				draftSha256: "e".repeat(64), createdAt: "2026-09-26T12:00:00Z", updatedAt: "2026-09-26T12:00:00Z" }); }}
			onLoadLatest={async () => ({ ...review, draftRevision: 2, draftSha256: "f".repeat(64), status: "approved_local",
                segments: review.segments.map((segment, index) => index === 0 ? { ...segment, speaker: "Remoto" } : index === 1 ? { ...segment, text: "Fala remota" } : segment),
            })}
            onRepairTarget={new URLSearchParams(location.search).has("repair") ? () => setReview({ ...review,
                publicationTargetState: "valid", publicationTarget: {
                    campaignSlug: "yuhara-main", sourceSessionId: "sessao-synthetic",
                    jobId: "synthetic",
                    attempt: 1,
                },
            }) : undefined}
            onClose={() => {}}
			onPublish={async () => {
				throw new Error("Synthetic fixture cannot publish");
			}}
		/>
        </>
	);
}
