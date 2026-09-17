from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import VERSION
from .agent import AgentController, wait_until_ready
from .agent_connection import probe_agent
from .installed_acceptance import (
    REQUIRED_OBSERVATIONS,
    InstalledAcceptanceError,
    finalize_installed_acceptance,
    write_receipt,
)
from .pairing import TOKEN_PATTERN, ensure_pairing_token
from .paths import CompanionPaths, default_paths, migrate_v02_layout
from .settings import SettingsStore
from .single_active_version import ReconcileResult, reconcile_packaged_installation
from .startup import set_start_with_windows
from .system_log import SystemLog

PRODUCTION_ORIGIN = "https://dnd.faysk.dev"
PROCESSING_URL = f"{PRODUCTION_ORIGIN}/edit/processamento"


def default_roots() -> tuple[Path, Path]:
    paths = default_paths()
    return paths.state_root, paths.data_root


def validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or "*" in origin
        or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"))
    ):
        raise ValueError("EXACT_HTTPS_OR_LOOPBACK_ORIGIN_REQUIRED")
    return origin


def _write_diagnostic(path: Path | None, status: str, detail: str | None = None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_detail = "" if detail is None else re.sub(r"[^A-Za-z0-9_.:-]", "_", detail)[:160]
    line = status if not safe_detail else f"{status}:{safe_detail}"
    path.write_text(line + "\n", encoding="utf-8")


def _atomic_json(path: Path, value: object) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _safe_error_detail(exc: BaseException) -> str:
    if isinstance(exc, ModuleNotFoundError):
        return f"ModuleNotFoundError.{exc.name or 'unknown'}"
    if isinstance(exc, (RuntimeError, ValueError)):
        text = str(exc)
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", text)[:120]
        if safe:
            return f"{type(exc).__name__}.{safe}"
    return type(exc).__name__


def _entry_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "tda_companion.windows_app"]


def _agent_arguments(args: argparse.Namespace) -> list[str]:
    values = [
        "--agent", "--state-root", str(args.state_root), "--data-root", str(args.data_root),
        "--logs-root", str(args.logs_root), "--port", str(args.port),
    ]
    for origin in sorted(args.origins):
        values.extend(["--origin", origin])
    return values


def _paths_for_args(args: argparse.Namespace) -> CompanionPaths:
    defaults = default_paths()
    if (
        args.state_root.resolve() == defaults.state_root.resolve()
        and args.data_root.resolve() == defaults.data_root.resolve()
        and args.logs_root.resolve() == defaults.logs_root.resolve()
    ):
        return defaults
    root = args.state_root.resolve().parent
    return CompanionPaths(
        root=root,
        companion_root=root / "Companion",
        state_root=args.state_root.resolve(),
        data_root=args.data_root.resolve(),
        logs_root=args.logs_root.resolve(),
        cache_root=root / "Cache",
        models_root=root / "Models",
        runtime_root=root / "Runtime",
    )


def _reconcile_installation(paths: CompanionPaths) -> ReconcileResult:
    return reconcile_packaged_installation(
        paths,
        VERSION,
        Path(sys.executable),
        current_pid=os.getpid(),
    )


