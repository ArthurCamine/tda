import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalBridge } from "./bridge";
import {
	BridgeError,
	parseLocalReview,
	parseLocalRuns,
	parseLocalSources,
	type LocalReviewSegment,
} from "./protocol";
import { LOCAL_JSON_BODY_MAX_BYTES } from "./request-budget";
import strings from "../../../../fixtures/transcript-review-strings-v1.json";

const token = "review_bridge_token_1234567890123456789012";
const signal = () => new AbortController().signal;
const sourceSha = "a".repeat(64);
const sourceId = `craig-${sourceSha}`;
const runId = "run-job-review-a1";
const transcriptSha = "b".repeat(64);
const draftSha = "c".repeat(64);

function rawReview(
	segments: Array<{
		track_number: number;
		segment_id: string;
		start: number;
		end: number;
		text: string;
		speaker: string;
		reviewed: boolean;
	}> = [
		{
			track_number: 1,
			segment_id: "1-0",
			start: 0,
			end: 1,
			text: "Texto original",
			speaker: "Alice",
			reviewed: false,
		},
	],
) {
	return {
		schema_version: "tda_local_review_v1",
		source_id: sourceId,
		run_id: runId,
		base_transcript_sha256: transcriptSha,
		draft_revision: 0,
		draft_sha256: draftSha,
		status: "draft",
		approval_current: false,
		approved_at: null,
		created_at: "2026-09-21T00:00:00.000Z",
		updated_at: "2026-09-21T00:00:00.000Z",
		lineage: {
			profile_id: "legacy-profile",
			engine: "faster-whisper",
			model: "large-v3",
			model_revision: null,
			device: "cuda",
			compute_type: "float16",
			alignment: "native",
			execution_lineage: {
				schema_version: "tda_execution_lineage_v1",
				companion_version: "0.3.14",
				runtime_family: "whisper",
				runtime_version: "1.1.5",
				device: "cuda",
				compute_type: "float16",
				gpu: {
					vendor: "NVIDIA",
					index: 0,
					model: "NVIDIA Test GPU",
					vram_total_bytes: 8589934592,
					compute_capability: "8.9",
					driver_version: "600.12",
				},
			},
			completed_at: "2026-09-21T00:00:00.000Z",
		},
		stats: {
			audio_work_seconds: 60,
			processing_seconds: 12,
			session_duration_seconds: 60,
			rtf: 0.2,
			word_count: 2,
			segment_count: segments.length,
			track_count: 1,
		},
		warnings: ["LOW_CONFIDENCE"],
		publication_target: {
			schema_version: "tda_publication_target_v1",
			campaign_slug: "yuhara-main",
			source_session_id: "sessao-00001",
			source_id: sourceId,
			run_id: runId,
			job_id: "job-review",
			attempt: 1,
			transcript_sha256: transcriptSha,
		},
		review: {
			reviewed_segments: segments.filter((item) => item.reviewed).length,
			total_segments: segments.length,
			review_percent:
				segments.length === 0
					? 100
					: (segments.filter((item) => item.reviewed).length / segments.length) * 100,
			edited_segments: 0,
			word_count: segments.reduce(
				(total, item) => total + item.text.trim().split(/\s+/u).length,
				0,
			),
			warning_count: 1,
		},
		segments,
		sync: { status: "not_configured" },
	};
}

afterEach(() => {
	new LocalBridge().disconnect();
});

