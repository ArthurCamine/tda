from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from . import VERSION
from .agent_connection import AgentConnection, AgentConnectionError
from .asr_models import get_profile
from .asr_runtime import inspect_whisper_runtime
from .desktop import DesktopBridge, _CRAIG_SOURCE_ID, _PROFILE_ORDER
from .network import NetworkError
from .paths import CompanionPaths
from .qwen_desktop_prepare import QwenDesktopPrepareError, prepare_qwen_profile_from_craig
from .qwen_runtime import inspect_qwen_runtime
from .runtime_rc_updates import install_published_runtime_rc
from .settings import SettingsStore
from .system_log import SystemLog
from .telemetry import SystemTelemetry

_QWEN_ALIGNER_DIRECTORY = "qwen3-forced-aligner-0.6b-hf"
_PREPARATION_COMPONENT = "preparation"

_NETWORK_MESSAGES = {
    "OFFLINE": "Este computador parece estar sem acesso à Internet.",
    "DNS_FAILED": "Não foi possível resolver o endereço do TDA.",
    "PROXY_FAILED": "O proxy configurado não conseguiu acessar o TDA.",
    "CONNECT_TIMEOUT": "A conexão com o TDA demorou demais e expirou.",
    "TLS_FAILED": "Não foi possível validar a conexão segura com o TDA.",
    "HTTP_ERROR": "O servidor do TDA respondeu com erro.",
    "MANIFEST_INVALID": "O canal de atualização respondeu com dados inválidos.",
    "HASH_MISMATCH": "O arquivo baixado falhou na verificação de integridade.",
    "RUNTIME_COMPATIBLE_RELEASE_UNAVAILABLE": (
        "Não há um runtime de transcrição compatível publicado para esta versão do Companion."
    ),
    "RUNTIME_RC_RELEASE_NOT_PUBLISHED": (
        "O runtime compatível desta versão de teste ainda não terminou de ser publicado. "
        "Tente novamente quando a publicação concluir."
    ),
    "RUNTIME_RC_RELEASE_INCOMPLETE": (
        "O pacote de runtime publicado está incompleto e foi rejeitado pelo Companion."
    ),
    "DOWNLOAD_CONTINUES_IN_BACKGROUND": (
        "O download continua em segundo plano pelo Windows. Aguarde alguns instantes e tente "
        "novamente; o Companion retomará o mesmo download."
    ),
    "DOWNLOAD_OUTPUT_MISSING": (
        "O Windows concluiu o transporte sem disponibilizar o arquivo esperado. Tente novamente."
    ),
}


