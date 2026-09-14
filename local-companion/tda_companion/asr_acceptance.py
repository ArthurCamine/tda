from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .asr_models import AsrProfile, get_profile, inspect_model_install
from .asr_whisper import (
    WhisperPlan,
    WhisperRuntimeError,
    load_whisper_model,
    prepare_whisper_model,
    probe_whisper_cuda,
    resolve_whisper_plan,
    whisper_transcribe_options,
)

ACCEPTANCE_SCHEMA = "tda_whisper_gpu_acceptance_v1"
_MAX_AUDIO_BYTES = 2 * 1024**3
_COPY_CHUNK = 1024 * 1024


class WhisperAcceptanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _text_hash(segments: list[dict[str, Any]]) -> str:
    value = "\n".join(str(segment.get("text") or "").strip() for segment in segments).strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _serialize_segment(segment: Any) -> dict[str, Any]:
    words: list[dict[str, Any]] = []
    for word in getattr(segment, "words", None) or []:
        text = str(getattr(word, "word", "")).strip()
        if not text:
            continue
        value: dict[str, Any] = {
            "text": text,
            "start": round(float(getattr(word, "start", 0.0)), 3),
            "end": round(float(getattr(word, "end", 0.0)), 3),
        }
        probability = getattr(word, "probability", None)
        if probability is not None:
            value["confidence"] = round(float(probability), 6)
        words.append(value)
    return {
        "start": round(float(getattr(segment, "start", 0.0)), 3),
        "end": round(float(getattr(segment, "end", 0.0)), 3),
        "text": str(getattr(segment, "text", "")).strip(),
        "words": words,
    }


