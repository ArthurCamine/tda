from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.diagnostics as diagnostics
from tda_companion.asr_acceptance import WhisperAcceptanceError, _verify_model_integrity
from tda_companion.asr_models import get_profile, model_path, write_install_marker


def _install_model(models_root: Path, profile_id: str) -> Path:
    profile = get_profile(profile_id)
    target = model_path(models_root, profile)
    target.mkdir(parents=True)
    for index, name in enumerate(profile.required_files, start=1):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{profile_id}:{index}".encode("utf-8"))
    write_install_marker(target, profile)
    return target


def test_whisper_physical_integrity_rehash_detects_tampering(tmp_path: Path):
    models_root = tmp_path / "Models"
    target = _install_model(models_root, "whisper-turbo")
    profile = get_profile("whisper-turbo")

    verified = _verify_model_integrity(models_root, profile)
    assert verified["status"] == "ready"
    assert len(str(verified["content_sha256"])) == 64

    (target / "model.bin").write_bytes(b"tampered-after-install-marker")
    with pytest.raises(WhisperAcceptanceError, match="ACCEPTANCE_MODEL_INTEGRITY_FAILED"):
        _verify_model_integrity(models_root, profile)


def test_daily_model_diagnostic_is_explicitly_metadata_only(monkeypatch, tmp_path: Path):
    calls: list[bool] = []

    def fake_inspect(_root, _profile, *, verify_hash=False):
        calls.append(bool(verify_hash))
        return {"status": "ready", "content_sha256": "a" * 64}

    monkeypatch.setattr(diagnostics, "inspect_model_install", fake_inspect)
    result = diagnostics._model_check(tmp_path, "whisper-turbo", "model", "Modelo")

    assert result["status"] == "pass"
    assert "metadados" in result["message"].lower()
    assert "metadata-only" in result["detail"]
    assert calls == [False]


def test_qwen_gate_diagnostic_reports_hash_verified_at_acceptance(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_physical_gate",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "ready": True,
            "accepted_at": "2026-09-14T01:00:00Z",
        },
    )
    paths = SimpleNamespace(
        state_root=tmp_path / "State",
        runtime_root=tmp_path / "Runtime",
        models_root=tmp_path / "Models",
    )

    result = diagnostics._qwen_gate_check(paths, "qwen-fast", "qwen_gate", "Qwen Rápido")

    assert result["status"] == "pass"
    assert "sha256-full-at-acceptance" in result["detail"]
