"use client";

import {
	type KeyboardEvent as ReactKeyboardEvent,
	useEffect,
	useRef,
	useState,
	useSyncExternalStore,
} from "react";
import { AnimatedProgress } from "@/components/ui/animated-progress";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status";
import { ProcessingCommandBar } from "./command-bar";
import { supportsTerminalJobDelete } from "./compatibility";
import { ProcessingController } from "./controller";
import { LocalReviewWorkspace } from "./local-review";
import { publishApprovedLocalReview } from "./publication-client";
import type { QueueFilter } from "./queue-model";
import { ProcessingQueueView } from "./queue-view";
import { ProcessingSubmission } from "./submission";
import { PROCESSING_REFRESH_POLICY } from "./refresh-policy";
import {
	jobLabels,
	presentConnectionError,
	presentJobError,
	presentJobEvent,
	presentJobTitle,
	stageLabels,
} from "./presentation";
import type { JobEvent, LocalJob } from "./protocol";
import styles from "./processing.module.css";

type Confirmation =
	| { id: string; action: "cancel" | "retry" | "delete" }
	| { action: "resume" };

type ProcessingView = "overview" | "queue" | "results" | "diagnostics";

const processingViews: readonly { id: ProcessingView; label: string }[] = [
	{ id: "overview", label: "Visão geral" },
	{ id: "queue", label: "Fila" },
	{ id: "results", label: "Resultados" },
	{ id: "diagnostics", label: "Diagnóstico" },
];

function progressPercent(job: LocalJob): number | null {
	if (!job.progress) return null;
	if (job.progress.completed === 0 && job.status !== "succeeded") return null;
	if (
		job.status === "running" &&
		(job.progress.completed >= job.progress.total ||
			consolidationStages.has(job.stage))
	)
		return null;
	return Math.round((job.progress.completed / job.progress.total) * 100);
}

function formatBytes(value: number | null): string {
	if (value === null || !Number.isFinite(value)) return "—";
	const gib = value / 1024 ** 3;
	return `${gib >= 10 ? gib.toFixed(0) : gib.toFixed(1)} GB`;
}

