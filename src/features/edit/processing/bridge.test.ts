import { describe, expect, it, vi } from "vitest";
import { LocalBridge } from "./bridge";
import {
	LOCAL_API,
	parseCapabilities,
	parseJob,
	parseJobActivity,
	parseJobEventPage,
	parseJobEvents,
	parseJobs,
	parsePreparationStatus,
	parseResultSummary,
} from "./protocol";
import {
	craigTranscriptionRequestByteLength,
	LOCAL_JSON_BODY_MAX_BYTES,
} from "./request-budget";
const signal = () => new AbortController().signal;
const token = "synthetic_test_token_12345678901234567890";
const job = {
	id: "test-job",
	kind: "synthetic.fixture",
	status: "running",
	stage: "fixture",
	progress: { completed: 1, total: 3, unit: "items" },
	error: null,
	result_available: false,
	updated_at: "2026-09-07T12:00:00Z",
};
describe("processing protocol contract", () => {
	it("accepts the Agent's full 96-character worker event code budget", () => {
		const code = "A".repeat(96);
		expect(
			parseJobEvents({
				events: [
					{
						seq: 1,
						attempt: 2,
						code,
						at: "2026-09-19T12:00:00Z",
						level: "info",
						data: {},
					},
				],
			})[0],
		).toMatchObject({ code, attempt: 2 });
	});

	it("parses paginated event metadata and normalizes legacy descending pages", () => {
		const modern = parseJobEventPage({
			events: [
				{ seq: 10, code: "A", at: "2026-09-19T12:00:00Z", level: "info", data: {} },
				{ seq: 11, code: "B", at: "2026-09-19T12:00:01Z", level: "info", data: {} },
			],
			has_more: true,
			next_after_seq: 11,
			next_before_seq: 10,
		});
		expect(modern).toMatchObject({
			hasMore: true,
			nextAfterSeq: 11,
			nextBeforeSeq: 10,
		});
		expect(modern.events.map((event) => event.seq)).toEqual([10, 11]);

		const legacy = parseJobEventPage({
			events: [
				{ seq: 2, code: "B", at: "2026-09-19T12:00:01Z", level: "info", data: {} },
				{ seq: 1, code: "A", at: "2026-09-19T12:00:00Z", level: "info", data: {} },
			],
		});
		expect(legacy.events.map((event) => event.seq)).toEqual([1, 2]);
		expect(legacy.hasMore).toBe(false);
	});

	it("parses bounded authoritative job activity and rejects ambiguous identities", () => {
		const activity = parseJobActivity({
			schema_version: "tda_job_activity_v1",
			attempt: 2,
			metrics: [
				{
					track: 1,
					metric: "qwen_windows_completed",
					value: 250,
					updated_at: "2026-09-26T20:00:00Z",
				},
				{
					track: null,
					metric: "model_downloaded_bytes",
					value: 25,
					updated_at: "2026-09-26T20:00:01Z",
				},
			],
		});
		expect(activity).toEqual({
			schemaVersion: "tda_job_activity_v1",
			attempt: 2,
			metrics: [
				{
					track: 1,
					metric: "qwen_windows_completed",
					value: 250,
					updatedAt: "2026-09-26T20:00:00Z",
				},
				{
					track: null,
					metric: "model_downloaded_bytes",
					value: 25,
					updatedAt: "2026-09-26T20:00:01Z",
				},
			],
		});

		for (const invalid of [
			{
				schema_version: "tda_job_activity_v1",
				attempt: 0,
				metrics: [],
			},
			{
				schema_version: "tda_job_activity_v1",
				attempt: 1,
				metrics: [
					{
						track: null,
						metric: "qwen_windows_completed",
						value: 1,
						updated_at: "2026-09-26T20:00:00Z",
					},
				],
			},
			{
				schema_version: "tda_job_activity_v1",
				attempt: 1,
				metrics: [
					{
						track: 1,
						metric: "model_downloaded_bytes",
						value: 1,
						updated_at: "2026-09-26T20:00:00Z",
					},
				],
			},
			{
				schema_version: "tda_job_activity_v1",
				attempt: 1,
				metrics: [
					{
						track: 1,
						metric: "whisper_segments_completed",
						value: 10,
						updated_at: "2026-09-26T20:00:00Z",
					},
					{
						track: 1,
						metric: "whisper_segments_completed",
						value: 11,
						updated_at: "2026-09-26T20:00:01Z",
					},
				],
			},
		])
			expect(() => parseJobActivity(invalid)).toThrow();
	});

	it("keeps legacy/job-level event attempt nullable and rejects invalid attempts", () => {
		expect(
			parseJobEvents({
				events: [
					{
						seq: 1,
						code: "QUEUED",
						at: "2026-09-19T12:00:00Z",
						level: "info",
						data: {},
					},
					{
						seq: 2,
						attempt: null,
						code: "DUPLICATE_SUBMISSION_REUSED",
						at: "2026-09-19T12:00:01Z",
						level: "info",
						data: {},
					},
				],
			}).map((event) => event.attempt),
		).toEqual([null, null]);

		for (const attempt of [0, -1, 1.5, true]) {
			expect(() =>
				parseJobEvents({
					events: [
						{
							seq: 1,
							attempt,
							code: "RUNNING",
							at: "2026-09-19T12:00:00Z",
							level: "info",
							data: {},
						},
					],
				}),
			).toThrow();
		}
	});
});

