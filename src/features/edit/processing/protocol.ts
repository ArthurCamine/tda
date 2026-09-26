import { supportsQwenAlignmentRuntime } from "./compatibility";
import { isReviewStringV1 } from "../../transcript-review/text-contract";

export const LOCAL_API = "http://127.0.0.1:8765/api/v1";
export type Lifecycle = "preparing" | "ready" | "paused";
export type TranscriptionProfileId =
	| "whisper-turbo"
	| "whisper-detailed"
	| "qwen-fast"
	| "qwen-quality";
export type Health = {
	api_version: "1";
	service_version: string;
	lifecycle: Lifecycle;
};
export type TranscriptionProfileState = {
	id: TranscriptionProfileId;
	engine: "whisper" | "qwen3";
	ready: boolean;
	preparationRequired: boolean;
	reason: string | null;
};
export type Capabilities = {
	capabilities: string[];
	sync: boolean;
	device: { id: string; label: string };
	transcription: {
		profiles: TranscriptionProfileId[];
		catalog: TranscriptionProfileState[];
	};
};
export type PreparationStatus = {
	schema: "tda_profile_preparation_v1";
	state: "idle" | "running" | "completed" | "failed";
	active: boolean;
	operationId: string | null;
	sourceId: string | null;
	profileId: TranscriptionProfileId | null;
	engine: "whisper" | "qwen3" | null;
	stage: string;
	title: string;
	detail: string;
	sequence: number;
	elapsedSeconds: number;
	errorCode: string | null;
};
export type CraigSource = {
	schemaVersion: "tda_craig_ingest_v1";
	sourceId: string;
	sourceSha256: string;
	sizeBytes: number;
	trackCount: number;
	reused: boolean;
};
export type CraigTranscriptionInput = {
	campaignId: string;
	sessionId: string;
	sourceId: string;
	profileId: TranscriptionProfileId;
	glossary: string;
	context: string;
};
export type JobStatus =
	| "queued"
	| "running"
	| "succeeded"
	| "failed"
	| "cancelled"
	| "interrupted";
export type JobContext = {
	campaignId: string;
	sessionId: string;
	sourceId: string;
	profileId?: TranscriptionProfileId;
};
export type LocalJob = {
	id: string;
	kind: string;
	status: JobStatus;
	stage: string;
	progress: null | { completed: number; total: number; unit: string };
	error: null | { code: string; recoverable: boolean };
	result_available: boolean;
	updated_at: string;
	attempt: number;
	context: JobContext | null;
};
export type JobEventLevel = "info" | "warning" | "error";
export type JobEventValue = string | number | boolean | null;
export type JobEvent = {
	seq: number;
	attempt: number | null;
	code: string;
	at: string;
	level: JobEventLevel;
	data: Readonly<Record<string, JobEventValue>>;
};
export type SystemGpu = {
	index: number;
	name: string;
	utilizationPercent: number | null;
	memoryUsedBytes: number | null;
	memoryTotalBytes: number | null;
};
export type SystemSnapshot = {
	sampledAt: string;
	host: { os: string; cpu: string | null };
	cpu: { utilizationPercent: number | null };
	memory: {
		usedBytes: number | null;
		totalBytes: number | null;
		percent: number | null;
	};
	gpus: readonly SystemGpu[];
};
export type ResultSummary = {
	jobId: string;
	campaignId: string;
	sessionId: string;
	sourceId: string;
	publicationId: string;
	profileId?: TranscriptionProfileId;
	transcriptSha256?: string;
	runId?: string;
};
export type LocalSourceSummary = {
	sourceId: string;
	sourceSha256: string;
	recordingId: string | null;
	trackCount: number;
};
export type LocalPublicationTarget = {
	campaignSlug: string;
	sourceSessionId: string;
	jobId: string;
	attempt: number;
};
export type LocalExecutionLineage = {
	schemaVersion: "tda_execution_lineage_v1";
	companionVersion: string | null;
	runtimeFamily: string | null;
	runtimeVersion: string | null;
	device: string | null;
	computeType: string | null;
	gpu: {
		vendor: string | null;
		index: number | null;
		model: string | null;
		vramTotalBytes: number | null;
		computeCapability: string | null;
		driverVersion: string | null;
	} | null;
};
export type LocalReviewStatus = "draft" | "reviewed" | "approved_local";

export type LocalRunReviewSummary = {
	status: LocalReviewStatus | "unknown";
	draftRevision: number | null;
	reviewPercent: number | null;
	updatedAt: string | null;
};

