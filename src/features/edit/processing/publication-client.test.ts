import { describe, expect, it, vi } from "vitest";
import type { LocalReview } from "./protocol";
import {
	PublicationClientError,
	publishApprovedLocalReview,
} from "./publication-client";

const sourceId = `craig-${"a".repeat(64)}`;
const review: LocalReview = {
	sourceId,
	runId: "run-job-a1",
	baseTranscriptSha256: "b".repeat(64),
	draftRevision: 2,
	draftSha256: "c".repeat(64),
	status: "approved_local",
	approvalCurrent: true,
	approvedAt: "2026-09-21T12:01:00Z",
	createdAt: "2026-09-21T12:00:00Z",
	updatedAt: "2026-09-21T12:01:00Z",
	lineage: {
		profileId: "whisper-detailed",
		engine: "faster-whisper",
		model: "large-v3",
		modelRevision: null,
		device: "cuda",
		computeType: "float16",
		alignment: "native",
		executionLineage: {
			schemaVersion: "tda_execution_lineage_v1",
			companionVersion: "0.3.14",
			runtimeFamily: "whisper",
			runtimeVersion: "1.1.5",
			device: "cuda",
			computeType: "float16",
			gpu: {
				vendor: "NVIDIA",
				index: 0,
				model: "NVIDIA Test GPU",
				vramTotalBytes: 8 * 1024 ** 3,
				computeCapability: "8.9",
				driverVersion: "600.12",
			},
		},
		completedAt: "2026-09-21T11:59:00Z",
	},
	stats: {
		audioWorkSeconds: 60,
		processingSeconds: 12,
		sessionDurationSeconds: 60,
		rtf: 0.2,
		wordCount: 2,
		segmentCount: 1,
		trackCount: 1,
	},
	warnings: [],
	publicationTarget: {
		campaignSlug: "yuhara-main",
		sourceSessionId: "sessao-00001",
		jobId: "job-a",
		attempt: 1,
	},
	review: {
		reviewedSegments: 1,
		totalSegments: 1,
		reviewPercent: 100,
		editedSegments: 1,
		wordCount: 2,
		warningCount: 0,
	},
	segments: [
		{
			trackNumber: 1,
			segmentId: "1-0",
			start: 0,
			end: 1,
			text: "Olá mundo",
			speaker: "Alice",
			reviewed: true,
		},
	],
	sync: { status: "not_configured" },
};

const receipt = {
	ok: true,
	receipt: {
		schemaVersion: "tda_transcript_publication_receipt_v1",
		status: "committed",
		receiptId: "11111111-1111-4111-8111-111111111111",
		campaignId: "22222222-2222-4222-8222-222222222222",
		sessionId: "33333333-3333-4333-8333-333333333333",
		revisionId: "44444444-4444-4444-8444-444444444444",
		revisionNumber: 7,
		operationId: "55555555-5555-4555-8555-555555555555",
		sourceId,
		runId: "run-job-a1",
		baseTranscriptSha256: "b".repeat(64),
		draftSha256: "c".repeat(64),
		payloadSha256: "d".repeat(64),
		segmentCount: 1,
		wordCount: 2,
		committedAt: "2026-09-21T12:02:00Z",
	},
};

