from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.qwen_desktop_prepare as prepare
from tda_companion.qwen_desktop_prepare import QwenDesktopPrepareError, prepare_qwen_profile_from_craig, probe_qwen_long_track_gate


def _result(payload: dict, returncode: int = 0):
    return SimpleNamespace(stdout=json.dumps(payload), returncode=returncode)


def test_probe_requires_runtime_long_track_gate_feature(monkeypatch, tmp_path: Path):
    worker = tmp_path / "TDAQwenWorker.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(prepare, "current_qwen_worker", lambda _root: worker)

    def runner(command, **kwargs):  # noqa: ANN001, ANN003
        return _result(
            {
                "schema": "tda_qwen_runtime_probe_v1",
                "ready": True,
                "cuda_available": True,
                "long_track_acceptance_window": False,
            }
        )

    with pytest.raises(QwenDesktopPrepareError, match="QWEN_RUNTIME_LONG_GATE_REQUIRED"):
        probe_qwen_long_track_gate(tmp_path / "Runtime", runner=runner)


def test_prepare_qwen_uses_staged_track_and_returns_only_safe_gate_summary(monkeypatch, tmp_path: Path):
    runtime_root = tmp_path / "Runtime"
    worker = tmp_path / "TDAQwenWorker.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(prepare, "current_qwen_worker", lambda _root: worker)

    source_id = "craig-" + "a" * 64
    package_root = tmp_path / "Data" / "staging" / source_id
    tracks_root = package_root / "tracks"
    tracks_root.mkdir(parents=True)
    track = tracks_root / "001.flac"
    track.write_bytes(b"fLaC")
    package = SimpleNamespace(
        tracks=(SimpleNamespace(number=1, size_bytes=1234, path="tracks/001.flac"),),
    )
    monkeypatch.setattr(prepare, "load_craig_package", lambda *_args, **_kwargs: package)

    calls: list[list[str]] = []
    progress_events: list[tuple[str, dict[str, object]]] = []

    def runner(command, **kwargs):  # noqa: ANN001, ANN003
        calls.append(command)
        if "--probe" in command:
            return _result(
                {
                    "schema": "tda_qwen_runtime_probe_v1",
                    "ready": True,
                    "cuda_available": True,
                    "torch_cuda": "13.2",
                    "long_track_acceptance_window": True,
                }
            )
        return _result(
            {
                "schema": "tda_qwen_gpu_acceptance_v1",
                "pass": True,
                "gpu": {"name": "NVIDIA GeForce RTX 4070 Laptop GPU"},
                "inference": {"audio_seconds": 60.0, "transcript_sha256": "b" * 64},
                "source_window": {
                    "start_seconds": 540.0,
                    "duration_seconds": 60.0,
                    "energy_dbfs": -21.5,
                },
            }
        )

    value = prepare_qwen_profile_from_craig(
        data_root=tmp_path / "Data",
        cache_root=tmp_path / "Cache",
        models_root=tmp_path / "Models",
        runtime_root=runtime_root,
        state_root=tmp_path / "State",
        source_id=source_id,
        profile_id="qwen-quality",
        runner=runner,
        progress=lambda stage, context: progress_events.append((stage, context)),
    )

    assert [stage for stage, _ in progress_events] == [
        "runtime_probe",
        "runtime_probe_ready",
        "selecting_audio",
        "physical_gate",
        "physical_gate_ready",
    ]
    assert progress_events[2][1]["track_count"] == 1
    assert progress_events[3][1]["audio_window_seconds"] == 60
    assert value == {
        "ready": True,
        "profile_id": "qwen-quality",
        "gpu_name": "NVIDIA GeForce RTX 4070 Laptop GPU",
        "audio_seconds": 60.0,
        "window_start_seconds": 540.0,
        "window_energy_dbfs": -21.5,
        "runtime_cuda": "13.2",
    }
    acceptance = calls[-1]
    assert "--acceptance-window" in acceptance
    assert "--record-gate" in acceptance
    assert "--transcript-out" not in acceptance
    assert str(track.resolve()) in acceptance
    assert str(track.resolve()) not in repr(value)