def ensure_agent_running(args: argparse.Namespace) -> subprocess.Popen | None:
    # Recovery is application-owned. Before deciding what is on the Agent port,
    # converge the installed tree to the version that is currently executing.
    _reconcile_installation(_paths_for_args(args))

    existing = probe_agent(args.port, expected_version=VERSION, timeout=0.5)
    if existing.state == "exact":
        return None
    if existing.state == "compatible":
        # A different Companion version is never an operational fallback. If it
        # survived reconciliation, fail closed instead of silently using it.
        raise RuntimeError("STALE_AGENT_VERSION_REMAINS")
    if existing.state in {"foreign", "incompatible"}:
        return None

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        _entry_command() + _agent_arguments(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"LOCAL_AGENT_EXITED:{process.returncode}")
        if wait_until_ready(args.port, timeout=0.3, expected_version=VERSION):
            return process
    raise RuntimeError("LOCAL_AGENT_START_TIMEOUT")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    paths = default_paths()
    parser = argparse.ArgumentParser(prog="TDACompanion")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--agent", action="store_true")
    mode.add_argument("--ui", action="store_true")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--install-rc-runtime", choices=("whisper", "qwen"), help=argparse.SUPPRESS)
    mode.add_argument("--installed-acceptance", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--state-root", type=Path, default=paths.state_root)
    parser.add_argument("--data-root", type=Path, default=paths.data_root)
    parser.add_argument("--logs-root", type=Path, default=paths.logs_root)
    parser.add_argument("--origin", action="append")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--diagnostic-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--rc-artifact", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--rc-artifact-sha256", help=argparse.SUPPRESS)
    parser.add_argument("--rc-result-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-candidate-msi", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-payload-manifest", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-source-sha", help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-craig-zip", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-bits-evidence", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acceptance-result-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--acceptance-observation", action="append", choices=sorted(REQUIRED_OBSERVATIONS), help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("INVALID_PORT")
    if args.install_rc_runtime and (
        args.rc_artifact is None or args.rc_artifact_sha256 is None or args.rc_result_file is None
    ):
        parser.error("RC_RUNTIME_ARTIFACT_HASH_AND_RESULT_REQUIRED")
    if args.installed_acceptance and (
        args.acceptance_candidate_msi is None
        or args.acceptance_payload_manifest is None
        or not args.acceptance_source_sha
        or args.acceptance_craig_zip is None
        or args.acceptance_bits_evidence is None
        or args.acceptance_result_file is None
    ):
        parser.error("ACCEPTANCE_CANDIDATE_PAYLOAD_SOURCE_CRAIG_BITS_AND_RESULT_REQUIRED")
    origins = args.origin or [PRODUCTION_ORIGIN]
    try:
        args.origins = frozenset(validate_origin(origin) for origin in origins)
    except ValueError as exc:
        parser.error(str(exc))
    if args.headless:
        args.agent = True
    return args


def _install_rc_runtime(args: argparse.Namespace) -> int:
    from .rc_runtime_artifacts import RcRuntimeArtifactError, install_rc_runtime_artifact

    result_path: Path = args.rc_result_file
    try:
        paths = default_paths()
        paths.ensure_runtime_dirs()
        result = install_rc_runtime_artifact(
            args.install_rc_runtime,
            args.rc_artifact,
            expected_artifact_sha256=args.rc_artifact_sha256,
            runtime_root=paths.runtime_root,
            cache_root=paths.cache_root,
        )
        _atomic_json(result_path, {"schema": "tda_rc_runtime_install_v1", "ok": True, **result})
        return 0
    except RcRuntimeArtifactError as exc:
        _atomic_json(result_path, {"schema": "tda_rc_runtime_install_v1", "ok": False, "error": exc.code})
        return 66
    except BaseException:
        _atomic_json(result_path, {"schema": "tda_rc_runtime_install_v1", "ok": False, "error": "RC_RUNTIME_INSTALL_FAILED"})
        return 70


def _run_installed_acceptance(args: argparse.Namespace) -> int:
    destination: Path = args.acceptance_result_file
    try:
        receipt = finalize_installed_acceptance(
            executable=Path(sys.executable).resolve(),
            paths=_paths_for_args(args),
            port=args.port,
            candidate_msi=args.acceptance_candidate_msi,
            payload_manifest=args.acceptance_payload_manifest,
            source_sha=args.acceptance_source_sha,
            craig_zip=args.acceptance_craig_zip,
            observations=args.acceptance_observation or (),
            destination=destination,
            bits_evidence=args.acceptance_bits_evidence,
        )
        return 0 if receipt.get("pass") is True else 66
    except InstalledAcceptanceError as exc:
        write_receipt(destination, passed=False, stage="validation", checks={}, error_code=exc.code)
        return 66
    except BaseException:
        write_receipt(destination, passed=False, stage="validation", checks={}, error_code="ACCEPTANCE_EXECUTION_FAILED")
        return 70


def _show_desktop_error(exc: BaseException) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "TDA Companion",
            "Não foi possível abrir a interface do TDA Companion.\n\n"
            f"Código: {_safe_error_detail(exc)}\n\n"
            "O TDA tentou reparar o serviço local automaticamente. O diagnóstico registra os detalhes da falha.",
        )
        root.destroy()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker:
        from .asr_worker import run_worker_stdio
        return run_worker_stdio()
    if args.install_rc_runtime:
        return _install_rc_runtime(args)
    if args.installed_acceptance:
        return _run_installed_acceptance(args)

    diagnostic_file: Path | None = args.diagnostic_file
    _write_diagnostic(diagnostic_file, "BOOTSTRAP")
    try:
        paths = _paths_for_args(args)
        defaults = default_paths()
        if paths.root == defaults.root:
            migrate_v02_layout(defaults)
        paths.ensure_runtime_dirs()
        system_log = SystemLog(paths.logs_root)

        reconciliation = _reconcile_installation(paths)
        if reconciliation.applied and (reconciliation.terminated_pids or reconciliation.removed_entries):
            system_log.write(
                "info",
                "bootstrap",
                "INSTALLATION_RECONCILED",
                "TDA Companion removed stale installed versions",
                {
                    "version": VERSION,
                    "terminated_process_count": len(reconciliation.terminated_pids),
                    "removed_version_count": len(reconciliation.removed_entries),
                },
            )

        token = ensure_pairing_token(paths.state_root / "pairing-token.txt")
        _write_diagnostic(diagnostic_file, "TOKEN_READY")

        if args.agent:
            system_log.write("info", "bootstrap", "AGENT_BOOTSTRAP", "TDA Companion Agent starting", {"version": VERSION})
            controller = AgentController(
                paths.data_root, token, args.origins, args.port, system_log, models_root=paths.models_root,
            )
            controller.run_forever(on_ready=lambda: _write_diagnostic(diagnostic_file, "READY"))
            return 0

        ensure_agent_running(args)
        settings = SettingsStore(paths.state_root / "settings.json")
        executable = Path(sys.executable).resolve()
        if os.name == "nt":
            set_start_with_windows(bool(settings.snapshot()["start_with_windows"]), executable)
        _write_diagnostic(diagnostic_file, "READY")
        from .desktop_runtime import run_desktop
        run_desktop(
            token=token,
            port=args.port,
            paths=paths,
            settings=settings,
            executable=executable,
            start_agent=lambda: ensure_agent_running(args),
        )
        return 0
    except BaseException as exc:
        _write_diagnostic(diagnostic_file, "FAILED", _safe_error_detail(exc))
        if args.agent:
            return 1
        _show_desktop_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
