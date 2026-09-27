import type { Page, Route } from "@playwright/test";

export const LOCAL_API = "http://127.0.0.1:8765/api/v1";
export const UI_ORIGIN = "http://127.0.0.1:3102";
export const BROWSER_TOKEN = "browser_session_fixture_123456789012345678901234567890";

const sourceSha = "a".repeat(64);
export const CRAIG_SOURCE_ID = `craig-${sourceSha}`;
export const TRANSCRIPT_SHA = "b".repeat(64);

export type FixtureJobStatus =
	| "queued"
	| "running"
	| "succeeded"
	| "failed"
	| "cancelled"
	| "interrupted";

export type FixtureSystemGpu = {
	index: number;
	name: string;
	utilizationPercent: number | null;
	memoryUsedBytes: number | null;
	memoryTotalBytes: number | null;
};

export type FixtureSystemSnapshot = {
	sampledAt?: string;
	os?: string;
	cpuModel?: string | null;
	cpuPercent?: number | null;
	memoryUsedBytes?: number | null;
	memoryTotalBytes?: number | null;
	memoryPercent?: number | null;
	gpus?: FixtureSystemGpu[];
};

export type CompanionFixtureOptions = {
	apiVersion?: string;
	serviceVersion?: string;
	lifecycle?: "preparing" | "ready" | "paused";
	initialJobs?: Record<string, unknown>[];
	jobEvents?: Record<string, unknown>[];
	expireBrowserSessionOnce?: boolean;
	profileReady?: boolean;
	reviewEnabled?: boolean;
	qwenRuntimeVersion?: string;
	advanceJobs?: boolean;
	ambiguousJobPostOnce?: boolean;
	jobReadDelayMs?: number;
	system?: FixtureSystemSnapshot;
};

export type CompanionFixtureState = {
	requests: { method: string; path: string; authorization?: string; idempotencyKey?: string }[];
	sessionCount: number;
	uploadCount: number;
	jobPostCount: number;
	preparationPostCount: number;
	idempotencyKeys: string[];
	jobStatusesServed: string[];
	job: Record<string, unknown> | null;
	setJob(job: Record<string, unknown> | null): void;
	setLifecycle(value: "preparing" | "ready" | "paused"): void;
	setSystem(value: FixtureSystemSnapshot | undefined): void;
};

export function fixtureJob(
	status: FixtureJobStatus,
	overrides: Record<string, unknown> = {},
): Record<string, unknown> {
	const terminal = status === "succeeded";
	return {
		id: "craig-job-1",
		kind: "transcription.craig",
		status,
		stage:
			status === "queued"
				? "queued"
				: status === "running"
					? "transcription"
					: status,
		progress:
			status === "queued"
				? { completed: 0, total: 2, unit: "tracks" }
				: status === "running"
					? { completed: 1, total: 2, unit: "tracks" }
					: { completed: 2, total: 2, unit: "tracks" },
		error: null,
		result_available: terminal,
		updated_at: "2026-09-20T18:00:00Z",
		attempt: 1,
		context: {
			campaign_id: "yuhara-main",
			session_id: "sessao-42",
			source_id: CRAIG_SOURCE_ID,
			profile_id: "qwen-quality",
		},
		...overrides,
	};
}

function json(route: Route, value: unknown, status = 200) {
	return route.fulfill({
		status,
		headers: {
			"Access-Control-Allow-Origin": UI_ORIGIN,
			"Content-Type": "application/json",
			"Cache-Control": "no-store",
		},
		body: JSON.stringify(value),
	});
}


function invalidRequest(route: Route, code = "INVALID_REQUEST") {
	return json(route, { error: { code, recoverable: false } }, 422);
}

function exactObject(
	value: unknown,
	expected: Readonly<Record<string, unknown>>,
): boolean {
	if (!value || typeof value !== "object" || Array.isArray(value)) return false;
	const row = value as Record<string, unknown>;
	const expectedKeys = Object.keys(expected).sort();
	const actualKeys = Object.keys(row).sort();
	if (JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) return false;
	return expectedKeys.every((key) => row[key] === expected[key]);
}

