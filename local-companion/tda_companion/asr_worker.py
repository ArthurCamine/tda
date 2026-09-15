from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, TextIO

from .asr_models import ModelRegistryError, get_profile
from .asr_whisper import WhisperRuntimeError, transcribe_craig_package
from .craig import CraigPackageError
from .craig_runtime import load_craig_package
from .transcription_runs import (
    TranscriptionRunError,
    migrate_legacy_transcript,
    write_compatibility_mirror,
    write_completed_run,
)
from .worker_protocol import (
    MAX_LINE_BYTES,
    WorkerCancelCommand,
    WorkerMessage,
    WorkerProtocolError,
    WorkerRunCommand,
)


class _Emitter:
    def __init__(self, stream: TextIO, command: WorkerRunCommand):
        self.stream = stream
        self.command = command
        self.seq = 0
        self.lock = threading.Lock()

    def emit(self, type: str, payload: dict | None = None) -> None:
        with self.lock:
            message = WorkerMessage.create(
                job_id=self.command.job_id,
                attempt=self.command.attempt,
                seq=self.seq,
                type=type,
                payload=payload,
            )
            self.seq += 1
            self.stream.write(message.encode())
            self.stream.flush()


def _read_bounded_line(stream: BinaryIO) -> bytes:
    line = stream.readline(MAX_LINE_BYTES + 1)
    if len(line) > MAX_LINE_BYTES:
        raise WorkerProtocolError("WORKER_LINE_TOO_LARGE")
    return line


def _watch_cancel(stream: BinaryIO, command: WorkerRunCommand, cancelled: threading.Event) -> None:
    try:
        while not cancelled.is_set():
            line = _read_bounded_line(stream)
            if not line:
                return
            value = WorkerCancelCommand.decode(line)
            if value.job_id == command.job_id and value.attempt == command.attempt:
                cancelled.set()
                return
    except (OSError, ValueError, WorkerProtocolError):
        return


def _run_fixture(command: WorkerRunCommand, emitter: _Emitter, cancelled: threading.Event) -> int:
    units = int(command.payload["units"])
    completed = int(command.payload.get("completed", 0))
    emitter.emit("ready", {"kind": command.kind})
    emitter.emit("stage", {"stage": "fixture", "label": "Synthetic fixture"})

    for current in range(completed + 1, units + 1):
        if cancelled.is_set():
            emitter.emit("cancelled", {"completed": current - 1, "total": units})
            return 0
        hashlib.sha256(f"{command.job_id}:{command.attempt}:{current}".encode("utf-8")).digest()
        emitter.emit(
            "progress",
            {"completed": current, "total": units, "unit": "items", "stage": "fixture"},
        )
        emitter.emit("heartbeat", {"completed": current})
        time.sleep(0.002)

    emitter.emit("result", {"kind": command.kind, "units": units})
    return 0


def _worker_root(name: str) -> Path:
    value = os.environ.get(name)
    if not value or "\x00" in value:
        raise WhisperRuntimeError("WORKER_ASR_ROOTS_MISSING")
    return Path(value).resolve()


def _stable_error_code(error: BaseException) -> str:
    code = str(error)
    if re.fullmatch(r"[A-Z0-9_]{1,96}", code):
        if isinstance(
            error,
            (WhisperRuntimeError, ModelRegistryError, CraigPackageError, TranscriptionRunError),
        ):
            return code
        if error.__class__.__name__ == "QwenRuntimeError":
            return code
    return "WORKER_EXECUTION_FAILED"


