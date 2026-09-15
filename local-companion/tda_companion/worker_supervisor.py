from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .asr_runtime import current_whisper_worker
from .qwen_physical_gate import inspect_qwen_physical_gate
from .qwen_runtime import current_qwen_worker
from .worker_protocol import WorkerCancelCommand, WorkerMessage, WorkerProtocolError, WorkerRunCommand


class WorkerProcessError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkerOutcome:
    terminal: str
    payload: dict
    returncode: int


def default_worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, "-m", "tda_companion.asr_worker"]


class WorkerSupervisor:
    """Supervise one heavy local worker without loading model code into FastAPI."""

    def __init__(
        self,
        *,
        command_factory: Callable[[], list[str]] = default_worker_command,
        startup_timeout: float = 10.0,
        heartbeat_timeout: float = 30.0,
        cancel_grace: float = 3.0,
        data_root: Path | None = None,
        models_root: Path | None = None,
        runtime_root: Path | None = None,
        state_root: Path | None = None,
    ):
        self.command_factory = command_factory
        self.startup_timeout = startup_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.cancel_grace = cancel_grace
        self.data_root = data_root.resolve() if data_root is not None else None
        self.models_root = models_root.resolve() if models_root is not None else None
        self.runtime_root = (
            runtime_root.resolve()
            if runtime_root is not None
            else self.data_root.parent / "Runtime"
            if self.data_root is not None
            else None
        )
        self.state_root = (
            state_root.resolve()
            if state_root is not None
            else self.data_root.parent / "State"
            if self.data_root is not None
            else None
        )

    @staticmethod
    def _creationflags() -> int:
        if os.name != "nt":
            return 0
        return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    @staticmethod
    def _drain_stderr(stream) -> None:
        try:
            while stream.read(8192):
                pass
        except (OSError, ValueError):
            pass

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if self.data_root is not None:
            environment["TDA_WORKER_DATA_ROOT"] = str(self.data_root)
        if self.models_root is not None:
            environment["TDA_WORKER_MODELS_ROOT"] = str(self.models_root)
        return environment

    def _run_command(
        self,
        command: WorkerRunCommand,
        *,
        on_progress: Callable[[WorkerMessage], object],
        on_event: Callable[[WorkerMessage], object] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        process_command: list[str] | None = None,
    ) -> WorkerOutcome:
        encoded_command = command.encode()
        executable_command = process_command or self.command_factory()
        if not executable_command or not all(isinstance(item, str) and item for item in executable_command):
            raise WorkerProcessError("WORKER_COMMAND_INVALID")
        process = subprocess.Popen(
            executable_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            close_fds=True,
            creationflags=self._creationflags(),
            env=self._environment(),
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        lines: queue.Queue[str | None] = queue.Queue()

        def read_stdout() -> None:
            try:
                for line in process.stdout:
                    lines.put(line)
            except (OSError, UnicodeError, ValueError):
                pass
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_stdout, name="tda-worker-stdout", daemon=True)
        stderr_reader = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr,),
            name="tda-worker-stderr",
            daemon=True,
        )
        reader.start()
        stderr_reader.start()

        ready = False
        previous_seq: int | None = None
        last_message = time.monotonic()
        started = last_message
        cancel_sent = False
        cancel_deadline: float | None = None
        terminal: WorkerMessage | None = None

        try:
            process.stdin.write(encoded_command)
            process.stdin.flush()

            while terminal is None:
                now = time.monotonic()
                if is_cancelled is not None and is_cancelled() and not cancel_sent:
                    process.stdin.write(
                        WorkerCancelCommand(job_id=command.job_id, attempt=command.attempt).encode()
                    )
                    process.stdin.flush()
                    cancel_sent = True
                    cancel_deadline = now + self.cancel_grace

                if not ready and now - started > self.startup_timeout:
                    raise WorkerProcessError("WORKER_START_TIMEOUT")
                if ready and now - last_message > self.heartbeat_timeout:
                    raise WorkerProcessError("WORKER_HEARTBEAT_TIMEOUT")
                if cancel_deadline is not None and now > cancel_deadline:
                    raise WorkerProcessError("WORKER_CANCEL_TIMEOUT")

                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None and lines.empty():
                        break
                    continue
                if line is None:
                    if process.poll() is not None:
                        break
                    continue

                try:
                    message = WorkerMessage.decode(
                        line,
                        expected_job_id=command.job_id,
                        expected_attempt=command.attempt,
                        previous_seq=previous_seq,
                    )
                except WorkerProtocolError as exc:
                    raise WorkerProcessError(str(exc)) from None
                previous_seq = message.seq
                last_message = time.monotonic()

                if message.type == "ready":
                    ready = True
                elif message.type == "progress":
                    on_progress(message)
                elif message.type in {"stage", "event", "heartbeat"}:
                    if on_event is not None:
                        on_event(message)
                elif message.type == "error":
                    code = str(message.payload.get("code") or "WORKER_EXECUTION_FAILED")
                    raise WorkerProcessError(code)
                elif message.type in {"result", "cancelled"}:
                    terminal = message

            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                returncode = process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                raise WorkerProcessError("WORKER_EXIT_TIMEOUT") from None

            if terminal is None:
                raise WorkerProcessError("WORKER_EXITED_WITHOUT_RESULT")
            if terminal.type == "result" and returncode != 0:
                raise WorkerProcessError("WORKER_NONZERO_EXIT")
            return WorkerOutcome(terminal=terminal.type, payload=terminal.payload, returncode=returncode)
        except BaseException:
            self._stop_process(process)
            raise
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.stdout.close()
                process.stderr.close()
            except (OSError, ValueError):
                pass

    def run_fixture(
        self,
        *,
        job_id: str,
        attempt: int,
        units: int,
        completed: int,
        on_progress: Callable[[WorkerMessage], object],
        on_event: Callable[[WorkerMessage], object] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> WorkerOutcome:
        return self._run_command(
            WorkerRunCommand(
                job_id=job_id,
                attempt=attempt,
                kind="synthetic.fixture",
                payload={"units": units, "completed": completed},
            ),
            on_progress=on_progress,
            on_event=on_event,
            is_cancelled=is_cancelled,
        )

    def run_craig(
        self,
        *,
        job_id: str,
        attempt: int,
        source_id: str,
        profile_id: str,
        glossary: str,
        context: str,
        cpu: bool,
        on_progress: Callable[[WorkerMessage], object],
        on_event: Callable[[WorkerMessage], object] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> WorkerOutcome:
        if self.data_root is None or self.models_root is None:
            raise WorkerProcessError("WORKER_ASR_ROOTS_UNCONFIGURED")

        worker_command = WorkerRunCommand(
            job_id=job_id,
            attempt=attempt,
            kind="transcription.craig",
            payload={
                "source_id": source_id,
                "profile_id": profile_id,
                "glossary": glossary,
                "context": context,
                "cpu": cpu,
            },
        )
        # Validate all user-derived identifiers before consulting runtime state.
        # Invalid source/profile input must not cause worker lookup or filesystem activity.
        worker_command.encode()

        runtime_command = None
        if profile_id.startswith("whisper-"):
            if self.runtime_root is None:
                raise WorkerProcessError("WHISPER_RUNTIME_UNCONFIGURED")
            worker = current_whisper_worker(self.runtime_root)
            if worker is None:
                raise WorkerProcessError("WHISPER_RUNTIME_UNAVAILABLE")
            runtime_command = [str(worker)]
        elif profile_id.startswith("qwen-"):
            if self.runtime_root is None or self.state_root is None:
                raise WorkerProcessError("QWEN_RUNTIME_UNCONFIGURED")
            gate = inspect_qwen_physical_gate(
                self.state_root,
                self.runtime_root,
                self.models_root,
                profile_id=profile_id,
                verify_model_content=True,
            )
            if gate.get("ready") is not True:
                raise WorkerProcessError("QWEN_PHYSICAL_ACCEPTANCE_REQUIRED")
            worker = current_qwen_worker(self.runtime_root)
            if worker is None:
                raise WorkerProcessError("QWEN_RUNTIME_UNAVAILABLE")
            runtime_command = [str(worker)]

        return self._run_command(
            worker_command,
            on_progress=on_progress,
            on_event=on_event,
            is_cancelled=is_cancelled,
            process_command=runtime_command,
        )
