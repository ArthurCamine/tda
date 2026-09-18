from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .craig import CraigPackageError
from .craig_runtime import load_craig_package
from .qwen_acceptance_window import QWEN_GATE_WINDOW_SECONDS
from .qwen_runtime import current_qwen_worker

_MAX_STDOUT_BYTES = 64 * 1024
_GATE_TIMEOUT_SECONDS = 2 * 60 * 60
ProgressCallback = Callable[[str, dict[str, object]], None]

_RETRYABLE_TRACK_ERRORS = {
    "QWEN_ACCEPTANCE_AUDIO_TOO_SHORT",
    "QWEN_ACCEPTANCE_AUDIO_INVALID",
    "QWEN_ACCEPTANCE_AUDIO_STREAM_MISSING",
    "QWEN_ACCEPTANCE_WINDOW_DECODE_FAILED",
    "QWEN_ACCEPTANCE_NO_SPEECH_RECOGNIZED",
}


class QwenDesktopPrepareError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _parse_json_stdout(result: Any, *, schema: str) -> dict[str, Any]:
    raw = str(getattr(result, "stdout", "") or "")
    if len(raw.encode("utf-8", errors="replace")) > _MAX_STDOUT_BYTES:
        raise QwenDesktopPrepareError("QWEN_PREPARATION_RESPONSE_TOO_LARGE")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise QwenDesktopPrepareError("QWEN_PREPARATION_RESPONSE_MISSING")
    try:
        value = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise QwenDesktopPrepareError("QWEN_PREPARATION_RESPONSE_INVALID") from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise QwenDesktopPrepareError("QWEN_PREPARATION_RESPONSE_INVALID")
    return value


