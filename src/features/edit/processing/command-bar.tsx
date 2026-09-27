"use client";

import { AnimatedMetric } from "@/components/ui/animated-metric";
import { Button } from "@/components/ui/button";
import type { Health, SystemSnapshot, ExecutionDevice } from "./protocol";
import { selectExecutionGpu } from "./execution-device";
import styles from "./command-bar.module.css";

type Props = Readonly<{
	connection: "disconnected" | "connecting" | "connected" | "error";
	connected: boolean;
	connectionLabel: string;
	health: Health | null;
	system: SystemSnapshot | null;
	executionDevice?: ExecutionDevice | null;
	refreshError: string | null;
	checkedAt: string | null;
	runningCount: number;
	queuedCount: number;
	attentionCount: number;
	refreshing: boolean;
	pendingLifecycle: "pause" | "resume" | null;
	onRefresh: () => void;
	onToggleLifecycle: () => void;
	onAttention: () => void;
	onDiagnostics: () => void;
}>;

function compactGpuName(value: string): string {
	return value
		.replace(/^NVIDIA\s+/iu, "")
		.replace(/^GeForce\s+/iu, "")
		.replace(/\s+Laptop GPU$/iu, "")
		.trim();
}

function compactMemoryValue(bytes: number): string {
	const gib = bytes / 1024 ** 3;
	return gib >= 10 ? gib.toFixed(0) : gib.toFixed(1);
}

function formatPercent(value: number): string {
	return `${Math.round(value)}%`;
}

function freshness(checkedAt: string | null, stale: boolean): string {
	if (stale) return "desatualizado";
	if (!checkedAt) return "aguardando leitura";
	const elapsed = Math.max(0, Date.now() - Date.parse(checkedAt));
	const seconds = Math.round(elapsed / 1000);
	if (seconds <= 2) return "agora";
	if (seconds < 60) return `há ${seconds} s`;
	return `há ${Math.floor(seconds / 60)} min`;
}

function countLabel(value: number, singular: string, plural: string): string {
	return `${value} ${value === 1 ? singular : plural}`;
}

