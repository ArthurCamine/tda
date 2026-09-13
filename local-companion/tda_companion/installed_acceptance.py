from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from . import VERSION
from .paths import CompanionPaths
from .payload_evidence import PayloadEvidenceError, verify_installed_payload

INSTALLED_ACCEPTANCE_SCHEMA = "tda_installed_acceptance_v2"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_SHA = re.compile(r"^[a-f0-9]{40}$")
_OPERATION_ID = re.compile(r"^[a-f0-9]{32}$")
_ALLOWED_CAPABILITY_STATES = frozenset({"ready", "degraded", "blocked"})
_ALLOWED_SEVERITIES = frozenset({"info", "degraded", "blocker"})
_PRIVACY_PROOF_FIELDS = frozenset({"contains_token", "contains_paths", "contains_transcript"})
REQUIRED_OBSERVATIONS = frozenset(
    {
        "agent_recovery",
        "port_conflict",
        "diagnostics_ui",
        "close_hides_ui",
        "tray_exit",
        "craig_selected",
        "craig_survives_agent_loss",
        "background_download_resume",
    }
)


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
    return {"version": VERSION}


def verify_candidate(candidate_msi: Path, source_sha: str) -> dict[str, object]:
    candidate = candidate_msi.resolve()
    if candidate.suffix.casefold() != ".msi" or not candidate.is_file():
        raise InstalledAcceptanceError("ACCEPTANCE_CANDIDATE_MSI_INVALID")
    normalized_source = source_sha.strip().casefold()
    if not _SOURCE_SHA.fullmatch(normalized_source):
        raise InstalledAcceptanceError("ACCEPTANCE_SOURCE_SHA_INVALID")
    return {"source_sha": normalized_source, "msi_sha256": sha256_file(candidate)}


def verify_payload(executable: Path, manifest: Path, source_sha: str) -> dict[str, object]:
    try:
        evidence = verify_installed_payload(
            executable.resolve().parent,
            manifest,
            expected_version=VERSION,
            expected_source_sha=source_sha,
        )
    except PayloadEvidenceError as exc:
        raise InstalledAcceptanceError(exc.code) from exc
    files = evidence.get("files")
    if not isinstance(files, dict):
        raise InstalledAcceptanceError("PAYLOAD_MANIFEST_INVALID")
    exe = files.get("TDACompanion.exe")
    helper = files.get("TDACompanionMaintenance.exe")
    if not isinstance(exe, dict) or not isinstance(helper, dict):
        raise InstalledAcceptanceError("PAYLOAD_MANIFEST_INVALID")
    return {
        "source_tree_sha": evidence["source_tree_sha"],
        "payload_manifest_sha256": evidence["manifest_sha256"],
        "executable_sha256": exe["sha256"],
        "maintenance_helper_sha256": helper["sha256"],
    }


def verify_craig_fixture(craig_zip: Path) -> dict[str, object]:
    from .craig import CraigPackageError, inspect_craig_zip

    source = craig_zip.resolve()
    try:
        tracks, _info, _raw_present = inspect_craig_zip(source)
    except CraigPackageError as exc:
        raise InstalledAcceptanceError("ACCEPTANCE_CRAIG_FIXTURE_INVALID") from exc
    return {"track_count": len(tracks), "zip_sha256": sha256_file(source)}


def summarize_diagnostics(value: dict[str, Any]) -> dict[str, object]:
    overall = str(value.get("overall") or "unknown")
    raw_capabilities = value.get("capabilities")
    capabilities: dict[str, dict[str, str]] = {}

    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(raw_capabilities, dict):
        rows = [
            (name, raw)
            for name, raw in raw_capabilities.items()
            if isinstance(name, str) and isinstance(raw, dict)
        ]
    elif isinstance(raw_capabilities, list):
        for raw in raw_capabilities:
            if not isinstance(raw, dict):
                continue
            capability_id = raw.get("id")
            if isinstance(capability_id, str):
                rows.append((capability_id, raw))

    for name, raw in rows:
        if name not in {"core", "network", "maintenance", "whisper", "qwen"}:
            continue
        # Diagnostics use `status`; older receipt fixtures used `state`. Accept
        # both, normalize to the receipt contract and fail closed on unknowns.
        state = str(raw.get("state") or raw.get("status") or "blocked")
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
        "operation_id", "action", "status", "stage", "failure_stage",
        "error_code", "msi_exit_code", "target_version", "purge",
    )
    return {key: value.get(key) for key in allowed if key in value}


def _validate_receipt_value(value: object, *, depth: int = 0) -> None:
    if depth > 16:
        raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_TOO_DEEP")
    if isinstance(value, dict):
        for key, child in value.items():
            folded = str(key).casefold()
            if folded in _PRIVACY_PROOF_FIELDS:
                if child is not False:
                    raise InstalledAcceptanceError("ACCEPTANCE_RECEIPT_PRIVACY_PROOF_INVALID")
                continue
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


def finalize_installed_acceptance(
    *,
    executable: Path,
    paths: CompanionPaths,
    port: int,
    candidate_msi: Path,
    payload_manifest: Path,
    source_sha: str,
    craig_zip: Path,
    observations: Iterable[str],
    destination: Path,
) -> dict[str, object]:
    observed = frozenset(str(value).strip() for value in observations if str(value).strip())
    if observed != REQUIRED_OBSERVATIONS:
        return write_receipt(
            destination,
            passed=False,
            stage="manual_observations",
            checks={"observations": {name: name in observed for name in sorted(REQUIRED_OBSERVATIONS)}},
            error_code="ACCEPTANCE_OBSERVATIONS_INCOMPLETE",
        )

    candidate = verify_candidate(candidate_msi, source_sha)
    artifact = {
        **candidate,
        **verify_installed_layout(executable, paths),
        **verify_payload(executable, payload_manifest, str(candidate["source_sha"])),
    }
    craig_fixture = verify_craig_fixture(craig_zip)

    from .diagnostics import run_diagnostics

    diagnostic_summary = summarize_diagnostics(run_diagnostics(paths, port))
    capabilities = diagnostic_summary.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    required_capabilities = ("core", "network", "maintenance")
    operational = all(
        isinstance(capabilities.get(name), dict)
        and capabilities[name].get("state") == "ready"
        for name in required_capabilities
    )
    checks: dict[str, object] = {
        "observations": {name: True for name in sorted(REQUIRED_OBSERVATIONS)},
        "craig_fixture": craig_fixture,
        "diagnostics": diagnostic_summary,
    }
    return write_receipt(
        destination,
        passed=operational,
        stage="completed" if operational else "diagnostics",
        checks=checks,
        artifact=artifact,
        error_code=None if operational else "ACCEPTANCE_REQUIRED_CAPABILITY_NOT_READY",
    )
