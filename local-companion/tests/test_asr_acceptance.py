from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tda_companion.asr_acceptance import WhisperAcceptanceError, run_whisper_gpu_acceptance


class _Monitor:
    def start(self) -> None:
        return None

    def stop(self) -> dict:
        return {
            "available": True,
            "index": 0,
            "name": "NVIDIA GeForce RTX 4070 Laptop GPU",
            "driver": "999.1",
            "memory_total_bytes": 8 * 1024**3,
            "baseline_memory_used_bytes": 512 * 1024**2,
            "peak_memory_used_bytes": 6 * 1024**3,
            "peak_utilization_percent": 97,
        }


class _Model:
    def transcribe(self, _path: str, **_options):
        word = SimpleNamespace(word=" segredo", start=0.1, end=0.4, probability=0.99)
        segment = SimpleNamespace(id=0, start=0.1, end=0.5, text="segredo da mesa", words=[word])
        return iter([segment]), SimpleNamespace(duration=2.0)


def _prepare(_models_root: Path, _profile) -> Path:
    return Path("model")


def _load(_path: Path, _plan):
    return _Model(), "float16", False


def _cuda() -> dict:
    return {
        "available": True,
        "device_count": 1,
        "supported_compute_types": ["float16", "int8_float16"],
    }


def _integrity(_models_root: Path, _profile) -> dict[str, object]:
    return {"status": "ready", "content_sha256": "c" * 64}


def _bad_integrity(_models_root: Path, _profile) -> dict[str, object]:
    return {"status": "corrupt"}


def test_acceptance_receipt_proves_cuda_without_leaking_transcript(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    receipt = run_whisper_gpu_acceptance(
        audio,
        tmp_path / "Models",
        profile_id="whisper-turbo",
        required_gpu_name="RTX 4070",
        cuda_status=_cuda(),
        prepare_model=_prepare,
        model_loader=_load,
        monitor_factory=_Monitor,
        integrity_checker=_integrity,
    )

    assert receipt["pass"] is True
    assert receipt["inference"]["device"] == "cuda"
    assert receipt["inference"]["compute_type"] == "float16"
    assert receipt["inference"]["rtf"] is not None
    assert receipt["gpu"]["required_name_match"] is True
    assert receipt["gpu"]["peak_utilization_percent"] == 97
    assert receipt["model_revision"]
    assert receipt["model_content_sha256"] == "c" * 64
    assert receipt["model_integrity"] == "sha256-full"
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert "segredo da mesa" not in serialized
    assert "fake-audio" not in serialized


def test_acceptance_writes_transcript_only_when_explicit(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")
    transcript = tmp_path / "acceptance-transcript.json"

    receipt = run_whisper_gpu_acceptance(
        audio,
        tmp_path / "Models",
        profile_id="whisper-detailed",
        transcript_out=transcript,
        cuda_status=_cuda(),
        prepare_model=_prepare,
        model_loader=_load,
        monitor_factory=_Monitor,
        integrity_checker=_integrity,
    )

    assert receipt["inference"]["transcript_written"] is True
    payload = json.loads(transcript.read_text(encoding="utf-8"))
    assert payload["schema"] == "tda_whisper_acceptance_transcript_v1"
    assert payload["segments"][0]["text"] == "segredo da mesa"


def test_acceptance_requires_cuda_and_expected_physical_gpu(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    with pytest.raises(WhisperAcceptanceError, match="WHISPER_CUDA_UNAVAILABLE"):
        run_whisper_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="whisper-turbo",
            cuda_status={"available": False, "device_count": 0, "supported_compute_types": []},
            prepare_model=_prepare,
            model_loader=_load,
            monitor_factory=_Monitor,
            integrity_checker=_integrity,
        )

    with pytest.raises(WhisperAcceptanceError, match="ACCEPTANCE_GPU_NAME_MISMATCH"):
        run_whisper_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="whisper-turbo",
            required_gpu_name="RTX 3090",
            cuda_status=_cuda(),
            prepare_model=_prepare,
            model_loader=_load,
            monitor_factory=_Monitor,
            integrity_checker=_integrity,
        )


def test_acceptance_fails_closed_when_full_model_hash_does_not_validate(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    with pytest.raises(WhisperAcceptanceError, match="ACCEPTANCE_MODEL_INTEGRITY_FAILED"):
        run_whisper_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="whisper-turbo",
            cuda_status=_cuda(),
            prepare_model=_prepare,
            model_loader=_load,
            monitor_factory=_Monitor,
            integrity_checker=_bad_integrity,
        )
