from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import tda_companion.diagnostics as diagnostics


def _paths(tmp_path: Path):
    return SimpleNamespace(runtime_root=tmp_path / "Runtime")


def _completed(value: dict, *, returncode: int = 0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(value))


def _probe(
    *,
    cuda: bool = True,
    capability: str = "8.9",
    native: bool = True,
    execution_ready: bool | None = None,
    execution_error: str | None = None,
):
    devices = (
        [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 4070 Laptop GPU",
                "compute_capability": capability,
                "total_memory_bytes": 8 * 1024**3,
            }
        ]
        if cuda
        else []
    )
    return {
        "schema": "tda_qwen_runtime_probe_v1",
        "ready": True,
        "python_packages": {
            "torch": "2.13.0+cu126",
            "transformers": "5.17.0",
        },
        "torch_cuda": "12.6",
        "driver_version": "570.144",
        "cuda_execution_ready": cuda if execution_ready is None else execution_ready,
        "cuda_execution_error": execution_error,
        "cuda_available": cuda,
        "cuda_device_count": len(devices),
        "bf16_supported": cuda,
        "qwen3_asr_native": native,
        "forced_aligner_native": native,
        "devices": devices,
    }


def test_qwen_diagnostic_reports_missing_without_failing_companion(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {"status": "missing", "version": None, "worker": None},
    )
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))
    assert result == {
        "code": "qwen_runtime",
        "status": "unavailable",
        "message": "Runtime Qwen ainda não está instalado",
    }


def test_qwen_diagnostic_fails_on_corrupt_runtime_before_probe(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {"status": "corrupt", "version": "1.0.0", "worker": None},
    )
    monkeypatch.setattr(
        diagnostics.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("probe should not run")),
    )
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))
    assert result["status"] == "fail"
    assert "integridade" in result["message"]
    assert result["detail"] == "versão 1.0.0"


def test_qwen_diagnostic_warns_when_runtime_is_valid_but_cuda_is_unavailable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "ready",
            "version": "1.0.0",
            "worker": str(tmp_path / "TDAQwenWorker.exe"),
        },
    )
    monkeypatch.setattr(
        diagnostics.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(_probe(cuda=False)),
    )
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))
    assert result["status"] == "warning"
    assert "CUDA não está disponível" in result["message"]
    assert "Torch 2.13.0+cu126" in result["detail"]


def test_qwen_diagnostic_fails_when_packaged_runtime_lacks_native_qwen_support(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "ready",
            "version": "1.0.0",
            "worker": str(tmp_path / "TDAQwenWorker.exe"),
        },
    )
    monkeypatch.setattr(
        diagnostics.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(_probe(native=False)),
    )
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))
    assert result["status"] == "fail"
    assert "suporte nativo completo" in result["message"]


def test_qwen_diagnostic_fails_when_gpu_is_found_but_cuda_cannot_execute(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "ready",
            "version": "1.0.5",
            "worker": str(tmp_path / "TDAQwenWorker.exe"),
        },
    )
    monkeypatch.setattr(
        diagnostics.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(
            _probe(
                execution_ready=False,
                execution_error="QWEN_CUDA_DRIVER_INCOMPATIBLE",
            )
        ),
    )

    result = diagnostics._qwen_runtime_check(_paths(tmp_path))

    assert result["status"] == "fail"
    assert "execução CUDA falhou" in result["message"]
    assert "QWEN_CUDA_DRIVER_INCOMPATIBLE" in result["detail"]
    assert "driver 570.144" in result["detail"]


def test_qwen_diagnostic_warns_for_unsupported_compute_capability(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "ready",
            "version": "1.0.0",
            "worker": str(tmp_path / "TDAQwenWorker.exe"),
        },
    )
    monkeypatch.setattr(
        diagnostics.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(_probe(capability="7.5")),
    )
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))
    assert result["status"] == "warning"
    assert "compute capability mínimo" in result["message"]
    assert "CC 7.5" in result["detail"]


def test_qwen_diagnostic_passes_only_with_integrity_native_support_and_compatible_gpu(monkeypatch, tmp_path: Path):
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "ready",
            "version": "1.0.0",
            "worker": str(tmp_path / "TDAQwenWorker.exe"),
        },
    )

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return _completed(_probe())

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    result = diagnostics._qwen_runtime_check(_paths(tmp_path))

    assert result["status"] == "pass"
    assert result["message"] == "Runtime Qwen íntegro e executável"
    assert "RTX 4070" in result["detail"]
    assert "CC 8.9" in result["detail"]
    assert calls["command"][1] == "--probe"
    assert calls["kwargs"]["timeout"] == 20
