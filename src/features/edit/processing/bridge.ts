import {
	AUTOMATIC_LOOPBACK_SESSION_MINIMUM_VERSION,
	supportsAutomaticLoopbackSession,
} from "./compatibility";
import {
	BridgeError,
	type LocalReview,
	type CraigTranscriptionInput,
	type LocalReviewSegment,
	type LocalReviewStatus,
	identifier,
	LOCAL_API,
	parseCapabilities,
	parseCraigSource,
	parseHealth,
	parseJob,
	parseJobActivity,
	parsePreparationStatus,
	record,
	text,
	parseJobEventPage,
	parseJobListPage,
	parseJobs,
	parseLocalReview,
	parseLocalRuns,
	parseLocalSources,
	parseResultSummary,
	parseSystemSnapshot,
	runIdentifier,
} from "./protocol";
import {
	buildCraigTranscriptionRequest,
	LOCAL_JSON_BODY_MAX_BYTES,
	serializedJsonBody,
} from "./request-budget";

const LOCAL_REVIEW_BODY_MAX_BYTES = 32 * 1024 * 1024;

type PairingMode = "none" | "legacy" | "browser";

let pairedToken = "";
let pairingMode: PairingMode = "none";
const pairingListeners = new Set<() => void>();

function notifyPairing() {
	for (const listener of pairingListeners) listener();
}

export function localBridgePaired(): boolean {
	return pairedToken.length > 0;
}

export function subscribeLocalBridgePairing(listener: () => void) {
	pairingListeners.add(listener);
	return () => pairingListeners.delete(listener);
}

function mapStatus(status: number, serverCode: string | null = null): BridgeError {
	return new BridgeError(
		status === 401
			? "unauthorized"
			: status === 403
				? "forbidden"
				: status === 409
					? "conflict"
					: "service_error",
		serverCode,
	);
}

function sanitizedServerCode(value: unknown): string | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) return null;
	const error = (value as Record<string, unknown>).error;
	if (!error || typeof error !== "object" || Array.isArray(error)) return null;
	const code = (error as Record<string, unknown>).code;
	return typeof code === "string" && /^[A-Z0-9_]{1,96}$/u.test(code)
		? code
		: null;
}

export class LocalBridge {
	constructor(
		private readonly request: typeof fetch = (input, init) =>
			fetch(input, init),
	) {}

	private setPairing(token: string, mode: Exclude<PairingMode, "none">) {
		if (!/^[A-Za-z0-9_-]{32,256}$/u.test(token))
			throw new BridgeError("unauthorized");
		pairedToken = token;
		pairingMode = mode;
		notifyPairing();
	}

	pair(token: string) {
		this.setPairing(token, "legacy");
	}

	async bootstrap(signal: AbortSignal) {
		// Health is intentionally public so we confirm the expected loopback
		// protocol before asking the local Agent for a browser-scoped credential.
		const health = await this.health(signal);
		if (!supportsAutomaticLoopbackSession(health.service_version))
			throw new BridgeError("version_incompatible", null, {
				detectedServiceVersion: health.service_version,
				minimumServiceVersion: AUTOMATIC_LOOPBACK_SESSION_MINIMUM_VERSION,
			});
		const value = record(
			await this.json("/session", signal, {}, undefined, true),
		);
		if (value.schema !== "tda_loopback_session_v1")
			throw new BridgeError("session_incompatible", null, {
				detectedServiceVersion: health.service_version,
				minimumServiceVersion: AUTOMATIC_LOOPBACK_SESSION_MINIMUM_VERSION,
			});
		const token = text(value.token, 256);
		if (!/^[A-Za-z0-9_-]{32,256}$/u.test(token))
			throw new BridgeError("invalid_response");
		if (
			typeof value.expires_in_seconds !== "number" ||
			!Number.isSafeInteger(value.expires_in_seconds) ||
			value.expires_in_seconds < 60
		)
			throw new BridgeError("invalid_response");
		this.setPairing(token, "browser");
	}

	disconnect() {
		if (!pairedToken && pairingMode === "none") return;
		pairedToken = "";
		pairingMode = "none";
		notifyPairing();
	}

	private token() {
		if (!pairedToken) throw new BridgeError("unauthorized");
		return pairedToken;
	}