describe("loopback bridge", () => {
	it("keeps credentials off health and only sends bearer to fixed loopback", async () => {
		const request = vi
			.fn<typeof fetch>()
			.mockImplementation(async (url) =>
				Response.json(
					String(url).endsWith("/health")
						? { api_version: "1", service_version: "0.1.0", lifecycle: "ready" }
						: job,
				),
			);
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		await bridge.health(signal());
		await bridge.synthetic("safe-key", signal());
		expect(request.mock.calls[0][1]?.headers).not.toHaveProperty(
			"Authorization",
		);
		const [url, options] = request.mock.calls[1];
		expect(url).toBe(`${LOCAL_API}/jobs`);
		expect(options).toMatchObject({
			method: "POST",
			credentials: "omit",
			redirect: "error",
			referrerPolicy: "no-referrer",
			cache: "no-store",
			mode: "cors",
			headers: {
				Authorization: `Bearer ${token}`,
				"Idempotency-Key": "safe-key",
				"Content-Type": "application/json",
			},
		});
		expect(JSON.parse(String(options?.body))).toEqual({
			kind: "synthetic.fixture",
			campaign_id: "synthetic-campaign",
			session_id: "synthetic-session",
			source_id: "synthetic-source",
			units: 3,
		});
		bridge.disconnect();
		await expect(bridge.jobs(signal())).rejects.toMatchObject({
			code: "unauthorized",
		});
		expect(request).toHaveBeenCalledTimes(2);
	});
	it("bootstraps an ephemeral browser credential without a copied master token", async () => {
		const sessionToken = "browser_session_token_123456789012345678901234";
		const request = vi.fn<typeof fetch>().mockImplementation(async (url) => {
			const value = String(url);
			if (value.endsWith("/health"))
				return Response.json({
					api_version: "1",
					service_version: "0.3.14",
					lifecycle: "ready",
				});
			if (value.endsWith("/session"))
				return Response.json({
					schema: "tda_loopback_session_v1",
					token: sessionToken,
					expires_in_seconds: 28_800,
				});
			return Response.json({ jobs: [] });
		});
		const bridge = new LocalBridge(request);

		await bridge.bootstrap(signal());
		await bridge.jobs(signal());

		expect(request).toHaveBeenCalledTimes(3);
		expect(request.mock.calls[0][1]?.headers).not.toHaveProperty("Authorization");
		expect(request.mock.calls[1][1]?.headers).not.toHaveProperty("Authorization");
		expect(request.mock.calls[1][0]).toBe(`${LOCAL_API}/session`);
		expect(request.mock.calls[2][1]?.headers).toMatchObject({
			Authorization: `Bearer ${sessionToken}`,
		});
	});

	it("renews an expired browser session and retries with the replacement bearer", async () => {
		const firstToken = "browser_session_token_111111111111111111111111";
		const secondToken = "browser_session_token_22222222222222222222222";
		let sessionCount = 0;
		let jobsCount = 0;
		const request = vi.fn<typeof fetch>().mockImplementation(async (url) => {
			const value = String(url);
			if (value.endsWith("/health"))
				return Response.json({
					api_version: "1",
					service_version: "0.3.14",
					lifecycle: "ready",
				});
			if (value.endsWith("/session")) {
				sessionCount += 1;
				return Response.json({
					schema: "tda_loopback_session_v1",
					token: sessionCount === 1 ? firstToken : secondToken,
					expires_in_seconds: 28_800,
				});
			}
			if (value.endsWith("/jobs")) {
				jobsCount += 1;
				if (jobsCount === 1)
					return Response.json(
						{ error: { code: "SESSION_EXPIRED", recoverable: true } },
						{ status: 401 },
					);
				return Response.json({ jobs: [] });
			}
			throw new Error("unexpected request");
		});
		const bridge = new LocalBridge(request);

		await bridge.bootstrap(signal());
		const jobs = await bridge.jobs(signal());

		expect(jobs).toEqual([]);
		expect(sessionCount).toBe(2);
		expect(jobsCount).toBe(2);
		const retriedJobs = request.mock.calls.at(-1);
		expect(retriedJobs?.[1]?.headers).toMatchObject({
			Authorization: `Bearer ${secondToken}`,
		});
	});

	it("renews an expired browser session before retrying a Craig upload", async () => {
		const firstToken = "browser_session_token_333333333333333333333333";
		const secondToken = "browser_session_token_44444444444444444444444";
		let sessionCount = 0;
		let uploadCount = 0;
		const sourceId = `craig-${"a".repeat(64)}`;
		const request = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
			const value = String(url);
			if (value.endsWith("/health"))
				return Response.json({
					api_version: "1",
					service_version: "0.3.14",
					lifecycle: "ready",
				});
			if (value.endsWith("/session")) {
				sessionCount += 1;
				return Response.json({
					schema: "tda_loopback_session_v1",
					token: sessionCount === 1 ? firstToken : secondToken,
					expires_in_seconds: 28_800,
				});
			}
			if (value.endsWith("/sources/craig")) {
				uploadCount += 1;
				if (uploadCount === 1)
					return Response.json(
						{ error: { code: "SESSION_EXPIRED", recoverable: true } },
						{ status: 401 },
					);
				expect(init?.headers).toMatchObject({
					Authorization: `Bearer ${secondToken}`,
				});
				return Response.json({
					schema_version: "tda_craig_ingest_v1",
					source_id: sourceId,
					source_sha256: "a".repeat(64),
					size_bytes: 3,
					track_count: 1,
					reused: false,
					source_name: "session.zip",
				});
			}
			throw new Error("unexpected request");
		});
		const bridge = new LocalBridge(request);

		await bridge.bootstrap(signal());
		const staged = await bridge.craigSource(
			new File([new Uint8Array([1, 2, 3])], "session.zip", {
				type: "application/zip",
			}),
			signal(),
		);

		expect(staged.sourceId).toBe(sourceId);
		expect(sessionCount).toBe(2);
		expect(uploadCount).toBe(2);
	});

	it("reports the detected and minimum version before requesting a session from Companion 0.3.13", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json({
				api_version: "1",
				service_version: "0.3.13",
				lifecycle: "ready",
			}),
		);
		const bridge = new LocalBridge(request);

		await expect(bridge.bootstrap(signal())).rejects.toMatchObject({
			code: "version_incompatible",
			details: {
				detectedServiceVersion: "0.3.13",
				minimumServiceVersion: "0.3.14",
			},
		});
		expect(request).toHaveBeenCalledTimes(1);
		expect(request.mock.calls[0][0]).toBe(`${LOCAL_API}/health`);
	});

	it("rejects a malformed health contract separately from a valid incompatible API", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(
				Response.json({
					service_version: "0.3.14",
					lifecycle: "ready",
				}),
			),
		);

		await expect(bridge.bootstrap(signal())).rejects.toMatchObject({
			code: "invalid_response",
		});
	});

	it("distinguishes an incompatible API from an old Companion version", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(
				Response.json({
					api_version: "2",
					service_version: "0.3.99",
					lifecycle: "ready",
				}),
			),
		);

		await expect(bridge.bootstrap(signal())).rejects.toMatchObject({
			code: "api_incompatible",
			details: {
				detectedApiVersion: "2",
				requiredApiVersion: "1",
			},
		});
	});

	it("distinguishes a missing browser-session contract after compatible health", async () => {
		const request = vi.fn<typeof fetch>().mockImplementation(async (url) =>
			String(url).endsWith("/health")
				? Response.json({
						api_version: "1",
						service_version: "0.3.14",
						lifecycle: "ready",
					})
				: Response.json({ schema: "legacy_pairing_v1" }),
		);
		const bridge = new LocalBridge(request);

		await expect(bridge.bootstrap(signal())).rejects.toMatchObject({
			code: "session_incompatible",
			details: {
				detectedServiceVersion: "0.3.14",
				minimumServiceVersion: "0.3.14",
			},
		});
	});

	it("rejects an oversized UTF-8 Craig request before sending credentials or bytes", async () => {
		const request = vi.fn<typeof fetch>();
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		const input = {
			campaignId: "yuhara-main",
			sessionId: "sessao-42",
			sourceId: `craig-${"a".repeat(64)}`,
			profileId: "qwen-quality" as const,
			glossary: "",
			context: "",
		};
		const emptyBytes = craigTranscriptionRequestByteLength(input);
		const available = LOCAL_JSON_BODY_MAX_BYTES - emptyBytes;
		const context = `${"😀".repeat(Math.floor(available / 4))}${"a".repeat(
			available % 4,
		)}a`;
		const oversized = { ...input, context };
		expect(craigTranscriptionRequestByteLength(oversized)).toBe(
			LOCAL_JSON_BODY_MAX_BYTES + 1,
		);

		await expect(
			bridge.transcription(oversized, "utf8-budget", signal()),
		).rejects.toMatchObject({ code: "payload_too_large" });
		expect(request).not.toHaveBeenCalled();
		bridge.disconnect();
	});

	it("starts and observes Agent-owned profile preparation", async () => {
		const sourceId = `craig-${"a".repeat(64)}`;
		const preparation = {
			schema: "tda_profile_preparation_v1",
			state: "running",
			active: true,
			operation_id: "op123",
			source_id: sourceId,
			profile_id: "qwen-quality",
			engine: "qwen3",
			stage: "qwen_probe",
			title: "Verificando CUDA e runtime…",
			detail: "Validação local.",
			sequence: 2,
			elapsed_seconds: 1.5,
			error_code: null,
		};
		const request = vi.fn<typeof fetch>().mockImplementation(async () =>
			Response.json(preparation),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		const started = await bridge.prepareProfile(
			sourceId,
			"qwen-quality",
			signal(),
		);
		const observed = await bridge.preparation(signal());

		expect(started).toMatchObject({
			state: "running",
			profileId: "qwen-quality",
			stage: "qwen_probe",
		});
		expect(observed.operationId).toBe("op123");
		expect(request.mock.calls[0][0]).toBe(`${LOCAL_API}/preparation`);
		expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
			source_id: sourceId,
			profile_id: "qwen-quality",
		});
		expect(request.mock.calls[1][1]?.method).toBe("GET");
		bridge.disconnect();
	});

	it("sends bounded event cursors without putting them in the path identity", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json({
				events: [
					{ seq: 42, code: "TRACK_COMPLETED", at: "2026-09-19T12:00:00Z", level: "info", data: {} },
				],
				has_more: false,
				next_after_seq: 42,
				next_before_seq: 42,
			}),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		const page = await bridge.events("test-job", signal(), {
			afterSeq: 41,
			limit: 200,
		});

		expect(page.events[0]?.seq).toBe(42);
		expect(request.mock.calls[0][0]).toBe(
			`${LOCAL_API}/jobs/test-job/events?after_seq=41&limit=200`,
		);
		bridge.disconnect();
	});

	it("reads authoritative activity through the authenticated local bridge", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json({
				schema_version: "tda_job_activity_v1",
				attempt: 2,
				metrics: [
					{
						track: 3,
						metric: "whisper_segments_completed",
						value: 97,
						updated_at: "2026-09-26T20:00:00Z",
					},
				],
			}),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		const activity = await bridge.activity("test-job", signal(), 2);

		expect(activity.attempt).toBe(2);
		expect(activity.metrics[0]).toMatchObject({
			track: 3,
			metric: "whisper_segments_completed",
			value: 97,
		});
		expect(request.mock.calls[0][0]).toBe(
			`${LOCAL_API}/jobs/test-job/activity?attempt=2`,
		);
		expect(request.mock.calls[0][1]?.method).toBe("GET");
		await expect(
			bridge.activity("test-job", signal(), 0),
		).rejects.toMatchObject({ code: "invalid_response" });
		expect(request).toHaveBeenCalledTimes(1);
		bridge.disconnect();
	});

	it("deletes a terminal job through the authenticated local action endpoint", async () => {
		const request = vi.fn<typeof fetch>().mockResolvedValue(
			Response.json({ deleted: true, id: "test-job" }),
		);
		const bridge = new LocalBridge(request);
		bridge.pair(token);

		await bridge.deleteJob("test-job", signal());

		expect(request).toHaveBeenCalledTimes(1);
		const [url, options] = request.mock.calls[0];
		expect(url).toBe(`${LOCAL_API}/jobs/test-job/delete`);
		expect(options).toMatchObject({
			method: "POST",
			credentials: "omit",
			redirect: "error",
			referrerPolicy: "no-referrer",
			cache: "no-store",
			mode: "cors",
			headers: {
				Accept: "application/json",
				Authorization: `Bearer ${token}`,
				"Content-Type": "application/json",
			},
			body: "{}",
		});
		bridge.disconnect();
	});

	it("rejects path injection without a request", async () => {
		const request = vi.fn<typeof fetch>();
		const bridge = new LocalBridge(request);
		bridge.pair(token);
		for (const id of [
			"../health",
			"http://evil.test",
			"job?secret=1",
			"%2fhealth",
		])
			await expect(bridge.job(id, signal())).rejects.toMatchObject({
				code: "invalid_response",
			});
		expect(request).not.toHaveBeenCalled();
	});
	it.each([
		[401, "unauthorized"],
		[403, "forbidden"],
		[409, "conflict"],
		[500, "service_error"],
	])("maps HTTP %s without exposing content", async (status, code) => {
		const bridge = new LocalBridge(
			vi
				.fn<typeof fetch>()
				.mockResolvedValue(
					new Response("private diagnostic", { status: Number(status) }),
				),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code,
			message: code,
		});
	});
	it("does not guess network failures are an offline PC", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code: "unreachable",
		});
	});
	it.each([
		new Response("<html>error</html>"),
		Response.json({ api_version: "2" }),
		new Response("{broken", {
			headers: { "content-type": "application/json" },
		}),
	])("rejects malformed or incompatible services", async (response) => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(response),
		);
		await expect(bridge.health(signal())).rejects.toThrow();
	});
	it("bounds chunked responses", async () => {
		const bridge = new LocalBridge(
			vi.fn<typeof fetch>().mockResolvedValue(
				new Response(" ".repeat(1024 * 1024 + 1), {
					headers: { "content-type": "application/json" },
				}),
			),
		);
		await expect(bridge.health(signal())).rejects.toMatchObject({
			code: "invalid_response",
		});
	});
});
describe("preparation wire validation", () => {
	it("fences a ready Qwen profile when the physical gate still reports runtime 1.0.11", () => {
		const capabilities = parseCapabilities({
			capabilities: ["transcription.craig", "transcription.prepare"],
			sync: false,
			device: { id: "device-1", label: "TDA local" },
			transcription: {
				profiles: ["qwen-quality"],
				catalog: [
					{
						id: "qwen-quality",
						engine: "qwen3",
						ready: true,
						preparation_required: false,
						reason: null,
					},
				],
				qwen_physical_gate: {
					"qwen-quality": {
						status: "ready",
						ready: true,
						profile_id: "qwen-quality",
						runtime_version: "1.0.11",
					},
				},
			},
		});

		expect(capabilities.transcription.profiles).toEqual([]);
		expect(capabilities.transcription.catalog[0]).toMatchObject({
			id: "qwen-quality",
			ready: false,
			preparationRequired: false,
			reason: "QWEN_RUNTIME_ALIGNMENT_UPGRADE_REQUIRED",
		});
	});

	it("keeps Qwen ready when the physical gate reports owned-overflow recovery runtime 1.0.12+", () => {
		const capabilities = parseCapabilities({
			capabilities: ["transcription.craig"],
			sync: false,
			device: { id: "device-1", label: "TDA local" },
			transcription: {
				profiles: ["qwen-fast"],
				catalog: [
					{
						id: "qwen-fast",
						engine: "qwen3",
						ready: true,
						preparation_required: false,
						reason: null,
					},
				],
				qwen_physical_gate: {
					"qwen-fast": {
						status: "ready",
						ready: true,
						profile_id: "qwen-fast",
						runtime_version: "1.0.12",
					},
				},
			},
		});

		expect(capabilities.transcription.profiles).toEqual(["qwen-fast"]);
		expect(capabilities.transcription.catalog[0]?.ready).toBe(true);
	});

	it("rejects an impossible ready Qwen gate without a runtime identity", () => {
		expect(() =>
			parseCapabilities({
				capabilities: ["transcription.craig"],
				sync: false,
				device: { id: "device-1", label: "TDA local" },
				transcription: {
					profiles: ["qwen-fast"],
					qwen_physical_gate: {
						"qwen-fast": {
							status: "ready",
							ready: true,
							profile_id: "qwen-fast",
						},
					},
				},
			}),
		).toThrow();
	});

	it("parses the full profile catalog and preparation status", () => {
		const capabilities = parseCapabilities({
			capabilities: ["transcription.prepare"],
			sync: false,
			device: { id: "device-1", label: "TDA local" },
			transcription: {
				profiles: [],
				catalog: [
					{
						id: "qwen-quality",
						engine: "qwen3",
						ready: false,
						preparation_required: true,
						reason: "QWEN_RUNTIME_REQUIRED",
					},
				],
			},
		});
		expect(capabilities.transcription.catalog[0]).toMatchObject({
			id: "qwen-quality",
			ready: false,
			preparationRequired: true,
		});

		expect(
			parsePreparationStatus({
				schema: "tda_profile_preparation_v1",
				state: "completed",
				active: false,
				operation_id: "op123",
				source_id: `craig-${"a".repeat(64)}`,
				profile_id: "qwen-quality",
				engine: "qwen3",
				stage: "complete",
				title: "Preparação concluída.",
				detail: "Pronto.",
				sequence: 8,
				elapsed_seconds: 42.5,
				error_code: null,
			}),
		).toMatchObject({
			state: "completed",
			profileId: "qwen-quality",
			elapsedSeconds: 42.5,
		});
	});
});

