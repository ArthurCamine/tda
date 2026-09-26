from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .asr_models import get_profile, inspect_model_install
from .asr_runtime import inspect_whisper_runtime, install_whisper_runtime_archive
from .asr_runtime_updates import (
    download_whisper_runtime,
    fetch_whisper_runtime_manifest,
    whisper_runtime_update_available,
)
from .craig import CraigPackageError
from .craig_runtime import load_craig_package
from .network import NetworkError
from .qwen_desktop_prepare import (
    QwenDesktopPrepareError,
    prepare_qwen_profile_from_craig,
    probe_qwen_long_track_gate,
)
from .qwen_physical_gate import inspect_qwen_physical_gate
from .qwen_runtime import inspect_qwen_runtime, install_qwen_runtime_archive
from .qwen_runtime_updates import (
    download_qwen_runtime,
    fetch_qwen_runtime_manifest,
    qwen_runtime_update_available,
)
from .runtime_compat import (
    qwen_runtime_version_compatible,
    whisper_runtime_version_compatible,
)
from .runtime_rc_updates import install_published_runtime_rc
from .system_log import SystemLog
from .whisper_desktop_prepare import WhisperDesktopPrepareError, prepare_whisper_profile

_PROFILE_IDS = ("qwen-quality", "qwen-fast", "whisper-detailed", "whisper-turbo")
_SOURCE_ID = re.compile(r"^craig-[0-9a-f]{64}$")
_QWEN_RUNTIME_REPAIRABLE_PROBE_ERRORS = frozenset(
    {
        "QWEN_RUNTIME_LONG_GATE_REQUIRED",
        "QWEN_AUDIO_DECODE_RUNTIME_FAILED",
        "QWEN_RUNTIME_PROBE_FAILED",
    }
)


class ProfilePreparationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,96}", code):
        return code
    value = str(exc).strip()
    if re.fullmatch(r"[A-Z0-9_]{1,96}", value):
        return value
    return "TRANSCRIPTION_PREPARATION_FAILED"


def _check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise ProfilePreparationError("TRANSCRIPTION_PREPARATION_CANCELLED")


_BACKGROUND_DOWNLOAD_CODE = "DOWNLOAD_CONTINUES_IN_BACKGROUND"
_PREPARATION_MAX_SECONDS = 2 * 60 * 60


