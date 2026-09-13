from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import VERSION
from .paths import CompanionPaths

INSTALLED_ACCEPTANCE_SCHEMA = "tda_installed_acceptance_v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_OPERATION_ID = re.compile(r"^[a-f0-9]{32}$")
_ALLOWED_CAPABILITY_STATES = frozenset({"ready", "degraded", "blocked"})
_ALLOWED_SEVERITIES = frozenset({"info", "degraded", "blocker"})


class InstalledAcceptanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installed_layout(executable: Path, paths: CompanionPaths) -> dict[str, object]:
    exe = executable.resolve()
    expected = (paths.companion_root / "versions" / VERSION / "TDACompanion.exe").resolve()
    if exe != expected or not exe.is_file():
        raise InstalledAcceptanceError("INSTALLED_LAYOUT_EXECUTABLE_MISMATCH")

    helper = exe.parent / "TDACompanionMaintenance.exe"
    if not helper.is_file():
        raise InstalledAcceptanceError("INSTALLED_LAYOUT_MAINTENANCE_HELPER_MISSING")

    current = paths.companion_root / "current-version.txt"
    try:
        current_version = current.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise InstalledAcceptanceError("INSTALLED_LAYOUT_VERSION_MARKER_MISSING") from exc
    if current_version != VERSION:
        raise InstalledAcceptanceError("INSTALLED_LAYOUT_VERSION_MARKER_MISMATCH")

    exe_sha256 = sha256_file(exe)
    helper_sha256 = sha256_file(helper)
    if not _SHA256.fullmatch(exe_sha256) or not _SHA256.fullmatch(helper_sha256):
        raise InstalledAcceptanceError("INSTALLED_LAYOUT_HASH_INVALID")
    return {
        "version": VERSION,
        "executable_sha256": exe_sha256,
        "maintenance_helper_sha256": helper_sha256,
    }


def summarize_diagnostics(value: dict[str, Any]) -> dict[str, object]:
    overall = str(value.get("overall") or "unknown")
    raw_capabilities = value.get("capabilities")
    capabilities: dict[str, dict[str, str]] = {}
    if isinstance(raw_capabilities, dict):
        for name in ("core", "network", "maintenance", "whisper", "qwen"):
            raw = raw_capabilities.get(name)
            if not isinstance(raw, dict):
                continue
            state = str(raw.get("state") or "blocked")
            severity = str(raw.get("severity") or "blocker")
            if state not in _ALLOWED_CAPABILITY_STATES:
                state = "blocked"
            if severity not in _ALLOWED_SEVERITIES:
                severity = "blocker"
            capabilities[name] = {"state": state, "severity": severity}
    return {"overall": overall, "capabilities": capabilities}


def maintenance_summary(value: dict[str, Any] | None) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    operation_id = value.get("operation_id")
    if operation_id is not None and (
        not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id)
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
    )
    return {key: value.get(key) for key in allowed if key in value}


def _validate_receipt_value(value: object, *, depth: int = 0) -> None:
    if depth > 16:
        raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_TOO_DEEP")
    if isinstance(value, dict):
        for key, child in value.items():
            folded = str(key).casefold()
            if any(term in folded for term in ("token", "password", "authorization", "transcript", "path")):
                raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_PRIVATE_FIELD")
            _validate_receipt_value(child, depth=depth + 1)
        return
    if isinstance(value, list):
        for child in value:
            _validate_receipt_value(child, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > 512:
            raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_STRING_TOO_LARGE")
        if re.search(r"[A-Za-z]:\\", value) or value.startswith("/") or "Bearer " in value:
            raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_PRIVATE_VALUE")


def write_receipt(
    destination: Path,
    *,
    passed: bool,
    stage: str,
    checks: dict[str, object],
    artifact: dict[str, object] | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": INSTALLED_ACCEPTANCE_SCHEMA,
        "pass": bool(passed),
        "accepted_at": datetime.now(UTC).isoformat(),
        "version": VERSION,
        "stage": stage,
        "checks": checks,
        "contains_token": False,
        "contains_paths": False,
        "contains_transcript": False,
    }
    if artifact is not None:
        receipt["artifact"] = artifact
    if error_code is not None:
        receipt["error_code"] = re.sub(r"[^A-Z0-9_.:-]", "_", error_code.upper())[:120]

    _validate_receipt_value(receipt)
    target = destination.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return receipt
