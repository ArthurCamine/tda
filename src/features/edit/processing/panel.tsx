"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { StatusPill, type StatusTone } from "@/components/ui/status";
import { ProcessingController } from "./controller";
import {
	connectionHelp,
	jobLabels,
	presentJobEvent,
	stageLabels,
} from "./presentation";
import type { JobEvent, LocalJob, SystemGpu } from "./protocol";
import styles from "./processing.module.css";

type Confirmation =
	| { id: string; action: "cancel" | "retry" | "delete" }
	| { action: "resume" };

function jobTone(status: LocalJob["status"]): StatusTone {
	if (status === "succeeded") return "success";
	if (status === "failed" || status === "interrupted") return "danger";
	if (status === "running" || status === "queued") return "accent";
	return "neutral";
}

function jobTitle(job: LocalJob): string {
	if (job.kind === "synthetic.fixture") return "Ensaio sintético";
	if (job.kind === "transcription.session") return "Transcrição de sessão";
	return job.kind;
}

function progressPercent(job: LocalJob): number | null {
	if (!job.progress) return null;
	return Math.round((job.progress.completed / job.progress.total) * 100);
}

function formatBytes(value: number | null): string {
	if (value === null || !Number.isFinite(value)) return "—";
	const gib = value / 1024 ** 3;
	return `${gib >= 10 ? gib.toFixed(0) : gib.toFixed(1)} GB`;
}

function formatPercent(value: number | null): string {
	return value === null ? "—" : `${Math.round(value)}%`;
}

