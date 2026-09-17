from __future__ import annotations

import json
import shutil
import tempfile
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
from .settings import SettingsStore
from .system_log import SystemLog
from .telemetry import SystemTelemetry

_NETWORK_MESSAGES = {
    "OFFLINE": "Este computador parece estar sem acesso à Internet.",
    "DNS_FAILED": "Não foi possível resolver o endereço do TDA.",
    "PROXY_FAILED": "O proxy configurado não conseguiu acessar o TDA.",
    "CONNECT_TIMEOUT": "A conexão com o TDA demorou demais e expirou.",
    "TLS_FAILED": "Não foi possível validar a conexão segura com o TDA.",
    "HTTP_ERROR": "O servidor do TDA respondeu com erro.",
    "MANIFEST_INVALID": "O canal de atualização respondeu com dados inválidos.",
    "HASH_MISMATCH": "O arquivo baixado falhou na verificação de integridade.",
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

    @staticmethod
    def _friendly_network_error(exc: NetworkError) -> RuntimeError:
        if exc.code.startswith("BITS_"):
            message = (
                "O serviço de download em segundo plano do Windows encontrou um problema. "
                "Tente novamente."
            )
        elif exc.code.endswith("_SIZE_EXCEEDED") or exc.code.endswith("_SIZE_MISMATCH"):
            message = "O arquivo baixado não corresponde ao tamanho publicado e foi descartado."
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

    def _wait_maintenance_handoff(self, operation_id: str, timeout: float = 3.0) -> None:
        path = (
            self.paths.cache_root
            / "maintenance"
            / "operations"
            / f"{operation_id}.json"
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self._read_maintenance_summary(
                path,
                expected_operation_id=operation_id,
            )
            if value is not None:
                if value.get("status") == "failed":
                    raise RuntimeError("MAINTENANCE_HANDOFF_FAILED")
                return
            time.sleep(0.05)
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
            # Agent availability must not determine whether the local UI can
            # render. Telemetry is best-effort and independently degradable.
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
            # Logs already live in the local per-user filesystem. They are most
            # useful precisely when the Agent is unavailable or its loopback
            # owner fails verification, so the trusted Desktop reads the same
            # sanitized log files directly instead of blanking the diagnostics UI.
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

    def install_whisper_runtime(self) -> dict[str, object]:
        try:
            return super().install_whisper_runtime()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def check_qwen_runtime(self) -> dict[str, object]:
        try:
            return super().check_qwen_runtime()
        except NetworkError as exc:
            raise self._friendly_network_error(exc) from None

    def install_qwen_runtime(self) -> dict[str, object]:
        try:
            return super().install_qwen_runtime()
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
        try:
            launched = super()._launch_maintenance(
                [
                    *arguments,
                    "--cleanup-self",
                    "--operation-id",
                    operation_id,
                ]
            )
        except BaseException:
            shutil.rmtree(
                Path(tempfile.gettempdir()) / "TDACompanionMaintenance" / operation_id,
                ignore_errors=True,
            )
            raise
        if not launched:
            raise RuntimeError("MAINTENANCE_LAUNCH_FAILED")
        self._wait_maintenance_handoff(operation_id)
        return True

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
        if profile.engine == "whisper":
            runtime = self.install_whisper_runtime()
            refreshed = self.transcription_profiles()
            ready = next((item for item in refreshed["profiles"] if item["id"] == profile_id), None)
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise RuntimeError("WHISPER_RUNTIME_UNAVAILABLE")
            return {
                "ready": True,
                "profile_id": profile_id,
                "prepared": bool(runtime.get("accepted")),
                "runtime_version": runtime.get("version"),
                "model_prepare_on_job": True,
            }

        runtime = self.install_qwen_runtime()
        try:
            result = prepare_qwen_profile_from_craig(
                data_root=self.paths.data_root,
                cache_root=self.paths.cache_root,
                models_root=self.paths.models_root,
                runtime_root=self.paths.runtime_root,
                state_root=self.paths.state_root,
                source_id=source_id,
                profile_id=profile_id,
            )
        except QwenDesktopPrepareError as exc:
            raise RuntimeError(exc.code) from None

        refreshed = self.transcription_profiles()
        ready = next((item for item in refreshed["profiles"] if item["id"] == profile_id), None)
        if not isinstance(ready, dict) or ready.get("ready") is not True:
            raise RuntimeError("QWEN_PHYSICAL_ACCEPTANCE_NOT_VISIBLE")
        return {
            **result,
            "prepared": True,
            "runtime_version": runtime.get("version"),
        }
