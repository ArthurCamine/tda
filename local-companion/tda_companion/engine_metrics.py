"""Comparable engine wall clock and metadata-only work provenance, separate from job time."""
from __future__ import annotations

import math
import time

VERSION = "engine_processing_v1"
STAGES = ("runtime_validation", "checkpoint_scan", "model_prepare", "model_load",
          "transcription", "alignment_and_energy", "consolidation")
ALIASES = {"runtime_fingerprint": "runtime_validation", "alignment": "alignment_and_energy",
           "energy_analysis": "alignment_and_energy", "cross_track_dedup": "consolidation",
           "merge_timeline": "consolidation", "turn_building": "consolidation"}


class EngineMeasurement:
    def __init__(self, report, *, clock=None):
        self.clock = clock or time.monotonic
        self.report = report
        self.last = self.clock()
        self.stage = "runtime_validation"
        self.seconds = dict.fromkeys(STAGES, 0.0)
        self.completed_reuse = set()
        self.text_reuse = set()

    def _close_stage(self):
        now = self.clock()
        self.seconds[self.stage] += max(0.0, now - self.last)
        self.last = now

    def emit(self, event):
        if event.get("type") == "stage":
            stage = ALIASES.get(event.get("stage"), event.get("stage"))
            if stage in STAGES:
                self.switch(stage)
        track = event.get("track")
        if isinstance(track, int) and not isinstance(track, bool):
            if event.get("code") == "ASR_CHECKPOINT_REUSED":
                self.completed_reuse.add(track)
            elif event.get("code") in {"ASR_TEXT_CHECKPOINT_REUSED", "ASR_TEXT_CHECKPOINT_COMPAT_REUSED"}:
                self.text_reuse.add(track)
        self.report(event)

    def switch(self, stage):
        if stage not in STAGES:
            raise ValueError("ENGINE_METRICS_STAGE_INVALID")
        self._close_stage()
        self.stage = stage

    def finish(self, tracks):
        self._close_stage()
        values = tuple(tracks)
        completed = [t for t in values if t.number in self.completed_reuse]
        text = [t for t in values if t.number in self.text_reuse and t.number not in self.completed_reuse]
        fresh = [t for t in values if t.number not in self.completed_reuse | self.text_reuse]
        duration = lambda selected: round(sum(float(t.duration_seconds or 0) for t in selected), 6)
        seconds = {key: round(value, 6) for key, value in self.seconds.items()}
        return {"version": VERSION, "stage_seconds": seconds,
                "total_processing_seconds": round(sum(seconds.values()), 6),
                "external_preparation_included": False,
                "total_tracks": len(values), "fresh_asr_tracks": len(fresh),
                "text_checkpoint_reused_tracks": len(text), "completed_checkpoint_reused_tracks": len(completed),
                "fresh_audio_work_seconds": duration(fresh), "reused_audio_work_seconds": duration(completed + text),
                "fresh_calibration_eligible": bool(values) and not completed and not text and duration(fresh) > 0}


def validate_engine_metrics(value):
    if value is None:
        return
    keys = {"version", "stage_seconds", "total_processing_seconds", "external_preparation_included",
            "total_tracks", "fresh_asr_tracks", "text_checkpoint_reused_tracks", "completed_checkpoint_reused_tracks",
            "fresh_audio_work_seconds", "reused_audio_work_seconds", "fresh_calibration_eligible"}
    if not isinstance(value, dict) or set(value) != keys or value["version"] != VERSION:
        raise ValueError("ENGINE_METRICS_INVALID")
    stages = value["stage_seconds"]
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise ValueError("ENGINE_METRICS_INVALID")
    for raw in [*stages.values(), value["total_processing_seconds"], value["fresh_audio_work_seconds"], value["reused_audio_work_seconds"]]:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= 2**53 - 1:
            raise ValueError("ENGINE_METRICS_INVALID")
    counts = [value[key] for key in ("total_tracks", "fresh_asr_tracks", "text_checkpoint_reused_tracks", "completed_checkpoint_reused_tracks")]
    if any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 256 for n in counts) or counts[0] != sum(counts[1:]):
        raise ValueError("ENGINE_METRICS_INVALID")
    eligible = counts[0] > 0 and counts[0] == counts[1] and value["fresh_audio_work_seconds"] > 0
    if value["external_preparation_included"] is not False or value["fresh_calibration_eligible"] is not eligible:
        raise ValueError("ENGINE_METRICS_INVALID")
    if abs(sum(stages.values()) - value["total_processing_seconds"]) > 0.00001:
        raise ValueError("ENGINE_METRICS_INVALID")


def fresh_calibration_sample(value):
    try:
        validate_engine_metrics(value)
    except (ValueError, TypeError):
        return None
    if value is None or not value["fresh_calibration_eligible"]:
        return None
    return value["total_processing_seconds"] / value["fresh_audio_work_seconds"]
