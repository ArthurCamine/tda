import { LocalBridge } from "./bridge";
import { supportsTerminalJobDelete } from "./compatibility";
import { PROCESSING_REFRESH_POLICY } from "./refresh-policy";
import {
	BridgeError,
	type BridgeErrorCode,
	type BridgeErrorDetails,
	type Capabilities,
	type Health,
	type JobEvent,
	type LocalJob,
	type LocalReview,
	type LocalReviewSegment,
	type LocalReviewStatus,
	type LocalRunSummary,
	type LocalSourceSummary,
	type ResultSummary,
	type SystemSnapshot,
} from "./protocol";

export type ProcessingMutationKind =
	| "pause"
	| "resume"
	| "cancel"
	| "retry"
	| "delete"
	| "synthetic"
	| "result";

export type ProcessingMutation = Readonly<{
	kind: ProcessingMutationKind;
	targetId?: string;
}>;

export type ProcessingState = Readonly<{
	connection: "disconnected" | "connecting" | "connected" | "error";
	refreshing: boolean;
	refreshError: BridgeErrorCode | null;
	telemetryRefreshError: BridgeErrorCode | null;
	eventsRefreshError: BridgeErrorCode | null;
	libraryRefreshError: BridgeErrorCode | null;
	telemetryCheckedAt: string | null;
	mutation: ProcessingMutation | null;
	health: Health | null;
	capabilities: Capabilities | null;
	jobs: readonly LocalJob[];
	localSources: readonly LocalSourceSummary[];
	localRuns: readonly LocalRunSummary[];
	localReview: LocalReview | null;
	localReviewBusy: boolean;
	localReviewError: string | null;
	system: SystemSnapshot | null;
	events: readonly JobEvent[];
	eventsHasOlder: boolean;
	observedJobId: string | null;
	error: BridgeErrorCode | null;
	errorDetails: BridgeErrorDetails | null;
	serverError: string | null;
	checkedAt: string | null;
	result: ResultSummary | null;
	uncertainSubmission: boolean;
}>;

const initial: ProcessingState = {
	connection: "disconnected",
	refreshing: false,
	refreshError: null,
	telemetryRefreshError: null,
	eventsRefreshError: null,
	libraryRefreshError: null,
	telemetryCheckedAt: null,
	mutation: null,
	health: null,
	capabilities: null,
	jobs: [],
	localSources: [],
	localRuns: [],
	localReview: null,
	localReviewBusy: false,
	localReviewError: null,
	system: null,
	events: [],
	eventsHasOlder: false,
	observedJobId: null,
	error: null,
	errorDetails: null,
	serverError: null,
	checkedAt: null,
	result: null,
	uncertainSubmission: false,
};

function mergeJobEvents(
	current: readonly JobEvent[],
	incoming: readonly JobEvent[],
): JobEvent[] {
	const bySeq = new Map<number, JobEvent>();
	for (const event of current) bySeq.set(event.seq, event);
	for (const event of incoming) bySeq.set(event.seq, event);
	return [...bySeq.values()].sort((left, right) => left.seq - right.seq);
}

export class ProcessingController {
	#state = initial;
	#listeners = new Set<() => void>();
	#request = new AbortController();
	#epoch = 0;
	#readSequence = 0;
	#refreshSequence = 0;
	#lastDeepReadAt = 0;
	#submissionKey: string | null = null;
	#observedJobOverrideId: string | null = null;

	constructor(private readonly bridge = new LocalBridge()) {}

	snapshot = () => this.#state;
	serverSnapshot = () => initial;

	subscribe = (listener: () => void) => {
		this.#listeners.add(listener);
		return () => {
			this.#listeners.delete(listener);
		};
	};