function formatTime(value: string): string {
	return new Date(value).toLocaleTimeString("pt-BR", {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}

function formatDateTime(value: string): string {
	return new Date(value).toLocaleString("pt-BR", {
		day: "2-digit",
		month: "short",
		hour: "2-digit",
		minute: "2-digit",
	});
}

function progressCopy(job: LocalJob): string {
	if (!job.progress) return "Sem medida de progresso nesta etapa.";
	const unit = job.progress.unit === "items" ? "itens" : job.progress.unit;
	return `${job.progress.completed} de ${job.progress.total} ${unit}`;
}

function eventTrackContext(events: readonly JobEvent[]) {
	for (const event of events) {
		const track = event.data.track;
		const total = event.data.total_tracks;
		const speaker = event.data.speaker;
		if (typeof track === "number" || typeof speaker === "string") {
			return {
				track: typeof track === "number" ? track : null,
				total: typeof total === "number" ? total : null,
				speaker: typeof speaker === "string" ? speaker : null,
			};
		}
	}
	return null;
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
	return (
		<div className={styles.metric}>
			<span>{label}</span>
			<strong>{value}</strong>
			{detail ? <small>{detail}</small> : null}
		</div>
	);
}

function GpuMetric({ gpu }: { gpu: SystemGpu }) {
	return (
		<div className={styles.metric}>
			<span>GPU</span>
			<strong>{formatPercent(gpu.utilizationPercent)}</strong>
			<small title={gpu.name}>
				{formatBytes(gpu.memoryUsedBytes)} / {formatBytes(gpu.memoryTotalBytes)} VRAM
			</small>
		</div>
	);
}

function JobRow({
	job,
	busy,
	onCancel,
	onRetry,
	onResult,
	onDelete,
}: {
	job: LocalJob;
	busy: boolean;
	onCancel: () => void;
	onRetry: () => void;
	onResult: () => void;
	onDelete: () => void;
}) {
	const percent = progressPercent(job);
	return (
		<li className={styles.jobRow} data-status={job.status}>
			<div className={styles.jobRowMain}>
				<strong>{jobTitle(job)}</strong>
				<span>
					{job.context?.sessionId ? `Sessão ${job.context.sessionId} · ` : ""}
					{stageLabels[job.stage] ?? job.stage}
				</span>
			</div>
			<div className={styles.jobRowProgress}>
				{job.progress ? (
					<>
						<progress
							aria-label={`Progresso do trabalho ${job.id}`}
							value={job.progress.completed}
							max={job.progress.total}
						/>
						<span>{percent}%</span>
					</>
				) : (
					<span>Sem medida de progresso nesta etapa.</span>
				)}
			</div>
			<StatusPill tone={jobTone(job.status)}>{jobLabels[job.status]}</StatusPill>
			<time dateTime={job.updated_at}>{formatDateTime(job.updated_at)}</time>
			<div className={styles.rowActions}>
				{["queued", "running"].includes(job.status) ? (
					<Button size="sm" disabled={busy} onClick={onCancel}>
						Cancelar trabalho
					</Button>
				) : null}
				{["failed", "interrupted"].includes(job.status) && job.error?.recoverable ? (
					<Button size="sm" disabled={busy} onClick={onRetry}>
						Repetir trabalho
					</Button>
				) : null}
				{job.status === "succeeded" && job.result_available ? (
					<Button size="sm" disabled={busy} onClick={onResult}>
						Consultar resultado local
					</Button>
				) : null}
				{["succeeded", "failed", "interrupted", "cancelled"].includes(job.status) ? (
					<Button size="sm" variant="tertiary" disabled={busy} onClick={onDelete}>
						Remover
					</Button>
				) : null}
			</div>
		</li>
	);
}

export function ProcessingPanel() {
	const [controller] = useState(() => new ProcessingController());
	const state = useSyncExternalStore(
		controller.subscribe,
		controller.snapshot,
		controller.serverSnapshot,
	);
	const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
	const token = useRef<HTMLInputElement>(null);
	const dialog = useRef<HTMLDialogElement>(null);

	useEffect(() => () => controller.disconnect(), [controller]);
	useEffect(() => {
		if (state.connection !== "connected" || state.busy) return;
		const timer = setTimeout(() => {
			if (document.visibilityState === "visible") void controller.refresh();
		}, 3000);
		const visible = () => {
			if (document.visibilityState === "visible") void controller.refresh();
		};
		document.addEventListener("visibilitychange", visible);
		return () => {
			clearTimeout(timer);
			document.removeEventListener("visibilitychange", visible);
		};
	}, [controller, state.connection, state.busy]);
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
			: state.error === "incompatible"
				? "Versão incompatível"
				: "Serviço desconectado";
	const running = state.jobs.filter((job) => job.status === "running");
	const queued = state.jobs.filter((job) => job.status === "queued");
	const succeeded = state.jobs.filter((job) => job.status === "succeeded");
	const attention = state.jobs.filter((job) =>
		["failed", "interrupted"].includes(job.status),
	);
	const finished = state.jobs.filter((job) =>
		["succeeded", "cancelled"].includes(job.status),
	);
	const activeJob = running[0] ?? null;
	const observedJob = state.jobs.find((job) => job.id === state.observedJobId) ?? activeJob;
	const gpu = state.system?.gpus[0] ?? null;
	const trackContext = eventTrackContext(state.events);

	async function confirm() {
		const choice = confirmation;
		setConfirmation(null);
		if (!choice) return;
		if (choice.action === "resume") await controller.lifecycle("resume");
		else if (choice.action === "delete") await controller.deleteJob(choice.id);
		else await controller.jobAction(choice.id, choice.action);
	}

	const renderRow = (job: LocalJob) => (
		<JobRow
			key={job.id}
			job={job}
			busy={state.busy}
			onCancel={() => setConfirmation({ id: job.id, action: "cancel" })}
			onRetry={() => setConfirmation({ id: job.id, action: "retry" })}
			onResult={() => void controller.result(job.id)}
			onDelete={() => setConfirmation({ id: job.id, action: "delete" })}
		/>
	);

	return (
		<div className={styles.panel} data-global-loading="off">
			<section className={styles.connection} aria-labelledby="local-computer">
				<div className={styles.connectionMain}>
					<div className={styles.computerGlyph} aria-hidden="true" />
					<div>
						<div className={styles.connectionTitle}>
							<h2 id="local-computer">Computador local</h2>
							<StatusPill tone={connected ? "success" : state.error ? "danger" : "neutral"}>
								{label}
							</StatusPill>
						</div>
						{connected ? (
							<p className={styles.connectionMeta}>
								{state.capabilities?.device.label} · API v1 · serviço {state.health?.service_version}
								{state.system?.host.os ? ` · ${state.system.host.os}` : ""}
							</p>
						) : (
							<p className={styles.connectionMeta}>
								O processamento e os áudios permanecem neste computador.
							</p>
						)}
					</div>
				</div>

				{connected ? (
					<>
						<section className={styles.telemetry} aria-label="Uso do computador local">
							{gpu ? <GpuMetric gpu={gpu} /> : null}
							<Metric
								label="CPU"
								value={formatPercent(state.system?.cpu.utilizationPercent ?? null)}
								detail={state.system?.host.cpu ?? undefined}
							/>
							<Metric
								label="RAM"
								value={formatPercent(state.system?.memory.percent ?? null)}
								detail={
									state.system
										? `${formatBytes(state.system.memory.usedBytes)} / ${formatBytes(state.system.memory.totalBytes)}`
										: "Telemetria indisponível"
								}
							/>
						</section>
						<div className={styles.connectionActions}>
							<Button size="sm" disabled={state.busy} onClick={() => void controller.refresh()}>
								Atualizar estado
							</Button>
							{state.health?.lifecycle === "paused" ? (
								<Button size="sm" disabled={state.busy} onClick={() => setConfirmation({ action: "resume" })}>
									Retomar fila
								</Button>
							) : state.health?.lifecycle === "ready" ? (
								<Button size="sm" disabled={state.busy} onClick={() => void controller.lifecycle("pause")}>
									Pausar novas execuções
								</Button>
							) : null}
							<Button
								size="sm"
								variant="tertiary"
								onClick={() => {
									setConfirmation(null);
									controller.disconnect();
								}}
							>
								Desconectar esta aba
							</Button>
						</div>
					</>
				) : (
					<form
						className={styles.pairing}
						onSubmit={(event) => {
							event.preventDefault();
							const value = token.current?.value ?? "";
							if (token.current) token.current.value = "";
							void controller.connect(value.trim());
						}}
					>
						<label htmlFor="pair-token">Token de pareamento do aplicativo local</label>
						<div className={styles.pairingControls}>
							<input
								ref={token}
								id="pair-token"
								type="password"
								autoComplete="off"
								spellCheck={false}
								required
								minLength={32}
								maxLength={256}
								disabled={state.busy}
								aria-describedby="pair-help"
							/>
							<Button type="submit" size="sm" disabled={state.busy}>
								Conectar neste computador
							</Button>
						</div>
						<p id="pair-help" className={styles.pairingHelp}>
							O token fica apenas na memória desta aba. Recarregar exige novo pareamento.
						</p>
					</form>
				)}
				{state.error ? (
					<p className={styles.connectionError} role="alert">
						{connectionHelp[state.error]} <small>Código: {state.error}</small>
					</p>
				) : null}
			</section>

			{connected ? (
				<>
					<section className={styles.summary} aria-label="Resumo da fila local">
						<Metric label="Processando" value={String(running.length)} />
						<Metric label="Na fila" value={String(queued.length)} />
						<Metric label="Concluídos" value={String(succeeded.length)} />
						<Metric label="Com atenção" value={String(attention.length)} />
					</section>

					<div className={styles.workspace}>
						<div className={styles.primaryColumn}>
							<section aria-labelledby="processing-now">
								<div className={styles.sectionHeading}>
									<h2 id="processing-now">Processando agora</h2>
									{state.checkedAt ? (
										<span>
											Atualizado às <time dateTime={state.checkedAt}>{formatTime(state.checkedAt)}</time>
										</span>
									) : null}
								</div>
								{activeJob ? (
									<article className={styles.activeJob}>
										<div className={styles.activeHeader}>
											<div>
												<span className={styles.overline}>{activeJob.context?.sessionId ? `Sessão ${activeJob.context.sessionId}` : "Trabalho local"}</span>
												<h3>{jobTitle(activeJob)}</h3>
											</div>
											<StatusPill tone="accent">Processando</StatusPill>
										</div>
										<div className={styles.activeMeta}>
											<span>{stageLabels[activeJob.stage] ?? activeJob.stage}</span>
											{trackContext?.track != null && trackContext.total != null ? (
												<span>Arquivo {trackContext.track} de {trackContext.total}</span>
											) : null}
											{trackContext?.speaker ? <span>Voz: {trackContext.speaker}</span> : null}
											{activeJob.attempt > 0 ? <span>Tentativa {activeJob.attempt}</span> : null}
										</div>
										{activeJob.progress ? (
											<div className={styles.activeProgress}>
												<progress
													aria-label={`Progresso do trabalho ${activeJob.id}`}
													value={activeJob.progress.completed}
													max={activeJob.progress.total}
												/>
												<strong>{progressPercent(activeJob)}%</strong>
												<span>{progressCopy(activeJob)}</span>
											</div>
										) : (
											<p className={styles.noProgress}>Sem medida de progresso nesta etapa.</p>
										)}
										<section className={styles.pipeline} aria-label="Etapa atual do processamento">
											<span data-state={activeJob.stage === "queued" ? "current" : "done"}>Preparação</span>
											<span data-state={["fixture", "transcribing", "diarization", "noise_cleanup", "resuming"].includes(activeJob.stage) ? "current" : activeJob.stage === "complete" ? "done" : "pending"}>Processamento</span>
											<span data-state={activeJob.stage === "complete" ? "current" : "pending"}>Consolidação</span>
										</section>
										<div className={styles.activeActions}>
											<Button
												size="sm"
												className={styles.dangerAction}
												disabled={state.busy}
												onClick={() => setConfirmation({ id: activeJob.id, action: "cancel" })}
											>
												Cancelar trabalho
											</Button>
										</div>
									</article>
								) : (
									<div className={styles.emptyState}>
										<strong>Nada processando agora.</strong>
										<span>{queued.length ? "Há trabalhos aguardando a próxima execução." : "A fila local está livre."}</span>
									</div>
								)}
							</section>

							{queued.length ? (
								<section aria-labelledby="queued-jobs">
									<div className={styles.sectionHeading}>
										<h2 id="queued-jobs">A seguir na fila</h2>
										<span>{queued.length}</span>
									</div>
									<ul className={styles.compactJobs}>{queued.map(renderRow)}</ul>
								</section>
							) : null}

							{attention.length ? (
								<section aria-labelledby="attention-jobs">
									<div className={styles.sectionHeading}>
										<h2 id="attention-jobs">Precisam de atenção</h2>
									</div>
									<ul className={styles.compactJobs}>{attention.map(renderRow)}</ul>
								</section>
							) : null}

							{finished.length ? (
								<section aria-labelledby="recent-jobs">
									<div className={styles.sectionHeading}>
										<h2 id="recent-jobs">Finalizados recentemente</h2>
										<span>{finished.length}</span>
									</div>
									<ul className={styles.compactJobs}>{finished.slice(0, 4).map(renderRow)}</ul>
								</section>
							) : null}
						</div>

						<aside className={styles.inspector} aria-labelledby="processing-details">
							<div className={styles.inspectorHeader}>
								<div>
									<span className={styles.overline}>Trabalho observado</span>
									<h2 id="processing-details">Detalhes do processamento</h2>
								</div>
							</div>
							{observedJob ? (
								<dl className={styles.jobDetails}>
									<div><dt>Trabalho</dt><dd>{jobTitle(observedJob)}</dd></div>
									<div><dt>Estado</dt><dd>{jobLabels[observedJob.status]}</dd></div>
									<div><dt>Etapa</dt><dd>{stageLabels[observedJob.stage] ?? observedJob.stage}</dd></div>
									{observedJob.context?.sessionId ? <div><dt>Sessão</dt><dd>{observedJob.context.sessionId}</dd></div> : null}
									<div><dt>ID local</dt><dd className={styles.mono}>{observedJob.id}</dd></div>
								</dl>
							) : (
								<p className={styles.inspectorEmpty}>Nenhum trabalho observado.</p>
							)}

							<div className={styles.logHeader}>
								<h3>Log em tempo real</h3>
								<span>{state.events.length ? "● ativo" : "sem eventos"}</span>
							</div>
							<div
								className={styles.log}
								role="log"
								aria-label="Eventos do processamento local"
								aria-relevant="additions text"
							>
								{state.events.length ? (
									state.events.slice(0, 24).map((event) => {
										const presented = presentJobEvent(event);
										return (
											<div className={styles.logEntry} key={event.seq} data-level={event.level}>
												<time dateTime={event.at}>{formatTime(event.at)}</time>
												<div>
													<span>{presented.title}</span>
													{presented.detail ? <small>{presented.detail}</small> : null}
												</div>
											</div>
										);
									})
								) : (
									<p>Nenhum evento detalhado recebido para este trabalho.</p>
								)}
							</div>

							{state.capabilities?.capabilities.includes("synthetic.fixture") ? (
								<div className={styles.integrationTool}>
									<div>
										<strong>Diagnóstico</strong>
										<span>Ensaio pequeno, sem áudio e sem publicação.</span>
									</div>
									<Button
										size="sm"
										disabled={state.busy || state.health?.lifecycle !== "ready"}
										onClick={() => void controller.synthetic()}
									>
										Executar ensaio sintético
									</Button>
								</div>
							) : null}
							{state.uncertainSubmission ? (
								<p className={styles.connectionError} role="alert">
									A resposta desta tentativa não chegou. Reconecte e consulte a fila antes de iniciar outra tentativa; a chave desta aba será reutilizada.
								</p>
							) : null}
						</aside>
					</div>

					<section className={styles.syncStrip} aria-labelledby="local-sync">
						<div>
							<h2 id="local-sync">Sincronização com o Edit</h2>
							<p>
								<strong>Sincronização não configurada.</strong> Concluir localmente não significa enviar ou publicar.
							</p>
						</div>
						{state.result ? (
							<div className={styles.resultSummary} role="status">
								<span>Resultado local</span>
								<strong>{state.result.sessionId}</strong>
								<small>Pacote {state.result.publicationId.slice(0, 12)}…</small>
							</div>
						) : null}
					</section>
				</>
			) : (
				<section className={styles.disconnectedQueue} aria-labelledby="local-queue">
					<h2 id="local-queue">Fila local</h2>
					<p>
						Conecte o serviço para consultar a fila persistida. A ausência de conexão não significa que o processamento parou.
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
										? `O trabalho ${confirmation.id}, seus eventos e eventual resultado local serão excluídos do histórico. Modelos, sessão Craig e checkpoints não serão apagados.`
										: `Uma nova tentativa será criada para ${confirmation.id}; repetir não promete retomar do ponto exato.`}
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