def _finish_resumable_download(
    operation: Callable[[float], object],
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> object:
    """Reconnect to the same BITS-owned transfer instead of starting a fallback.

    DOWNLOAD_CONTINUES_IN_BACKGROUND is progress, not a failed transport. The
    deterministic BITS destination lets the next call resume/acknowledge the
    same transfer without duplicating multi-gigabyte runtime downloads.
    """
    deadline = time.monotonic() + _PREPARATION_MAX_SECONDS
    while True:
        _check_cancelled(is_cancelled)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProfilePreparationError("TRANSCRIPTION_PREPARATION_TIMEOUT")
        try:
            return operation(remaining)
        except NetworkError as exc:
            if exc.code != _BACKGROUND_DOWNLOAD_CODE:
                raise
            _check_cancelled(is_cancelled)
            if time.monotonic() >= deadline:
                raise ProfilePreparationError(
                    "TRANSCRIPTION_PREPARATION_TIMEOUT"
                ) from exc
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _runtime_ready(state: dict, family: str) -> bool:
    version = state.get("version")
    if state.get("status") != "ready" or not isinstance(version, str):
        return False
    return (
        whisper_runtime_version_compatible(version)
        if family == "whisper"
        else qwen_runtime_version_compatible(version)
    )


def _probe_qwen_runtime(
    runtime_root: Path,
    is_cancelled: Callable[[], bool] | None,
) -> dict:
    if is_cancelled is None:
        return probe_qwen_long_track_gate(runtime_root)
    return probe_qwen_long_track_gate(
        runtime_root,
        is_cancelled=is_cancelled,
    )


def whisper_model_ready(state: dict[str, object]) -> bool:
    metadata_sha256 = state.get("metadata_sha256")
    return (
        state.get("status") == "ready"
        and isinstance(metadata_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", metadata_sha256) is not None
    )


def profile_catalog(
    state_root: Path,
    runtime_root: Path,
    models_root: Path,
) -> list[dict[str, object]]:
    whisper_state = inspect_whisper_runtime(runtime_root, verify_worker=False)
    qwen_state = inspect_qwen_runtime(runtime_root, verify_worker=False)
    result: list[dict[str, object]] = []

    for profile_id in _PROFILE_IDS:
        profile = get_profile(profile_id)
        ready = False
        reason: str | None = None
        if profile.engine == "whisper":
            if not _runtime_ready(whisper_state, "whisper"):
                reason = "WHISPER_RUNTIME_REQUIRED"
            else:
                model = inspect_model_install(models_root, profile, verify_hash=False)
                ready = whisper_model_ready(model)
                if not ready:
                    reason = "WHISPER_MODEL_PREPARATION_REQUIRED"
        else:
            if not _runtime_ready(qwen_state, "qwen"):
                reason = "QWEN_RUNTIME_REQUIRED"
            else:
                gate = inspect_qwen_physical_gate(
                    state_root,
                    runtime_root,
                    models_root,
                    profile_id=profile_id,
                    verify_model_content=False,
                )
                ready = gate.get("ready") is True
                if not ready:
                    reason = str(
                        gate.get("reason")
                        or f"QWEN_GATE_{str(gate.get('status') or 'missing').upper()}"
                    )
        result.append(
            {
                "id": profile_id,
                "engine": profile.engine,
                "ready": ready,
                "preparation_required": not ready,
                "reason": reason,
            }
        )
    return result


def _install_whisper_runtime(
    runtime_root: Path,
    cache_root: Path,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    _check_cancelled(is_cancelled)
    state = inspect_whisper_runtime(runtime_root, verify_worker=True)
    if _runtime_ready(state, "whisper"):
        return {
            "status": "ready",
            "version": state.get("version"),
            "accepted": False,
            "reused": True,
        }

    stable_error: BaseException | None = None
    try:
        _check_cancelled(is_cancelled)
        manifest = fetch_whisper_runtime_manifest()
        current = state.get("version") if state.get("status") == "ready" else None
        current_value = current if isinstance(current, str) else None
        if (
            whisper_runtime_version_compatible(manifest.version)
            and whisper_runtime_update_available(current_value, manifest)
        ):
            target = runtime_root / "whisper" / manifest.version
            repairing = target.exists() or target.is_symlink()
            archive = _finish_resumable_download(
                lambda remaining: download_whisper_runtime(
                    manifest,
                    cache_root,
                    timeout=min(300.0, remaining),
                ),
                is_cancelled=is_cancelled,
            )
            if not isinstance(archive, Path):
                raise ProfilePreparationError("WHISPER_RUNTIME_DOWNLOAD_INVALID")
            _check_cancelled(is_cancelled)
            install_whisper_runtime_archive(
                archive,
                runtime_root,
                version=manifest.version,
                expected_sha256=manifest.sha256,
                replace_corrupt=repairing,
            )
            _check_cancelled(is_cancelled)
        state = inspect_whisper_runtime(runtime_root, verify_worker=True)
        if _runtime_ready(state, "whisper"):
            return {
                "status": "ready",
                "version": state.get("version"),
                "accepted": True,
                "channel": "stable",
            }
    except ProfilePreparationError:
        raise
    except (NetworkError, RuntimeError, OSError) as exc:
        stable_error = exc

    try:
        _check_cancelled(is_cancelled)
        result = _finish_resumable_download(
            lambda remaining: install_published_runtime_rc(
                "whisper",
                runtime_root=runtime_root,
                cache_root=cache_root,
                timeout=min(300.0, remaining),
            ),
            is_cancelled=is_cancelled,
        )
        if not isinstance(result, dict):
            raise ProfilePreparationError("WHISPER_RUNTIME_INSTALL_FAILED")
        _check_cancelled(is_cancelled)
    except Exception as exc:
        if stable_error is not None:
            raise ProfilePreparationError(_error_code(exc)) from exc
        raise ProfilePreparationError(_error_code(exc)) from exc
    state = inspect_whisper_runtime(runtime_root, verify_worker=True)
    if not _runtime_ready(state, "whisper"):
        raise ProfilePreparationError("WHISPER_RUNTIME_INSTALL_VERIFY_FAILED")
    return {"status": "ready", "accepted": True, **result}


def _install_qwen_runtime(
    runtime_root: Path,
    cache_root: Path,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    _check_cancelled(is_cancelled)
    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    if _runtime_ready(state, "qwen"):
        try:
            _probe_qwen_runtime(runtime_root, is_cancelled)
            return {
                "status": "ready",
                "version": state.get("version"),
                "accepted": False,
                "reused": True,
            }
        except QwenDesktopPrepareError as exc:
            # Hardware/driver failures are not repaired by downloading the same
            # runtime again. Only runtime-capability probe failures enter update.
            if exc.code not in _QWEN_RUNTIME_REPAIRABLE_PROBE_ERRORS:
                raise ProfilePreparationError(exc.code) from exc

    stable_error: BaseException | None = None
    try:
        _check_cancelled(is_cancelled)
        manifest = fetch_qwen_runtime_manifest()
        current = state.get("version") if state.get("status") == "ready" else None
        current_value = current if isinstance(current, str) else None
        if (
            qwen_runtime_version_compatible(manifest.version)
            and qwen_runtime_update_available(current_value, manifest)
        ):
            target = runtime_root / "qwen" / manifest.version
            repairing = target.exists() or target.is_symlink()
            archive = _finish_resumable_download(
                lambda remaining: download_qwen_runtime(
                    manifest,
                    cache_root,
                    timeout=min(300.0, remaining),
                ),
                is_cancelled=is_cancelled,
            )
            if not isinstance(archive, Path):
                raise ProfilePreparationError("QWEN_RUNTIME_DOWNLOAD_INVALID")
            _check_cancelled(is_cancelled)
            install_qwen_runtime_archive(
                archive,
                runtime_root,
                version=manifest.version,
                expected_sha256=manifest.bundle.archive_sha256,
                replace_corrupt=repairing,
            )
            _check_cancelled(is_cancelled)
        state = inspect_qwen_runtime(runtime_root, verify_worker=True)
        if _runtime_ready(state, "qwen"):
            try:
                _probe_qwen_runtime(runtime_root, is_cancelled)
                return {
                    "status": "ready",
                    "version": state.get("version"),
                    "accepted": True,
                    "channel": "stable",
                }
            except QwenDesktopPrepareError as exc:
                if exc.code not in _QWEN_RUNTIME_REPAIRABLE_PROBE_ERRORS:
                    raise ProfilePreparationError(exc.code) from exc
    except ProfilePreparationError:
        # Hardware/GPU failures discovered after a freshly installed Stable
        # runtime are authoritative. Falling back to another runtime build would
        # hide the real machine error and waste a multi-gigabyte download.
        raise
    except (NetworkError, RuntimeError, OSError) as exc:
        stable_error = exc

    try:
        _check_cancelled(is_cancelled)
        result = _finish_resumable_download(
            lambda remaining: install_published_runtime_rc(
                "qwen",
                runtime_root=runtime_root,
                cache_root=cache_root,
                timeout=min(300.0, remaining),
            ),
            is_cancelled=is_cancelled,
        )
        if not isinstance(result, dict):
            raise ProfilePreparationError("QWEN_RUNTIME_INSTALL_FAILED")
        _check_cancelled(is_cancelled)
        _probe_qwen_runtime(runtime_root, is_cancelled)
    except Exception as exc:
        if stable_error is not None:
            raise ProfilePreparationError(_error_code(exc)) from exc
        raise ProfilePreparationError(_error_code(exc)) from exc
    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    if not _runtime_ready(state, "qwen"):
        raise ProfilePreparationError("QWEN_RUNTIME_INSTALL_VERIFY_FAILED")
    return {"status": "ready", "accepted": True, **result}


class ProfilePreparationManager:
    """One-at-a-time first-use preparation owned by the Agent.

    The browser starts this operation after Craig ingest. The long runtime/model/
    GPU work happens on a background thread and is observed through a tiny,
    sanitized status DTO. Audio, paths and transcript text never cross the API.
    """

    def __init__(
        self,
        *,
        data_root: Path,
        models_root: Path,
        runtime_root: Path,
        state_root: Path,
        cache_root: Path,
        system_log: SystemLog | None = None,
    ):
        self.data_root = data_root.resolve()
        self.models_root = models_root.resolve()
        self.runtime_root = runtime_root.resolve()
        self.state_root = state_root.resolve()
        self.cache_root = cache_root.resolve()
        self.system_log = system_log
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._started_at: float | None = None
        self._state: dict[str, object] = {
            "schema": "tda_profile_preparation_v1",
            "state": "idle",
            "active": False,
            "operation_id": None,
            "source_id": None,
            "profile_id": None,
            "engine": None,
            "stage": "idle",
            "title": "Nenhuma preparação em andamento.",
            "detail": "",
            "sequence": 0,
            "error_code": None,
        }

    def _log(self, level: str, code: str, message: str, context: dict[str, object]) -> None:
        if self.system_log is not None:
            self.system_log.write(level, "preparation", code, message, context)

    def _snapshot_locked(self) -> dict[str, object]:
        value = dict(self._state)
        if self._state.get("active") is True and self._started_at is not None:
            value["elapsed_seconds"] = round(
                max(0.0, time.monotonic() - self._started_at),
                1,
            )
        else:
            value["elapsed_seconds"] = float(
                self._state.get("elapsed_seconds") or 0.0
            )
        return value

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_locked()

    def request_cancel(
        self,
        expected_operation_id: str | None = None,
    ) -> dict[str, object] | bool:
        """Cancel only the operation the caller actually observed.

        Internal shutdown callers may omit the fence and retain the historical
        boolean contract. Browser/API callers must provide an operation id and
        receive the authoritative snapshot for that exact operation.
        """
        with self._lock:
            active = self._state.get("active") is True
            current_operation_id = self._state.get("operation_id")
            if expected_operation_id is None:
                if active:
                    self._cancel.set()
                return active
            if (
                not isinstance(expected_operation_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", expected_operation_id) is None
            ):
                raise ProfilePreparationError(
                    "TRANSCRIPTION_PREPARATION_OPERATION_INVALID"
                )
            if current_operation_id != expected_operation_id:
                raise ProfilePreparationError(
                    "TRANSCRIPTION_PREPARATION_STALE_OPERATION"
                )
            # Repeating cancel for the same operation is idempotent, including
            # after it has already reached a terminal state.
            if active:
                self._cancel.set()
            return self._snapshot_locked()

    def wait(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _deadline_expired(self) -> bool:
        started = self._started_at
        return (
            started is not None
            and time.monotonic() - started >= _PREPARATION_MAX_SECONDS
        )

    def _should_stop(self) -> bool:
        return self._cancel.is_set() or self._deadline_expired()

    def _ensure_not_cancelled(self) -> None:
        if self._deadline_expired():
            raise ProfilePreparationError("TRANSCRIPTION_PREPARATION_TIMEOUT")
        _check_cancelled(self._cancel.is_set)

    def _set(
        self,
        stage: str,
        title: str,
        detail: str,
        *,
        state: str = "running",
        context: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            changed = (
                stage != self._state.get("stage")
                or state != self._state.get("state")
            )
            if changed:
                self._state["sequence"] = int(self._state.get("sequence") or 0) + 1
            terminal_elapsed = (
                round(max(0.0, time.monotonic() - self._started_at), 1)
                if state != "running" and self._started_at is not None
                else None
            )
            self._state.update(
                {
                    "state": state,
                    "active": state == "running",
                    "stage": stage,
                    "title": title,
                    "detail": detail,
                }
            )
            if terminal_elapsed is not None:
                self._state["elapsed_seconds"] = terminal_elapsed
            profile_id = str(self._state.get("profile_id") or "")
            operation_id = str(self._state.get("operation_id") or "")
            sequence = int(self._state.get("sequence") or 0)
        if changed:
            payload: dict[str, object] = {
                "stage": stage,
                "profile_id": profile_id,
                "operation_id": operation_id,
                "sequence": sequence,
            }
            if context:
                payload.update(context)
            self._log(
                "error" if state == "failed" else "info",
                "PREPARATION_" + re.sub(r"[^A-Z0-9]", "_", stage.upper())[:72],
                f"{title} {detail}".strip(),
                payload,
            )

    def _qwen_progress(self, stage: str, context: dict[str, object]) -> None:
        mapping = {
            "runtime_probe": (
                "qwen_probe",
                "Verificando CUDA e runtime…",
                "Confirmando que o worker Qwen e a GPU suportam o gate físico.",
            ),
            "runtime_probe_ready": (
                "qwen_audio",
                "Runtime e GPU reconhecidos.",
                "Selecionando uma faixa adequada para a validação local.",
            ),
            "selecting_audio": (
                "qwen_audio",
                "Selecionando amostra de áudio…",
                "Procurando uma janela local com fala suficiente; nenhum áudio é enviado.",
            ),
            "physical_gate": (
                "qwen_gate",
                "Executando gate físico do Qwen…",
                "Preparando modelos, transcrevendo a amostra e validando o alinhamento na GPU.",
            ),
            "physical_gate_ready": (
                "verify",
                "Gate físico aprovado.",
                "Confirmando que o perfil ficou executável.",
            ),
        }
        value = mapping.get(stage)
        if value is not None:
            self._set(*value, context=context)

    def start(self, source_id: str, profile_id: str) -> dict[str, object]:
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise ProfilePreparationError("CRAIG_SOURCE_INVALID")
        if profile_id not in _PROFILE_IDS:
            raise ProfilePreparationError("TRANSCRIPTION_PROFILE_INVALID")
        with self._lock:
            thread_alive = self._thread is not None and self._thread.is_alive()
            if self._state.get("active") is True or thread_alive:
                if (
                    self._state.get("active") is True
                    and self._state.get("source_id") == source_id
                    and self._state.get("profile_id") == profile_id
                ):
                    return self._snapshot_locked()
                # Terminal state is published just before _run() unwinds. Fence
                # that tiny interval with the physical thread state so a second
                # preparation cannot overlap model/runtime cleanup.
                raise ProfilePreparationError("TRANSCRIPTION_PREPARATION_ALREADY_RUNNING")

            operation_id = uuid4().hex
            profile = get_profile(profile_id)
            self._cancel.clear()
            self._started_at = time.monotonic()
            self._state = {
                "schema": "tda_profile_preparation_v1",
                "state": "running",
                "active": True,
                "operation_id": operation_id,
                "source_id": source_id,
                "profile_id": profile_id,
                "engine": profile.engine,
                "stage": "starting",
                "title": "Iniciando preparação…",
                "detail": "Conferindo runtime, modelo e capacidade local.",
                "sequence": 1,
                "error_code": None,
            }
            initial = self._snapshot_locked()
            self._thread = threading.Thread(
                target=self._run,
                args=(operation_id, source_id, profile_id),
                name="tda-profile-preparation",
                daemon=True,
            )
            self._thread.start()

        self._log(
            "info",
            "PREPARATION_STARTED",
            "Preparação de transcrição iniciada.",
            {
                "profile_id": profile_id,
                "engine": profile.engine,
                "operation_id": operation_id,
            },
        )
        return initial

    def _run(self, operation_id: str, source_id: str, profile_id: str) -> None:
        profile = get_profile(profile_id)
        try:
            self._ensure_not_cancelled()
            self._set(
                "validating_source",
                "Validando fonte Craig…",
                "Conferindo o pacote local antes de preparar runtime e modelo.",
            )
            package_root = self.data_root / "staging" / source_id
            try:
                load_craig_package(package_root, verify_tracks=False)
            except CraigPackageError as exc:
                raise ProfilePreparationError(str(exc)) from exc
            self._ensure_not_cancelled()
            catalog = profile_catalog(self.state_root, self.runtime_root, self.models_root)
            current = next(item for item in catalog if item["id"] == profile_id)
            if current.get("ready") is True:
                self._set(
                    "complete",
                    "Perfil pronto.",
                    "Nenhuma preparação adicional foi necessária.",
                    state="completed",
                )
                return

            self._ensure_not_cancelled()
            self._set(
                "runtime",
                "Preparando runtime de transcrição…",
                "Baixando, verificando ou reutilizando o runtime compatível.",
            )
            if profile.engine == "whisper":
                runtime = _install_whisper_runtime(
                    self.runtime_root,
                    self.cache_root,
                    is_cancelled=self._should_stop,
                )
                self._set(
                    "whisper_model",
                    "Preparando modelo Whisper…",
                    "Baixando e verificando o modelo selecionado quando necessário.",
                    context={"runtime_version": str(runtime.get("version") or "")},
                )
                try:
                    prepare_whisper_profile(
                        models_root=self.models_root,
                        runtime_root=self.runtime_root,
                        profile_id=profile_id,
                        is_cancelled=self._should_stop,
                    )
                except WhisperDesktopPrepareError as exc:
                    raise ProfilePreparationError(exc.code) from exc
            else:
                runtime = _install_qwen_runtime(
                    self.runtime_root,
                    self.cache_root,
                    is_cancelled=self._should_stop,
                )
                self._set(
                    "qwen_probe",
                    "Runtime Qwen pronto.",
                    "Iniciando validação de CUDA, modelo e amostra real na GPU.",
                    context={"runtime_version": str(runtime.get("version") or "")},
                )
                try:
                    prepare_qwen_profile_from_craig(
                        data_root=self.data_root,
                        cache_root=self.cache_root,
                        models_root=self.models_root,
                        runtime_root=self.runtime_root,
                        state_root=self.state_root,
                        source_id=source_id,
                        profile_id=profile_id,
                        progress=self._qwen_progress,
                        is_cancelled=self._should_stop,
                    )
                except QwenDesktopPrepareError as exc:
                    raise ProfilePreparationError(exc.code) from exc

            self._ensure_not_cancelled()
            refreshed = profile_catalog(self.state_root, self.runtime_root, self.models_root)
            ready = next(item for item in refreshed if item["id"] == profile_id)
            if ready.get("ready") is not True:
                raise ProfilePreparationError(
                    "QWEN_PHYSICAL_ACCEPTANCE_NOT_VISIBLE"
                    if profile.engine == "qwen3"
                    else "WHISPER_MODEL_PREPARATION_NOT_VISIBLE"
                )
            self._set(
                "complete",
                "Preparação concluída.",
                "Runtime, modelo e validações locais estão prontos.",
                state="completed",
            )
        except Exception as exc:
            code = _error_code(exc)
            if (
                code == "TRANSCRIPTION_PREPARATION_CANCELLED"
                and self._deadline_expired()
                and not self._cancel.is_set()
            ):
                code = "TRANSCRIPTION_PREPARATION_TIMEOUT"
            with self._lock:
                self._state["error_code"] = code
            self._set(
                "failed",
                "A preparação encontrou um problema.",
                f"Código: {code}",
                state="failed",
                context={"error_code": code},
            )
        finally:
            with self._lock:
                if self._state.get("operation_id") != operation_id:
                    return
                self._state["active"] = False