	private async responseJson(response: Response, maxBytes = 1024 * 1024) {
		const isJson =
			response.headers.get("content-type")?.includes("application/json") ?? false;
		const reader = response.body?.getReader();
		if (!reader) {
			if (!response.ok) throw mapStatus(response.status);
			throw new BridgeError("invalid_response");
		}

		let size = 0;
		let data = "";
		const decoder = new TextDecoder();
		try {
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				size += value.byteLength;
				if (size > maxBytes) {
					await reader.cancel();
					if (!response.ok) throw mapStatus(response.status);
					throw new BridgeError("invalid_response");
				}
				if (isJson) data += decoder.decode(value, { stream: true });
			}
		} finally {
			reader.releaseLock();
		}

		if (!isJson) {
			if (!response.ok) throw mapStatus(response.status);
			throw new BridgeError("invalid_response");
		}

		let value: unknown;
		try {
			value = JSON.parse(data + decoder.decode()) as unknown;
		} catch {
			if (!response.ok) throw mapStatus(response.status);
			throw new BridgeError("invalid_response");
		}
		if (!response.ok)
			throw mapStatus(response.status, sanitizedServerCode(value));
		return value;
	}

	private async json(
		path: string,
		signal: AbortSignal,
		body?: unknown,
		key?: string,
		publicRequest = false,
	) {
		let timedOut = false;
		const requestOnce = async () => {
			const timeout = AbortSignal.timeout(8000);
			const headers: Record<string, string> = { Accept: "application/json" };
			if (!publicRequest) headers.Authorization = `Bearer ${this.token()}`;
			const serialized = body === undefined ? null : serializedJsonBody(body);
			if (serialized && serialized.byteLength > LOCAL_JSON_BODY_MAX_BYTES)
				throw new BridgeError("payload_too_large");
			if (serialized) headers["Content-Type"] = "application/json";
			if (key) headers["Idempotency-Key"] = identifier(key);
			try {
				const response = await this.request(`${LOCAL_API}${path}`, {
					method: serialized === null ? "GET" : "POST",
					headers,
					body: serialized?.body,
					mode: "cors",
					credentials: "omit",
					redirect: "error",
					cache: "no-store",
					referrerPolicy: "no-referrer",
					signal: AbortSignal.any([signal, timeout]),
				});
				return await this.responseJson(response);
			} catch (error) {
				if (timeout.aborted && !signal.aborted) timedOut = true;
				throw error;
			}
		};

		try {
			return await requestOnce();
		} catch (error) {
			if (
				error instanceof BridgeError &&
				error.code === "unauthorized" &&
				!publicRequest &&
				pairingMode === "browser" &&
				!signal.aborted
			) {
				await this.bootstrap(signal);
				timedOut = false;
				return await requestOnce();
			}
			if (error instanceof BridgeError) throw error;
			throw new BridgeError(timedOut ? "timeout" : "unreachable");
		}
	}

	private async reviewJson(
		path: string,
		signal: AbortSignal,
		body?: unknown,
	) {
		let timedOut = false;
		const requestOnce = async () => {
			const timeout = AbortSignal.timeout(30_000);
			const serialized = body === undefined ? null : serializedJsonBody(body);
			if (serialized && serialized.byteLength > LOCAL_REVIEW_BODY_MAX_BYTES)
				throw new BridgeError("payload_too_large");
			const headers: Record<string, string> = {
				Accept: "application/json",
				Authorization: `Bearer ${this.token()}`,
			};
			if (serialized) headers["Content-Type"] = "application/json";
			try {
				const response = await this.request(`${LOCAL_API}${path}`, {
					method: serialized === null ? "GET" : "POST",
					headers,
					body: serialized?.body,
					mode: "cors",
					credentials: "omit",
					redirect: "error",
					cache: "no-store",
					referrerPolicy: "no-referrer",
					signal: AbortSignal.any([signal, timeout]),
				});
				return await this.responseJson(response, LOCAL_REVIEW_BODY_MAX_BYTES);
			} catch (error) {
				if (timeout.aborted && !signal.aborted) timedOut = true;
				throw error;
			}
		};
		try {
			return await requestOnce();
		} catch (error) {
			if (
				error instanceof BridgeError &&
				error.code === "unauthorized" &&
				pairingMode === "browser" &&
				!signal.aborted
			) {
				await this.bootstrap(signal);
				timedOut = false;
				return await requestOnce();
			}
			if (error instanceof BridgeError) throw error;
			throw new BridgeError(timedOut ? "timeout" : "unreachable");
		}
	}

	async health(signal: AbortSignal) {
		return parseHealth(
			await this.json("/health", signal, undefined, undefined, true),
		);
	}
	async capabilities(signal: AbortSignal) {
		return parseCapabilities(await this.json("/capabilities", signal));
	}
	async preparation(signal: AbortSignal) {
		return parsePreparationStatus(await this.json("/preparation", signal));
	}
	async prepareProfile(
		sourceId: string,
		profileId: CraigTranscriptionInput["profileId"],
		signal: AbortSignal,
	) {
		return parsePreparationStatus(
			await this.json("/preparation", signal, {
				source_id: identifier(sourceId),
				profile_id: profileId,
			}),
		);
	}
	async cancelPreparation(operationId: string, signal: AbortSignal) {
		if (!/^[0-9a-f]{32}$/u.test(operationId))
			throw new BridgeError("invalid_response");
		return parsePreparationStatus(
			await this.json("/preparation/cancel", signal, {
				expected_operation_id: operationId,
			}),
		);
	}
	async jobs(signal: AbortSignal) {
		return parseJobs(await this.json("/jobs", signal));
	}
	async jobPage(
		scope: "all" | "active" | "history",
		signal: AbortSignal,
		options: Readonly<{ cursor?: string; limit?: number }> = {},
	) {
		const params = new URLSearchParams({ scope });
		if (options.cursor !== undefined) params.set("cursor", options.cursor);
		if (options.limit !== undefined) params.set("limit", String(options.limit));
		return parseJobListPage(
			await this.json(`/jobs?${params.toString()}`, signal),
		);
	}
	async job(id: string, signal: AbortSignal) {
		return parseJob(await this.json(`/jobs/${identifier(id)}`, signal));
	}
	async activity(id: string, signal: AbortSignal, attempt?: number) {
		if (
			attempt !== undefined &&
			(!Number.isSafeInteger(attempt) || attempt < 1)
		)
			throw new BridgeError("invalid_response");
		const query = attempt === undefined ? "" : `?attempt=${attempt}`;
		return parseJobActivity(
			await this.json(`/jobs/${identifier(id)}/activity${query}`, signal),
		);
	}
	async events(
		id: string,
		signal: AbortSignal,
		options: Readonly<{
			afterSeq?: number;
			beforeSeq?: number;
			limit?: number;
		}> = {},
	) {
		const params = new URLSearchParams();
		if (options.afterSeq !== undefined)
			params.set("after_seq", String(options.afterSeq));
		if (options.beforeSeq !== undefined)
			params.set("before_seq", String(options.beforeSeq));
		if (options.limit !== undefined) params.set("limit", String(options.limit));
		const query = params.size > 0 ? `?${params.toString()}` : "";
		return parseJobEventPage(
			await this.json(`/jobs/${identifier(id)}/events${query}`, signal),
		);
	}
	async system(signal: AbortSignal) {
		return parseSystemSnapshot(await this.json("/system", signal));
	}
	async lifecycle(action: "pause" | "resume", signal: AbortSignal) {
		return parseHealth(await this.json("/lifecycle", signal, { action }));
	}
	async jobAction(id: string, action: "cancel" | "retry", signal: AbortSignal) {
		return parseJob(
			await this.json(`/jobs/${identifier(id)}/${action}`, signal, {}),
		);
	}
	async deleteJob(id: string, signal: AbortSignal) {
		await this.json(`/jobs/${identifier(id)}/delete`, signal, {});
	}
	async craigSource(file: File, signal: AbortSignal) {
		if (!(file instanceof Blob) || file.size <= 0)
			throw new BridgeError("invalid_response");
		let timedOut = false;
		const uploadOnce = async () => {
			const timeout = AbortSignal.timeout(15 * 60 * 1000);
			try {
				const response = await this.request(`${LOCAL_API}/sources/craig`, {
					method: "POST",
					headers: {
						Accept: "application/json",
						Authorization: `Bearer ${this.token()}`,
						"Content-Type": "application/zip",
					},
					body: file,
					mode: "cors",
					credentials: "omit",
					redirect: "error",
					cache: "no-store",
					referrerPolicy: "no-referrer",
					signal: AbortSignal.any([signal, timeout]),
				});
				return parseCraigSource(await this.responseJson(response));
			} catch (error) {
				if (timeout.aborted && !signal.aborted) timedOut = true;
				throw error;
			}
		};
		try {
			return await uploadOnce();
		} catch (error) {
			if (
				error instanceof BridgeError &&
				error.code === "unauthorized" &&
				pairingMode === "browser" &&
				!signal.aborted
			) {
				await this.bootstrap(signal);
				timedOut = false;
				return await uploadOnce();
			}
			if (error instanceof BridgeError) throw error;
			throw new BridgeError(timedOut ? "timeout" : "unreachable");
		}
	}
	async transcription(input: CraigTranscriptionInput, key: string, signal: AbortSignal) {
		const payload = buildCraigTranscriptionRequest({
			...input,
			campaignId: identifier(input.campaignId),
			sessionId: identifier(input.sessionId),
			sourceId: identifier(input.sourceId),
		});
		return parseJob(
			await this.json(
				"/jobs",
				signal,
				payload,
				key,
			),
		);
	}
	async synthetic(key: string, signal: AbortSignal) {
		return parseJob(
			await this.json(
				"/jobs",
				signal,
				{
					kind: "synthetic.fixture",
					campaign_id: "synthetic-campaign",
					session_id: "synthetic-session",
					source_id: "synthetic-source",
					units: 3,
				},
				key,
			),
		);
	}
	async result(id: string, signal: AbortSignal) {
		return parseResultSummary(
			await this.json(`/jobs/${identifier(id)}/result`, signal),
			id,
		);
	}

	async localSources(signal: AbortSignal) {
		return parseLocalSources(await this.json("/sources", signal));
	}

	async localRuns(sourceId: string, signal: AbortSignal) {
		return parseLocalRuns(
			await this.json(`/sources/${identifier(sourceId)}/runs`, signal),
		);
	}

	async localReview(sourceId: string, runId: string, signal: AbortSignal) {
		return parseLocalReview(
			await this.reviewJson(
				`/sources/${identifier(sourceId)}/runs/${runIdentifier(runId)}/review`,
				signal,
			),
		);
	}

	async repairPublicationTarget(sourceId: string, runId: string, signal: AbortSignal) {
        await this.json(`/sources/${identifier(sourceId)}/runs/${runIdentifier(runId)}/publication-target/repair`, signal, {});
        return this.localReview(sourceId, runId, signal);
    }

	async saveLocalReview(
		sourceId: string,
		runId: string,
		baseline: LocalReview,
		status: LocalReviewStatus,
		segments: readonly LocalReviewSegment[],
		signal: AbortSignal,
	) {
		if (baseline.snapshotContract !== "tda_local_review_cas_v1")
			throw new BridgeError("incompatible", "LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED");
		if (baseline.sourceId !== sourceId || baseline.runId !== runId)
			throw new BridgeError("conflict", "LOCAL_REVIEW_DRAFT_CONFLICT");
		const expected = baseline.persistence === "ephemeral_base"
			? { persistence: "ephemeral_base", base_transcript_sha256: baseline.baseTranscriptSha256 }
			: { persistence: "persisted", draft_revision: baseline.draftRevision, draft_sha256: baseline.draftSha256 };
		return parseLocalReview(
			await this.reviewJson(
				`/sources/${identifier(sourceId)}/runs/${runIdentifier(runId)}/review`,
				signal,
				{
					snapshot_contract: baseline.snapshotContract,
					expected,
					status,
					segments: segments.map((segment) => ({
						track_number: segment.trackNumber,
						segment_id: segment.segmentId,
						start: segment.start,
						end: segment.end,
						text: segment.text,
						speaker: segment.speaker,
						reviewed: segment.reviewed,
					})),
				},
			),
		);
	}
}