export type LocalRunSummary = {
	runId: string;
	sourceId: string;
	profileId: string;
	engine: string | null;
	model: string | null;
	modelRevision: string | null;
	device: string | null;
	computeType: string | null;
	alignment: string | null;
	executionLineage: LocalExecutionLineage | null;
	language: string | null;
	completedAt: string | null;
	transcriptSha256: string;
	transcriptSizeBytes: number;
	stats: {
		audioWorkSeconds: number | null;
		processingSeconds: number | null;
		sessionDurationSeconds: number | null;
		durationSemantics?: "session_extent_v1";
		rtf: number | null;
		wordCount: number | null;
		segmentCount: number | null;
		trackCount: number | null;
		turnCount: number | null;
		deduplicatedSegmentCount: number | null;
		warningCount: number | null;
	};
	publicationTarget: LocalPublicationTarget | null;
	review: LocalRunReviewSummary | null;
};
export type LocalReviewSegment = {
	trackNumber: number;
	segmentId: string;
	start: number;
	end: number;
	text: string;
	speaker: string;
	reviewed: boolean;
};
export type LocalReview = {
	sourceId: string;
	runId: string;
	baseTranscriptSha256: string;
	draftRevision: number | null;
	draftSha256: string | null;
	persistence?: "persisted" | "ephemeral_base";
	snapshotContract?: "tda_local_review_cas_v1";
	status: LocalReviewStatus;
	approvalCurrent: boolean;
	approvedAt: string | null;
	createdAt: string | null;
	updatedAt: string | null;
	lineage: {
		profileId: string;
		engine: string | null;
		model: string | null;
		modelRevision: string | null;
		device: string | null;
		computeType: string | null;
		alignment: string | null;
		executionLineage: LocalExecutionLineage | null;
		completedAt: string | null;
	};
	stats: {
		audioWorkSeconds: number | null;
		processingSeconds: number | null;
		sessionDurationSeconds: number | null;
		durationSemantics?: "session_extent_v1";
		rtf: number | null;
		wordCount: number | null;
		segmentCount: number | null;
		trackCount: number | null;
	};
	warnings: readonly string[];
	warningSummary?: {
		totalCount: number;
		displayedCount: number;
		truncated: boolean;
	};
	publicationTarget: LocalPublicationTarget | null;
	review: {
		reviewedSegments: number;
		totalSegments: number;
		reviewPercent: number;
		editedSegments: number;
		wordCount: number;
		warningCount: number;
	};
	segments: readonly LocalReviewSegment[];
	sync: { status: "not_configured" };
};
export type BridgeErrorCode =
	| "unreachable"
	| "unauthorized"
	| "forbidden"
	| "api_incompatible"
	| "version_incompatible"
	| "session_incompatible"
	| "incompatible"
	| "invalid_response"
	| "payload_too_large"
	| "timeout"
	| "conflict"
	| "service_error";
