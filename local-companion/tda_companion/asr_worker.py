from __future__ import annotations

from .atomic_storage import AtomicStorageError

import hashlib
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable, TextIO

from .asr_models import ModelRegistryError, get_profile
from .attempt_fence import AttemptFenceError, claim_attempt_outcome
from .asr_whisper import WhisperRuntimeError, transcribe_craig_package
from .craig import CraigPackageError
from .craig_runtime import load_craig_package
from .execution_device import reset_execution_device
from .execution_lineage import capture_execution_lineage
from .transcript import TranscriptValidationError
from .transcription_runs import (
    TranscriptionRunError,
    migrate_legacy_transcript,
    remove_incomplete_runs,
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


def _run_fixture(
    command: WorkerRunCommand,
    emitter: _Emitter,
    cancelled: threading.Event,
    *,
    emit_ready: bool = True,
) -> int:
    units = int(command.payload["units"])
    completed = int(command.payload.get("completed", 0))
    if emit_ready:
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


def _run_craig(
    command: WorkerRunCommand,
    emitter: _Emitter,
    cancelled: threading.Event,
    *,
    emit_ready: bool = True,
) -> int:
    reset_execution_device()
    if emit_ready:
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
        # Ingest already established full per-track SHA-256 identities. Re-reading
        # every staged FLAC here made large sessions spend minutes on disk I/O
        # before the first ASR stage while GPU/CPU looked idle. Normal execution
        # revalidates the manifest, safe paths and exact sizes; explicit ingest /
        # deep diagnostics remain the byte-hash trust boundary.
        emitter.emit(
            "stage",
            {
                "stage": "source_validation",
                "profile": str(command.payload["profile_id"]),
            },
        )
        package = load_craig_package(package_root, verify_tracks=False)
        removed_runs = remove_incomplete_runs(package_root)
        if removed_runs:
            emitter.emit(
                "event",
                {
                    "code": "INCOMPLETE_RUNS_CLEANED",
                    "stage": "source_validation",
                    "count": removed_runs,
                },
            )
        emitter.emit(
            "event",
            {
                "code": "SOURCE_VALIDATED",
                "stage": "source_validation",
                "track_count": len(package.tracks),
            },
        )
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

        if document.source_sha256.lower() != package.source_sha256.lower():
            raise TranscriptionRunError("TRANSCRIPTION_SOURCE_HASH_MISMATCH")

        def reserve_run_commit() -> None:
            winner = claim_attempt_outcome(
                package_root,
                command.job_id,
                command.attempt,
                "commit",
            )
            if winner != "commit":
                raise AttemptFenceError("ATTEMPT_CANCELLED")
            emitter.emit(
                "event",
                {
                    "code": "RUN_COMMIT_FENCE_WON",
                    "stage": "result_prepare",
                    "attempt": command.attempt,
                },
            )

        execution_lineage = capture_execution_lineage(document)
        manifest = write_completed_run(
            package_root,
            document,
            job_id=command.job_id,
            attempt=command.attempt,
            glossary=str(command.payload.get("glossary") or ""),
            context=str(command.payload.get("context") or ""),
            execution_lineage=execution_lineage,
            before_commit=reserve_run_commit,
        )
        run_id = str(manifest["run_id"])
        digest = str(manifest["transcript_sha256"])

        # Keep the historical root transcript only as a compatibility mirror.
        # The immutable run is authoritative: a locked/corrupt legacy mirror must
        # not turn a fully committed ASR result into a failed job.
        try:
            mirror_digest = write_compatibility_mirror(package_root, run_id)
            if mirror_digest != digest:
                emitter.emit(
                    "event",
                    {
                        "code": "COMPATIBILITY_MIRROR_WRITE_FAILED",
                        "stage": "result_prepare",
                        "reason": "hash_mismatch",
                    },
                )
        except (OSError, TranscriptionRunError) as exc:
            emitter.emit(
                "event",
                {
                    "code": ("COMPATIBILITY_MIRROR_LEGACY_PRESERVED" if str(exc) == "TRANSCRIPTION_LEGACY_PRESERVED_IN_PLACE"
                             else "COMPATIBILITY_MIRROR_WRITE_FAILED"),
                    "stage": "result_prepare",
                    "reason": "legacy_preserved" if str(exc) == "TRANSCRIPTION_LEGACY_PRESERVED_IN_PLACE" else "write_failed",
                },
            )

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
    except AtomicStorageError as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        emitter.emit("error", {"code": str(exc), "recoverable": True, "stage": "result_prepare"})
        return 66
    except AttemptFenceError as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        code = str(exc)
        if code == "ATTEMPT_CANCELLED":
            emitter.emit("cancelled", {"stage": "result_prepare", "fence": "cancel"})
            return 0
        safe_code = code if re.fullmatch(r"[A-Z0-9_]{1,96}", code) else "ATTEMPT_FENCE_FAILED"
        emitter.emit("error", {"code": safe_code, "recoverable": True})
        return 66
    except WhisperRuntimeError as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        if exc.code == "ASR_CANCELLED" or cancelled.is_set():
            emitter.emit("cancelled", {"stage": "transcription"})
            return 0
        emitter.emit("error", {"code": _stable_error_code(exc), "recoverable": True})
        return 66
    except TranscriptValidationError:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        emitter.emit(
            "error",
            {"code": "TRANSCRIPT_VALIDATION_FAILED", "recoverable": False},
        )
        return 66
    except (ModelRegistryError, CraigPackageError, TranscriptionRunError) as exc:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        emitter.emit("error", {"code": _stable_error_code(exc), "recoverable": False})
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
    *,
    pre_worker_bootstrap: Callable[[], None] | None = None,
    bootstrap_stage: str = "runtime_bootstrap",
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
    ready_emitted = False

    # Frozen Qwen/Torch initialization can legitimately take longer than the
    # generic process startup budget and must happen before worker threads exist.
    # Emit protocol ownership first, expose a bounded bootstrap stage to the
    # supervisor, then perform the heavy single-threaded import. Cancellation
    # remains safe because the supervisor can force-stop the isolated process.
    if pre_worker_bootstrap is not None:
        ready_payload = {"kind": command.kind}
        profile_id = command.payload.get("profile_id")
        if isinstance(profile_id, str) and profile_id:
            ready_payload["profile_id"] = profile_id
        try:
            emitter.emit("ready", ready_payload)
            emitter.emit("stage", {"stage": bootstrap_stage})
            ready_emitted = True
            pre_worker_bootstrap()
        except BaseException:
            try:
                emitter.emit(
                    "error",
                    {"code": "WORKER_RUNTIME_BOOTSTRAP_FAILED", "recoverable": True},
                )
            except BaseException:
                pass
            return 70

    watcher = threading.Thread(
        target=_watch_cancel,
        args=(input_stream, command, cancelled),
        name="tda-worker-control",
        daemon=True,
    )
    watcher.start()

    try:
        if command.kind == "synthetic.fixture":
            return _run_fixture(command, emitter, cancelled, emit_ready=not ready_emitted)
        if command.kind == "transcription.craig":
            return _run_craig(command, emitter, cancelled, emit_ready=not ready_emitted)
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