def _run_craig(command: WorkerRunCommand, emitter: _Emitter, cancelled: threading.Event) -> int:
    emitter.emit(
        "ready",
        {"kind": command.kind, "profile_id": command.payload["profile_id"]},
    )
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(5.0):
            if cancelled.is_set():
                return
            try:
                emitter.emit("heartbeat", {"stage": "asr"})
            except (OSError, ValueError, WorkerProtocolError):
                return

    heartbeat_thread = threading.Thread(target=heartbeat, name="tda-worker-heartbeat", daemon=True)
    heartbeat_thread.start()
    try:
        data_root = _worker_root("TDA_WORKER_DATA_ROOT")
        models_root = _worker_root("TDA_WORKER_MODELS_ROOT")
        source_id = str(command.payload["source_id"])
        staging_root = (data_root / "staging").resolve()
        package_root = (staging_root / source_id).resolve()
        if package_root.parent != staging_root:
            raise CraigPackageError("CRAIG_STAGING_PATH_INVALID")
        package = load_craig_package(package_root)
        profile = get_profile(str(command.payload["profile_id"]))

        # Preserve a valid pre-runs transcript before any compatibility mirror can
        # replace it. Migration is idempotent and never removes the legacy file.
        migrate_legacy_transcript(
            package_root,
            source_id=source_id,
            source_sha256=package.source_sha256,
        )

        def report(value: dict) -> None:
            event_type = value.get("type")
            payload = {key: item for key, item in value.items() if key != "type"}
            if event_type == "stage":
                emitter.emit("stage", payload)
            elif event_type == "progress":
                emitter.emit("progress", payload)
            elif event_type == "event":
                emitter.emit("event", payload)

        if profile.engine == "whisper":
            document = transcribe_craig_package(
                package,
                package_root,
                models_root,
                profile_id=profile.id,
                glossary=str(command.payload.get("glossary") or ""),
                context=str(command.payload.get("context") or ""),
                cpu=bool(command.payload.get("cpu", False)),
                report=report,
                is_cancelled=cancelled.is_set,
            )
        elif profile.engine == "qwen3":
            if bool(command.payload.get("cpu", False)):
                from .asr_qwen import QwenRuntimeError

                raise QwenRuntimeError("QWEN_CPU_UNSUPPORTED")
            # Import lazily so the normal Companion/Whisper process never needs to
            # import Torch/Transformers. The isolated Qwen worker owns this stack.
            from .asr_qwen_strict import transcribe_craig_package_qwen_strict

            document = transcribe_craig_package_qwen_strict(
                package,
                package_root,
                models_root,
                profile_id=profile.id,
                glossary=str(command.payload.get("glossary") or ""),
                context=str(command.payload.get("context") or ""),
                report=report,
                is_cancelled=cancelled.is_set,
            )
        else:
            raise WhisperRuntimeError("ASR_ENGINE_NOT_IMPLEMENTED")

        if cancelled.is_set():
            emitter.emit("cancelled", {"stage": "result_prepare"})
            return 0

        manifest = write_completed_run(
            package_root,
            document,
            job_id=command.job_id,
            attempt=command.attempt,
            glossary=str(command.payload.get("glossary") or ""),
            context=str(command.payload.get("context") or ""),
        )
        run_id = str(manifest["run_id"])
        digest = str(manifest["transcript_sha256"])

        # Existing 0.3.x API/result consumers still validate the root transcript.
        # Keep it only as a compatibility mirror; immutable runs are authoritative.
        if write_compatibility_mirror(package_root, run_id) != digest:
            raise TranscriptionRunError("TRANSCRIPTION_RUN_MIRROR_HASH_MISMATCH")

        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        emitter.emit(
            "result",
            {
                "kind": command.kind,
                "schema_version": document.schema_version,
                "source_id": source_id,
                "profile_id": profile.id,
                "artifact": "transcript.json",
                "run_id": run_id,
                "sha256": digest,
            },
        )
        return 0
    except WhisperRuntimeError as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        if exc.code == "ASR_CANCELLED" or cancelled.is_set():
            emitter.emit("cancelled", {"stage": "transcription"})
            return 0
        emitter.emit("error", {"code": _stable_error_code(exc), "recoverable": True})
        return 66
    except (ModelRegistryError, CraigPackageError, TranscriptionRunError) as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        emitter.emit("error", {"code": _stable_error_code(exc), "recoverable": True})
        return 66
    except Exception as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        if exc.__class__.__name__ == "QwenRuntimeError":
            if str(exc) == "ASR_CANCELLED" or cancelled.is_set():
                emitter.emit("cancelled", {"stage": "transcription"})
                return 0
            emitter.emit("error", {"code": _stable_error_code(exc), "recoverable": True})
            return 66
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)


def run_worker_stdio(
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    input_stream = stdin or getattr(sys.stdin, "buffer", None)
    output_stream = stdout or sys.stdout
    if input_stream is None or output_stream is None:
        return 70

    try:
        command_line = _read_bounded_line(input_stream)
        if not command_line:
            return 64
        command = WorkerRunCommand.decode(command_line)
    except WorkerProtocolError:
        return 64

    emitter = _Emitter(output_stream, command)
    cancelled = threading.Event()
    watcher = threading.Thread(
        target=_watch_cancel,
        args=(input_stream, command, cancelled),
        name="tda-worker-control",
        daemon=True,
    )
    watcher.start()

    try:
        if command.kind == "synthetic.fixture":
            return _run_fixture(command, emitter, cancelled)
        if command.kind == "transcription.craig":
            return _run_craig(command, emitter, cancelled)
        emitter.emit("error", {"code": "WORKER_KIND_UNSUPPORTED", "recoverable": False})
        return 65
    except BaseException:
        try:
            emitter.emit("error", {"code": "WORKER_EXECUTION_FAILED", "recoverable": True})
        except BaseException:
            pass
        return 70
    finally:
        cancelled.set()
        try:
            input_stream.close()
        except (OSError, ValueError):
            pass
        watcher.join(timeout=1.0)


def main() -> int:
    return run_worker_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