export type BridgeErrorDetails = Readonly<{
	detectedServiceVersion?: string;
	minimumServiceVersion?: string;
	detectedApiVersion?: string;
	requiredApiVersion?: string;
}>;
export class BridgeError extends Error {
	constructor(
		public readonly code: BridgeErrorCode,
		public readonly serverCode: string | null = null,
		public readonly details: BridgeErrorDetails = {},
	) {
		super(serverCode ?? code);
	}
}
function invalid(): never {
	throw new BridgeError("invalid_response");
}
export function record(value: unknown): Record<string, unknown> {
	if (!value || typeof value !== "object" || Array.isArray(value))
		return invalid();
	return value as Record<string, unknown>;
}
export function text(value: unknown, max = 128): string {
	if (
		typeof value !== "string" ||
		!value.length ||
		value.length > max ||
		Array.from(value).some(
			(char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
		)
	)
		return invalid();
	return value;
}
function nullableText(value: unknown, max = 160): string | null {
	if (value === null || value === undefined) return null;
	return text(value, max);
}
export function identifier(value: unknown): string {
	const id = text(value);
	if (!/^[A-Za-z0-9_-]+$/u.test(id)) return invalid();
	return id;
}
function boolean(value: unknown): boolean {
	if (typeof value !== "boolean") return invalid();
	return value;
}
function nonNegativeInteger(value: unknown): number {
	if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
		return invalid();
	return value;
}
function nullableNonNegativeNumber(value: unknown): number | null {
	if (value === null || value === undefined) return null;
	if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
		return invalid();
	return value;
}
function nullablePercent(value: unknown): number | null {
	const parsed = nullableNonNegativeNumber(value);
	if (parsed !== null && parsed > 100) return invalid();
	return parsed;
}
function isoDate(value: unknown): string {
	const parsed = text(value, 64);
	if (!Number.isFinite(Date.parse(parsed))) return invalid();
	return parsed;
}
function sha256(value: unknown): string {
	const parsed = text(value, 64);
	if (!/^[a-f0-9]{64}$/u.test(parsed)) return invalid();
	return parsed;
}
export function runIdentifier(value: unknown): string {
	const id = text(value, 196);
	if (!/^[A-Za-z0-9_-]{1,196}$/u.test(id)) return invalid();
	return id;
}
function contentText(value: unknown, max: number): string {
	if (typeof value !== "string" || !value.trim() || value.length > max)
		return invalid();
	if (value.includes("\0")) return invalid();
	return value;
}
function nonNegativeNumber(value: unknown): number {
	if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
		return invalid();
	return value;
}
function nullableIsoDate(value: unknown): string | null {
	if (value === null || value === undefined) return null;
	return isoDate(value);
}
export function transcriptionProfile(value: unknown): TranscriptionProfileId {
	const parsed = text(value, 32);
	if (
		!["whisper-turbo", "whisper-detailed", "qwen-fast", "qwen-quality"].includes(
			parsed,
		)
	)
		return invalid();
	return parsed as TranscriptionProfileId;
}
export function parseHealth(value: unknown): Health {
	const row = record(value);
	const apiVersion = text(row.api_version, 16);
	if (apiVersion !== "1") {
		throw new BridgeError("api_incompatible", null, {
			detectedApiVersion: apiVersion,
			requiredApiVersion: "1",
		});
	}
	if (!["preparing", "ready", "paused"].includes(String(row.lifecycle)))
		return invalid();
	return {
		api_version: "1",
		service_version: text(row.service_version),
		lifecycle: row.lifecycle as Lifecycle,
	};
}
export function parseCapabilities(value: unknown): Capabilities {
	const row = record(value);
	const device = record(row.device);
	if (!Array.isArray(row.capabilities) || row.capabilities.length > 100)
		return invalid();
	let profiles: TranscriptionProfileId[] = [];
	let catalog: TranscriptionProfileState[] = [];
	if (row.transcription !== undefined && row.transcription !== null) {
		const transcription = record(row.transcription);
		const qwenGateState = new Map<
			TranscriptionProfileId,
			{ ready: boolean; runtimeVersion: string | null; reason: string | null }
		>();
		if (transcription.qwen_physical_gate !== undefined) {
			const gates = record(transcription.qwen_physical_gate);
			for (const profileId of ["qwen-fast", "qwen-quality"] as const) {
				if (gates[profileId] === undefined) continue;
				const gate = record(gates[profileId]);
				if (transcriptionProfile(gate.profile_id) !== profileId) return invalid();
				const ready = boolean(gate.ready);
				const runtimeVersion =
					gate.runtime_version === null || gate.runtime_version === undefined
						? null
						: text(gate.runtime_version, 32);
				if (ready && runtimeVersion === null) return invalid();
				qwenGateState.set(profileId, {
					ready,
					runtimeVersion,
					reason:
						gate.reason === null || gate.reason === undefined
							? null
							: text(gate.reason, 96),
				});
			}
		}
		if (!Array.isArray(transcription.profiles) || transcription.profiles.length > 8)
			return invalid();
		profiles = transcription.profiles.map(transcriptionProfile);
		if (new Set(profiles).size !== profiles.length) return invalid();

		if (transcription.catalog !== undefined) {
			if (!Array.isArray(transcription.catalog) || transcription.catalog.length > 8)
				return invalid();
			catalog = transcription.catalog.map((raw) => {
				const item = record(raw);
				const engine = text(item.engine, 16);
				if (engine !== "whisper" && engine !== "qwen3") return invalid();
				const reason =
					item.reason === null || item.reason === undefined
						? null
						: text(item.reason, 96);
				return {
					id: transcriptionProfile(item.id),
					engine,
					ready: boolean(item.ready),
					preparationRequired: boolean(item.preparation_required),
					reason,
				};
			});
			if (new Set(catalog.map((item) => item.id)).size !== catalog.length)
				return invalid();
		} else {
			catalog = profiles.map((id) => ({
				id,
				engine: id.startsWith("qwen-") ? "qwen3" : "whisper",
				ready: true,
				preparationRequired: false,
				reason: null,
			}));
		}

		const qwenBlocked = new Set<TranscriptionProfileId>();
		catalog = catalog.map((item) => {
			if (item.engine !== "qwen3") return item;
			const gate = qwenGateState.get(item.id);
			if (!gate) return item;
			if (!gate.ready) {
				qwenBlocked.add(item.id);
				return {
					...item,
					ready: false,
					preparationRequired: true,
					reason: gate.reason ?? "QWEN_PHYSICAL_ACCEPTANCE_REQUIRED",
				};
			}
			if (!supportsQwenAlignmentRuntime(gate.runtimeVersion)) {
				qwenBlocked.add(item.id);
				return {
					...item,
					ready: false,
					preparationRequired: false,
					reason: "QWEN_RUNTIME_ALIGNMENT_UPGRADE_REQUIRED",
				};
			}
			return item;
		});
		profiles = profiles.filter((profileId) => !qwenBlocked.has(profileId));
	}
	return {
		capabilities: row.capabilities.map((value) => text(value)),
		sync: boolean(row.sync),
		device: { id: identifier(device.id), label: text(device.label) },
		transcription: { profiles, catalog },
	};
}

export function parsePreparationStatus(value: unknown): PreparationStatus {
	const row = record(value);
	if (row.schema !== "tda_profile_preparation_v1") return invalid();
	if (!["idle", "running", "completed", "failed"].includes(String(row.state)))
		return invalid();
	const nullableText = (raw: unknown, limit = 128) =>
		raw === null || raw === undefined ? null : text(raw, limit);
	const profile =
		row.profile_id === null || row.profile_id === undefined
			? null
			: transcriptionProfile(row.profile_id);
	const engine =
		row.engine === null || row.engine === undefined ? null : text(row.engine, 16);
	if (engine !== null && engine !== "whisper" && engine !== "qwen3")
		return invalid();
	const elapsed =
		typeof row.elapsed_seconds === "number" &&
		Number.isFinite(row.elapsed_seconds) &&
		row.elapsed_seconds >= 0
			? row.elapsed_seconds
			: invalid();
	return {
		schema: "tda_profile_preparation_v1",
		state: row.state as PreparationStatus["state"],
		active: boolean(row.active),
		operationId: nullableText(row.operation_id, 64),
		sourceId: nullableText(row.source_id, 80),
		profileId: profile,
		engine,
		stage: text(row.stage, 64),
		title: text(row.title, 240),
		detail: row.detail === "" ? "" : text(row.detail, 500),
		sequence: nonNegativeInteger(row.sequence),
		elapsedSeconds: elapsed,
		errorCode: nullableText(row.error_code, 96),
	};
}
export function parseCraigSource(value: unknown): CraigSource {
	const row = record(value);
	if (row.schema_version !== "tda_craig_ingest_v1")
		throw new BridgeError("incompatible");
	const sourceId = identifier(row.source_id);
	const sourceSha256 = sha256(row.source_sha256);
	if (sourceId !== `craig-${sourceSha256}`) return invalid();
	const sizeBytes = nonNegativeInteger(row.size_bytes);
	const trackCount = nonNegativeInteger(row.track_count);
	if (sizeBytes <= 0 || trackCount <= 0 || trackCount > 256) return invalid();
	return {
		schemaVersion: "tda_craig_ingest_v1",
		sourceId,
		sourceSha256,
		sizeBytes,
		trackCount,
		reused: boolean(row.reused),
	};
}
export function parseJob(value: unknown): LocalJob {
	const row = record(value);
	if (
		![
			"queued",
			"running",
			"succeeded",
			"failed",
			"cancelled",
			"interrupted",
		].includes(String(row.status))
	)
		return invalid();
	let progress: LocalJob["progress"] = null;
	if (row.progress !== null) {
		const p = record(row.progress);
		if (
			typeof p.completed !== "number" ||
			typeof p.total !== "number" ||
			!Number.isSafeInteger(p.completed) ||
			!Number.isSafeInteger(p.total) ||
			p.completed < 0 ||
			p.total <= 0 ||
			p.completed > p.total
		)
			return invalid();
		progress = {
			completed: p.completed,
			total: p.total,
			unit: text(p.unit, 40),
		};
	}
	const error = row.error === null ? null : record(row.error);
	let context: JobContext | null = null;
	if (row.context !== undefined && row.context !== null) {
		const rawContext = record(row.context);
		const base = {
			campaignId: identifier(rawContext.campaign_id),
			sessionId: identifier(rawContext.session_id),
			sourceId: identifier(rawContext.source_id),
		};
		context =
			rawContext.profile_id === undefined || rawContext.profile_id === null
				? base
				: { ...base, profileId: transcriptionProfile(rawContext.profile_id) };
	}
	return {
		id: identifier(row.id),
		kind: text(row.kind),
		status: row.status as JobStatus,
		stage: text(row.stage),
		progress,
		error: error
			? { code: text(error.code), recoverable: boolean(error.recoverable) }
			: null,
		result_available: boolean(row.result_available),
		updated_at: isoDate(row.updated_at),
		attempt:
			row.attempt === undefined ? 0 : nonNegativeInteger(row.attempt),
		context,
	};
}
export function parseJobs(value: unknown): LocalJob[] {
	const rows = record(value).jobs;
	if (!Array.isArray(rows) || rows.length > 1000) return invalid();
	const jobs = rows.map(parseJob);
	if (new Set(jobs.map((job) => job.id)).size !== jobs.length) return invalid();
	return jobs;
}
export function parseJobEvents(value: unknown): JobEvent[] {
	const rows = record(value).events;
	if (!Array.isArray(rows) || rows.length > 100) return invalid();
	return rows.map((value) => {
		const row = record(value);
		const level = row.level === undefined ? "info" : text(row.level, 16);
		if (!["info", "warning", "error"].includes(level)) return invalid();
		const rawData =
			row.data === undefined || row.data === null ? {} : record(row.data);
		const entries = Object.entries(rawData);
		if (entries.length > 32) return invalid();
		const data: Record<string, JobEventValue> = {};
		for (const [key, raw] of entries) {
			if (!/^[A-Za-z0-9_-]{1,64}$/u.test(key)) return invalid();
			if (raw === null || typeof raw === "boolean") data[key] = raw;
			else if (typeof raw === "number" && Number.isFinite(raw)) data[key] = raw;
			else if (typeof raw === "string") data[key] = text(raw, 256);
			else return invalid();
		}
		const attempt =
			row.attempt === undefined || row.attempt === null
				? null
				: nonNegativeInteger(row.attempt);
		if (attempt !== null && attempt < 1) return invalid();
		return {
			seq: nonNegativeInteger(row.seq),
			attempt,
			code: text(row.code, 96),
			at: isoDate(row.at),
			level: level as JobEventLevel,
			data,
		};
	});
}
export function parseSystemSnapshot(value: unknown): SystemSnapshot {
	const row = record(value);
	const host = record(row.host);
	const cpu = record(row.cpu);
	const memory = record(row.memory);
	if (!Array.isArray(row.gpus) || row.gpus.length > 16) return invalid();
	const gpus = row.gpus.map((value) => {
		const gpu = record(value);
		return {
			index: nonNegativeInteger(gpu.index),
			name: text(gpu.name, 160),
			utilizationPercent: nullablePercent(gpu.utilization_percent),
			memoryUsedBytes: nullableNonNegativeNumber(gpu.memory_used_bytes),
			memoryTotalBytes: nullableNonNegativeNumber(gpu.memory_total_bytes),
		};
	});
	return {
		sampledAt: isoDate(row.sampled_at),
		host: {
			os: text(host.os, 160),
			cpu: nullableText(host.cpu),
		},
		cpu: { utilizationPercent: nullablePercent(cpu.utilization_percent) },
		memory: {
			usedBytes: nullableNonNegativeNumber(memory.used_bytes),
			totalBytes: nullableNonNegativeNumber(memory.total_bytes),
			percent: nullablePercent(memory.percent),
		},
		gpus,
	};
}
// Only identity/hashes are retained. Transcript text and local artifact content never enter the cloud UI bridge.
export function parseLocalSources(value: unknown): LocalSourceSummary[] {
	const row = record(value);
	if (row.schema_version !== "tda_craig_sources_v1") return invalid();
	if (!Array.isArray(row.sources) || row.sources.length > 1000) return invalid();
	const sources = row.sources.map((raw) => {
		const item = record(raw);
		const sourceSha256 = sha256(item.source_sha256);
		const sourceId = identifier(item.source_id);
		if (sourceId !== `craig-${sourceSha256}`) return invalid();
		const trackCount = nonNegativeInteger(item.track_count);
		if (trackCount < 1 || trackCount > 256) return invalid();
		return {
			sourceId,
			sourceSha256,
			recordingId: nullableText(item.recording_id, 256),
			trackCount,
		};
	});
	if (new Set(sources.map((item) => item.sourceId)).size !== sources.length)
		return invalid();
	return sources;
}


function parseExecutionLineage(value: unknown): LocalExecutionLineage | null {
	if (value === null || value === undefined) return null;
	const row = record(value);
	if (row.schema_version !== "tda_execution_lineage_v1") return invalid();
	const rawGpu = row.gpu;
	let gpu: LocalExecutionLineage["gpu"] = null;
	if (rawGpu !== null && rawGpu !== undefined) {
		const item = record(rawGpu);
		gpu = {
			vendor: nullableText(item.vendor, 64),
			index:
				item.index === null || item.index === undefined
					? null
					: nonNegativeInteger(item.index),
			model: nullableText(item.model, 160),
			vramTotalBytes: nullableNonNegativeNumber(item.vram_total_bytes),
			computeCapability: nullableText(item.compute_capability, 32),
			driverVersion: nullableText(item.driver_version, 64),
		};
	}
	return {
		schemaVersion: "tda_execution_lineage_v1",
		companionVersion: nullableText(row.companion_version, 64),
		runtimeFamily: nullableText(row.runtime_family, 64),
		runtimeVersion: nullableText(row.runtime_version, 128),
		device: nullableText(row.device, 64),
		computeType: nullableText(row.compute_type, 64),
		gpu,
	};
}

function parsePublicationTarget(
	value: unknown,
	expected: {
		sourceId: string;
		runId: string;
		transcriptSha256: string;
	},
): LocalPublicationTarget | null {
	if (value === null || value === undefined) return null;
	const row = record(value);
	if (row.schema_version !== "tda_publication_target_v1") return invalid();
	const sourceId = identifier(row.source_id);
	const runId = runIdentifier(row.run_id);
	const transcriptSha256 = sha256(row.transcript_sha256);
	const attempt = nonNegativeInteger(row.attempt);
	if (
		attempt < 1 ||
		sourceId !== expected.sourceId ||
		runId !== expected.runId ||
		transcriptSha256 !== expected.transcriptSha256
	)
		return invalid();
	return {
		campaignSlug: identifier(row.campaign_slug),
		sourceSessionId: identifier(row.source_session_id),
		jobId: identifier(row.job_id),
		attempt,
	};
}

function parseLocalRunReview(value: unknown): LocalRunReviewSummary | null {
	if (value === null || value === undefined) return null;
	const row = record(value);
	const status = String(row.status);
	if (status === "unknown") {
		if (
			row.draft_revision !== null ||
			row.review_percent !== null ||
			row.updated_at !== null
		)
			return invalid();
		return {
			status: "unknown",
			draftRevision: null,
			reviewPercent: null,
			updatedAt: null,
		};
	}
	if (!["draft", "reviewed", "approved_local"].includes(status)) return invalid();
	const reviewPercent = nonNegativeNumber(row.review_percent);
	if (reviewPercent > 100) return invalid();
	const updatedAt = nullableIsoDate(row.updated_at);
	if (updatedAt === null) return invalid();
	return {
		status: status as LocalReviewStatus,
		draftRevision: nonNegativeInteger(row.draft_revision),
		reviewPercent,
		updatedAt,
	};
}

export function parseLocalRuns(value: unknown): LocalRunSummary[] {
	const row = record(value);
	if (row.schema_version !== "tda_transcription_runs_v1") return invalid();
	const sourceId = identifier(row.source_id);
	if (!Array.isArray(row.runs) || row.runs.length > 1000) return invalid();
	return row.runs.map((raw) => {
		const item = record(raw);
		if (item.status !== "completed") return invalid();
		if (identifier(item.source_id) !== sourceId) return invalid();
		const runId = runIdentifier(item.run_id);
		const transcriptSha256 = sha256(item.transcript_sha256);
		const stats = record(item.stats ?? {});
		const nullableMetric = (metric: unknown) =>
			metric === null || metric === undefined ? null : nonNegativeNumber(metric);
		const nullableCount = (metric: unknown) =>
			metric === null || metric === undefined ? null : nonNegativeInteger(metric);
		return {
			runId,
			sourceId,
			profileId: text(item.profile_id, 64),
			engine: nullableText(item.engine, 64),
			model: nullableText(item.model, 256),
			modelRevision: nullableText(item.model_revision, 256),
			device: nullableText(item.device, 64),
			computeType: nullableText(item.compute_type, 64),
			alignment: nullableText(item.alignment, 128),
			executionLineage: parseExecutionLineage(item.execution_lineage),
			language: nullableText(item.language, 32),
			completedAt: nullableIsoDate(item.completed_at),
			transcriptSha256,
			transcriptSizeBytes: (() => {
				const size = nonNegativeInteger(item.transcript_size_bytes);
				if (size < 1) return invalid();
				return size;
			})(),
			stats: {
				audioWorkSeconds: nullableMetric(stats.audio_work_seconds),
				processingSeconds: nullableMetric(stats.processing_seconds),
				sessionDurationSeconds: nullableMetric(stats.session_duration_seconds),
				...(stats.duration_semantics === "session_extent_v1"
					? { durationSemantics: "session_extent_v1" as const }
					: {}),
				rtf: nullableMetric(stats.rtf),
				wordCount: nullableCount(stats.word_count),
				segmentCount: nullableCount(stats.segment_count),
				trackCount: nullableCount(stats.track_count),
				turnCount: nullableCount(stats.turn_count),
				deduplicatedSegmentCount: nullableCount(
					stats.deduplicated_segment_count,
				),
				warningCount: nullableCount(stats.warning_count),
			},
			publicationTarget: parsePublicationTarget(item.publication_target, {
				sourceId,
				runId,
				transcriptSha256,
			}),
			review: parseLocalRunReview(item.review),
		};
	});
}

export function parseLocalReview(value: unknown): LocalReview {
	const row = record(value);
	if (row.schema_version !== "tda_local_review_v1") return invalid();
	const status = text(row.status, 32);
	if (!["draft", "reviewed", "approved_local"].includes(status)) return invalid();
	const approvalCurrent =
		row.approval_current === undefined ? false : boolean(row.approval_current);
	const approvedAt =
		row.approved_at === undefined || row.approved_at === null
			? null
			: isoDate(row.approved_at);
	if (status === "approved_local" && !approvalCurrent) return invalid();
	if (approvalCurrent !== (approvedAt !== null)) return invalid();
	const sourceId = identifier(row.source_id);
	const runId = runIdentifier(row.run_id);
	const baseTranscriptSha256 = sha256(row.base_transcript_sha256);
	const supportsCas = row.snapshot_contract === "tda_local_review_cas_v1";
	if (row.snapshot_contract !== undefined && !supportsCas) return invalid();
	const ephemeral = supportsCas && row.persistence === "ephemeral_base";
	if (supportsCas && !["persisted", "ephemeral_base"].includes(String(row.persistence))) return invalid();
	if (ephemeral && (row.draft_revision !== null || row.draft_sha256 !== null ||
		row.created_at !== null || row.updated_at !== null || status !== "draft")) return invalid();
	if (!supportsCas && row.persistence !== undefined) return invalid();
	const lineage = record(row.lineage);
	const stats = record(row.stats);
	const review = record(row.review);
	const sync = record(row.sync);
	if (sync.status !== "not_configured") return invalid();
	if (!Array.isArray(row.warnings) || row.warnings.length > 1000) return invalid();
	if (!Array.isArray(row.segments) || row.segments.length > 100_000) return invalid();
	const segments = row.segments.map((raw) => {
		const segment = record(raw);
		const start = nonNegativeNumber(segment.start);
		const end = nonNegativeNumber(segment.end);
		if (end < start) return invalid();
		const trackNumber = nonNegativeInteger(segment.track_number);
		if (trackNumber < 1) return invalid();
		return {
			trackNumber,
			segmentId: contentText(segment.segment_id, 256),
			start,
			end,
			text: isReviewStringV1(segment.text, "text") ? segment.text : invalid(),
			speaker: isReviewStringV1(segment.speaker, "speaker") ? segment.speaker : invalid(),
			reviewed: boolean(segment.reviewed),
		};
	});
	const totalSegments = nonNegativeInteger(review.total_segments);
	const reviewedSegments = nonNegativeInteger(review.reviewed_segments);
	if (totalSegments !== segments.length || reviewedSegments > totalSegments)
		return invalid();
	const reviewPercent = nonNegativeNumber(review.review_percent);
	if (reviewPercent > 100) return invalid();
	const warningCount = nonNegativeInteger(review.warning_count);
	let warningSummary: LocalReview["warningSummary"];
	if (row.warning_summary !== undefined) {
		const summary = record(row.warning_summary);
		const totalCount = nonNegativeInteger(summary.total_count);
		const displayedCount = nonNegativeInteger(summary.displayed_count);
		const truncated = boolean(summary.truncated);
		if (totalCount !== warningCount || displayedCount !== row.warnings.length ||
			displayedCount !== Math.min(totalCount, 1000) || truncated !== (totalCount > displayedCount)) return invalid();
		warningSummary = { totalCount, displayedCount, truncated };
	}
	return {
		sourceId,
		runId,
		baseTranscriptSha256,
		draftRevision: ephemeral ? null : nonNegativeInteger(row.draft_revision),
		draftSha256: ephemeral ? null : sha256(row.draft_sha256),
		persistence: ephemeral ? "ephemeral_base" : "persisted",
		...(supportsCas ? { snapshotContract: "tda_local_review_cas_v1" as const } : {}),
		status: status as LocalReviewStatus,
		approvalCurrent,
		approvedAt,
		createdAt: ephemeral ? null : isoDate(row.created_at),
		updatedAt: ephemeral ? null : isoDate(row.updated_at),
		lineage: {
			profileId: text(lineage.profile_id, 64),
			engine: nullableText(lineage.engine, 64),
			model: nullableText(lineage.model, 256),
			modelRevision: nullableText(lineage.model_revision, 256),
			device: nullableText(lineage.device, 64),
			computeType: nullableText(lineage.compute_type, 64),
			alignment: nullableText(lineage.alignment, 128),
			executionLineage: parseExecutionLineage(lineage.execution_lineage),
			completedAt: nullableIsoDate(lineage.completed_at),
		},
		stats: {
			audioWorkSeconds: nullableNonNegativeNumber(stats.audio_work_seconds),
			processingSeconds: nullableNonNegativeNumber(stats.processing_seconds),
			sessionDurationSeconds: nullableNonNegativeNumber(stats.session_duration_seconds),
			...(stats.duration_semantics === "session_extent_v1"
				? { durationSemantics: "session_extent_v1" as const }
				: {}),
			rtf: nullableNonNegativeNumber(stats.rtf),
			wordCount:
				stats.word_count === null || stats.word_count === undefined
					? null
					: nonNegativeInteger(stats.word_count),
			segmentCount:
				stats.segment_count === null || stats.segment_count === undefined
					? null
					: nonNegativeInteger(stats.segment_count),
			trackCount:
				stats.track_count === null || stats.track_count === undefined
					? null
					: nonNegativeInteger(stats.track_count),
		},
		warnings: row.warnings.map((warning) => contentText(warning, 1024)),
		...(warningSummary ? { warningSummary } : {}),
		publicationTarget: parsePublicationTarget(row.publication_target, {
			sourceId,
			runId,
			transcriptSha256: baseTranscriptSha256,
		}),
		review: {
			reviewedSegments,
			totalSegments,
			reviewPercent,
			editedSegments: nonNegativeInteger(review.edited_segments),
			wordCount: nonNegativeInteger(review.word_count),
			warningCount,
		},
		segments,
		sync: { status: "not_configured" },
	};
}

export function parseResultSummary(
	value: unknown,
	jobId: string,
): ResultSummary {
	const row = record(value);
	if (row.schema_version !== "tda_local_result_v1")
		throw new BridgeError("incompatible");
	if (row.job_id !== jobId) return invalid();
	if (record(row.sync).status !== "not_configured") return invalid();

	const base = {
		jobId: identifier(row.job_id),
		campaignId: identifier(row.campaign_id),
		sessionId: identifier(row.session_id),
		sourceId: identifier(row.source_id),
	};
	if (row.publication_bundle !== undefined && row.publication_bundle !== null) {
		const bundle = record(row.publication_bundle);
		if (bundle.schema_version !== "publication_bundle_v1")
			throw new BridgeError("incompatible");
		return { ...base, publicationId: sha256(bundle.publication_id) };
	}
	if (row.transcription !== undefined && row.transcription !== null) {
		const transcription = record(row.transcription);
		if (transcription.schema_version !== "tda_transcript_v1")
			throw new BridgeError("incompatible");
		if (transcription.artifact !== "transcript.json") return invalid();
		const transcriptSha256 = sha256(transcription.sha256);
		const runId = text(transcription.run_id, 196);
		if (!/^[A-Za-z0-9_-]{1,196}$/u.test(runId)) return invalid();
		return {
			...base,
			publicationId: transcriptSha256,
			profileId: transcriptionProfile(transcription.profile_id),
			transcriptSha256,
			runId,
		};
	}
	return invalid();
}