describe("local result/review contracts", () => {
	it("parses exactly the shared editorial string acceptance fixture", () => {
		for (const item of strings.cases) {
			const raw = rawReview();
			const value = (item.codePoints ? String.fromCodePoint(...item.codePoints) : item.value).repeat(item.repeat);
			raw.segments[0][item.field as "text" | "speaker"] = value;
			if (item.valid) expect(parseLocalReview(raw).segments[0][item.field as "text" | "speaker"], item.name).toBe(value);
			else expect(() => parseLocalReview(raw), item.name).toThrow();
		}
	});
	it("requires an exact approval proof marker for approved review responses", () => {
		const approved = {
			...rawReview(),
			status: "approved_local",
			approval_current: true,
			approved_at: "2026-09-26T17:00:00.000Z",
		};
		expect(parseLocalReview(approved)).toMatchObject({
			status: "approved_local",
			approvalCurrent: true,
			approvedAt: "2026-09-26T17:00:00.000Z",
		});
		expect(() =>
			parseLocalReview({
				...approved,
				approval_current: false,
				approved_at: null,
			}),
		).toThrow();
	});

	it("parses an ephemeral base without inventing revision, hash or timestamps", () => {
		const raw = { ...rawReview(), snapshot_contract: "tda_local_review_cas_v1", persistence: "ephemeral_base",
			draft_revision: null, draft_sha256: null, created_at: null, updated_at: null };
		expect(parseLocalReview(raw)).toMatchObject({ persistence: "ephemeral_base", draftRevision: null, draftSha256: null });
		expect(() => parseLocalReview({ ...raw, draft_revision: 0 })).toThrow();
		expect(() => parseLocalReview({ ...raw, status: "approved_local" })).toThrow();
		expect(() => parseLocalReview({ ...raw, snapshot_contract: undefined })).toThrow();
	});
	it("transmits the opened snapshot identity and rejects legacy writes", async () => {
		const transport = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(rawReview()));
		const bridge = new LocalBridge(transport);
		bridge.pair(token);
		const baseline = parseLocalReview({ ...rawReview(), snapshot_contract: "tda_local_review_cas_v1", persistence: "persisted" });
		await bridge.saveLocalReview(sourceId, runId, baseline, "reviewed", baseline.segments, signal());
		expect(JSON.parse(String(transport.mock.calls[0][1]?.body))).toMatchObject({
			snapshot_contract: "tda_local_review_cas_v1",
			expected: { persistence: "persisted", draft_revision: 0, draft_sha256: draftSha },
		});
		const ephemeral = parseLocalReview({ ...rawReview(), snapshot_contract: "tda_local_review_cas_v1", persistence: "ephemeral_base",
			draft_revision: null, draft_sha256: null, created_at: null, updated_at: null });
		await bridge.saveLocalReview(sourceId, runId, ephemeral, "draft", ephemeral.segments, signal());
		expect(JSON.parse(String(transport.mock.calls[1][1]?.body)).expected).toEqual({ persistence: "ephemeral_base", base_transcript_sha256: transcriptSha });
		await expect(bridge.saveLocalReview(sourceId, runId, parseLocalReview(rawReview()), "draft", baseline.segments, signal())).rejects.toMatchObject({ serverCode: "LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED" });
		expect(transport).toHaveBeenCalledTimes(2);
	});
	it("distinguishes a bounded warning projection from the factual total", () => {
		const raw = rawReview();
		raw.warnings = Array.from({ length: 1000 }, () => "WARNING");
		raw.review.warning_count = 5000;
		const summary = { total_count: 5000, displayed_count: 1000, truncated: true };
		Object.assign(raw, { warning_summary: summary });
		const parsed = parseLocalReview(raw);
		expect(parsed.review.warningCount).toBe(5000);
		expect(parsed.warningSummary).toEqual({ totalCount: 5000, displayedCount: 1000, truncated: true });
		summary.displayed_count = 999;
		expect(() => parseLocalReview(raw)).toThrow();
		expect(parseLocalReview(rawReview()).warningSummary).toBeUndefined();
	});
	it("parses sanitized source and completed-run metadata including legacy profiles", () => {
		const historical = rawReview();
		expect(parseLocalReview(historical).stats.durationSemantics).toBeUndefined();
		expect(parseLocalReview({ ...historical, stats: { ...historical.stats,
			duration_semantics: "session_extent_v1" } }).stats.durationSemantics).toBe("session_extent_v1");
		expect(
			parseLocalSources({
				schema_version: "tda_craig_sources_v1",
				sources: [
					{
						source_id: sourceId,
						source_sha256: sourceSha,
						recording_id: "recording",
						track_count: 2,
					},
				],
			}),
		).toEqual([
			{
				sourceId,
				sourceSha256: sourceSha,
				recordingId: "recording",
				trackCount: 2,
			},
		]);

		const parsedRuns = parseLocalRuns({
				schema_version: "tda_transcription_runs_v1",
				source_id: sourceId,
				runs: [
					{
						run_id: runId,
						status: "completed",
						source_id: sourceId,
						profile_id: "legacy-profile",
						engine: "faster-whisper",
						model: "large-v3",
						model_revision: null,
						device: "cuda",
						compute_type: "float16",
						alignment: "native",
						execution_lineage: {
							schema_version: "tda_execution_lineage_v1",
							companion_version: "0.3.14",
							runtime_family: "whisper",
							runtime_version: "1.1.5",
							device: "cuda",
							compute_type: "float16",
							gpu: {
								vendor: "NVIDIA",
								index: 0,
								model: "NVIDIA Test GPU",
								vram_total_bytes: 8589934592,
								compute_capability: "8.9",
								driver_version: "600.12",
							},
						},
						language: "pt",
						completed_at: "2026-09-21T00:00:00.000Z",
						transcript_sha256: transcriptSha,
						transcript_size_bytes: 1200,
						publication_target: {
			schema_version: "tda_publication_target_v1",
			campaign_slug: "yuhara-main",
			source_session_id: "sessao-00001",
			source_id: sourceId,
			run_id: runId,
			job_id: "job-review",
			attempt: 1,
			transcript_sha256: transcriptSha,
		},
						stats: {
							audio_work_seconds: 60,
							processing_seconds: 12,
							session_duration_seconds: 60,
							rtf: 0.2,
							word_count: 10,
							segment_count: 2,
							track_count: 1,
							turn_count: 8,
							deduplicated_segment_count: 1,
							warning_count: 3,
						},
					},
				],
			});
		expect(parsedRuns[0]).toMatchObject({
			runId,
			sourceId,
			profileId: "legacy-profile",
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
					vramTotalBytes: 8589934592,
					computeCapability: "8.9",
					driverVersion: "600.12",
				},
			},
			transcriptSha256: transcriptSha,
			publicationTarget: {
				campaignSlug: "yuhara-main",
				sourceSessionId: "sessao-00001",
				jobId: "job-review",
				attempt: 1,
			},
			stats: {
				audioWorkSeconds: 60,
				processingSeconds: 12,
				sessionDurationSeconds: 60,
				rtf: 0.2,
				wordCount: 10,
				segmentCount: 2,
				trackCount: 1,
				turnCount: 8,
				deduplicatedSegmentCount: 1,
				warningCount: 3,
			},
			review: null,
		});
	});

	it("parses lightweight review state and keeps unknown fail-safe", () => {
		const baseRun = {
			run_id: runId,
			status: "completed",
			source_id: sourceId,
			profile_id: "whisper-detailed",
			engine: "faster-whisper",
			model: "large-v3",
			model_revision: null,
			language: "pt",
			completed_at: "2026-09-21T00:00:00.000Z",
			transcript_sha256: transcriptSha,
			transcript_size_bytes: 1200,
			stats: {},
		};
		const known = parseLocalRuns({
			schema_version: "tda_transcription_runs_v1",
			source_id: sourceId,
			runs: [
				{
					...baseRun,
					review: {
						status: "approved_local",
						draft_revision: 4,
						review_percent: 87.5,
						updated_at: "2026-09-25T10:30:00.000Z",
					},
				},
			],
		});
		expect(known[0]?.review).toEqual({
			status: "approved_local",
			draftRevision: 4,
			reviewPercent: 87.5,
			updatedAt: "2026-09-25T10:30:00.000Z",
		});

		const unknown = parseLocalRuns({
			schema_version: "tda_transcription_runs_v1",
			source_id: sourceId,
			runs: [
				{
					...baseRun,
					review: {
						status: "unknown",
						draft_revision: null,
						review_percent: null,
						updated_at: null,
					},
				},
			],
		});
		expect(unknown[0]?.review).toEqual({
			status: "unknown",
			draftRevision: null,
			reviewPercent: null,
			updatedAt: null,
		});

		expect(() =>
			parseLocalRuns({
				schema_version: "tda_transcription_runs_v1",
				source_id: sourceId,
				runs: [
					{
						...baseRun,
						review: {
							status: "approved_local",
							draft_revision: 4,
							review_percent: 101,
							updated_at: "2026-09-25T10:30:00.000Z",
						},
					},
				],
			}),
		).toThrow(BridgeError);
	});

	it("rejects a publication target that does not bind to the opened run", () => {
		const invalid = rawReview();
		invalid.publication_target.run_id = "run-other-a1";
		expect(() => parseLocalReview(invalid)).toThrow(BridgeError);
	});

	it("rejects review payloads that claim cloud sync or invalid track identity", () => {
		expect(() =>
			parseLocalReview({
				...rawReview(),
				sync: { status: "synchronized" },
			}),
		).toThrow(BridgeError);

		const invalid = rawReview();
		const first = invalid.segments[0];
		if (!first) throw new Error("fixture segment missing");
		first.track_number = 0;
		expect(() => parseLocalReview(invalid)).toThrow(BridgeError);
	});

	it("uses a dedicated review response budget above the 1 MiB generic limit", async () => {
		const segments = Array.from({ length: 12 }, (_, index) => ({
			track_number: 1,
			segment_id: `1-${index}`,
			start: index,
			end: index + 0.5,
			text: "x".repeat(95_000),
			speaker: "Alice",
			reviewed: false,
		}));
		const payload = rawReview(segments);
		const encoded = JSON.stringify(payload);
		expect(new TextEncoder().encode(encoded).byteLength).toBeGreaterThan(1024 * 1024);

		const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(payload));
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		const review = await bridge.localReview(sourceId, runId, signal());

		expect(review.segments).toHaveLength(12);
		expect(review.segments[0].text).toHaveLength(95_000);
		expect(request).toHaveBeenCalledWith(
			`http://127.0.0.1:8765/api/v1/sources/${sourceId}/runs/${runId}/review`,
			expect.objectContaining({ method: "GET" }),
		);
	});

	it("saves review JSON larger than the normal 4096-byte command budget without changing that budget", async () => {
		const rawSegments = Array.from({ length: 8 }, (_, index) => ({
			track_number: 1,
			segment_id: `1-${index}`,
			start: index,
			end: index + 0.5,
			text: `Trecho ${index} ${"z".repeat(900)}`,
			speaker: "Alice",
			reviewed: index % 2 === 0,
		}));
		const response = rawReview(rawSegments);
		response.draft_revision = 1;
		const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		const segments: LocalReviewSegment[] = rawSegments.map((item) => ({
			trackNumber: item.track_number,
			segmentId: item.segment_id,
			start: item.start,
			end: item.end,
			text: item.text,
			speaker: item.speaker,
			reviewed: item.reviewed,
		}));

		await bridge.saveLocalReview(
			sourceId,
			runId,
			parseLocalReview({ ...rawReview(), snapshot_contract: "tda_local_review_cas_v1", persistence: "persisted" }),
			"reviewed",
			segments,
			signal(),
		);

		const [, init] = request.mock.calls[0];
		if (!init) throw new Error("missing review request init");
		expect(init).toMatchObject({
			method: "POST",
			credentials: "omit",
			cache: "no-store",
			redirect: "error",
		});
		expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
			"application/json",
		);
		const bodyBytes = new TextEncoder().encode(String(init.body)).byteLength;
		expect(bodyBytes).toBeGreaterThan(LOCAL_JSON_BODY_MAX_BYTES);
		expect(LOCAL_JSON_BODY_MAX_BYTES).toBe(4096);
	});

	it("loads the source catalog and run metadata without requesting transcript review", async () => {
		const request = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(
				Response.json({
					schema_version: "tda_craig_sources_v1",
					sources: [
						{
							source_id: sourceId,
							source_sha256: sourceSha,
							recording_id: null,
							track_count: 1,
						},
					],
				}),
			)
			.mockResolvedValueOnce(
				Response.json({
					schema_version: "tda_transcription_runs_v1",
					source_id: sourceId,
					runs: [
						{
							run_id: runId,
							status: "completed",
							source_id: sourceId,
							profile_id: "whisper-detailed",
							engine: "faster-whisper",
							model: "large-v3",
							model_revision: "rev",
							language: "pt",
							completed_at: "2026-09-21T00:00:00.000Z",
							transcript_sha256: transcriptSha,
							transcript_size_bytes: 900,
							stats: {},
						},
					],
				}),
			);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		await bridge.localSources(signal());
		await bridge.localRuns(sourceId, signal());

		expect(request).toHaveBeenCalledTimes(2);
		expect(request.mock.calls.map(([url]) => String(url))).toEqual([
			"http://127.0.0.1:8765/api/v1/sources",
			`http://127.0.0.1:8765/api/v1/sources/${sourceId}/runs`,
		]);
		expect(
			request.mock.calls.some(([url]) => String(url).endsWith("/review")),
		).toBe(false);
	});
});