describe("wire validation", () => {
	it.each([
		{ completed: 4, total: 3, unit: "items" },
		{ completed: -1, total: 3, unit: "items" },
		{ completed: 0, total: 0, unit: "items" },
		{ completed: 0, total: Infinity, unit: "items" },
	])("rejects impossible progress", (progress) => {
		expect(() => parseJob({ ...job, progress })).toThrow();
	});
	it("accepts unknown progress and rejects duplicate identities", () => {
		expect(parseJob({ ...job, progress: null }).progress).toBeNull();
		expect(() => parseJobs({ jobs: [job, job] })).toThrow();
	});
	it("retains immutable run identity for transcription results", () => {
		const value = {
			schema_version: "tda_local_result_v1",
			campaign_id: "campaign",
			session_id: "session",
			source_id: "source",
			job_id: "job-transcription",
			transcription: {
				schema_version: "tda_transcript_v1",
				profile_id: "qwen-quality",
				artifact: "transcript.json",
				run_id: "run-job-transcription-a2",
				sha256: "b".repeat(64),
			},
			sync: { status: "not_configured" },
		};
		expect(parseResultSummary(value, "job-transcription")).toEqual({
			campaignId: "campaign",
			sessionId: "session",
			sourceId: "source",
			jobId: "job-transcription",
			publicationId: "b".repeat(64),
			profileId: "qwen-quality",
			transcriptSha256: "b".repeat(64),
			runId: "run-job-transcription-a2",
		});
		expect(() =>
			parseResultSummary(
				{
					...value,
					transcription: { ...value.transcription, run_id: "../outside" },
				},
				"job-transcription",
			),
		).toThrow();
	});

	it("retains only result identity bound to the requested job", () => {
		const value = {
			schema_version: "tda_local_result_v1",
			campaign_id: "synthetic-campaign",
			session_id: "synthetic-session",
			source_id: "synthetic-source",
			job_id: "test-job",
			publication_bundle: {
				schema_version: "publication_bundle_v1",
				publication_id: "a".repeat(64),
				recap: "synthetic recap",
			},
			sync: { status: "not_configured" },
		};
		expect(parseResultSummary(value, "test-job")).toEqual({
			campaignId: "synthetic-campaign",
			sessionId: "synthetic-session",
			sourceId: "synthetic-source",
			jobId: "test-job",
			publicationId: "a".repeat(64),
		});
		expect(() => parseResultSummary(value, "other-job")).toThrow();
		expect(() =>
			parseResultSummary(
				{ ...value, sync: { status: "confirmed" } },
				"test-job",
			),
		).toThrow();
	});
});
