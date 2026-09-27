export const PROCESSING_TIMING_VERSION = "engine_processing_v1";
export const processingStageLabels: Record<string, string> = {
	runtime_validation: "Validação local", checkpoint_scan: "Verificação de checkpoints",
	model_prepare: "Preparação dos modelos", model_load: "Carregamento dos modelos",
	transcription: "Transcrição", alignment_and_energy: "Alinhamento e análise de áudio", consolidation: "Consolidação",
};
const stages = ["runtime_validation", "checkpoint_scan", "model_prepare", "model_load", "transcription", "alignment_and_energy", "consolidation"] as const;
export type EngineProcessingMetrics = {
	version: typeof PROCESSING_TIMING_VERSION;
	stageSeconds: Record<typeof stages[number], number>;
	totalProcessingSeconds: number;
	totalTracks: number;
	freshAsrTracks: number;
	textCheckpointReusedTracks: number;
	completedCheckpointReusedTracks: number;
	freshAudioWorkSeconds: number;
	reusedAudioWorkSeconds: number;
	freshCalibrationEligible: boolean;
};
const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER;
export function parseEngineMetrics(value: unknown, expectedTracks?: unknown, expectedAudio?: unknown): EngineProcessingMetrics | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) return null;
	const row = value as Record<string, unknown>;
	if (row.version !== PROCESSING_TIMING_VERSION || row.external_preparation_included !== false) return null;
	const raw = row.stage_seconds;
	if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
	const stage = raw as Record<string, unknown>;
	if (Object.keys(stage).length !== stages.length || stages.some(key => !number(stage[key]))) return null;
	const counts = [row.total_tracks, row.fresh_asr_tracks, row.text_checkpoint_reused_tracks, row.completed_checkpoint_reused_tracks];
	if (counts.some(n => !number(n) || !Number.isInteger(n) || n > 256)) return null;
	const [total, fresh, text, completed] = counts as number[];
	if (total !== fresh + text + completed || !number(row.total_processing_seconds) || !number(row.fresh_audio_work_seconds) || !number(row.reused_audio_work_seconds)) return null;
	const eligible = total > 0 && total === fresh && row.fresh_audio_work_seconds > 0;
	if ((expectedTracks !== undefined && expectedTracks !== total) || (expectedAudio !== undefined && (!number(expectedAudio) || Math.abs(expectedAudio - row.fresh_audio_work_seconds - row.reused_audio_work_seconds) > 0.001))) return null;
	if (row.fresh_calibration_eligible !== eligible || Math.abs(stages.reduce((sum, key) => sum + (stage[key] as number), 0) - row.total_processing_seconds) > 0.00001) return null;
	return { version: PROCESSING_TIMING_VERSION, stageSeconds: Object.fromEntries(stages.map(key => [key, stage[key]])) as EngineProcessingMetrics["stageSeconds"],
		totalProcessingSeconds: row.total_processing_seconds, totalTracks: total, freshAsrTracks: fresh,
		textCheckpointReusedTracks: text, completedCheckpointReusedTracks: completed,
		freshAudioWorkSeconds: row.fresh_audio_work_seconds, reusedAudioWorkSeconds: row.reused_audio_work_seconds,
		freshCalibrationEligible: eligible };
}

/** Shared gate for benchmark/ETA consumers: never calibrate from recovered or legacy work. */
export function freshCalibrationRtf(metrics: EngineProcessingMetrics | null | undefined): number | null {
	return metrics?.version === PROCESSING_TIMING_VERSION && metrics.freshCalibrationEligible && metrics.freshAudioWorkSeconds > 0
		? metrics.totalProcessingSeconds / metrics.freshAudioWorkSeconds : null;
}