function formatTime(value: string): string {
	return new Date(value).toLocaleTimeString("pt-BR", {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}

function progressCopy(job: LocalJob): string {
	if (!job.progress) return "Sem medida de progresso nesta etapa.";
	const unit = job.progress.unit === "items" ? "itens" : job.progress.unit;
	return `${job.progress.completed} de ${job.progress.total} ${unit}`;
}

const preparationStages = new Set([
	"queued",
	"preparing",
	"runtime_validation",
	"source_validation",
	"checking_model",
	"downloading_model",
	"model_prepare",
	"model_load",
	"loading_cpu",
	"loading_cuda",
	"loading_cuda_fallback",
]);
const processingStages = new Set([
	"fixture",
	"transcribing",
	"transcription",
	"diarization",
	"noise_cleanup",
	"resuming",
	"alignment",
]);
const consolidationStages = new Set([
	"energy_analysis",
	"cross_track_dedup",
	"merge_timeline",
	"turn_building",
	"result_prepare",
	"consolidating",
	"complete",
]);

function pipelineState(
	stage: string,
	phase: "preparation" | "processing" | "consolidation",
): "current" | "done" | "pending" {
	if (phase === "preparation") return preparationStages.has(stage) ? "current" : "done";
	if (phase === "processing") {
		if (processingStages.has(stage)) return "current";
		return consolidationStages.has(stage) ? "done" : "pending";
	}
	return consolidationStages.has(stage) ? "current" : "pending";
}

function eventTrackContext(events: readonly JobEvent[]) {
	for (const event of events) {
		const track = event.data.track;
		const total = event.data.total_tracks;
		const speaker = event.data.speaker;
		const window = event.data.window;
		const segment = event.data.segment;
		if (
			typeof track === "number" ||
			typeof speaker === "string" ||
			typeof window === "number" ||
			typeof segment === "number"
		) {
			return {
				track: typeof track === "number" ? track : null,
				total: typeof total === "number" ? total : null,
				speaker: typeof speaker === "string" ? speaker : null,
				window: typeof window === "number" ? window : null,
				segment: typeof segment === "number" ? segment : null,
			};
		}
	}
	return null;
}

export function ProcessingPanel({
	publicationEnabled = false,
}: Readonly<{ publicationEnabled?: boolean }>) {
	const [controller] = useState(() => new ProcessingController());
	const state = useSyncExternalStore(
		controller.subscribe,
		controller.snapshot,
		controller.serverSnapshot,
	);
	const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
	const [view, setView] = useState<ProcessingView>("overview");
	const [queueFilter, setQueueFilter] = useState<QueueFilter>("active");
	const [queueSearchReset, setQueueSearchReset] = useState(0);
	const dialog = useRef<HTMLDialogElement>(null);

	useEffect(() => {
		void controller.connect();
		return () => controller.disconnect();
	}, [controller]);
	useEffect(() => {
		if (state.connection !== "connected" || state.mutation) return;
		const hasActiveWork = state.jobs.some((job) => job.status === "running");
		const delay = hasActiveWork
			? PROCESSING_REFRESH_POLICY.activePollMs
			: PROCESSING_REFRESH_POLICY.idlePollMs;
		const timer = window.setTimeout(() => {
			if (document.visibilityState === "visible")
				void controller.refresh("background");
		}, delay);
		const visible = () => {
			if (document.visibilityState === "visible")
				void controller.refresh("background");
		};
		document.addEventListener("visibilitychange", visible);
		return () => {
			window.clearTimeout(timer);
			document.removeEventListener("visibilitychange", visible);
		};
	}, [controller, state.connection, state.jobs, state.mutation]);
	useEffect(() => {
		if (confirmation) dialog.current?.showModal();
		else dialog.current?.close();
	}, [confirmation]);

	const connected = state.connection === "connected";
	const label = connected
		? { preparing: "Em preparação", ready: "Pronto", paused: "Fila pausada" }[
				state.health?.lifecycle ?? "preparing"
			]
		: state.connection === "connecting"
			? "Conectando"
			: state.error === "version_incompatible"
				? "Atualização necessária"
				: state.error === "api_incompatible"
					? "API incompatível"
					: state.error === "session_incompatible" || state.error === "incompatible"
						? "Companion incompatível"
						: "Serviço desconectado";
	const running = state.jobs.filter((job) => job.status === "running");
	const queued = state.jobs
		.filter((job) => job.status === "queued")
		.sort(
			(left, right) =>
				new Date(left.updated_at).getTime() - new Date(right.updated_at).getTime(),
		);
	const attention = state.jobs.filter((job) =>
		["failed", "interrupted"].includes(job.status),
	);
	const activeJob = running[0] ?? null;
	const activePercent = activeJob ? progressPercent(activeJob) : null;
	const observedJob = state.jobs.find((job) => job.id === state.observedJobId) ?? activeJob;
	const observedJobLive =
		observedJob !== null &&
		["queued", "running"].includes(observedJob.status);
	const trackContext =
		activeJob && state.observedJobId === activeJob.id
			? eventTrackContext(state.events)
			: null;
	const canDeleteJobs = supportsTerminalJobDelete(state.health?.service_version);

	async function confirm() {
		const choice = confirmation;
		setConfirmation(null);
		if (!choice) return;
		if (choice.action === "resume") await controller.lifecycle("resume");
		else if (choice.action === "delete") await controller.deleteJob(choice.id);
		else {
			await controller.jobAction(choice.id, choice.action);
			if (choice.action === "retry") {
				const retried = controller
					.snapshot()
					.jobs.find((job) => job.id === choice.id);
				if (retried && ["queued", "running"].includes(retried.status))
					setQueueFilter("active");
			}
		}
	}

	function activateView(next: ProcessingView) {
		const leavingDiagnostics = view === "diagnostics" && next !== "diagnostics";
		setView(next);
		if (leavingDiagnostics) void controller.observeJob(null);
		if (next === "results") void controller.refresh("results");
	}

	function openAttentionQueue() {
		if (view === "diagnostics") void controller.observeJob(null);
		setQueueFilter("attention");
		setQueueSearchReset((value) => value + 1);
		setView("queue");
		requestAnimationFrame(() => {
			document.querySelector("[data-processing-queue='true']")?.scrollIntoView({
				block: "nearest",
			});
		});
	}

	function selectViewFromKeyboard(
		event: ReactKeyboardEvent<HTMLButtonElement>,
		index: number,
	) {
		let nextIndex: number | null = null;
		if (event.key === "ArrowRight") {
			nextIndex = (index + 1) % processingViews.length;
		} else if (event.key === "ArrowLeft") {
			nextIndex = (index - 1 + processingViews.length) % processingViews.length;
		} else if (event.key === "Home") {
			nextIndex = 0;
		} else if (event.key === "End") {
			nextIndex = processingViews.length - 1;
		}
		if (nextIndex === null) return;
		event.preventDefault();
		const next = processingViews[nextIndex];
		if (!next) return;
		activateView(next.id);
		requestAnimationFrame(() => {
			document.getElementById(`processing-tab-${next.id}`)?.focus();
		});
	}

	return (
		<div className={styles.panel} data-global-loading="off">
			<div
				className={styles.processingTabs}
				aria-label="Áreas do processamento"
				role="tablist"
			>
				{processingViews.map((item, index) => (
					<button
						key={item.id}
						id={`processing-tab-${item.id}`}
						type="button"
						role="tab"
						aria-selected={view === item.id}
						aria-controls={`processing-view-${item.id}`}
						data-active={view === item.id ? "true" : "false"}
						tabIndex={view === item.id ? 0 : -1}
						onClick={() => activateView(item.id)}
						onKeyDown={(event) => selectViewFromKeyboard(event, index)}
					>
						{item.label}
					</button>
				))}
			</div>

			<ProcessingCommandBar
				connection={state.connection}
				connected={connected}
				connectionLabel={label}
				health={state.health}
				system={state.system}
				refreshError={state.refreshError ?? state.telemetryRefreshError}
				checkedAt={state.telemetryCheckedAt ?? state.checkedAt}
				runningCount={running.length}
				queuedCount={queued.length}
				attentionCount={attention.length}
				refreshing={state.refreshing}
				pendingLifecycle={
					state.mutation?.kind === "pause" || state.mutation?.kind === "resume"
						? state.mutation.kind
						: null
				}
				onRefresh={() => void controller.refresh("manual")}
				onToggleLifecycle={() => {
					if (state.health?.lifecycle === "paused")
						setConfirmation({ action: "resume" });
					else if (state.health?.lifecycle === "ready")
						void controller.lifecycle("pause");
				}}
				onAttention={openAttentionQueue}
				onDiagnostics={() => activateView("diagnostics")}
			/>

			{!connected ? (
				<section className={styles.connection} aria-label="Conexão com o TDA Companion">
					<div className={styles.pairing}>
						<strong>
							{state.connection === "connecting"
								? "Conectando ao TDA Companion…"
								: state.error === "version_incompatible"
									? "TDA Companion precisa ser atualizado."
									: state.error === "api_incompatible" || state.error === "session_incompatible"
										? "TDA Companion incompatível com esta tela."
										: "TDA Companion não está conectado."}
						</strong>
						<p className={styles.pairingHelp}>
							{state.error === "version_incompatible"
								? "Instale uma versão compatível e tente novamente."
								: state.error === "api_incompatible" || state.error === "session_incompatible"
									? "Atualize o aplicativo local antes de tentar conectar novamente."
									: "Se o aplicativo estiver aberto, esta página conecta automaticamente. Se estiver fechado, abra o Companion e tente novamente."}
						</p>
						<div className={styles.pairingControls}>
							<Button
								type="button"
								size="sm"
								disabled={state.connection === "connecting"}
								onClick={() => {
									window.location.href = "tda-companion://open";
									void (async () => {
										for (const delay of [1200, 2200, 3500]) {
											await new Promise((resolve) => window.setTimeout(resolve, delay));
											await controller.connect();
											if (controller.snapshot().connection === "connected") break;
										}
									})();
								}}
							>
								Abrir TDA Companion
							</Button>
							<Button
								type="button"
								size="sm"
								variant="tertiary"
								disabled={state.connection === "connecting"}
								onClick={() => void controller.connect()}
							>
								Tentar novamente
							</Button>
						</div>
					</div>
				</section>
			) : null}

			{state.error ? (
				<p className={styles.connectionError} role="alert">
					{state.serverError
						? presentJobError(state.serverError)
						: presentConnectionError(state.error, state.errorDetails)}{" "}
					<small>Código: {state.serverError ?? state.error}</small>
				</p>
			) : null}

			{connected ? (
				<>
					<section
						id="processing-view-overview"
						className={styles.viewPanel}
						role="tabpanel"
						aria-labelledby="processing-tab-overview"
						hidden={view !== "overview"}
					>
						<div className={styles.overviewTop}>
							<section aria-labelledby="processing-now">
								<div className={styles.sectionHeading}>
									<h2 id="processing-now">Processando agora</h2>
									{state.checkedAt ? (
										<span>
											Atualizado às{" "}
											<time dateTime={state.checkedAt}>
												{formatTime(state.checkedAt)}
											</time>
										</span>
									) : null}
								</div>
								{activeJob ? (
									<article className={styles.activeJob}>
										<div className={styles.activeHeader}>
											<div>
												<span className={styles.overline}>
													{activeJob.context?.sessionId
														? `Sessão ${activeJob.context.sessionId}`
														: "Trabalho local"}
												</span>
												<h3>{presentJobTitle(activeJob)}</h3>
											</div>
											<StatusPill tone="accent">Processando</StatusPill>
										</div>
										<div className={styles.activeMeta}>
											<span>
												{stageLabels[activeJob.stage] ?? activeJob.stage}
											</span>
											{trackContext?.track != null &&
											trackContext.total != null ? (
												<span>
													Arquivo {trackContext.track} de {trackContext.total}
												</span>
											) : null}
											{trackContext?.speaker ? (
												<span>Voz: {trackContext.speaker}</span>
											) : null}
											{trackContext?.window != null ? (
												<span>Janela {trackContext.window}</span>
											) : null}
											{trackContext?.segment != null ? (
												<span>Segmento {trackContext.segment}</span>
											) : null}
											{activeJob.attempt > 0 ? (
												<span>Tentativa {activeJob.attempt}</span>
											) : null}
											<span>
												Worker ativo · {formatTime(activeJob.updated_at)}
											</span>
										</div>
										{activeJob.progress && activePercent !== null ? (
											<div className={styles.activeProgress}>
												<AnimatedProgress
													key={`${activeJob.id}:${activeJob.attempt}:${activeJob.stage}`}
													ariaLabel={`Progresso do trabalho ${activeJob.id}`}
													value={activeJob.progress.completed}
													max={activeJob.progress.total}
													valueText={progressCopy(activeJob)}
												/>
												<strong>{activePercent}%</strong>
												<span>{progressCopy(activeJob)}</span>
											</div>
										) : (
											<p className={styles.noProgress}>
												{activeJob.progress &&
												activeJob.progress.completed > 0
													? `${progressCopy(activeJob)} concluídos · ${stageLabels[activeJob.stage] ?? activeJob.stage}.`
													: "Progresso percentual ainda não disponível. O stage e a atividade do worker continuam sendo atualizados."}
											</p>
										)}
										<section
											className={styles.pipeline}
											aria-label="Etapa atual do processamento"
										>
											<span
												data-state={pipelineState(
													activeJob.stage,
													"preparation",
												)}
											>
												Preparação
											</span>
											<span
												data-state={pipelineState(
													activeJob.stage,
													"processing",
												)}
											>
												Processamento
											</span>
											<span
												data-state={pipelineState(
													activeJob.stage,
													"consolidation",
												)}
											>
												Consolidação
											</span>
										</section>
										<div className={styles.activeActions}>
											<Button
												size="sm"
												className={styles.dangerAction}
												disabled={
													state.mutation?.kind === "cancel" &&
													state.mutation.targetId === activeJob.id
												}
												onClick={() =>
													setConfirmation({
														id: activeJob.id,
														action: "cancel",
													})
												}
											>
												{state.mutation?.kind === "cancel" &&
												state.mutation.targetId === activeJob.id
													? "Cancelando…"
													: "Cancelar trabalho"}
											</Button>
										</div>
									</article>
								) : (
									<div className={styles.emptyState}>
										<strong>Nada processando agora.</strong>
										<span>
											{queued.length
												? "Há trabalhos aguardando a próxima execução."
												: "A fila local está livre."}
										</span>
									</div>
								)}
							</section>
							<ProcessingSubmission
								className={styles.submissionCard}
								compact
							/>
						</div>
					</section>

					<section
						id="processing-view-queue"
						className={styles.viewPanel}
						role="tabpanel"
						aria-labelledby="processing-tab-queue"
						hidden={view !== "queue"}
					>
						<ProcessingQueueView
							jobs={state.jobs}
							filter={queueFilter}
							onFilterChange={setQueueFilter}
							resetSearchKey={queueSearchReset}
							mutation={state.mutation}
							canDelete={canDeleteJobs}
							onCancel={(job) =>
								setConfirmation({ id: job.id, action: "cancel" })
							}
							onRetry={(job) =>
								setConfirmation({ id: job.id, action: "retry" })
							}
							onResult={(job) => void controller.result(job.id)}
							onDelete={(job) =>
								setConfirmation({ id: job.id, action: "delete" })
							}
							onDiagnostics={(job) => {
								activateView("diagnostics");
								void controller.observeJob(job.id);
							}}
						/>
					</section>

					<section
						id="processing-view-results"
						className={styles.viewPanel}
						role="tabpanel"
						aria-labelledby="processing-tab-results"
						hidden={view !== "results"}
					>
						{state.libraryRefreshError ? <p role="status">Resultados desatualizados. A última leitura foi preservada; tente atualizar.</p> : null}
						<LocalReviewWorkspace
							runs={state.localRuns}
							review={state.localReview}
							busy={state.localReviewBusy}
							error={state.localReviewError}
							publicationEnabled={publicationEnabled}
							onOpen={(sourceId, runId) =>
								controller.openLocalReview(sourceId, runId)
							}
							onLoadLatest={controller.loadLatestLocalReview}
							onRepairTarget={state.capabilities?.capabilities.includes("transcription.target.repair") ? controller.repairPublicationTarget : undefined}
							onSave={(revision, status, segments) =>
								controller.saveLocalReview(revision, status, segments)
							}
							onClose={controller.closeLocalReview}
							onPublish={(review, operationId, expectedCurrentRevisionId, profileScope) =>
								publishApprovedLocalReview(review, operationId, expectedCurrentRevisionId, fetch, profileScope)
							}
						/>

						<section className={styles.syncStrip} aria-labelledby="local-sync">
							<div>
								<h2 id="local-sync">Sincronização com o Edit</h2>
								<p>
									{publicationEnabled ? (
										<>
											<strong>Publicação revisionada disponível.</strong>{" "}
											Somente um draft salvo como Aprovado localmente e uma
											confirmação explícita podem publicar.
										</>
									) : (
										<>
											<strong>Sincronização não configurada.</strong>{" "}
											Concluir localmente não significa enviar ou publicar.
										</>
									)}
								</p>
							</div>
							{state.result ? (
								<div className={styles.resultSummary} role="status">
									<span>Resultado local</span>
									<strong>{state.result.sessionId}</strong>
									<small>
										{state.result.runId
											? `Run ${state.result.runId} · SHA ${state.result.transcriptSha256?.slice(0, 12) ?? "—"}…`
											: `Pacote ${state.result.publicationId.slice(0, 12)}…`}
									</small>
								</div>
							) : null}
						</section>
					</section>

					<section
						id="processing-view-diagnostics"
						className={styles.viewPanel}
						role="tabpanel"
						aria-labelledby="processing-tab-diagnostics"
						hidden={view !== "diagnostics"}
					>
						<aside
							className={`${styles.inspector} ${styles.inspectorFull}`}
							aria-labelledby="processing-details"
						>
							<div className={styles.inspectorHeader}>
								<div>
									<span className={styles.overline}>Trabalho observado</span>
									<h2 id="processing-details">
										Detalhes do processamento
									</h2>
								</div>
							</div>
							<details className={styles.systemDetails}>
								<summary>Companion e máquina</summary>
								<dl className={styles.jobDetails}>
									<div>
										<dt>API</dt>
										<dd>{state.health?.api_version ?? "—"}</dd>
									</div>
									<div>
										<dt>Serviço</dt>
										<dd>{state.health?.service_version ?? "—"}</dd>
									</div>
									<div>
										<dt>Lifecycle</dt>
										<dd>{state.health?.lifecycle ?? "—"}</dd>
									</div>
									<div>
										<dt>Dispositivo</dt>
										<dd>{state.capabilities?.device.label ?? "—"}</dd>
									</div>
									<div>
										<dt>Sistema</dt>
										<dd>{state.system?.host.os ?? "—"}</dd>
									</div>
									<div>
										<dt>CPU</dt>
										<dd>{state.system?.host.cpu ?? "—"}</dd>
									</div>
									<div>
										<dt>RAM</dt>
										<dd>
											{state.system
												? `${formatBytes(state.system.memory.usedBytes)} / ${formatBytes(state.system.memory.totalBytes)} · ${state.system.memory.percent === null ? "—" : `${Math.round(state.system.memory.percent)}%`}`
												: "—"}
										</dd>
									</div>
									{state.system?.gpus.map((item) => (
										<div key={item.index}>
											<dt>GPU {item.index}</dt>
											<dd>
												{item.name} · {item.utilizationPercent === null ? "—" : `${Math.round(item.utilizationPercent)}%`} · {formatBytes(item.memoryUsedBytes)} / {formatBytes(item.memoryTotalBytes)} VRAM
											</dd>
										</div>
									))}
									<div className={styles.detailWide}>
										<dt>Capabilities</dt>
										<dd className={styles.mono}>
											{state.capabilities?.capabilities.join(", ") || "—"}
										</dd>
									</div>
								</dl>
							</details>

							{observedJob ? (
								<dl className={styles.jobDetails}>
									<div>
										<dt>Trabalho</dt>
										<dd>{presentJobTitle(observedJob)}</dd>
									</div>
									<div>
										<dt>Estado</dt>
										<dd>{jobLabels[observedJob.status]}</dd>
									</div>
									<div>
										<dt>Etapa</dt>
										<dd>
											{stageLabels[observedJob.stage] ?? observedJob.stage}
										</dd>
									</div>
									{observedJob.context?.sessionId ? (
										<div>
											<dt>Sessão</dt>
											<dd>{observedJob.context.sessionId}</dd>
										</div>
									) : null}
									<div>
										<dt>Tentativa</dt>
										<dd>{observedJob.attempt}</dd>
									</div>
									<div>
										<dt>ID local</dt>
										<dd className={styles.mono}>{observedJob.id}</dd>
									</div>
								</dl>
							) : (
								<p className={styles.inspectorEmpty}>
									Nenhum trabalho observado.
								</p>
							)}

							<div className={styles.logHeader}>
								<h3>
									{observedJobLive ? "Log em tempo real" : "Histórico de eventos"}
								</h3>
								<span>
									{state.events.length
										? observedJobLive
											? "● ativo"
											: `${state.events.length} mais recente${state.events.length === 1 ? "" : "s"}`
										: "sem eventos"}
								</span>
							</div>
							{state.eventsRefreshError ? <p role="status">Eventos desatualizados. O último histórico disponível foi preservado.</p> : null}
							<div
								className={`${styles.log} ${state.events.length ? "" : styles.logEmpty}`}
								role="log"
								aria-label="Eventos do processamento local"
								aria-relevant="additions text"
							>
								{state.events.length ? (
									state.events.slice(0, 100).map((event) => {
										const presented = presentJobEvent(event);
										return (
											<div
												className={styles.logEntry}
												key={event.seq}
												data-level={event.level}
											>
												<time dateTime={event.at}>
													{formatTime(event.at)}
												</time>
												<div>
													<span>{presented.title}</span>
													{presented.detail ? (
														<small>{presented.detail}</small>
													) : null}
												</div>
											</div>
										);
									})
								) : (
									<p>
										Nenhum evento detalhado disponível para este trabalho.
									</p>
								)}
							</div>

							{state.capabilities?.capabilities.includes(
								"synthetic.fixture",
							) ? (
								<div className={styles.integrationTool}>
									<div>
										<strong>Ensaio sintético</strong>
										<span>
											Diagnóstico pequeno, sem áudio e sem publicação.
										</span>
									</div>
									<Button
										size="sm"
										disabled={
											state.mutation?.kind === "synthetic" ||
											state.health?.lifecycle !== "ready"
										}
										onClick={() => void controller.synthetic()}
									>
										{state.mutation?.kind === "synthetic"
											? "Executando…"
											: "Executar ensaio sintético"}
									</Button>
								</div>
							) : null}

							{state.uncertainSubmission ? (
								<p className={styles.connectionError} role="alert">
									A resposta desta tentativa não chegou. Reconecte e
									consulte a fila antes de iniciar outra tentativa; a chave
									desta aba será reutilizada.
								</p>
							) : null}
						</aside>
					</section>
				</>
			) : (
				<section className={styles.disconnectedQueue} aria-labelledby="local-queue">
					<h2 id="local-queue">Fila local</h2>
					<p>
						Conecte o serviço para consultar a fila persistida. A ausência de
						conexão não significa que o processamento parou.
					</p>
				</section>
			)}


			<dialog
				ref={dialog}
				className={styles.dialog}
				onCancel={(event) => {
					event.preventDefault();
					setConfirmation(null);
				}}
			>
				{confirmation ? (
					<>
						<h2>
							{confirmation.action === "resume"
								? "Retomar a fila local?"
								: confirmation.action === "cancel"
									? "Cancelar este trabalho?"
									: confirmation.action === "delete"
										? "Excluir este trabalho?"
										: "Repetir este trabalho?"}
						</h2>
						<p>
							{confirmation.action === "resume"
								? "O serviço poderá iniciar os trabalhos que aguardam na fila."
								: confirmation.action === "cancel"
									? `O cancelamento será enviado ao trabalho ${confirmation.id}.`
									: confirmation.action === "delete"
										? `O trabalho ${confirmation.id}, seus eventos e a referência de resultado na fila serão excluídos. As transcrições em Resultados, revisões, modelos, sessão Craig e checkpoints serão preservados.`
										: `Uma nova tentativa será criada para ${confirmation.id}; checkpoints compatíveis serão reutilizados quando disponíveis, sem prometer retomada exata de toda etapa.`}
						</p>
						<div className={styles.dialogActions}>
							<Button onClick={() => setConfirmation(null)}>Voltar</Button>
							<Button variant="primary" onClick={() => void confirm()}>
								{confirmation.action === "delete" ? "Excluir" : "Confirmar"}
							</Button>
						</div>
					</>
				) : null}
			</dialog>
		</div>
	);
}
