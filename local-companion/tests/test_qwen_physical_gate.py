from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.asr_models import get_profile, model_path, write_install_marker
from tda_companion.qwen_acceptance import ALIGNER_PROFILE
from tda_companion.qwen_physical_gate import (
    MIN_GATE_AUDIO_SECONDS,
    QwenPhysicalGateError,
    inspect_qwen_physical_gate,
    ready_qwen_profiles,
    record_qwen_physical_gate,
)
from tda_companion.qwen_runtime import install_qwen_runtime_archive
from tda_companion.runtime_compat import MIN_COMPATIBLE_QWEN_RUNTIME_VERSION


def _install_runtime(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "qwen-runtime.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("TDAQwenWorker.exe", b"worker-v1")
        bundle.writestr("_internal/torch.dll", b"torch")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    install_qwen_runtime_archive(
        archive,
        root / "Runtime",
        version=MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
        expected_sha256=digest,
    )


def _install_model(models_root: Path, profile_id: str) -> Path:
    profile = get_profile(profile_id)
    target = model_path(models_root, profile)
    target.mkdir(parents=True)
    for index, name in enumerate(profile.required_files, start=1):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{profile_id}:{index}".encode())
    write_install_marker(target, profile)
    return target


def _install_aligner(models_root: Path) -> Path:
    target = model_path(models_root, ALIGNER_PROFILE)
    target.mkdir(parents=True)
    for index, name in enumerate(ALIGNER_PROFILE.required_files, start=1):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"aligner:{index}".encode())
    write_install_marker(target, ALIGNER_PROFILE)
    return target


def _receipt(profile_id: str = "qwen-fast") -> dict:
    profile = get_profile(profile_id)
    gpu = "NVIDIA GeForce RTX 4070 Laptop GPU"
    return {
        "schema": "tda_qwen_gpu_acceptance_v1",
        "pass": True,
        "profile_id": profile.id,
        "model": profile.model_id,
        "model_revision": profile.revision,
        "alignment_model": ALIGNER_PROFILE.model_id,
        "alignment_revision": ALIGNER_PROFILE.revision,
        "language": "Portuguese",
        "audio_sha256": "a" * 64,
        "runtime": {
            "torch": "2.14.0+cu132",
            "transformers": "5.17.0",
            "torch_cuda": "13.2",
        },
        "cuda": {
            "available": True,
            "device_count": 1,
            "bf16_supported": True,
            "torch_cuda": "13.2",
            "devices": [
                {
                    "index": 0,
                    "name": gpu,
                    "compute_capability": "8.9",
                    "total_memory_bytes": 8 * 1024**3,
                }
            ],
        },
        "gpu": {
            "name": gpu,
            "required_name": "RTX 4070",
            "required_name_match": True,
            "peak_used_memory_bytes": 6 * 1024**3,
        },
        "alignment_gpu": {
            "name": gpu,
            "required_name": "RTX 4070",
            "required_name_match": True,
            "peak_used_memory_bytes": 5 * 1024**3,
        },
        "inference": {
            "device": "cuda",
            "compute_type": "bfloat16",
            "audio_seconds": MIN_GATE_AUDIO_SECONDS,
            "rtf": 0.42,
            "transcript_sha256": "b" * 64,
            "transcript_written": False,
        },
        "alignment": {
            "compute_type": "bfloat16",
            "rtf": 0.18,
            "word_count": 87,
        },
        "total_seconds": 108.0,
    }


def _prepared(tmp_path: Path, profile_id: str = "qwen-fast") -> tuple[Path, Path, Path]:
    _install_runtime(tmp_path)
    models = tmp_path / "Models"
    _install_model(models, profile_id)
    _install_aligner(models)
    return tmp_path / "State", tmp_path / "Runtime", models