class NvmlPeakMonitor:
    """Best-effort telemetry for a physical acceptance run; never logs model text."""

    def __init__(self, index: int = 0, interval_seconds: float = 0.1):
        self.index = index
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = False
        self._handle: Any = None
        self._pynvml: Any = None
        self._gpu_name: str | None = None
        self._driver: str | None = None
        self._memory_total_bytes: int | None = None
        self._baseline_memory_used_bytes: int | None = None
        self._peak_memory_used_bytes: int | None = None
        self._peak_utilization_percent: int | None = None

    @staticmethod
    def _decode(value: Any) -> str | None:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value).strip() if value is not None else ""
        return text[:160] if text else None

    def start(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.index)
            self._gpu_name = self._decode(pynvml.nvmlDeviceGetName(self._handle))
            self._driver = self._decode(pynvml.nvmlSystemGetDriverVersion())
            memory = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            self._memory_total_bytes = max(0, int(memory.total))
            self._baseline_memory_used_bytes = max(0, int(memory.used))
            self._peak_memory_used_bytes = self._baseline_memory_used_bytes
            self._available = True
        except Exception:
            self._available = False
            return
        self._sample()
        self._thread = threading.Thread(target=self._run, name="tda-whisper-nvml", daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        if not self._available or self._pynvml is None or self._handle is None:
            return
        try:
            memory = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            utilization = self._pynvml.nvmlDeviceGetUtilizationRates(self._handle)
            used = max(0, int(memory.used))
            gpu = max(0, min(100, int(utilization.gpu)))
            self._peak_memory_used_bytes = max(self._peak_memory_used_bytes or 0, used)
            self._peak_utilization_percent = max(self._peak_utilization_percent or 0, gpu)
        except Exception:
            return

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def stop(self) -> dict[str, Any]:
        self._sample()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        return {
            "available": self._available,
            "index": self.index,
            "name": self._gpu_name,
            "driver": self._driver,
            "memory_total_bytes": self._memory_total_bytes,
            "baseline_memory_used_bytes": self._baseline_memory_used_bytes,
            "peak_memory_used_bytes": self._peak_memory_used_bytes,
            "peak_utilization_percent": self._peak_utilization_percent,
        }


def _runtime_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for module_name, key in (
        ("faster_whisper", "faster_whisper"),
        ("ctranslate2", "ctranslate2"),
        ("av", "av"),
    ):
        try:
            module = __import__(module_name)
            values[key] = str(getattr(module, "__version__", "unknown"))
        except Exception:
            values[key] = "unavailable"
    return values


def _validate_audio(path: Path) -> Path:
    source = path.resolve()
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise WhisperAcceptanceError("ACCEPTANCE_AUDIO_NOT_FOUND") from exc
    if not source.is_file() or size <= 0:
        raise WhisperAcceptanceError("ACCEPTANCE_AUDIO_INVALID")
    if size > _MAX_AUDIO_BYTES:
        raise WhisperAcceptanceError("ACCEPTANCE_AUDIO_TOO_LARGE")
    return source


def _verify_model_integrity(models_root: Path, profile: AsrProfile) -> dict[str, object]:
    state = inspect_model_install(models_root.resolve(), profile, verify_hash=True)
    digest = state.get("content_sha256")
    if state.get("status") != "ready" or not isinstance(digest, str) or len(digest) != 64:
        raise WhisperAcceptanceError("ACCEPTANCE_MODEL_INTEGRITY_FAILED")
    return state


def run_whisper_gpu_acceptance(
    audio_path: Path,
    models_root: Path,
    *,
    profile_id: str,
    glossary: str = "",
    context: str = "",
    required_gpu_name: str | None = None,
    transcript_out: Path | None = None,
    cuda_status: dict[str, Any] | None = None,
    prepare_model: Callable[..., Path] = prepare_whisper_model,
    model_loader: Callable[[Path, WhisperPlan], tuple[Any, str, bool]] = load_whisper_model,
    monitor_factory: Callable[[], Any] = NvmlPeakMonitor,
    integrity_checker: Callable[[Path, AsrProfile], dict[str, object]] = _verify_model_integrity,
) -> dict[str, Any]:
    source = _validate_audio(audio_path)
    profile: AsrProfile = get_profile(profile_id)
    if profile.engine != "whisper":
        raise WhisperAcceptanceError("ACCEPTANCE_WHISPER_PROFILE_REQUIRED")

    status = cuda_status if cuda_status is not None else probe_whisper_cuda()
    try:
        plan = resolve_whisper_plan(profile.id, cpu=False, cuda_status=status)
    except WhisperRuntimeError as exc:
        raise WhisperAcceptanceError(exc.code) from exc
    if plan.device != "cuda":
        raise WhisperAcceptanceError("ACCEPTANCE_CUDA_REQUIRED")

    total_started = time.monotonic()
    prepare_started = time.monotonic()
    try:
        prepared = prepare_model(models_root.resolve(), profile)
    except WhisperRuntimeError as exc:
        raise WhisperAcceptanceError(exc.code) from exc
    prepare_seconds = max(time.monotonic() - prepare_started, 0.0)

    integrity = integrity_checker(models_root.resolve(), profile)
    model_content_sha256 = integrity.get("content_sha256")
    if not isinstance(model_content_sha256, str) or len(model_content_sha256) != 64:
        raise WhisperAcceptanceError("ACCEPTANCE_MODEL_INTEGRITY_FAILED")

    monitor = monitor_factory()
    monitor.start()
    gpu_metrics: dict[str, Any] = {"available": False}
    try:
        load_started = time.monotonic()
        try:
            model, compute_type, used_fallback = model_loader(prepared, plan)
        except WhisperRuntimeError as exc:
            raise WhisperAcceptanceError(exc.code) from exc
        load_seconds = max(time.monotonic() - load_started, 0.0)

        transcription_started = time.monotonic()
        segments_iter, info = model.transcribe(
            str(source),
            **whisper_transcribe_options(glossary=glossary, context=context),
        )
        segments = [_serialize_segment(segment) for segment in segments_iter]
        segments = [segment for segment in segments if segment["text"]]
        transcription_seconds = max(time.monotonic() - transcription_started, 0.0)
    finally:
        gpu_metrics = monitor.stop()

    duration_seconds = max(0.0, float(getattr(info, "duration", 0.0) or 0.0))
    word_count = sum(len(segment["words"]) for segment in segments)
    if duration_seconds <= 0:
        raise WhisperAcceptanceError("ACCEPTANCE_AUDIO_DURATION_MISSING")
    if not segments or word_count <= 0:
        raise WhisperAcceptanceError("ACCEPTANCE_NO_SPEECH_RECOGNIZED")

    gpu_name = str(gpu_metrics.get("name") or "")
    required = (required_gpu_name or "").strip()
    gpu_match = not required or required.casefold() in gpu_name.casefold()
    if required and not gpu_match:
        raise WhisperAcceptanceError("ACCEPTANCE_GPU_NAME_MISMATCH")

    if transcript_out is not None:
        _atomic_json(
            transcript_out.resolve(),
            {
                "schema": "tda_whisper_acceptance_transcript_v1",
                "profile_id": profile.id,
                "model": profile.model_id,
                "revision": profile.revision,
                "language": "pt",
                "segments": segments,
            },
        )

    total_seconds = max(time.monotonic() - total_started, 0.0)
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "pass": True,
        "profile_id": profile.id,
        "model": profile.model_id,
        "model_revision": profile.revision,
        "model_content_sha256": model_content_sha256,
        "model_integrity": "sha256-full",
        "language": "pt",
        "audio_sha256": _sha256_file(source),
        "runtime": _runtime_versions(),
        "cuda": {
            "device_count": int(status.get("device_count") or 0),
            "supported_compute_types": sorted(str(item) for item in (status.get("supported_compute_types") or [])),
        },
        "gpu": {**gpu_metrics, "required_name": required or None, "required_name_match": gpu_match},
        "inference": {
            "device": plan.device,
            "compute_type": compute_type,
            "memory_fallback": bool(used_fallback),
            "audio_seconds": round(duration_seconds, 3),
            "prepare_seconds": round(prepare_seconds, 3),
            "model_load_seconds": round(load_seconds, 3),
            "transcription_seconds": round(transcription_seconds, 3),
            "total_seconds": round(total_seconds, 3),
            "rtf": round(transcription_seconds / duration_seconds, 6),
            "segment_count": len(segments),
            "word_count": word_count,
            "transcript_sha256": _text_hash(segments),
            "transcript_written": transcript_out is not None,
        },
    }
