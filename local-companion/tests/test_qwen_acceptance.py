from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion.qwen_acceptance import (
    QwenAcceptanceError,
    _qwen_inference_failure_code,
    run_qwen_gpu_acceptance,
)


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
            "peak_memory_used_bytes": 7 * 1024**3,
            "peak_utilization_percent": 96,
        }


def _cuda() -> dict:
    return {
        "available": True,
        "device_count": 1,
        "bf16_supported": True,
        "torch_cuda": "13.2",
        "devices": [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 4070 Laptop GPU",
                "compute_capability": "8.9",
                "total_memory_bytes": 8 * 1024**3,
            }
        ],
    }


def _prepare_model(_models_root: Path, _profile) -> Path:
    return Path("qwen-model")


def _prepare_aligner(_models_root: Path) -> Path:
    return Path("qwen-aligner")


def _asr(_model_root: Path, _audio: Path, plan, *, prompt: str) -> dict:
    assert plan.device == "cuda"
    assert plan.dtype == "bfloat16"
    assert "Vocabulário" in prompt
    return {
        "text": "segredo da mesa",
        "language": "Portuguese",
        "compute_type": "bfloat16",
        "model_load_seconds": 0.2,
        "inference_seconds": 0.5,
    }


def _align(_aligner_root: Path, _audio: Path, text: str, language: str, plan) -> dict:
    assert text == "segredo da mesa"
    assert language == "Portuguese"
    assert plan.device == "cuda"
    return {
        "words": [
            {"text": "segredo", "start": 0.1, "end": 0.4},
            {"text": "da", "start": 0.4, "end": 0.5},
            {"text": "mesa", "start": 0.5, "end": 0.8},
        ],
        "compute_type": "bfloat16",
        "model_load_seconds": 0.1,
        "inference_seconds": 0.2,
    }


def _duration(_audio: Path) -> float:
    return 2.0


def test_qwen_receipt_proves_gpu_and_alignment_without_leaking_transcript(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    receipt = run_qwen_gpu_acceptance(
        audio,
        tmp_path / "Models",
        profile_id="qwen-fast",
        glossary="Dandelion, Pipipi",
        required_gpu_name="RTX 4070",
        cuda_status=_cuda(),
        prepare_model=_prepare_model,
        prepare_aligner=_prepare_aligner,
        asr_runner=_asr,
        aligner_runner=_align,
        monitor_factory=_Monitor,
        duration_reader=_duration,
    )

    assert receipt["pass"] is True
    assert receipt["inference"]["device"] == "cuda"
    assert receipt["inference"]["compute_type"] == "bfloat16"
    assert receipt["alignment"]["word_count"] == 3
    assert receipt["gpu"]["required_name_match"] is True
    assert receipt["alignment_gpu"]["required_name_match"] is True
    assert receipt["model_revision"]
    assert receipt["alignment_revision"]
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert "segredo da mesa" not in serialized
    assert "fake-audio" not in serialized


def test_qwen_writes_transcript_only_when_explicit(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")
    transcript = tmp_path / "qwen-acceptance-transcript.json"

    receipt = run_qwen_gpu_acceptance(
        audio,
        tmp_path / "Models",
        profile_id="qwen-quality",
        glossary="Dandelion",
        transcript_out=transcript,
        cuda_status=_cuda(),
        prepare_model=_prepare_model,
        prepare_aligner=_prepare_aligner,
        asr_runner=_asr,
        aligner_runner=_align,
        monitor_factory=_Monitor,
        duration_reader=_duration,
    )

    assert receipt["inference"]["transcript_written"] is True
    payload = json.loads(transcript.read_text(encoding="utf-8"))
    assert payload["schema"] == "tda_qwen_acceptance_transcript_v1"
    assert payload["text"] == "segredo da mesa"
    assert payload["words"][0]["text"] == "segredo"


def test_qwen_requires_cuda_capability_and_expected_gpu(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    with pytest.raises(QwenAcceptanceError, match="QWEN_CUDA_UNAVAILABLE"):
        run_qwen_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="qwen-fast",
            cuda_status={"available": False, "device_count": 0, "devices": []},
            prepare_model=_prepare_model,
            prepare_aligner=_prepare_aligner,
            asr_runner=_asr,
            aligner_runner=_align,
            monitor_factory=_Monitor,
            duration_reader=_duration,
        )

    unsupported = _cuda()
    unsupported["devices"] = [{**unsupported["devices"][0], "compute_capability": "7.5"}]
    with pytest.raises(QwenAcceptanceError, match="QWEN_CUDA_CAPABILITY_UNSUPPORTED"):
        run_qwen_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="qwen-fast",
            cuda_status=unsupported,
            prepare_model=_prepare_model,
            prepare_aligner=_prepare_aligner,
            asr_runner=_asr,
            aligner_runner=_align,
            monitor_factory=_Monitor,
            duration_reader=_duration,
        )

    with pytest.raises(QwenAcceptanceError, match="QWEN_ACCEPTANCE_GPU_NAME_MISMATCH"):
        run_qwen_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="qwen-fast",
            glossary="Dandelion",
            required_gpu_name="RTX 3090",
            cuda_status=_cuda(),
            prepare_model=_prepare_model,
            prepare_aligner=_prepare_aligner,
            asr_runner=_asr,
            aligner_runner=_align,
            monitor_factory=_Monitor,
            duration_reader=_duration,
        )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError("CUDA out of memory"), "QWEN_ASR_GPU_MEMORY_EXHAUSTED"),
        (RuntimeError("CUBLAS_STATUS_EXECUTION_FAILED"), "QWEN_ASR_CUDA_FAILED"),
        (AttributeError("processor has no attribute"), "QWEN_ASR_RUNTIME_API_FAILED"),
        (ValueError("invalid audio shape"), "QWEN_ASR_INPUT_FAILED"),
        (RuntimeError("unknown backend failure"), "QWEN_ASR_INFERENCE_FAILED"),
    ],
)
def test_qwen_inference_failure_classifier_keeps_safe_cause_class(
    error: BaseException,
    code: str,
):
    assert _qwen_inference_failure_code(error) == code


def test_qwen_acceptance_rejects_samples_above_alignment_window(tmp_path: Path):
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-audio")

    with pytest.raises(QwenAcceptanceError, match="QWEN_ACCEPTANCE_AUDIO_TOO_LONG"):
        run_qwen_gpu_acceptance(
            audio,
            tmp_path / "Models",
            profile_id="qwen-fast",
            cuda_status=_cuda(),
            prepare_model=_prepare_model,
            prepare_aligner=_prepare_aligner,
            asr_runner=_asr,
            aligner_runner=_align,
            monitor_factory=_Monitor,
            duration_reader=lambda _path: 241.0,
        )
