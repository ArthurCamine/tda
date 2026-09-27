import { expect, it } from "vitest";
import { freshCalibrationRtf, parseEngineMetrics } from "./engine-metrics";

const fresh = {
	version: "engine_processing_v1", external_preparation_included: false,
	stage_seconds: { runtime_validation: 0, checkpoint_scan: 0, model_prepare: 10, model_load: 5, transcription: 20, alignment_and_energy: 0, consolidation: 0 },
	total_processing_seconds: 35, total_tracks: 4, fresh_asr_tracks: 4,
	text_checkpoint_reused_tracks: 0, completed_checkpoint_reused_tracks: 0,
	fresh_audio_work_seconds: 400, reused_audio_work_seconds: 0, fresh_calibration_eligible: true,
};
it("calibrates only the explicit complete fresh measurement version", () => {
	expect(freshCalibrationRtf(parseEngineMetrics(fresh))).toBe(35 / 400);
	expect(freshCalibrationRtf(parseEngineMetrics({ ...fresh, fresh_asr_tracks: 1, completed_checkpoint_reused_tracks: 3, fresh_audio_work_seconds: 100, reused_audio_work_seconds: 300, fresh_calibration_eligible: false }))).toBeNull();
	expect(freshCalibrationRtf(parseEngineMetrics({ ...fresh, version: "unknown" }))).toBeNull();
	expect(parseEngineMetrics(undefined)).toBeNull();
});
it("rejects inconsistent, nonfinite and false fresh claims", () => {
	for (const patch of [{ total_processing_seconds: 34 }, { fresh_asr_tracks: 3 }, { fresh_audio_work_seconds: Number.NaN }, { fresh_calibration_eligible: false }]) {
		expect(parseEngineMetrics({ ...fresh, ...patch })).toBeNull();
	}
});
