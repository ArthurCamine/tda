from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.whisper_desktop_prepare as prepare
from tda_companion.whisper_desktop_prepare import (
    WhisperDesktopPrepareError,
    prepare_whisper_profile,
)


def _result(payload: dict, returncode: int = 0):
    return SimpleNamespace(stdout=json.dumps(payload), returncode=returncode)


def test_prepare_whisper_reuses_verified_model_without_starting_worker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        prepare,
        "inspect_model_install",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "content_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        prepare,
        "current_whisper_worker",
        lambda _root: (_ for _ in ()).throw(AssertionError("worker should not run")),
    )

    value = prepare_whisper_profile(
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
        profile_id="whisper-detailed",
    )

    assert value == {
        "ready": True,
        "profile_id": "whisper-detailed",
        "prepared": False,
        "model_content_sha256": "a" * 64,
    }


def test_prepare_whisper_invokes_isolated_worker_and_verifies_result(monkeypatch, tmp_path: Path):
    worker = tmp_path / "TDAWhisperWorker.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(prepare, "current_whisper_worker", lambda _root: worker)

    states = iter(
        [
            {"status": "missing"},
            {"status": "ready", "content_sha256": "b" * 64},
        ]
    )
    monkeypatch.setattr(
        prepare,
        "inspect_model_install",
        lambda *_args, **_kwargs: next(states),
    )
    seen: dict[str, object] = {}

    def runner(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return _result(
            {
                "schema": "tda_whisper_model_prepare_v1",
                "ready": True,
                "profile_id": "whisper-detailed",
                "prepared": True,
                "content_sha256": "b" * 64,
            }
        )

    value = prepare_whisper_profile(
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
        profile_id="whisper-detailed",
        runner=runner,
    )

    assert value["ready"] is True
    assert value["prepared"] is True
    assert value["model_content_sha256"] == "b" * 64
    command = seen["command"]
    assert command[0] == str(worker)
    assert command[1:3] == ["--prepare-model", "--models-root"]
    assert "--profile" in command
    assert "whisper-detailed" in command
    assert seen["kwargs"]["timeout"] == 2 * 60 * 60


def test_prepare_whisper_preserves_worker_failure_code(monkeypatch, tmp_path: Path):
    worker = tmp_path / "TDAWhisperWorker.exe"
    worker.write_bytes(b"worker")
    monkeypatch.setattr(prepare, "current_whisper_worker", lambda _root: worker)
    monkeypatch.setattr(
        prepare,
        "inspect_model_install",
        lambda *_args, **_kwargs: {"status": "missing"},
    )

    def runner(command, **kwargs):
        return _result(
            {
                "schema": "tda_whisper_model_prepare_v1",
                "ready": False,
                "error": "WHISPER_MODEL_DOWNLOAD_FAILED",
            },
            returncode=66,
        )

    with pytest.raises(WhisperDesktopPrepareError, match="WHISPER_MODEL_DOWNLOAD_FAILED"):
        prepare_whisper_profile(
            models_root=tmp_path / "Models",
            runtime_root=tmp_path / "Runtime",
            profile_id="whisper-turbo",
            runner=runner,
        )
