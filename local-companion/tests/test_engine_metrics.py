from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from tda_companion.engine_metrics import EngineMeasurement, fresh_calibration_sample, validate_engine_metrics
from tda_companion.transcript import TranscriptDocument
from tda_companion.transcription_runs import write_completed_run, load_run
from test_transcription_runs import _document


@pytest.mark.parametrize("completed,text", [(0, 0), (1, 0), (4, 0), (0, 1), (1, 2)])
def test_checkpoint_work_is_partitioned_and_never_calibrated_as_fresh(completed, text):
    clock = [0.0]
    timer = EngineMeasurement(lambda _: None, clock=lambda: clock[0])
    for track in range(completed):
        timer.emit({"code": "ASR_CHECKPOINT_REUSED", "track": track})
    for track in range(completed, completed + text):
        timer.emit({"code": "ASR_TEXT_CHECKPOINT_REUSED", "track": track})
    clock[0] = 10
    metrics = timer.finish([SimpleNamespace(number=n, duration_seconds=100) for n in range(4)])
    validate_engine_metrics(metrics)
    assert metrics["fresh_audio_work_seconds"] == (4 - completed - text) * 100
    assert metrics["reused_audio_work_seconds"] == (completed + text) * 100
    assert fresh_calibration_sample(metrics) == (None if completed + text else 0.025)
    assert fresh_calibration_sample(None) is None
    assert fresh_calibration_sample({**metrics, "version": "future"}) is None


def test_actual_engines_include_same_prepare_load_boundary(tmp_path, monkeypatch):
    import tda_companion.engine_metrics as metrics_module
    import tda_companion.asr_whisper as whisper
    import tda_companion.asr_qwen_strict as qwen
    from tda_companion.asr_qwen import AudioWindow
    from test_asr_qwen_strict import _package, _plan
    clock = [0.0]
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: clock[0])
    def advance(seconds, result):
        clock[0] += seconds
        return result
    package, root = _package(tmp_path)
    monkeypatch.setattr(whisper, "prepare_whisper_model", lambda *a, **k: advance(10, tmp_path))
    class Whisper:
        def transcribe(self, *_args, **_kwargs):
            return advance(20, (iter([SimpleNamespace(id=0, start=0, end=1, text="synthetic", words=[])]), SimpleNamespace(duration=100)))
    whisper_doc = whisper.transcribe_craig_package(package, root, tmp_path, profile_id="whisper-turbo", checkpoints=False,
        cuda_status={"available": True, "supported_compute_types": ["float16"]},
        model_loader=lambda _, plan: advance(5, (Whisper(), plan.compute_type, False)))
    class Asr:
        def transcribe(self, *_args, **_kwargs):
            return advance(20, ("", "Portuguese"))
        def close(self):
            pass
    class Aligner:
        def close(self):
            pass
    qwen_doc = qwen.transcribe_craig_package_qwen_strict(package, root, tmp_path, profile_id="qwen-fast", checkpoints=False,
        plan_resolver=_plan, model_prepare=lambda *_: advance(10, tmp_path), aligner_prepare=lambda *_: tmp_path,
        asr_session_factory=lambda *_: advance(5, Asr()), aligner_session_factory=lambda *_: Aligner(),
        window_reader=lambda _: iter([AudioWindow(index=1, start=0, end=100, audio="synthetic")]))
    for document in (whisper_doc, qwen_doc):
        metrics = document.stats.processing_metrics
        validate_engine_metrics(metrics)
        assert metrics["total_processing_seconds"] == 35
        assert metrics["stage_seconds"]["model_prepare"] == 10
        assert metrics["stage_seconds"]["model_load"] == 5
        assert metrics["stage_seconds"]["transcription"] == 20
        assert metrics["fresh_calibration_eligible"]
    # Preserve the old recorded scope instead of retroactively redefining it.
    assert whisper_doc.stats.processing_seconds == 20
    assert qwen_doc.stats.processing_seconds == 35


def test_metrics_roundtrip_in_run_and_old_transcript_remains_valid(tmp_path):
    doc = _document("a" * 64, "whisper-turbo", "synthetic")
    historical = json.loads(json.dumps(doc.as_dict()))
    historical["stats"].pop("processing_metrics")
    assert TranscriptDocument.from_dict(historical).stats.processing_metrics is None
    timer = EngineMeasurement(lambda _: None, clock=lambda: 0)
    metrics = timer.finish(doc.tracks)
    doc = replace(doc, stats=replace(doc.stats, processing_metrics=metrics))
    root = tmp_path / ("craig-" + "a" * 64)
    root.mkdir()
    manifest = write_completed_run(root, doc, job_id="metrics", attempt=1)
    assert load_run(root, manifest["run_id"])["stats"]["processing_metrics"] == metrics
    assert TranscriptDocument.from_dict(json.loads(json.dumps(doc.as_dict()))).stats.processing_metrics == metrics
    with pytest.raises(ValueError):
        validate_engine_metrics({**metrics, "private_text": "never accepted"})