def test_physical_gate_binds_runtime_model_aligner_and_contains_no_private_text(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    gate = record_qwen_physical_gate(
        state,
        runtime,
        models,
        _receipt(),
        profile_id="qwen-fast",
    )

    assert gate["ready"] is True
    assert gate["runtime_version"] == MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
    assert gate["metrics"]["audio_seconds"] == MIN_GATE_AUDIO_SECONDS
    persisted = (state / "qwen-physical-gates" / "qwen-fast.json").read_text(encoding="utf-8")
    assert "transcript_sha256" not in persisted
    assert "audio_sha256" not in persisted
    assert "contains_transcript\":false" in persisted
    assert ready_qwen_profiles(state, runtime, models) == ["qwen-fast"]


def test_gate_rejects_audio_shorter_than_production_window(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    short = _receipt()
    short["inference"]["audio_seconds"] = MIN_GATE_AUDIO_SECONDS - 0.001

    with pytest.raises(QwenPhysicalGateError, match="QWEN_GATE_AUDIO_TOO_SHORT"):
        record_qwen_physical_gate(state, runtime, models, short, profile_id="qwen-fast")

    gate_path = state / "qwen-physical-gates" / "qwen-fast.json"
    assert not gate_path.exists()
    assert ready_qwen_profiles(state, runtime, models) == []


def test_reader_invalidates_legacy_short_gate(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    record_qwen_physical_gate(state, runtime, models, _receipt(), profile_id="qwen-fast")
    gate_path = state / "qwen-physical-gates" / "qwen-fast.json"
    persisted = json.loads(gate_path.read_text(encoding="utf-8"))
    persisted["metrics"]["audio_seconds"] = 30.0
    gate_path.write_text(json.dumps(persisted, separators=(",", ":")), encoding="utf-8")

    inspected = inspect_qwen_physical_gate(state, runtime, models, profile_id="qwen-fast")
    assert inspected["ready"] is False
    assert inspected["status"] == "invalid"
    assert inspected["reason"] == "QWEN_GATE_AUDIO_TOO_SHORT"
    assert ready_qwen_profiles(state, runtime, models) == []


def test_gate_is_invalidated_when_worker_or_model_content_changes(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    record_qwen_physical_gate(state, runtime, models, _receipt(), profile_id="qwen-fast")

    worker = runtime / "qwen" / MIN_COMPATIBLE_QWEN_RUNTIME_VERSION / "TDAQwenWorker.exe"
    worker.write_bytes(b"tampered")
    stale = inspect_qwen_physical_gate(state, runtime, models, profile_id="qwen-fast")
    assert stale["ready"] is False
    assert stale["status"] == "stale"

    other = tmp_path / "other"
    state2, runtime2, models2 = _prepared(other)
    record_qwen_physical_gate(state2, runtime2, models2, _receipt(), profile_id="qwen-fast")
    model = model_path(models2, "qwen-fast") / "model.safetensors"
    model.write_bytes(b"changed-after-acceptance")
    assert inspect_qwen_physical_gate(state2, runtime2, models2, profile_id="qwen-fast")["ready"] is True
    verified = inspect_qwen_physical_gate(
        state2,
        runtime2,
        models2,
        profile_id="qwen-fast",
        verify_model_content=True,
    )
    assert verified["ready"] is False
    assert verified["reason"] == "QWEN_GATE_MODEL_NOT_READY"


def test_gate_is_per_profile_and_rejects_receipts_with_private_payload(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    record_qwen_physical_gate(state, runtime, models, _receipt(), profile_id="qwen-fast")
    assert inspect_qwen_physical_gate(state, runtime, models, profile_id="qwen-quality")["ready"] is False

    bad = _receipt()
    bad["text"] = "conteúdo que não pode entrar no receipt de gate"
    with pytest.raises(QwenPhysicalGateError, match="QWEN_GATE_PRIVATE_PAYLOAD_REJECTED"):
        record_qwen_physical_gate(state, runtime, models, bad, profile_id="qwen-fast")


def test_gate_requires_the_configured_physical_gpu_name(tmp_path: Path):
    state, runtime, models = _prepared(tmp_path)
    bad = _receipt()
    bad["gpu"]["name"] = "NVIDIA GeForce RTX 3090"
    with pytest.raises(QwenPhysicalGateError, match="QWEN_GATE_GPU_NAME_MISMATCH"):
        record_qwen_physical_gate(state, runtime, models, bad, profile_id="qwen-fast")