def _run(
    command: list[str],
    *,
    timeout: float,
    runner: Callable[..., Any],
) -> Any:
    try:
        return runner(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise QwenDesktopPrepareError("QWEN_PREPARATION_TIMEOUT") from exc
    except OSError as exc:
        raise QwenDesktopPrepareError("QWEN_RUNTIME_EXEC_FAILED") from exc


def probe_qwen_long_track_gate(
    runtime_root: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    worker = current_qwen_worker(runtime_root)
    if worker is None:
        raise QwenDesktopPrepareError("QWEN_RUNTIME_UNAVAILABLE")
    result = _run([str(worker), "--probe"], timeout=30.0, runner=runner)
    value = _parse_json_stdout(result, schema="tda_qwen_runtime_probe_v1")
    if value.get("audio_decode_ready") is not True:
        raise QwenDesktopPrepareError("QWEN_AUDIO_DECODE_RUNTIME_FAILED")
    if int(getattr(result, "returncode", 1)) != 0 or value.get("ready") is not True:
        raise QwenDesktopPrepareError("QWEN_RUNTIME_PROBE_FAILED")
    if value.get("long_track_acceptance_window") is not True:
        raise QwenDesktopPrepareError("QWEN_RUNTIME_LONG_GATE_REQUIRED")
    if value.get("cuda_available") is not True:
        raise QwenDesktopPrepareError("QWEN_CUDA_UNAVAILABLE")
    if value.get("cuda_execution_ready") is not True:
        code = str(value.get("cuda_execution_error") or "QWEN_CUDA_EXECUTION_FAILED")
        if code not in {"QWEN_CUDA_DRIVER_INCOMPATIBLE", "QWEN_CUDA_EXECUTION_FAILED"}:
            code = "QWEN_CUDA_EXECUTION_FAILED"
        raise QwenDesktopPrepareError(code)
    return value


def prepare_qwen_profile_from_craig(
    *,
    data_root: Path,
    cache_root: Path,
    models_root: Path,
    runtime_root: Path,
    state_root: Path,
    source_id: str,
    profile_id: str,
    required_gpu_name: str = "RTX 4070",
    runner: Callable[..., Any] = subprocess.run,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    if profile_id not in {"qwen-fast", "qwen-quality"}:
        raise QwenDesktopPrepareError("QWEN_PROFILE_REQUIRED")
    report = progress or (lambda _stage, _context: None)
    worker = current_qwen_worker(runtime_root)
    if worker is None:
        raise QwenDesktopPrepareError("QWEN_RUNTIME_UNAVAILABLE")
    report("runtime_probe", {"profile_id": profile_id})
    probe = probe_qwen_long_track_gate(runtime_root, runner=runner)
    report(
        "runtime_probe_ready",
        {
            "profile_id": profile_id,
            "runtime_cuda": str(probe.get("torch_cuda") or "unknown"),
            "driver_version": str(probe.get("driver_version") or "unknown"),
        },
    )

    package_root = data_root.resolve() / "staging" / source_id
    try:
        package = load_craig_package(package_root, verify_tracks=True)
    except CraigPackageError as exc:
        raise QwenDesktopPrepareError(str(exc)) from exc
    if not package.tracks:
        raise QwenDesktopPrepareError("CRAIG_TRACKS_EMPTY")
    report(
        "selecting_audio",
        {"profile_id": profile_id, "track_count": len(package.tracks)},
    )

    scratch = cache_root.resolve() / "qwen-acceptance"
    scratch.mkdir(parents=True, exist_ok=True)
    last_retryable: str | None = None
    candidates = sorted(package.tracks, key=lambda track: (-track.size_bytes, track.number))
    for track in candidates:
        source = (package_root / track.path).resolve()
        if package_root.resolve() not in source.parents or not source.is_file():
            last_retryable = "CRAIG_TRACK_PATH_INVALID"
            continue
        report(
            "physical_gate",
            {
                "profile_id": profile_id,
                "track_number": int(track.number),
                "audio_window_seconds": int(QWEN_GATE_WINDOW_SECONDS),
            },
        )
        command = [
            str(worker),
            "--acceptance",
            "--acceptance-window",
            "--audio",
            str(source),
            "--models-root",
            str(models_root.resolve()),
            "--profile",
            profile_id,
            "--require-gpu-name",
            required_gpu_name,
            "--record-gate",
            "--runtime-root",
            str(runtime_root.resolve()),
            "--state-root",
            str(state_root.resolve()),
            "--scratch-root",
            str(scratch),
        ]
        result = _run(command, timeout=_GATE_TIMEOUT_SECONDS, runner=runner)
        value = _parse_json_stdout(result, schema="tda_qwen_gpu_acceptance_v1")
        if int(getattr(result, "returncode", 1)) != 0 or value.get("pass") is not True:
            code = str(value.get("error") or "QWEN_PHYSICAL_ACCEPTANCE_FAILED")
            if code in _RETRYABLE_TRACK_ERRORS:
                last_retryable = code
                continue
            raise QwenDesktopPrepareError(code)

        report(
            "physical_gate_ready",
            {
                "profile_id": profile_id,
                "track_number": int(track.number),
                "audio_window_seconds": int(QWEN_GATE_WINDOW_SECONDS),
            },
        )
        gpu = value.get("gpu") if isinstance(value.get("gpu"), dict) else {}
        inference = value.get("inference") if isinstance(value.get("inference"), dict) else {}
        window = value.get("source_window") if isinstance(value.get("source_window"), dict) else {}
        return {
            "ready": True,
            "profile_id": profile_id,
            "gpu_name": str(gpu.get("name") or "GPU local"),
            "audio_seconds": float(inference.get("audio_seconds") or 0.0),
            "window_start_seconds": float(window.get("start_seconds") or 0.0),
            "window_energy_dbfs": window.get("energy_dbfs"),
            "runtime_cuda": probe.get("torch_cuda"),
            "driver_version": probe.get("driver_version"),
        }

    raise QwenDesktopPrepareError(last_retryable or "QWEN_ACCEPTANCE_NO_SUITABLE_TRACK")