describe("publication client", () => {
	it.each(["503", "invalid-json", "invalid-receipt"])(
		"reconciles ambiguous %s with byte-identical lookup",
		async (mode) => {
			const first =
				mode === "503"
					? Response.json(
							{ ok: false, reason: "dependency_unavailable" },
							{ status: 503 },
						)
					: mode === "invalid-json"
						? new Response("{")
						: Response.json({ ok: true, receipt: {} });
			const transport = vi
				.fn<typeof fetch>()
				.mockResolvedValueOnce(first)
				.mockResolvedValueOnce(Response.json(receipt));
			await expect(
				publishApprovedLocalReview(
					review,
					receipt.receipt.operationId,
					transport,
				),
			).resolves.toMatchObject({ revisionNumber: 7 });
			expect(transport).toHaveBeenCalledTimes(2);
			expect(transport.mock.calls[1][0]).toBe(
				"/api/transcript-publications/receipt",
			);
			expect(transport.mock.calls[1][1]?.body).toBe(
				transport.mock.calls[0][1]?.body,
			);
		},
	);
	it.each(["not_found", "dependency_unavailable"])(
		"keeps ambiguous publish unresolved after %s readback",
		async (reason) => {
			const transport = vi
				.fn<typeof fetch>()
				.mockResolvedValueOnce(
					Response.json({ reason: "dependency_unavailable" }, { status: 503 }),
				)
				.mockResolvedValueOnce(
					Response.json(
						{ reason },
						{ status: reason === "not_found" ? 404 : 503 },
					),
				);
			await expect(
				publishApprovedLocalReview(
					review,
					receipt.receipt.operationId,
					transport,
				),
			).rejects.toMatchObject({ code: "unconfirmed" });
		},
	);
	it.each([
		"unauthenticated",
		"forbidden",
		"invalid_payload",
		"too_large",
		"not_found",
		"conflict",
	])("does not read back definitive %s", async (reason) => {
		const transport = vi
			.fn<typeof fetch>()
			.mockResolvedValue(Response.json({ reason }, { status: 400 }));
		await expect(
			publishApprovedLocalReview(
				review,
				receipt.receipt.operationId,
				transport,
			),
		).rejects.toMatchObject({ code: reason });
		expect(transport).toHaveBeenCalledTimes(1);
	});
	it.each([
		"operationId",
		"sourceId",
		"runId",
		"baseTranscriptSha256",
		"draftSha256",
	])("rejects readback for another %s", async (field) => {
		const transport = vi
			.fn<typeof fetch>()
			.mockRejectedValueOnce(new TypeError("lost"))
			.mockResolvedValueOnce(
				Response.json({
					...receipt,
					receipt: { ...receipt.receipt, [field]: "different" },
				}),
			);
		await expect(
			publishApprovedLocalReview(
				review,
				receipt.receipt.operationId,
				transport,
			),
		).rejects.toMatchObject({ code: "conflict" });
	});
	it("publishes an approved review with the durable target binding", async () => {
		const transport = vi
			.fn<typeof fetch>()
			.mockResolvedValue(Response.json(receipt));
		const result = await publishApprovedLocalReview(
			review,
			"55555555-5555-4555-8555-555555555555",
			transport,
		);
		expect(result).toMatchObject({ revisionNumber: 7 });
		const [path, init] = transport.mock.calls[0];
		expect(path).toBe("/api/transcript-publications");
		const body = JSON.parse(String(init?.body));
		expect(body).toMatchObject({
			operationId: "55555555-5555-4555-8555-555555555555",
			binding: {
				campaignSlug: "yuhara-main",
				sourceSessionId: "sessao-00001",
				jobId: "job-a",
				attempt: 1,
			},
			review: {
				status: "approved_local",
				draftSha256: "c".repeat(64),
			},
		});
		expect(body.review.lineage).not.toHaveProperty("executionLineage");
		expect(JSON.stringify(body)).not.toContain("NVIDIA Test GPU");
	});

	it("uses receipt readback after an ambiguous network failure", async () => {
		const transport = vi
			.fn<typeof fetch>()
			.mockRejectedValueOnce(new TypeError("connection reset"))
			.mockResolvedValueOnce(Response.json(receipt));
		const result = await publishApprovedLocalReview(
			review,
			"55555555-5555-4555-8555-555555555555",
			transport,
		);
		expect(result.revisionId).toBe("44444444-4444-4444-8444-444444444444");
		expect(transport.mock.calls.map(([path]) => path)).toEqual([
			"/api/transcript-publications",
			"/api/transcript-publications/receipt",
		]);
		expect(transport.mock.calls[0][1]?.body).toBe(
			transport.mock.calls[1][1]?.body,
		);
	});

	it("does not turn an explicit server rejection into an ambiguous retry", async () => {
		const transport = vi
			.fn<typeof fetch>()
			.mockResolvedValue(
				Response.json({ ok: false, reason: "forbidden" }, { status: 403 }),
			);
		await expect(
			publishApprovedLocalReview(
				review,
				"55555555-5555-4555-8555-555555555555",
				transport,
			),
		).rejects.toMatchObject({ code: "forbidden" });
		expect(transport).toHaveBeenCalledTimes(1);
	});

	it("keeps an operation unconfirmed when neither POST nor readback can prove commit", async () => {
		const transport = vi
			.fn<typeof fetch>()
			.mockRejectedValueOnce(new TypeError("connection reset"))
			.mockResolvedValueOnce(
				Response.json({ ok: false, reason: "not_found" }, { status: 404 }),
			);
		await expect(
			publishApprovedLocalReview(
				review,
				"55555555-5555-4555-8555-555555555555",
				transport,
			),
		).rejects.toEqual(new PublicationClientError("unconfirmed"));
	});
});