	private update(patch: Partial<ProcessingState>) {
		this.#state = { ...this.#state, ...patch };
		for (const listener of this.#listeners) listener();
	}

	private resetRequest() {
		this.#epoch++;
		this.#readSequence++;
		this.#request.abort();
		this.#request = new AbortController();
	}

	disconnect = () => {
		this.resetRequest();
		this.#observedJobOverrideId = null;
		this.bridge.disconnect();
		// Retain the idempotency key in memory after an ambiguous submission.
		this.update({
			...initial,
			uncertainSubmission: this.#submissionKey !== null,
		});
	};

	private async runOperation(
		mutation: ProcessingMutation | null,
		action: (signal: AbortSignal) => Promise<void>,
	) {
		if (mutation && this.#state.mutation) return;

		const epoch = this.#epoch;
		const signal = this.#request.signal;
		// A user mutation wins over any older background read that may still be
		// completing. We do not need to abort the read; its result becomes stale.
		this.#readSequence++;
		this.update({
			...(mutation ? { mutation } : {}),
			error: null,
			errorDetails: null,
			serverError: null,
		});

		try {
			await action(signal);
		} catch (error) {
			if (epoch === this.#epoch) {
				const code =
					error instanceof BridgeError ? error.code : "service_error";
				const bridgeFailure = [
					"unreachable",
					"unauthorized",
					"forbidden",
					"api_incompatible",
					"version_incompatible",
					"session_incompatible",
					"incompatible",
					"invalid_response",
					"timeout",
				].includes(code);
				if (
					[
						"forbidden",
						"api_incompatible",
						"version_incompatible",
						"session_incompatible",
						"incompatible",
					].includes(code)
				)
					this.bridge.disconnect();
				const serverError =
					error instanceof BridgeError ? error.serverCode : null;
				const errorDetails =
					error instanceof BridgeError ? error.details : null;
				if (bridgeFailure) {
					this.update({
						...initial,
						connection: "error",
						error: code,
						errorDetails,
						serverError,
						uncertainSubmission: this.#submissionKey !== null,
					});
				} else {
					this.update({ error: code, errorDetails, serverError });
				}
			}
		} finally {
			if (epoch === this.#epoch && mutation)
				this.update({ mutation: null });
		}
	}

	private async readJobScope(
		scope: "active" | "history",
		signal: AbortSignal,
	): Promise<LocalJob[]> {
		let cursor: string | undefined;
		let pages = 0;
		const byId = new Map<string, LocalJob>();
		const seenCursors = new Set<string>();
		while (!signal.aborted) {
			const page = await this.bridge.jobPage(scope, signal, {
				...(cursor ? { cursor } : {}),
				limit: 200,
			});
			for (const job of page.jobs) byId.set(job.id, job);
			if (!page.hasMore) break;
			const next = page.nextCursor;
			if (!next || seenCursors.has(next))
				throw new BridgeError("invalid_response");
			seenCursors.add(next);
			cursor = next;
			pages += 1;
			if (pages > 1000) throw new BridgeError("invalid_response");
		}
		return [...byId.values()];
	}

	private async readJobs(
		signal: AbortSignal,
		capabilities: Capabilities,
	): Promise<LocalJob[]> {
		if (!capabilities.capabilities.includes("job.list.cursor"))
			return this.bridge.jobs(signal);
		const [active, history] = await Promise.all([
			this.readJobScope("active", signal),
			this.readJobScope("history", signal),
		]);
		const byId = new Map<string, LocalJob>();
		for (const job of history) byId.set(job.id, job);
		for (const job of active) byId.set(job.id, job);
		return [...byId.values()].sort((left, right) => {
			const updated =
				Date.parse(right.updated_at) - Date.parse(left.updated_at);
			return updated || right.id.localeCompare(left.id);
		});
	}

	private async readEventTail(
		jobId: string,
		signal: AbortSignal,
		previous: ProcessingState,
		cursorSupported: boolean,
	): Promise<{ events: JobEvent[]; hasOlder: boolean }> {
		if (!cursorSupported) {
			const page = await this.bridge.events(jobId, signal);
			return { events: [...page.events], hasOlder: false };
		}
		const sameJob = previous.observedJobId === jobId;
		if (!sameJob || previous.events.length === 0) {
			const page = await this.bridge.events(jobId, signal, { limit: 200 });
			return { events: [...page.events], hasOlder: page.hasMore };
		}

		let events = [...previous.events];
		let afterSeq = events.at(-1)?.seq;
		if (afterSeq === undefined)
			return { events, hasOlder: previous.eventsHasOlder };

		while (!signal.aborted) {
			const page = await this.bridge.events(jobId, signal, {
				afterSeq,
				limit: 200,
			});
			events = mergeJobEvents(events, page.events);
			if (!page.hasMore) break;
			const next = page.nextAfterSeq;
			if (next === null || next <= afterSeq)
				throw new BridgeError("invalid_response");
			afterSeq = next;
		}
		return { events, hasOlder: previous.eventsHasOlder };
	}

	private async read(
		signal: AbortSignal,
		options: Readonly<{ deep?: boolean; includeLibrary?: boolean }> = {},
	) {
		const sequence = ++this.#readSequence;
		const previous = this.#state;
		const deep = options.deep ?? true;
		const health =
			deep || !previous.health
				? await this.bridge.health(signal)
				: previous.health;
		const capabilities =
			deep || !previous.capabilities
				? await this.bridge.capabilities(signal)
				: previous.capabilities;
		const jobs = await this.readJobs(signal, capabilities);
		const nextQueued =
			jobs
				.filter((job) => job.status === "queued")
				.sort(
					(left, right) =>
						new Date(left.updated_at).getTime() -
						new Date(right.updated_at).getTime(),
				)[0] ?? null;
		const requestedObservedJob = this.#observedJobOverrideId
			? (jobs.find((job) => job.id === this.#observedJobOverrideId) ?? null)
			: null;
		if (this.#observedJobOverrideId && !requestedObservedJob)
			this.#observedJobOverrideId = null;
		const observedJob =
			requestedObservedJob ??
			jobs.find((job) => job.status === "running") ??
			nextQueued ??
			jobs[0] ??
			null;

		const reviewEnabled =
			capabilities.capabilities.includes("transcription.review");
		const domainErrors: Record<"telemetry" | "events" | "library", BridgeErrorCode | null> = {
			telemetry: null, events: null, library: reviewEnabled ? previous.libraryRefreshError : null,
		};
		const preserveSecondary = async <T,>(
			work: Promise<T>,
			fallback: T,
			domain: keyof typeof domainErrors,
		): Promise<T> => {
			try {
				return await work;
			} catch (error) {
				domainErrors[domain] ??=
					error instanceof BridgeError ? error.code : "service_error";
				return fallback;
			}
		};
		const eventFallback =
			previous.observedJobId === observedJob?.id
				? { events: [...previous.events], hasOlder: previous.eventsHasOlder }
				: { events: [] as JobEvent[], hasOlder: false };
		const [system, eventState] = await Promise.all([
			capabilities.capabilities.includes("system.telemetry")
				? preserveSecondary(this.bridge.system(signal), previous.system, "telemetry")
				: Promise.resolve(null),
			observedJob && capabilities.capabilities.includes("job.events")
				? preserveSecondary(
						this.readEventTail(
							observedJob.id,
							signal,
							previous,
							capabilities.capabilities.includes("job.events.cursor"),
						),
						eventFallback,
						"events",
					)
				: Promise.resolve(eventFallback),
		]);

		const terminalStatuses = new Set([
			"succeeded",
			"failed",
			"interrupted",
			"cancelled",
		]);
		const terminalTransition = jobs.some((next) => {
			if (!terminalStatuses.has(next.status)) return false;
			const before = previous.jobs.find((job) => job.id === next.id);
			return !before || !terminalStatuses.has(before.status);
		});
		const reloadLibrary =
			reviewEnabled && ((options.includeLibrary ?? true) || terminalTransition);

		let localSources: readonly LocalSourceSummary[] = reviewEnabled
			? previous.localSources
			: [];
		let localRuns: LocalRunSummary[] = reviewEnabled
			? [...previous.localRuns]
			: [];
		if (reloadLibrary) {
			domainErrors.library = null;
			try {
				localSources = await this.bridge.localSources(signal);
				const loadRunBatch = async (
					offset: number,
				): Promise<LocalRunSummary[]> => {
					if (signal.aborted || offset >= localSources.length) return [];
					const batch = await Promise.all(
						localSources.slice(offset, offset + 8).map((source) =>
							preserveSecondary(
								this.bridge.localRuns(source.sourceId, signal),
								previous.localRuns.filter(
									(run) => run.sourceId === source.sourceId,
								),
								"library",
							),
						),
					);
					if (signal.aborted) return [];
					return [
						...batch.flat(),
						...(await loadRunBatch(offset + 8)),
					];
				};
				localRuns = await loadRunBatch(0);
				localRuns.sort((left, right) => {
					const leftTime = left.completedAt ? Date.parse(left.completedAt) : 0;
					const rightTime = right.completedAt ? Date.parse(right.completedAt) : 0;
					return rightTime - leftTime;
				});
			} catch (error) {
				// A library read is secondary to the operational snapshot. Keep the
				// previous successful catalog until a later refresh succeeds.
				domainErrors.library ??=
					error instanceof BridgeError ? error.code : "service_error";
				localSources = previous.localSources;
				localRuns = [...previous.localRuns];
			}
		}

		if (signal.aborted || sequence !== this.#readSequence) return false;
		this.update({
			connection: "connected",
			health,
			capabilities,
			jobs,
			localSources,
			localRuns,
			system,
			events: eventState.events,
			eventsHasOlder: eventState.hasOlder,
			observedJobId: observedJob?.id ?? null,
			checkedAt: new Date().toISOString(),
			refreshError: null,
			telemetryRefreshError: domainErrors.telemetry,
			eventsRefreshError: domainErrors.events,
			libraryRefreshError: domainErrors.library,
			telemetryCheckedAt: domainErrors.telemetry ? previous.telemetryCheckedAt
				: system ? new Date().toISOString() : null,
		});
		if (deep) this.#lastDeepReadAt = Date.now();
		return true;
	}

	private refreshFailure(error: unknown) {
		const code = error instanceof BridgeError ? error.code : "service_error";
		const hardFailure = [
			"unauthorized",
			"forbidden",
			"api_incompatible",
			"version_incompatible",
			"session_incompatible",
			"incompatible",
		].includes(code);
		const serverError = error instanceof BridgeError ? error.serverCode : null;
		const errorDetails = error instanceof BridgeError ? error.details : null;

		if (hardFailure) {
			if (
				[
					"forbidden",
					"api_incompatible",
					"version_incompatible",
					"session_incompatible",
					"incompatible",
				].includes(code)
			)
				this.bridge.disconnect();
			this.update({
				...initial,
				connection: "error",
				error: code,
				errorDetails,
				serverError,
				uncertainSubmission: this.#submissionKey !== null,
			});
			return;
		}

		// A polling failure is stale data, not an instruction to erase the last
		// valid operational snapshot.
		this.update({ refreshError: code });
	}

	connect = async (legacyToken?: string) => {
		this.disconnect();
		this.update({ connection: "connecting" });
		await this.runOperation(null, async (signal) => {
			if (legacyToken) {
				// Compatibility path for tests/support tooling only. Product UI uses
				// automatic browser sessions and never asks the user to copy a token.
				await this.bridge.health(signal);
				if (signal.aborted) return;
				this.bridge.pair(legacyToken);
			} else {
				await this.bridge.bootstrap(signal);
			}
			if (signal.aborted) return;
			await this.read(signal, { deep: true, includeLibrary: true });
		});
	};

	refresh = async (
		reason: "background" | "manual" | "results" = "manual",
	) => {
		if (
			this.#state.connection !== "connected" ||
			this.#state.refreshing
		)
			return;

		const epoch = this.#epoch;
		const signal = this.#request.signal;
		const refreshSequence = ++this.#refreshSequence;
		const active = this.#state.jobs.some((job) => job.status === "running");
		const deepEveryMs = active
			? PROCESSING_REFRESH_POLICY.activeDeepRefreshMs
			: PROCESSING_REFRESH_POLICY.idleDeepRefreshMs;
		const deep =
			reason !== "background" ||
			Date.now() - this.#lastDeepReadAt >= deepEveryMs;
		const includeLibrary = reason === "manual" || reason === "results";

		this.update({ refreshing: true });
		try {
			await this.read(signal, { deep, includeLibrary });
		} catch (error) {
			if (epoch === this.#epoch && !signal.aborted)
				this.refreshFailure(error);
		} finally {
			if (
				epoch === this.#epoch &&
				refreshSequence === this.#refreshSequence
			)
				this.update({ refreshing: false });
		}
	};

	observeJob = async (id: string | null) => {
		if (this.#state.connection !== "connected") return;
		if (this.#observedJobOverrideId === id) return;

		this.#observedJobOverrideId = id;
		if (id !== null) {
			// Do not briefly show another job's events while the requested
			// diagnostic history is being loaded.
			this.update({ observedJobId: id, events: [], eventsHasOlder: false });
		}
		await this.runOperation(null, async (signal) => {
			await this.read(signal, { deep: false, includeLibrary: false });
		});
	};

	loadOlderEvents = async () => {
		const jobId = this.#state.observedJobId;
		const firstSeq = this.#state.events[0]?.seq;
		if (
			this.#state.connection !== "connected" ||
			!jobId ||
			!this.#state.eventsHasOlder ||
			firstSeq === undefined
		)
			return;
		const epoch = this.#epoch;
		const signal = this.#request.signal;
		try {
			const page = await this.bridge.events(jobId, signal, {
				beforeSeq: firstSeq,
				limit: 200,
			});
			if (
				epoch !== this.#epoch ||
				signal.aborted ||
				this.#state.observedJobId !== jobId
			)
				return;
			this.update({
				events: mergeJobEvents(page.events, this.#state.events),
				eventsHasOlder: page.hasMore,
				eventsRefreshError: null,
			});
		} catch (error) {
			if (epoch === this.#epoch && !signal.aborted)
				this.update({
					eventsRefreshError:
						error instanceof BridgeError ? error.code : "service_error",
				});
		}
	};

	lifecycle = async (action: "pause" | "resume") => {
		if (this.#state.connection !== "connected") return;
		await this.runOperation({ kind: action }, async (signal) => {
			await this.bridge.lifecycle(action, signal);
			await this.read(signal, { deep: true, includeLibrary: false });
		});
	};

	jobAction = async (id: string, action: "cancel" | "retry") => {
		if (this.#state.connection !== "connected") return;
		const job = this.#state.jobs.find((job) => job.id === id);
		if (
			!job ||
			(action === "cancel"
				? !["queued", "running"].includes(job.status)
				: !["failed", "interrupted"].includes(job.status) ||
					!job.error?.recoverable)
		)
			return;

		await this.runOperation({ kind: action, targetId: id }, async (signal) => {
			await this.bridge.jobAction(id, action, signal);
			await this.read(signal, { deep: false, includeLibrary: false });
		});
	};

	deleteJob = async (id: string) => {
		if (
			this.#state.connection !== "connected" ||
			!supportsTerminalJobDelete(this.#state.health?.service_version)
		)
			return;
		const job = this.#state.jobs.find((candidate) => candidate.id === id);
		if (!job || ["queued", "running"].includes(job.status)) return;

		await this.runOperation({ kind: "delete", targetId: id }, async (signal) => {
			await this.bridge.deleteJob(id, signal);
			if (this.#observedJobOverrideId === id) this.#observedJobOverrideId = null;
			if (!signal.aborted && this.#state.result?.jobId === id)
				this.update({ result: null });
			await this.read(signal, { deep: false, includeLibrary: true });
		});
	};

	synthetic = async () => {
		if (
			this.#state.connection !== "connected" ||
			this.#state.health?.lifecycle !== "ready" ||
			!this.#state.capabilities?.capabilities.includes("synthetic.fixture")
		)
			return;

		await this.runOperation({ kind: "synthetic" }, async (signal) => {
			this.#submissionKey ??= crypto.randomUUID();
			await this.bridge.synthetic(this.#submissionKey, signal);
			if (signal.aborted) return;
			this.#submissionKey = null;
			this.update({ uncertainSubmission: false });
			await this.read(signal, { deep: false, includeLibrary: false });
		});
	};

	private async reviewAction(
		action: (signal: AbortSignal) => Promise<LocalReview>,
	) {
		if (
			this.#state.connection !== "connected" ||
			this.#state.localReviewBusy
		)
			return;
		const epoch = this.#epoch;
		const signal = this.#request.signal;
		this.update({ localReviewBusy: true, localReviewError: null });
		try {
			const localReview = await action(signal);
			if (epoch === this.#epoch && !signal.aborted)
				this.update({ localReview, localReviewError: null });
		} catch (error) {
			if (epoch === this.#epoch && !signal.aborted) {
				this.update({
					localReviewError:
						error instanceof BridgeError
							? (error.serverCode ?? error.code)
							: "service_error",
				});
			}
		} finally {
			if (epoch === this.#epoch)
				this.update({ localReviewBusy: false });
		}
	}

	openLocalReview = async (sourceId: string, runId: string) => {
		if (
			!this.#state.localRuns.some(
				(run) => run.sourceId === sourceId && run.runId === runId,
			)
		)
			return;
		await this.reviewAction((signal) =>
			this.bridge.localReview(sourceId, runId, signal),
		);
	};

	repairPublicationTarget = async () => {
        const current = this.#state.localReview;
        if (!current || current.publicationTarget) return;
        await this.reviewAction((signal) => this.bridge.repairPublicationTarget(current.sourceId, current.runId, signal));
    };

	saveLocalReview = async (
		baseline: LocalReview,
		status: LocalReviewStatus,
		segments: readonly LocalReviewSegment[],
	) => {
		const current = this.#state.localReview;
		if (!current) return;
		if (current.sourceId !== baseline.sourceId || current.runId !== baseline.runId ||
			current.draftRevision !== baseline.draftRevision || current.draftSha256 !== baseline.draftSha256 ||
			current.baseTranscriptSha256 !== baseline.baseTranscriptSha256) {
			this.update({ localReviewError: "LOCAL_REVIEW_DRAFT_CONFLICT" });
			return;
		}
		await this.reviewAction((signal) =>
			this.bridge.saveLocalReview(
				current.sourceId,
				current.runId,
				baseline,
				status,
				segments,
				signal,
			),
		);
	};

	closeLocalReview = () => {
		if (this.#state.localReviewBusy) return;
		this.update({ localReview: null, localReviewError: null });
	};

	result = async (id: string) => {
		if (
			this.#state.connection !== "connected" ||
			!this.#state.jobs.some(
				(job) =>
					job.id === id &&
					job.result_available &&
					job.status === "succeeded",
			)
		)
			return;

		await this.runOperation({ kind: "result", targetId: id }, async (signal) => {
			const result = await this.bridge.result(id, signal);
			if (!signal.aborted) this.update({ result });
		});
	};
}
