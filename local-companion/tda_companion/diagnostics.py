from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import VERSION
from .agent import wait_until_ready
from .asr_models import get_profile, inspect_model_install
from .asr_runtime import inspect_whisper_runtime
from .diagnostic_capabilities import build_capabilities, capability_rows, overall_status
from .network import NetworkClient, NetworkError
from .paths import CompanionPaths
from .qwen_acceptance import ALIGNER_PROFILE
from .qwen_physical_gate import inspect_qwen_physical_gate
from .qwen_runtime import inspect_qwen_runtime
from .system_log import SystemLog
from .telemetry import SystemTelemetry
from .updates import PRODUCTION_ORIGIN, UpdateManifest, fetch_manifest

WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_RENDERER_ENV = "TDA_DESKTOP_RENDERER"


def _check(code: str, status: str, message: str, detail: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "status": status, "message": message}
    if detail:
        value["detail"] = detail[:240]
    return value


def _writable_check(path: Path, code: str) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="tda-check-", dir=path)
        os.close(fd)
        Path(temporary).unlink(missing_ok=True)
        return _check(code, "pass", "Diretório gravável")
    except OSError as exc:
        return _check(code, "fail", "Diretório não está gravável", type(exc).__name__)


def _sqlite_check(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _check("sqlite", "unavailable", "Banco local ainda não foi criado")
    try:
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            row = db.execute("PRAGMA integrity_check").fetchone()
        finally:
            db.close()
        if row and row[0] == "ok":
            return _check("sqlite", "pass", "Banco local íntegro")
        return _check("sqlite", "fail", "SQLite integrity_check encontrou problema")
    except sqlite3.Error as exc:
        return _check("sqlite", "fail", "Não foi possível validar o banco local", type(exc).__name__)


def _valid_webview2_version(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parts = text.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return False
    return any(int(part) > 0 for part in parts)


def _windows_is_64bit() -> bool:
    architecture = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or ""
    ).lower()
    return architecture in {"amd64", "arm64", "ia64"} or architecture.endswith("64")


def _webview2_registry_version(winreg_module: Any, *, is_64bit: bool) -> tuple[str | None, str | None]:
    user_path = rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"
    machine_root = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" if is_64bit else r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
    machine_path = rf"{machine_root}\{WEBVIEW2_CLIENT_GUID}"
    locations = [
        (winreg_module.HKEY_CURRENT_USER, user_path),
        (winreg_module.HKEY_LOCAL_MACHINE, machine_path),
    ]
    first_error: str | None = None
    for hive, path in locations:
        try:
            with winreg_module.OpenKey(hive, path) as key:
                version, _ = winreg_module.QueryValueEx(key, "pv")
        except FileNotFoundError:
            continue
        except OSError as exc:
            if first_error is None:
                first_error = type(exc).__name__
            continue
        if _valid_webview2_version(version):
            return str(version).strip(), None
    return None, first_error


def _webview2_check() -> dict[str, Any]:
    if os.environ.get(WEBVIEW2_RENDERER_ENV, "").strip().lower() == "edgechromium":
        return _check(
            "webview2",
            "pass",
            "WebView2 Runtime ativo nesta interface",
            "renderer edgechromium",
        )
    if os.name != "nt":
        return _check("webview2", "unavailable", "WebView2 é específico do Windows")
    try:
        import winreg
    except Exception as exc:
        return _check("webview2", "warning", "Não foi possível consultar WebView2", type(exc).__name__)

    version, error = _webview2_registry_version(winreg, is_64bit=_windows_is_64bit())
    if version is not None:
        return _check("webview2", "pass", "WebView2 Runtime disponível", version)
    if error is not None:
        return _check("webview2", "warning", "Não foi possível consultar WebView2", error)
    return _check("webview2", "warning", "WebView2 Runtime não foi localizado no registro oficial")


def _whisper_runtime_check(paths: CompanionPaths) -> dict[str, Any]:
    state = inspect_whisper_runtime(paths.runtime_root, verify_worker=True)
    status = state.get("status")
    version = state.get("version")
    if status == "missing":
        return _check("whisper_runtime", "unavailable", "Runtime Whisper ainda não está instalado")
    if status != "ready":
        return _check(
            "whisper_runtime",
            "fail",
            "Runtime Whisper falhou na verificação de integridade",
            f"versão {version}" if version else None,
        )
    worker = state.get("worker")
    if not isinstance(worker, str):
        return _check("whisper_runtime", "fail", "Executável do runtime Whisper não foi localizado")
    try:
        process = subprocess.run(
            [worker, "--probe"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=12,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.returncode != 0 or len(process.stdout.encode("utf-8")) > 16 * 1024:
            return _check("whisper_runtime", "fail", "Probe do runtime Whisper falhou")
        value = json.loads(process.stdout)
        if not isinstance(value, dict) or value.get("schema") != "tda_whisper_runtime_probe_v1" or value.get("ready") is not True:
            return _check("whisper_runtime", "fail", "Probe do runtime Whisper retornou estado inválido")
        cuda_devices = int(value.get("cuda_device_count") or 0)
        detail = (
            f"v{version} · faster-whisper {value.get('faster_whisper', '—')} · "
            f"CTranslate2 {value.get('ctranslate2', '—')} · CUDA devices {cuda_devices}"
        )
        if cuda_devices < 1:
            return _check(
                "whisper_runtime",
                "warning",
                "Runtime Whisper íntegro, mas CUDA não está disponível",
                detail,
            )
        return _check("whisper_runtime", "pass", "Runtime Whisper íntegro e executável", detail)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _check("whisper_runtime", "fail", "Não foi possível executar o probe do runtime Whisper", type(exc).__name__)


def _qwen_runtime_check(paths: CompanionPaths) -> dict[str, Any]:
    state = inspect_qwen_runtime(paths.runtime_root, verify_worker=True)
    status = state.get("status")
    version = state.get("version")
    if status == "missing":
        return _check("qwen_runtime", "unavailable", "Runtime Qwen ainda não está instalado")
    if status != "ready":
        return _check(
            "qwen_runtime",
            "fail",
            "Runtime Qwen falhou na verificação de integridade",
            f"versão {version}" if version else None,
        )
    worker = state.get("worker")
    if not isinstance(worker, str):
        return _check("qwen_runtime", "fail", "Executável do runtime Qwen não foi localizado")
    try:
        process = subprocess.run(
            [worker, "--probe"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.returncode != 0 or len(process.stdout.encode("utf-8")) > 32 * 1024:
            return _check("qwen_runtime", "fail", "Probe do runtime Qwen falhou")
        value = json.loads(process.stdout)
        if (
            not isinstance(value, dict)
            or value.get("schema") != "tda_qwen_runtime_probe_v1"
            or value.get("ready") is not True
        ):
            return _check("qwen_runtime", "fail", "Probe do runtime Qwen retornou estado inválido")
        if value.get("qwen3_asr_native") is not True or value.get("forced_aligner_native") is not True:
            return _check(
                "qwen_runtime",
                "fail",
                "Runtime Qwen não contém suporte nativo completo de ASR/alinhamento",
            )

        packages = value.get("python_packages") if isinstance(value.get("python_packages"), dict) else {}
        devices = value.get("devices") if isinstance(value.get("devices"), list) else []
        first = devices[0] if devices and isinstance(devices[0], dict) else {}
        gpu_name = str(first.get("name") or "—")
        capability = str(first.get("compute_capability") or "—")
        detail = (
            f"v{version} · Torch {packages.get('torch', '—')} · "
            f"Transformers {packages.get('transformers', '—')} · CUDA {value.get('torch_cuda', '—')} · "
            f"{gpu_name} · CC {capability}"
        )
        if value.get("cuda_available") is not True or not devices:
            return _check(
                "qwen_runtime",
                "warning",
                "Runtime Qwen íntegro, mas CUDA não está disponível",
                detail,
            )
        try:
            major, minor = capability.split(".", 1)
            supported_capability = (int(major), int(minor)) >= (8, 0)
        except (AttributeError, TypeError, ValueError):
            supported_capability = False
        if not supported_capability:
            return _check(
                "qwen_runtime",
                "warning",
                "Runtime Qwen íntegro, mas a GPU não atende ao compute capability mínimo",
                detail,
            )
        return _check("qwen_runtime", "pass", "Runtime Qwen íntegro e executável", detail)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        return _check("qwen_runtime", "fail", "Não foi possível executar o probe do runtime Qwen", type(exc).__name__)


def _model_check(models_root: Path, profile_id: str, code: str, label: str) -> dict[str, Any]:
    state = inspect_model_install(models_root, get_profile(profile_id), verify_hash=False)
    status = state.get("status")
    if status == "ready":
        return _check(code, "pass", f"{label} pronto")
    if status == "missing":
        return _check(code, "unavailable", f"{label} ainda não foi instalado")
    return _check(code, "fail", f"{label} precisa de reparo", str(status or "invalid"))


def _qwen_aligner_check(models_root: Path) -> dict[str, Any]:
    state = inspect_model_install(models_root, ALIGNER_PROFILE, verify_hash=False)
    status = state.get("status")
    if status == "ready":
        return _check("qwen_aligner", "pass", "Alinhador Qwen pronto")
    if status == "missing":
        return _check("qwen_aligner", "unavailable", "Alinhador Qwen ainda não foi instalado")
    return _check("qwen_aligner", "fail", "Alinhador Qwen precisa de reparo", str(status or "invalid"))


def _qwen_gate_check(paths: CompanionPaths, profile_id: str, code: str, label: str) -> dict[str, Any]:
    state = inspect_qwen_physical_gate(
        paths.state_root,
        paths.runtime_root,
        paths.models_root,
        profile_id=profile_id,
        verify_model_content=False,
    )
    if state.get("ready") is True:
        accepted_at = state.get("accepted_at")
        return _check(code, "pass", f"Gate físico {label} aceito", str(accepted_at) if accepted_at else None)
    status = str(state.get("status") or "missing")
    reason = str(state.get("reason") or status)
    if status == "missing":
        return _check(code, "unavailable", f"Gate físico {label} ainda não foi executado", reason)
    return _check(code, "fail", f"Gate físico {label} não está válido", reason)


def _dns_check() -> dict[str, Any]:
    try:
        addresses = socket.getaddrinfo("dnd.faysk.dev", 443, type=socket.SOCK_STREAM)
        if not addresses:
            return _check("network_dns", "fail", "DNS do canal stable não retornou endereço", "DNS_FAILED")
        return _check("network_dns", "pass", "DNS do canal stable respondeu")
    except socket.gaierror:
        return _check("network_dns", "fail", "DNS do canal stable falhou", "DNS_FAILED")
    except OSError:
        return _check("network_dns", "fail", "Rede indisponível durante resolução DNS", "OFFLINE")


def _https_check(client: NetworkClient) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{PRODUCTION_ORIGIN}/api/health",
        headers={"Accept": "application/json", "Cache-Control": "no-store", "User-Agent": "TDACompanion"},
    )
    try:
        with client.open(request, timeout=4.0) as response:
            if response.status != 200:
                return _check("network_https", "fail", "HTTPS do TDA respondeu com erro", f"HTTP_{response.status}")
            response.read(16 * 1024 + 1)
        return _check("network_https", "pass", "HTTPS do TDA respondeu")
    except NetworkError as exc:
        return _check("network_https", "fail", "Não foi possível conectar ao TDA por HTTPS", exc.code)


def _manifest_check(client: NetworkClient) -> tuple[dict[str, Any], UpdateManifest | None]:
    try:
        manifest = fetch_manifest(timeout=5.0, client=client)
        return _check("network_manifest", "pass", "Manifest stable válido", f"v{manifest.version}"), manifest
    except NetworkError as exc:
        return _check("network_manifest", "fail", "Manifest stable não pôde ser validado", exc.code), None


def _asset_check(client: NetworkClient, manifest: UpdateManifest | None) -> dict[str, Any]:
    if manifest is None:
        return _check("network_asset", "unavailable", "Asset stable não foi testado porque o manifest falhou")
    request = urllib.request.Request(
        manifest.url,
        method="HEAD",
        headers={
            "Accept": "application/x-msi,application/octet-stream",
            "Cache-Control": "no-store",
            "User-Agent": "TDACompanion",
        },
    )
    try:
        with client.open(request, timeout=6.0) as response:
            if response.status not in {200, 206}:
                return _check("network_asset", "fail", "Asset stable respondeu com erro", f"HTTP_{response.status}")
            raw_size = response.headers.get("Content-Length")
            if raw_size:
                try:
                    size = int(raw_size)
                except ValueError:
                    return _check("network_asset", "fail", "Asset stable retornou tamanho inválido", "ASSET_SIZE_INVALID")
                if response.status == 200 and size != manifest.size:
                    return _check("network_asset", "fail", "Asset stable não corresponde ao tamanho do manifest", "ASSET_SIZE_MISMATCH")
        return _check("network_asset", "pass", "Asset stable está acessível", f"v{manifest.version}")
    except NetworkError as exc:
        return _check("network_asset", "fail", "Asset stable não está acessível", exc.code)


def _network_checks() -> tuple[list[dict[str, Any]], UpdateManifest | None]:
    dns = _dns_check()
    client = NetworkClient.internet()
    https = _https_check(client)
    if https["status"] != "pass":
        return [
            dns,
            https,
            _check("network_manifest", "unavailable", "Manifest não testado porque HTTPS falhou"),
            _check("network_asset", "unavailable", "Asset não testado porque HTTPS falhou"),
        ], None
    manifest_check, manifest = _manifest_check(client)
    asset = _asset_check(client, manifest)
    return [dns, https, manifest_check, asset], manifest


def _maintenance_metadata_check() -> dict[str, Any]:
    if os.name != "nt":
        return _check("maintenance_metadata", "unavailable", "Metadados MSI são específicos do Windows")
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Faysk\TDA Companion") as key:
            version, _ = winreg.QueryValueEx(key, "Version")
            product_code, _ = winreg.QueryValueEx(key, "ProductCode")
            install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
    except FileNotFoundError:
        return _check("maintenance_metadata", "fail", "Metadados MSI do Companion não foram encontrados")
    except OSError as exc:
        return _check("maintenance_metadata", "fail", "Não foi possível ler os metadados MSI", type(exc).__name__)
    if str(version) != VERSION or not str(product_code).strip() or not str(install_dir).strip():
        return _check("maintenance_metadata", "fail", "Metadados MSI estão inconsistentes", "MSI_METADATA_MISMATCH")
    return _check("maintenance_metadata", "pass", "Metadados MSI coerentes", f"v{version}")


def _maintenance_helper_check(paths: CompanionPaths) -> dict[str, Any]:
    if os.name != "nt":
        return _check("maintenance_helper", "unavailable", "Helper de manutenção é específico do Windows")
    marker = paths.companion_root / "current-version.txt"
    try:
        installed = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return _check("maintenance_helper", "fail", "Versão instalada não pôde ser confirmada", "VERSION_MARKER_MISSING")
    if installed != VERSION:
        return _check("maintenance_helper", "fail", "Versão instalada diverge da interface", "VERSION_MARKER_MISMATCH")
    helper = paths.companion_root / "versions" / VERSION / "TDACompanionMaintenance.exe"
    if not helper.is_file():
        return _check("maintenance_helper", "fail", "Helper de manutenção não foi localizado", "MAINTENANCE_HELPER_MISSING")
    return _check("maintenance_helper", "pass", "Helper de manutenção disponível", f"v{VERSION}")


def _maintenance_channel_check(manifest: UpdateManifest | None) -> dict[str, Any]:
    if manifest is None:
        return _check("maintenance_update_channel", "unavailable", "Canal stable não pôde ser validado")
    return _check("maintenance_update_channel", "pass", "Canal stable disponível", f"{manifest.tag} · v{manifest.version}")


def run_diagnostics(paths: CompanionPaths, port: int) -> dict[str, Any]:
    agent_ready = wait_until_ready(port, timeout=0.5)
    checks: list[dict[str, Any]] = [
        _check(
            "agent",
            "pass" if agent_ready else "fail",
            "Agent local respondendo" if agent_ready else "Agent local não respondeu",
        ),
        _writable_check(paths.state_root, "state"),
        _writable_check(paths.data_root, "data"),
        _sqlite_check(paths.data_root / "jobs.sqlite3"),
        _webview2_check(),
        _whisper_runtime_check(paths),
        _model_check(paths.models_root, "whisper-turbo", "whisper_model_turbo", "Modelo Whisper Turbo"),
        _model_check(paths.models_root, "whisper-detailed", "whisper_model_detailed", "Modelo Whisper Detalhado"),
        _qwen_runtime_check(paths),
        _model_check(paths.models_root, "qwen-fast", "qwen_model_fast", "Modelo Qwen Rápido"),
        _model_check(paths.models_root, "qwen-quality", "qwen_model_quality", "Modelo Qwen Qualidade"),
        _qwen_aligner_check(paths.models_root),
        _qwen_gate_check(paths, "qwen-fast", "qwen_gate_fast", "Qwen Rápido"),
        _qwen_gate_check(paths, "qwen-quality", "qwen_gate_quality", "Qwen Qualidade"),
    ]

    try:
        usage = shutil.disk_usage(paths.data_root)
        free_gib = usage.free / (1024**3)
        checks.append(
            _check(
                "disk",
                "pass" if free_gib >= 10 else "warning",
                f"{free_gib:.1f} GiB livres no volume de dados",
            )
        )
    except OSError as exc:
        checks.append(_check("disk", "warning", "Espaço livre indisponível", type(exc).__name__))

    telemetry = SystemTelemetry().snapshot()
    gpus = telemetry.get("gpus") or []
    checks.append(
        _check(
            "nvidia",
            "pass" if gpus else "unavailable",
            "GPU NVIDIA detectada" if gpus else "GPU/NVML NVIDIA indisponível",
            str(gpus[0].get("name")) if gpus else None,
        )
    )

    network_checks, manifest = _network_checks()
    checks.extend(network_checks)
    checks.extend(
        [
            _maintenance_metadata_check(),
            _maintenance_helper_check(paths),
            _maintenance_channel_check(manifest),
        ]
    )

    capabilities = build_capabilities(checks)
    overall = overall_status(capabilities)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": VERSION,
        "overall": overall,
        "capabilities": capabilities,
        "checks": capability_rows(capabilities) + checks,
        "system": telemetry,
    }


def export_diagnostics(paths: CompanionPaths, port: int, destination: Path | None = None) -> Path:
    report = run_diagnostics(paths, port)
    if destination is None:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        destination = paths.root / f"TDA-Diagnostico-{stamp}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    log = SystemLog(paths.logs_root)
    logs = log.tail(limit=500)
    manifest = {
        "schema": "tda_diagnostics_v1",
        "version": VERSION,
        "contains_audio": False,
        "contains_transcript": False,
        "contains_pairing_token": False,
    }

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("diagnostics.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("logs.json", json.dumps(logs, ensure_ascii=False, indent=2))
    return destination