export function ProcessingCommandBar({
	connection,
	connected,
	connectionLabel,
	health,
	system,
	executionDevice,
	refreshError,
	checkedAt,
	runningCount,
	queuedCount,
	attentionCount,
	refreshing,
	pendingLifecycle,
	onRefresh,
	onToggleLifecycle,
	onAttention,
	onDiagnostics,
}: Props) {
	// Machine inventory only; CUDA logical device identity is a separate contract.
	const executionGpu = selectExecutionGpu(system?.gpus ?? [], executionDevice);
	const gpu = executionGpu ?? system?.gpus.reduce<(typeof system.gpus)[number] | null>(
		(selected, candidate) => !selected || candidate.index < selected.index ? candidate : selected, null,
	) ?? null;
	const gpuMemory =
		gpu?.memoryUsedBytes !== null &&
		gpu?.memoryUsedBytes !== undefined &&
		gpu?.memoryTotalBytes !== null &&
		gpu?.memoryTotalBytes !== undefined &&
		gpu.memoryTotalBytes > 0
			? { used: gpu.memoryUsedBytes, total: gpu.memoryTotalBytes }
			: null;
	const stale = Boolean(refreshError);
	const gpuUnavailable = connected && Boolean(system) && system?.gpus.length === 0;
	const partialTelemetry =
		Boolean(gpu) &&
		(gpu?.utilizationPercent === null ||
			gpu?.memoryUsedBytes === null ||
			gpu?.memoryTotalBytes === null);
	const degradedHint = stale
		? "Dados desatualizados"
		: gpuUnavailable
			? "GPU não detectada"
			: partialTelemetry
				? "Telemetria parcial"
				: null;
	const tone =
		connection === "error"
			? "danger"
			: stale || gpuUnavailable || partialTelemetry || health?.lifecycle === "paused"
				? "warning"
				: health?.lifecycle === "ready"
					? "success"
					: "neutral";
	const primaryLifecycleAction =
		health?.lifecycle === "paused" ? "resume" : health?.lifecycle === "ready" ? "pause" : null;

	return (
		<section
			className={styles.bar}
			data-processing-command-bar="true"
			data-tone={tone}
			aria-label="Estado e comandos do TDA Companion"
		>
			<div className={styles.statusCluster}>
				<span
					className={styles.statusDot}
					data-processing-status-indicator="true"
					data-processing-status-dot="true"
					aria-hidden="true"
				/>
				<div className={styles.statusCopy}>
					<strong>
						Companion · <span className={styles.stateLabel}>{connectionLabel}</span>
					</strong>
					<span>{freshness(checkedAt, stale)}</span>
					{degradedHint ? <span className={styles.degradedHint}>{degradedHint}</span> : null}
				</div>
				{connected && gpu ? (
					<span className={styles.gpuCluster} title={`${executionGpu ? "GPU do processamento" : `GPU ${gpu.index} da máquina`} · ${gpu.name}`}>
						{executionGpu ? "GPU do processamento" : `GPU ${gpu.index}`} · {compactGpuName(gpu.name)}
						{gpu.utilizationPercent !== null ? (
							<>
								{" · "}
								<AnimatedMetric
									value={gpu.utilizationPercent}
									min={0}
									max={100}
									format={formatPercent}
									ariaLabel="Uso da GPU"
									minWidthCh={4}
								/>
							</>
						) : null}
						{gpuMemory ? (
							<>
								{" · "}
								<AnimatedMetric
									value={gpuMemory.used}
									min={0}
									max={gpuMemory.total}
									format={compactMemoryValue}
									ariaValueText={(value) => `${compactMemoryValue(value)} GB usados`}
									ariaLabel="VRAM usada"
									minWidthCh={3.2}
								/>
								/{compactMemoryValue(gpuMemory.total)} GB
							</>
						) : null}
					</span>
				) : null}
				{connected && system ? (
					<span className={styles.secondaryTelemetry}>
						{gpu ? "" : "GPU indisponível · "}
						CPU{" "}
						{system.cpu.utilizationPercent === null ? (
							"—"
						) : (
							<AnimatedMetric
								value={system.cpu.utilizationPercent}
								min={0}
								max={100}
								format={formatPercent}
								ariaLabel="Uso da CPU"
								minWidthCh={4}
							/>
						)}
						{" · "}
						RAM{" "}
						{system.memory.percent === null ? (
							"—"
						) : (
							<AnimatedMetric
								value={system.memory.percent}
								min={0}
								max={100}
								format={formatPercent}
								ariaLabel="Uso da RAM"
								minWidthCh={4}
							/>
						)}
					</span>
				) : null}
			</div>

			{connected ? (
				<div className={styles.counters} data-processing-counters="true">
					<span>{countLabel(runningCount, "processando", "processando")}</span>
					<span>{countLabel(queuedCount, "na fila", "na fila")}</span>
					{attentionCount > 0 ? (
						<button
							type="button"
							className={styles.attention}
							aria-label={countLabel(attentionCount, "atenção", "atenções")}
							onClick={onAttention}
						>
							{countLabel(attentionCount, "atenção", "atenções")}
						</button>
					) : (
						<span>0 atenção</span>
					)}
				</div>
			) : null}

			<div className={styles.actions}>
				{connected ? (
					<Button
						size="sm"
						variant="tertiary"
						className={styles.refreshAction}
						disabled={refreshing}
						aria-label={refreshing ? "Atualizando…" : "Atualizar estado"}
						onClick={onRefresh}
					>
						<span className={styles.actionLong}>
							{refreshing ? "Atualizando…" : "Atualizar estado"}
						</span>
						<span className={styles.actionShort}>
							{refreshing ? "Atualizando…" : "Atualizar"}
						</span>
					</Button>
				) : null}
				{connected && primaryLifecycleAction ? (
					<Button
						size="sm"
						disabled={pendingLifecycle === primaryLifecycleAction}
						aria-label={
							primaryLifecycleAction === "pause"
								? pendingLifecycle === "pause"
									? "Pausando…"
									: "Pausar novas execuções"
								: pendingLifecycle === "resume"
									? "Retomando…"
									: "Retomar novas execuções"
						}
						onClick={onToggleLifecycle}
					>
						<span className={styles.actionLong}>
							{primaryLifecycleAction === "pause"
								? pendingLifecycle === "pause"
									? "Pausando…"
									: "Pausar novas execuções"
								: pendingLifecycle === "resume"
									? "Retomando…"
									: "Retomar novas execuções"}
						</span>
						<span className={styles.actionShort}>
							{primaryLifecycleAction === "pause"
								? pendingLifecycle === "pause"
									? "Pausando…"
									: "Pausar"
								: pendingLifecycle === "resume"
									? "Retomando…"
									: "Retomar"}
						</span>
					</Button>
				) : null}
				{connected ? (
					<Button size="sm" variant="tertiary" onClick={onDiagnostics}>
						Diagnóstico
					</Button>
				) : null}
			</div>

			{connected && degradedHint ? (
				<div className={styles.degraded} role="status">
					<strong>{degradedHint}.</strong>
					<span>
						{stale
							? "O último snapshot válido foi preservado."
							: gpuUnavailable
								? "CPU e RAM continuam disponíveis; consulte Diagnóstico para detalhes da máquina."
								: "Alguns valores não vieram nesta amostra; o restante continua válido."}
					</span>
				</div>
			) : null}
		</section>
	);
}