class SessionDesktopBridge(DesktopBridge):
    """Desktop product workflow layered over the generic maintenance bridge.

    The installed product uses one verified AgentConnection for every loopback
    operation. Local-only UI state can still render while the Agent reconnects.
    """

    def __init__(
        self,
        *,
        token: str,
        port: int,
        paths: CompanionPaths,
        settings: SettingsStore,
        executable: Path,
        start_agent: Callable[[], object],
    ):
        super().__init__(
            token=token,
            port=port,
            paths=paths,
            settings=settings,
            executable=executable,
            start_agent=start_agent,
        )
        self.client = AgentConnection(
            token,
            port,
            start_agent,
            expected_version=VERSION,
        )
        self._last_maintenance_operation_id: str | None = None
        self._maintenance_handoff_process: subprocess.Popen | None = None
        self._preparation_lock = threading.Lock()
        self._preparation_log = SystemLog(self.paths.logs_root)
        self._preparation_started_at: float | None = None
        self._preparation_stage_started_at: float | None = None
        self._preparation_state: dict[str, object] = {
            "active": False,
            "state": "idle",
            "operation_id": None,
            "profile_id": None,
            "engine": None,
            "stage": "idle",
            "title": "Nenhuma preparação em andamento.",
            "detail": "",
            "sequence": 0,
            "current_bytes": None,
            "error_code": None,
        }

    @staticmethod
    def _safe_tree_bytes(root: Path, *, max_entries: int = 50_000) -> int | None:
        if not root.exists():
            return 0
        total = 0
        entries = 0
        try:
            for path in root.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                entries += 1
                if entries > max_entries:
                    return None
                total += path.stat().st_size
        except OSError:
            return None
        return total

    @staticmethod
    def _preparation_error_code(exc: BaseException) -> str:
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            return code[:96]
        value = str(exc).strip()
        if value.endswith("]") and "[" in value:
            candidate = value.rsplit("[", 1)[-1][:-1].strip()
            if candidate:
                return candidate[:96]
        return (value or type(exc).__name__)[:96]

    def _preparation_public(self) -> dict[str, object]:
        with self._preparation_lock:
            value = dict(self._preparation_state)
            now = time.monotonic()
            value["elapsed_seconds"] = (
                round(max(0.0, now - self._preparation_started_at), 1)
                if self._preparation_started_at is not None
                else 0.0
            )
            value["stage_elapsed_seconds"] = (
                round(max(0.0, now - self._preparation_stage_started_at), 1)
                if self._preparation_stage_started_at is not None
                else 0.0
            )
            return value

    def _set_preparation_stage(
        self,
        stage: str,
        title: str,
        detail: str,
        *,
        state: str = "running",
        current_bytes: int | None = None,
        context: dict[str, object] | None = None,
        force_log: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._preparation_lock:
            previous_stage = str(self._preparation_state.get("stage") or "")
            previous_state = str(self._preparation_state.get("state") or "")
            changed = stage != previous_stage or state != previous_state
            if changed:
                self._preparation_stage_started_at = now
                self._preparation_state["sequence"] = int(
                    self._preparation_state.get("sequence") or 0
                ) + 1
            self._preparation_state.update(
                {
                    "active": state == "running",
                    "state": state,
                    "stage": stage,
                    "title": title,
                    "detail": detail,
                    "current_bytes": current_bytes,
                }
            )
            profile_id = self._preparation_state.get("profile_id")
            engine = self._preparation_state.get("engine")
            operation_id = self._preparation_state.get("operation_id")
            sequence = self._preparation_state.get("sequence")

        if changed or force_log:
            level = "error" if state == "failed" else "info"
            code = "PREPARATION_" + "".join(
                char if char.isalnum() else "_" for char in stage.upper()
            )[:72]
            payload: dict[str, object] = {
                "stage": stage,
                "profile_id": profile_id,
                "engine": engine,
                "operation_id": operation_id,
                "sequence": sequence,
            }
            if current_bytes is not None:
                payload["downloaded_bytes"] = current_bytes
            if context:
                payload.update(context)
            self._preparation_log.write(
                level,
                _PREPARATION_COMPONENT,
                code,
                f"{title} {detail}".strip(),
                payload,
            )

    def _begin_preparation(self, profile_id: str, engine: str) -> None:
        now = time.monotonic()
        with self._preparation_lock:
            self._preparation_started_at = now
            self._preparation_stage_started_at = now
            self._preparation_state = {
                "active": True,
                "state": "running",
                "operation_id": uuid4().hex,
                "profile_id": profile_id,
                "engine": engine,
                "stage": "starting",
                "title": "Iniciando preparação…",
                "detail": "Conferindo o estado local antes de baixar ou executar qualquer modelo.",
                "sequence": 1,
                "current_bytes": None,
                "error_code": None,
            }
        self._preparation_log.write(
            "info",
            _PREPARATION_COMPONENT,
            "PREPARATION_STARTED",
            "Preparação de transcrição iniciada.",
            {"profile_id": profile_id, "engine": engine},
        )

    def _finish_preparation(self, *, error_code: str | None = None) -> None:
        if error_code:
            with self._preparation_lock:
                self._preparation_state["error_code"] = error_code
                self._preparation_state["failure_stage"] = self._preparation_state.get("stage")
            self._set_preparation_stage(
                "failed",
                "A preparação encontrou um problema.",
                f"Código: {error_code}",
                state="failed",
                context={
                    "error_code": error_code,
                    "failure_stage": self._preparation_state.get("failure_stage"),
                },
                force_log=True,
            )
            return
        self._set_preparation_stage(
            "complete",
            "Preparação concluída.",
            "Runtime, modelos e validações necessárias estão prontos.",
            state="completed",
            force_log=True,
        )

    def _runtime_download_bytes(self, family: str) -> int | None:
        root = self.paths.cache_root.resolve() / "runtime-rc" / family
        return self._safe_tree_bytes(root)

    def _qwen_download_state(self, profile_id: str) -> tuple[str, str, str, int | None]:
        profile = get_profile(profile_id)
        downloads = self.paths.models_root.resolve() / ".downloads"
        profile_partial = next(
            iter(sorted(downloads.glob(f"{profile.directory}-*.partial"))),
            None,
        ) if downloads.is_dir() else None
        aligner_partial = next(
            iter(sorted(downloads.glob(f"{_QWEN_ALIGNER_DIRECTORY}-*.partial"))),
            None,
        ) if downloads.is_dir() else None

        if profile_partial is not None:
            size = self._safe_tree_bytes(profile_partial)
            return (
                "qwen_model_download",
                "Baixando modelo Qwen…",
                "Recebendo o modelo de reconhecimento e validando os arquivos locais.",
                size,
            )

        model_root = self.paths.models_root.resolve() / profile.directory
        if not model_root.is_dir():
            return (
                "qwen_model_download",
                "Preparando modelo Qwen…",
                "Aguardando o download verificado do modelo de reconhecimento.",
                None,
            )

        if aligner_partial is not None:
            size = self._safe_tree_bytes(aligner_partial)
            return (
                "qwen_aligner_download",
                "Baixando alinhador por palavra…",
                "A transcrição de teste avançou; agora o modelo de alinhamento está sendo preparado.",
                size,
            )

        aligner_root = self.paths.models_root.resolve() / _QWEN_ALIGNER_DIRECTORY
        gate = (
            self.paths.state_root.resolve()
            / "qwen-physical-gates"
            / f"{profile_id}.json"
        )
        if not aligner_root.is_dir():
            return (
                "qwen_gpu_transcription",
                "Testando o Qwen na GPU…",
                "Carregando o modelo e transcrevendo uma janela local real de 180 s.",
                None,
            )
        if not gate.is_file():
            return (
                "qwen_gpu_gate",
                "Validando transcrição e alinhamento…",
                "Executando a amostra real de 180 s na GPU e conferindo o alinhamento por palavra.",
                None,
            )
        return (
            "verify",
            "Gate físico concluído.",
            "Confirmando que o Agent já reconhece este perfil como pronto.",
            None,
        )

    def preparation_status(self) -> dict[str, object]:
        current = self._preparation_public()
        if current.get("active") is not True:
            return current

        engine = current.get("engine")
        stage = str(current.get("stage") or "")
        if stage == "runtime":
            family = "qwen" if engine == "qwen3" else "whisper"
            downloaded = self._runtime_download_bytes(family)
            if downloaded:
                self._set_preparation_stage(
                    "runtime",
                    str(current.get("title") or "Preparando runtime…"),
                    str(current.get("detail") or ""),
                    current_bytes=downloaded,
                )
        elif engine == "qwen3" and stage.startswith("qwen"):
            inferred, title, detail, downloaded = self._qwen_download_state(
                str(current.get("profile_id") or "")
            )
            self._set_preparation_stage(
                inferred,
                title,
                detail,
                current_bytes=downloaded,
            )
        return self._preparation_public()

    def _qwen_prepare_progress(self, stage: str, context: dict[str, object]) -> None:
        if stage == "runtime_probe":
            self._set_preparation_stage(
                "qwen_probe",
                "Verificando CUDA e runtime…",
                "Confirmando que o worker Qwen e a GPU suportam o gate físico.",
                context=context,
            )
        elif stage == "runtime_probe_ready":
            self._set_preparation_stage(
                "qwen_audio",
                "Runtime e GPU reconhecidos.",
                "Selecionando uma faixa adequada para a validação local de 180 s.",
                context=context,
            )
        elif stage == "selecting_audio":
            self._set_preparation_stage(
                "qwen_audio",
                "Selecionando amostra de áudio…",
                "Procurando uma janela local de 180 s com fala suficiente; nenhum áudio é enviado.",
                context=context,
            )
        elif stage == "physical_gate":
            self._set_preparation_stage(
                "qwen_gate",
                "Executando gate físico do Qwen…",
                "Preparando modelos, transcrevendo 180 s e validando o alinhamento na GPU.",
                context=context,
            )
        elif stage == "physical_gate_ready":
            self._set_preparation_stage(
                "verify",
                "Gate físico aprovado.",
                "Confirmando a capacidade do Agent antes de criar o job.",
                context=context,
            )

    @staticmethod
    def _friendly_network_error(exc: NetworkError) -> RuntimeError:
        if exc.code.startswith("BITS_"):
            message = (
                "O serviço de download em segundo plano do Windows encontrou um problema. "
                "Tente novamente."
            )
        elif exc.code.endswith("_SIZE_EXCEEDED") or exc.code.endswith("_SIZE_MISMATCH"):
            message = "O arquivo baixado não corresponde ao tamanho publicado e foi descartado."
        elif exc.code.startswith("RUNTIME_RC_"):
            message = _NETWORK_MESSAGES.get(
                exc.code,
                "O pacote de transcrição desta versão falhou na validação e não foi instalado.",
            )
        else:
            message = _NETWORK_MESSAGES.get(
                exc.code,
                "Não foi possível acessar o serviço online do TDA.",
            )
        return RuntimeError(f"{message} [{exc.code}]")

    @staticmethod
    def _read_maintenance_summary(
        path: Path,
        *,
        expected_operation_id: str | None = None,
    ) -> dict[str, object] | None:
        try:
            if not path.is_file() or path.stat().st_size > 64 * 1024:
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        operation_id = value.get("operation_id")
        status = value.get("status")
        stage = value.get("stage")
        action = value.get("action")
        if (
            not isinstance(operation_id, str)
            or len(operation_id) != 32
            or (expected_operation_id is not None and operation_id != expected_operation_id)
            or status not in {"running", "completed", "failed"}
            or not isinstance(stage, str)
            or action not in {"update", "uninstall"}
        ):
            return None
        allowed = (
            "operation_id",
            "action",
            "status",
            "stage",
            "failure_stage",
            "error_code",
            "msi_exit_code",
            "target_version",
            "purge",
            "updated_at",
        )
        return {key: value.get(key) for key in allowed if key in value}

    def _maintenance_snapshot(self) -> dict[str, object] | None:
        return self._read_maintenance_summary(
            self.paths.cache_root / "maintenance" / "last-operation.json"
        )

    def _wait_maintenance_handoff(self, operation_id: str, timeout: float = 15.0) -> None:
        """Wait until the helper durably owns the operation journal.

        The old three-second blind timeout could report a failed handoff while
        Windows Defender was still cold-starting the one-file maintenance helper.
        Track the child process as well: an early exit is immediately actionable,
        while a live helper gets enough time to create its journal.
        """
        path = (
            self.paths.cache_root
            / "maintenance"
            / "operations"
            / f"{operation_id}.json"
        )
        deadline = time.monotonic() + timeout
        delay = 0.05
        while time.monotonic() < deadline:
            value = self._read_maintenance_summary(
                path,
                expected_operation_id=operation_id,
            )
            if value is not None:
                if value.get("status") == "failed":
                    code = value.get("error_code")
                    suffix = f":{code}" if isinstance(code, str) and code else ""
                    raise RuntimeError(f"MAINTENANCE_HANDOFF_FAILED{suffix}")
                return
            process = self._maintenance_handoff_process
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    raise RuntimeError(f"MAINTENANCE_EXITED_BEFORE_HANDOFF:{returncode}")
            time.sleep(delay)
            delay = min(0.25, delay * 1.5)
        raise RuntimeError("MAINTENANCE_HANDOFF_TIMEOUT")

    def _offline_snapshot(self, code: str) -> dict[str, object]:
        connection = self.client.status()
        try:
            usage = shutil.disk_usage(self.paths.data_root)
            storage = {"free_bytes": usage.free, "total_bytes": usage.total}
        except OSError:
            storage = {"free_bytes": None, "total_bytes": None}
        try:
            system = SystemTelemetry().snapshot()
        except Exception:
            system = {}
        whisper_runtime = inspect_whisper_runtime(self.paths.runtime_root, verify_worker=False)
        qwen_runtime = inspect_qwen_runtime(self.paths.runtime_root, verify_worker=False)
        return {
            "version": VERSION,
            "agent": {
                "product_id": "tda-companion",
                "api_version": "1",
                "service_version": connection.get("service_version") or VERSION,
                "port": self.port,
                "lifecycle": connection.get("state") or "unavailable",
                "error": code,
            },
            "connection": connection,
            "maintenance": self._maintenance_snapshot(),
            "system": system,
            "storage": storage,
            "counts": {"processing": 0, "queued": 0, "completed": 0, "attention": 0},
            "jobs": [],
            "settings": self.settings.snapshot(),
            "whisper_runtime": {
                "status": whisper_runtime.get("status"),
                "version": whisper_runtime.get("version"),
            },
            "qwen_runtime": {
                "status": qwen_runtime.get("status"),
                "version": qwen_runtime.get("version"),
            },
        }

    def snapshot(self) -> dict[str, object]:
        try:
            value = super().snapshot()
        except AgentConnectionError as exc:
            return self._offline_snapshot(exc.code)
        return {
            **value,
            "connection": self.client.status(),
            "maintenance": self._maintenance_snapshot(),
        }

    def logs(
        self,
        level: str | None = None,
        component: str | None = None,
        limit: int = 200,
    ) -> dict[str, object]:
        try:
            return super().logs(level=level, component=component, limit=limit)
        except AgentConnectionError as exc:
            rows = SystemLog(self.paths.logs_root).tail(
                level=level,
                component=component,
                limit=limit,
            )
            return {
                "logs": rows,
                "local_fallback": True,
                "error": exc.code,
                "connection": self.client.status(),
            }

    def transcription_profiles(self) -> dict[str, object]:
        try:
            return super().transcription_profiles()
        except AgentConnectionError as exc:
            return {
                "profiles": [],
                "recommended": None,
                "unavailable": True,
                "error": exc.code,
                "connection": self.client.status(),
            }

    def restart_agent(self) -> bool:
        return self.client.restart()

    def check_update(self) -> dict[str, object]:
        try:
            return super().check_update()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def download_update(self) -> dict[str, object]:
        try:
            return super().download_update()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def check_whisper_runtime(self) -> dict[str, object]:
        try:
            return super().check_whisper_runtime()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    @staticmethod
    def _runtime_rc_fallback_allowed() -> bool:
        # Stable runtime delivery is always attempted first. If no compatible
        # Stable runtime is available yet, a published runtime RC is still a
        # valid self-heal source: runtime_rc_updates verifies the immutable
        # prerelease identity, exact version, asset set, GitHub digests, sizes
        # and candidate manifest before installation. This keeps first-use
        # preparation automatic during a staggered Companion/runtime rollout
        # without weakening the Companion application's Stable update channel.
        return True

    def _install_runtime_rc_fallback(
        self,
        family: str,
        stable_result: dict[str, object],
    ) -> dict[str, object]:
        if stable_result.get("status") == "ready":
            return stable_result
        if not self._runtime_rc_fallback_allowed():
            raise NetworkError("RUNTIME_COMPATIBLE_RELEASE_UNAVAILABLE")
        result = install_published_runtime_rc(
            family,
            runtime_root=self.paths.runtime_root,
            cache_root=self.paths.cache_root,
        )
        return {
            "accepted": True,
            "available": True,
            **result,
        }

    def install_whisper_runtime(self) -> dict[str, object]:
        try:
            result = super().install_whisper_runtime()
            if result.get("accepted") is True or result.get("status") == "ready":
                return result
            return self._install_runtime_rc_fallback("whisper", result)
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def check_qwen_runtime(self) -> dict[str, object]:
        try:
            return super().check_qwen_runtime()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def install_qwen_runtime(self) -> dict[str, object]:
        try:
            result = super().install_qwen_runtime()
            if result.get("accepted") is True or result.get("status") == "ready":
                return result
            return self._install_runtime_rc_fallback("qwen", result)
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def _maintenance_helper(self) -> Path:
        operation_id = self._last_maintenance_operation_id
        if operation_id is None:
            raise RuntimeError("MAINTENANCE_OPERATION_ID_MISSING")
        source = self.executable.parent / "TDACompanionMaintenance.exe"
        if not source.is_file():
            raise RuntimeError("MAINTENANCE_HELPER_MISSING")
        parent = Path(tempfile.gettempdir()) / "TDACompanionMaintenance"
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / operation_id
        staging.mkdir(exist_ok=False)
        target = staging / "TDACompanionMaintenance.exe"
        shutil.copy2(source, target)
        return target

    def _launch_maintenance(self, arguments: list[str]) -> bool:
        operation_id = uuid4().hex
        self._last_maintenance_operation_id = operation_id
        helper: Path | None = None
        process: subprocess.Popen | None = None
        try:
            helper = self._maintenance_helper()
            process = subprocess.Popen(
                [
                    str(helper),
                    *arguments,
                    "--cleanup-self",
                    "--operation-id",
                    operation_id,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=self._maintenance_creationflags(),
            )
            self._maintenance_handoff_process = process
            self._wait_maintenance_handoff(operation_id)
            return True
        except BaseException:
            operation = (
                self.paths.cache_root
                / "maintenance"
                / "operations"
                / f"{operation_id}.json"
            )
            process_exited = process is None or process.poll() is not None
            if not operation.exists() and helper is not None and process_exited:
                try:
                    shutil.rmtree(helper.parent, ignore_errors=True)
                except OSError:
                    pass
            raise
        finally:
            self._maintenance_handoff_process = None

    def install_update(self) -> dict[str, object]:
        self._last_maintenance_operation_id = None
        try:
            result = super().install_update()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None
        operation_id = self._last_maintenance_operation_id
        if result.get("accepted") is True and operation_id is not None:
            return {**result, "operation_id": operation_id}
        return result

    def uninstall(self, purge: bool = False) -> dict[str, object]:
        self._last_maintenance_operation_id = None
        result = super().uninstall(purge)
        operation_id = self._last_maintenance_operation_id
        if result.get("accepted") is True and operation_id is not None:
            return {**result, "operation_id": operation_id}
        return result

    def _require_selected_source(self, source_id: str) -> None:
        if not isinstance(source_id, str) or not _CRAIG_SOURCE_ID.fullmatch(source_id):
            raise RuntimeError("CRAIG_SOURCE_INVALID")
        if source_id not in self._selected_sources:
            raise RuntimeError("CRAIG_SOURCE_NOT_SELECTED")

    def prepare_transcription_profile(self, source_id: str, profile_id: str) -> dict[str, object]:
        self._require_selected_source(source_id)
        if profile_id not in _PROFILE_ORDER:
            raise RuntimeError("TRANSCRIPTION_PROFILE_INVALID")
        if self._has_running_job():
            raise RuntimeError("TRANSCRIPTION_PREPARATION_BLOCKED_BY_RUNNING_JOB")

        current = self.transcription_profiles()
        selected = next((item for item in current["profiles"] if item["id"] == profile_id), None)
        if isinstance(selected, dict) and selected.get("ready") is True:
            return {"ready": True, "profile_id": profile_id, "prepared": False}

        profile = get_profile(profile_id)
        self._begin_preparation(profile_id, profile.engine)
        try:
            self._set_preparation_stage(
                "runtime",
                "Preparando runtime de transcrição…",
                (
                    "Baixando e verificando o runtime Whisper necessário."
                    if profile.engine == "whisper"
                    else "Baixando e verificando o runtime Qwen necessário."
                ),
            )

            if profile.engine == "whisper":
                runtime = self.install_whisper_runtime()
                self._set_preparation_stage(
                    "verify",
                    "Runtime Whisper pronto.",
                    "Confirmando que o Agent já anuncia o perfil selecionado.",
                    context={"runtime_version": runtime.get("version")},
                )
                refreshed = self.transcription_profiles()
                ready = next(
                    (item for item in refreshed["profiles"] if item["id"] == profile_id),
                    None,
                )
                if not isinstance(ready, dict) or ready.get("ready") is not True:
                    raise RuntimeError("WHISPER_RUNTIME_UNAVAILABLE")
                value = {
                    "ready": True,
                    "profile_id": profile_id,
                    "prepared": bool(runtime.get("accepted")),
                    "runtime_version": runtime.get("version"),
                    "model_prepare_on_job": True,
                }
                self._finish_preparation()
                return value

            runtime = self.install_qwen_runtime()
            self._set_preparation_stage(
                "qwen_probe",
                "Runtime Qwen pronto.",
                "Iniciando a validação de CUDA, modelo e amostra real na GPU.",
                context={"runtime_version": runtime.get("version")},
            )
            try:
                result = prepare_qwen_profile_from_craig(
                    data_root=self.paths.data_root,
                    cache_root=self.paths.cache_root,
                    models_root=self.paths.models_root,
                    runtime_root=self.paths.runtime_root,
                    state_root=self.paths.state_root,
                    source_id=source_id,
                    profile_id=profile_id,
                    progress=self._qwen_prepare_progress,
                )
            except QwenDesktopPrepareError as exc:
                raise RuntimeError(exc.code) from None

            self._set_preparation_stage(
                "verify",
                "Verificando perfil no Agent…",
                "O gate terminou; falta apenas confirmar que o perfil ficou executável.",
                context={
                    "runtime_version": runtime.get("version"),
                    "gpu_name": result.get("gpu_name"),
                },
            )
            refreshed = self.transcription_profiles()
            ready = next(
                (item for item in refreshed["profiles"] if item["id"] == profile_id),
                None,
            )
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise RuntimeError("QWEN_PHYSICAL_ACCEPTANCE_NOT_VISIBLE")
            value = {
                **result,
                "prepared": True,
                "runtime_version": runtime.get("version"),
            }
            self._finish_preparation()
            return value
        except Exception as exc:
            self._finish_preparation(error_code=self._preparation_error_code(exc))
            raise