export async function installCompanionFixture(
	page: Page,
	options: CompanionFixtureOptions = {},
): Promise<CompanionFixtureState> {
	let lifecycle = options.lifecycle ?? "ready";
	const additionalJobs = (options.initialJobs ?? []).slice(1);
	let systemState = options.system;
	let prepared = options.profileReady ?? false;
	const qwenRuntimeVersion = options.qwenRuntimeVersion ?? "1.0.12";
	let preparationReads = 0;
	let preparationStarted = false;
	let jobsReads = 0;
	let jobsGetCount = 0;
	let expired = false;
	let ambiguousJobPostConsumed = false;
	let submittedJob = false;
	const state: CompanionFixtureState = {
		requests: [],
		sessionCount: 0,
		uploadCount: 0,
		jobPostCount: 0,
		preparationPostCount: 0,
		idempotencyKeys: [],
		jobStatusesServed: [],
		job: options.initialJobs?.[0] ?? null,
		setJob(value) {
			state.job = value;
			jobsReads = 0;
		},
		setLifecycle(value) {
			lifecycle = value;
		},
		setSystem(value) {
			systemState = value;
		},
	};

	await page.route(`${LOCAL_API}/**`, async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname.replace("/api/v1", "") || "/";
		const authorization = request.headers().authorization;
		const idempotencyKey = request.headers()["idempotency-key"];
		state.requests.push({
			method: request.method(),
			path,
			...(authorization ? { authorization } : {}),
			...(idempotencyKey ? { idempotencyKey } : {}),
		});

		if (path === "/health") {
			return json(route, {
				api_version: options.apiVersion ?? "1",
				service_version: options.serviceVersion ?? "0.3.14",
				lifecycle,
			});
		}
		if (path === "/session" && request.method() === "POST") {
			state.sessionCount += 1;
			return json(route, {
				schema: "tda_loopback_session_v1",
				token: BROWSER_TOKEN,
				expires_in_seconds: 300,
			});
		}

		if (
			options.expireBrowserSessionOnce &&
			!expired &&
			path === "/capabilities" &&
			authorization === `Bearer ${BROWSER_TOKEN}`
		) {
			expired = true;
			return json(
				route,
				{ error: { code: "UNAUTHORIZED", recoverable: true } },
				401,
			);
		}

		if (!authorization?.startsWith("Bearer ")) {
			return json(
				route,
				{ error: { code: "UNAUTHORIZED", recoverable: false } },
				401,
			);
		}

		if (path === "/capabilities") {
			return json(route, {
				capabilities: [
					...(options.reviewEnabled ? ["transcription.review"] : []),
					"transcription.craig",
					"transcription.prepare",
					"transcription.prepare.cancel",
					"job.events",
					"system.telemetry",
				],
				sync: false,
				device: { id: "fixture-pc", label: "PC sintético" },
				transcription: {
					profiles: prepared ? ["qwen-quality"] : [],
					catalog: [
						{
							id: "qwen-quality",
							engine: "qwen3",
							ready: prepared,
							preparation_required: !prepared,
							reason: prepared ? null : "QWEN_PHYSICAL_ACCEPTANCE_REQUIRED",
						},
					],
					qwen_physical_gate: {
						"qwen-quality": prepared
							? {
									status: "ready",
									ready: true,
									profile_id: "qwen-quality",
									runtime_version: qwenRuntimeVersion,
								}
							: {
									status: "missing",
									ready: false,
									profile_id: "qwen-quality",
									reason: "QWEN_PHYSICAL_ACCEPTANCE_REQUIRED",
								},
					},
				},
			});
		}
		if (path === "/system") {
			const system = systemState;
			return json(route, {
				sampled_at: system?.sampledAt ?? "2026-09-20T18:00:00Z",
				host: {
					os: system?.os ?? "Windows 11",
					cpu: system?.cpuModel === undefined ? "Synthetic CPU" : system.cpuModel,
				},
				cpu: {
					utilization_percent:
						system?.cpuPercent === undefined ? 25 : system.cpuPercent,
				},
				memory: {
					used_bytes:
						system?.memoryUsedBytes === undefined
							? 8 * 1024 ** 3
							: system.memoryUsedBytes,
					total_bytes:
						system?.memoryTotalBytes === undefined
							? 32 * 1024 ** 3
							: system.memoryTotalBytes,
					percent:
						system?.memoryPercent === undefined ? 25 : system.memoryPercent,
				},
				gpus: (system?.gpus ?? []).map((gpu) => ({
					index: gpu.index,
					name: gpu.name,
					utilization_percent: gpu.utilizationPercent,
					memory_used_bytes: gpu.memoryUsedBytes,
					memory_total_bytes: gpu.memoryTotalBytes,
				})),
			});
		}
		if (path === "/sources" && request.method() === "GET") {
			return json(route, { schema_version: "tda_craig_sources_v1", sources: [] });
		}
		if (path === "/sources/craig" && request.method() === "POST") {
			const contentType = request.headers()["content-type"] ?? "";
			if (!contentType.startsWith("application/zip"))
				return json(
					route,
					{ error: { code: "CRAIG_ZIP_REQUIRED", recoverable: false } },
					415,
				);
			const body = request.postDataBuffer();
			if (!body || body.length === 0)
				return invalidRequest(route, "CRAIG_UPLOAD_EMPTY");
			state.uploadCount += 1;
			return json(route, {
				schema_version: "tda_craig_ingest_v1",
				source_id: CRAIG_SOURCE_ID,
				source_sha256: sourceSha,
				size_bytes: 2048,
				track_count: 2,
				reused: false,
			});
		}
		if (path === "/preparation" && request.method() === "POST") {
			let payload: unknown;
			try {
				payload = request.postDataJSON();
			} catch {
				return invalidRequest(route);
			}
			if (
				!exactObject(payload, {
					source_id: CRAIG_SOURCE_ID,
					profile_id: "qwen-quality",
				})
			)
				return invalidRequest(route);
			state.preparationPostCount += 1;
			preparationReads = 0;
			preparationStarted = true;
			return json(route, {
				schema: "tda_profile_preparation_v1",
				state: "running",
				active: true,
				operation_id: "c".repeat(32),
				source_id: CRAIG_SOURCE_ID,
				profile_id: "qwen-quality",
				engine: "qwen3",
				stage: "qwen_probe",
				title: "Validando Qwen",
				detail: "Fixture local",
				sequence: 1,
				elapsed_seconds: 0.1,
				error_code: null,
			});
		}
		if (path === "/preparation" && request.method() === "GET") {
			if (!preparationStarted) {
				return json(route, {
					schema: "tda_profile_preparation_v1",
					state: "idle",
					active: false,
					operation_id: null,
					source_id: null,
					profile_id: null,
					engine: null,
					stage: "idle",
					title: "Preparação inativa",
					detail: "",
					sequence: 0,
					elapsed_seconds: 0,
					error_code: null,
				});
			}
			preparationReads += 1;
			if (preparationReads >= 1) prepared = true;
			return json(route, {
				schema: "tda_profile_preparation_v1",
				state: "completed",
				active: false,
				operation_id: "c".repeat(32),
				source_id: CRAIG_SOURCE_ID,
				profile_id: "qwen-quality",
				engine: "qwen3",
				stage: "complete",
				title: "Qwen pronto",
				detail: "",
				sequence: 2,
				elapsed_seconds: 0.2,
				error_code: null,
			});
		}
		if (path === "/jobs" && request.method() === "POST") {
			let payload: unknown;
			try {
				payload = request.postDataJSON();
			} catch {
				return invalidRequest(route);
			}
			if (
				!idempotencyKey ||
				!/^[A-Za-z0-9_-]{1,128}$/u.test(idempotencyKey) ||
				!exactObject(payload, {
					kind: "transcription.craig",
					campaign_id: "yuhara-main",
					session_id: "sessao-42",
					source_id: CRAIG_SOURCE_ID,
					profile_id: "qwen-quality",
					glossary: "",
					context: "",
					cpu: false,
				})
			)
				return invalidRequest(route);
			state.jobPostCount += 1;
			state.idempotencyKeys.push(idempotencyKey);
			state.job = fixtureJob("queued");
			submittedJob = true;
			jobsReads = 0;
			if (options.ambiguousJobPostOnce && !ambiguousJobPostConsumed) {
				ambiguousJobPostConsumed = true;
				return route.abort("failed");
			}
			return json(route, state.job);
		}
		if (path === "/jobs" && request.method() === "GET") {
			jobsGetCount += 1;
			if (options.jobReadDelayMs && jobsGetCount > 1)
				await new Promise((resolve) =>
					setTimeout(resolve, options.jobReadDelayMs),
				);
			if (
				state.job &&
				submittedJob &&
				(options.advanceJobs ?? true)
			) {
				jobsReads += 1;
				if (jobsReads === 2) state.job = fixtureJob("running");
				else if (jobsReads >= 3) state.job = fixtureJob("succeeded");
			}
			const status = state.job?.status;
			if (typeof status === "string") state.jobStatusesServed.push(status);
			return json(route, {
				jobs: state.job
					? [
							state.job,
							...additionalJobs.filter(
								(job) => job.id !== state.job?.id,
							),
						]
					: additionalJobs,
			});
		}
		if (path === "/jobs/craig-job-1/events") {
			return json(route, {
				events:
					options.jobEvents ??
					(state.job?.status === "running"
						? [
								{
									seq: 2,
									code: "QWEN_WINDOW_TRANSCRIBED",
									at: "2026-09-20T18:00:01Z",
									level: "info",
									data: {
										track: 1,
										total_tracks: 2,
										speaker: "Alice",
										window: 1,
										start_seconds: 0,
										end_seconds: 30,
									},
								},
							]
						: []),
			});
		}
		if (path === "/jobs/craig-job-1/result") {
			return json(route, {
				schema_version: "tda_local_result_v1",
				campaign_id: "yuhara-main",
				session_id: "sessao-42",
				source_id: CRAIG_SOURCE_ID,
				job_id: "craig-job-1",
				transcription: {
					schema_version: "tda_transcript_v1",
					profile_id: "qwen-quality",
					artifact: "transcript.json",
					run_id: "run-craig-job-1-a1",
					sha256: TRANSCRIPT_SHA,
				},
				sync: { status: "not_configured" },
			});
		}
		if (
			path === "/jobs/craig-job-1/cancel" &&
			request.method() === "POST"
		) {
			state.job = fixtureJob("cancelled");
			return json(route, state.job);
		}
		if (
			path === "/jobs/craig-job-1/retry" &&
			request.method() === "POST"
		) {
			state.job = fixtureJob("queued", { attempt: 2 });
			jobsReads = 0;
			return json(route, state.job);
		}
		if (path === "/lifecycle" && request.method() === "POST") {
			const payload = request.postDataJSON() as { action?: string };
			lifecycle = payload.action === "pause" ? "paused" : "ready";
			return json(route, {
				api_version: "1",
				service_version: options.serviceVersion ?? "0.3.14",
				lifecycle,
			});
		}

		return json(
			route,
			{ error: { code: "FIXTURE_ROUTE_MISSING", recoverable: false } },
			404,
		);
	});

	return state;
}

export function failedJob(
	overrides: Record<string, unknown> = {},
): Record<string, unknown> {
	return fixtureJob("failed", {
		stage: "failed",
		progress: { completed: 1, total: 2, unit: "tracks" },
		error: { code: "QWEN_ALIGNMENT_REQUIRED", recoverable: true },
		result_available: false,
		...overrides,
	});
}
