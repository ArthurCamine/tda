from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import VERSION
from .bits_resume_evidence import BitsResumeEvidenceError, validate_bits_resume_evidence
from .installed_acceptance import INSTALLED_ACCEPTANCE_SCHEMA, REQUIRED_OBSERVATIONS
from .payload_evidence import PayloadEvidenceError, load_payload_manifest

CANDIDATE_SCHEMA = "tda_companion_candidate_v2"
PROMOTION_SCHEMA = "tda_companion_promotion_v2"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_SHA = re.compile(r"^[a-f0-9]{40}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RC_TAG = re.compile(r"^companion-rc-v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<prefix>[a-f0-9]{12})$")
_REQUIRED_CAPABILITIES = ("core", "network", "maintenance")
_ALLOWED_CAPABILITIES = frozenset({"core", "network", "maintenance", "whisper", "qwen"})
_ALLOWED_CAPABILITY_STATES = frozenset({"ready", "degraded", "blocked"})
_ALLOWED_SEVERITIES = frozenset({"info", "degraded", "blocker"})
_CANDIDATE_KEYS = frozenset(
    {
        "schema",
        "channel",
        "tag",
        "version",
        "source_sha",
        "source_tree_sha",
        "workflow_run_id",
        "assets",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {
        "schema",
        "pass",
        "accepted_at",
        "version",
        "stage",
        "checks",
        "contains_token",
        "contains_paths",
        "contains_transcript",
        "artifact",
    }
)
_ARTIFACT_KEYS = frozenset(
    {
        "version",
        "source_sha",
        "source_tree_sha",
        "msi_sha256",
        "payload_manifest_sha256",
        "executable_sha256",
        "maintenance_helper_sha256",
    }
)
_CHECK_KEYS = frozenset({"observations", "background_download_resume", "craig_fixture", "diagnostics"})
_CRAIG_KEYS = frozenset({"track_count", "zip_sha256"})
_DIAGNOSTIC_KEYS = frozenset({"overall", "capabilities"})
_CAPABILITY_KEYS = frozenset({"state", "severity"})


class ReleaseEvidenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceError(code) from exc
    if not isinstance(value, dict):
        raise ReleaseEvidenceError(code)
    return value


def _normalize_git_sha(value: str, code: str) -> str:
    normalized = value.strip().casefold()
    if not _SOURCE_SHA.fullmatch(normalized):
        raise ReleaseEvidenceError(code)
    return normalized


def _normalize_source_sha(value: str) -> str:
    return _normalize_git_sha(value, "RELEASE_SOURCE_SHA_INVALID")


def _candidate_tag(version: str, source_sha: str) -> str:
    if not _VERSION.fullmatch(version):
        raise ReleaseEvidenceError("RELEASE_VERSION_INVALID")
    source = _normalize_source_sha(source_sha)
    return f"companion-rc-v{version}-{source[:12]}"


def _asset_record(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ReleaseEvidenceError("RELEASE_ASSET_MISSING")
    return {
        "name": resolved.name,
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def _verify_checksum_file(checksum_path: Path, msi_sha256: str) -> None:
    try:
        text = checksum_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ReleaseEvidenceError("RELEASE_CHECKSUM_FILE_INVALID") from exc
    match = re.fullmatch(r"([A-Fa-f0-9]{64})\s+TDACompanion-x64\.msi", text)
    if not match or match.group(1).casefold() != msi_sha256:
        raise ReleaseEvidenceError("RELEASE_CHECKSUM_MISMATCH")


def _verify_payload_identity(
    payload_path: Path,
    *,
    version: str,
    source_sha: str,
    source_tree_sha: str,
) -> None:
    try:
        value = load_payload_manifest(payload_path)
    except PayloadEvidenceError as exc:
        raise ReleaseEvidenceError("RELEASE_PAYLOAD_MANIFEST_INVALID") from exc
    if value.get("version") != version:
        raise ReleaseEvidenceError("RELEASE_PAYLOAD_VERSION_MISMATCH")
    if value.get("source_sha") != source_sha:
        raise ReleaseEvidenceError("RELEASE_PAYLOAD_SOURCE_MISMATCH")
    if value.get("source_tree_sha") != source_tree_sha:
        raise ReleaseEvidenceError("RELEASE_PAYLOAD_TREE_MISMATCH")


def build_candidate_manifest(
    *,
    source_sha: str,
    source_tree_sha: str,
    workflow_run_id: int,
    msi_path: Path,
    checksum_path: Path,
    zip_path: Path,
    payload_manifest_path: Path,
) -> dict[str, object]:
    source = _normalize_source_sha(source_sha)
    tree = _normalize_git_sha(source_tree_sha, "RELEASE_SOURCE_TREE_INVALID")
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise ReleaseEvidenceError("RELEASE_WORKFLOW_RUN_INVALID")
    if not _VERSION.fullmatch(VERSION):
        raise ReleaseEvidenceError("RELEASE_VERSION_INVALID")
    if msi_path.name != "TDACompanion-x64.msi":
        raise ReleaseEvidenceError("RELEASE_MSI_NAME_INVALID")
    if checksum_path.name != "TDACompanion-x64.msi.sha256":
        raise ReleaseEvidenceError("RELEASE_CHECKSUM_NAME_INVALID")
    if zip_path.name != f"TDACompanion-{VERSION}-windows-x64.zip":
        raise ReleaseEvidenceError("RELEASE_ZIP_NAME_INVALID")
    if payload_manifest_path.name != "TDACompanion-payload-manifest.json":
        raise ReleaseEvidenceError("RELEASE_PAYLOAD_NAME_INVALID")

    _verify_payload_identity(
        payload_manifest_path,
        version=VERSION,
        source_sha=source,
        source_tree_sha=tree,
    )
    msi = _asset_record(msi_path)
    checksum = _asset_record(checksum_path)
    zip_asset = _asset_record(zip_path)
    payload = _asset_record(payload_manifest_path)
    _verify_checksum_file(checksum_path, str(msi["sha256"]))
    return {
        "schema": CANDIDATE_SCHEMA,
        "channel": "rc",
        "tag": _candidate_tag(VERSION, source),
        "version": VERSION,
        "source_sha": source,
        "source_tree_sha": tree,
        "workflow_run_id": workflow_run_id,
        "assets": {
            "msi": msi,
            "checksum": checksum,
            "zip": zip_asset,
            "payload_manifest": payload,
        },
    }


def verify_candidate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != _CANDIDATE_KEYS:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_SCHEMA_INVALID")
    if value.get("schema") != CANDIDATE_SCHEMA or value.get("channel") != "rc":
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_SCHEMA_INVALID")
    version = value.get("version")
    source_sha = value.get("source_sha")
    source_tree_sha = value.get("source_tree_sha")
    tag = value.get("tag")
    run_id = value.get("workflow_run_id")
    if not isinstance(version, str) or not _VERSION.fullmatch(version) or version != VERSION:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_VERSION_MISMATCH")
    if not isinstance(source_sha, str):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_SOURCE_INVALID")
    source = _normalize_source_sha(source_sha)
    if not isinstance(source_tree_sha, str):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_TREE_INVALID")
    tree = _normalize_git_sha(source_tree_sha, "RELEASE_CANDIDATE_TREE_INVALID")
    if tag != _candidate_tag(version, source):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_TAG_MISMATCH")
    if not isinstance(tag, str) or _RC_TAG.fullmatch(tag) is None:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_TAG_INVALID")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_RUN_INVALID")

    assets = value.get("assets")
    expected_keys = {"msi", "checksum", "zip", "payload_manifest"}
    if not isinstance(assets, dict) or set(assets) != expected_keys:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSETS_INVALID")
    expected_names = {
        "msi": "TDACompanion-x64.msi",
        "checksum": "TDACompanion-x64.msi.sha256",
        "zip": f"TDACompanion-{version}-windows-x64.zip",
        "payload_manifest": "TDACompanion-payload-manifest.json",
    }
    for key, expected_name in expected_names.items():
        row = assets.get(key)
        if not isinstance(row, dict):
            raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSET_INVALID")
        if set(row) != {"name", "sha256", "size"} or row.get("name") != expected_name:
            raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSET_INVALID")
        sha = row.get("sha256")
        size = row.get("size")
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSET_HASH_INVALID")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSET_SIZE_INVALID")
    value["source_sha"] = source
    value["source_tree_sha"] = tree
    return value


def verify_candidate_files(manifest: dict[str, Any], assets_root: Path) -> None:
    value = verify_candidate_manifest(manifest)
    assets = value["assets"]
    assert isinstance(assets, dict)
    for key in ("msi", "checksum", "zip", "payload_manifest"):
        row = assets[key]
        assert isinstance(row, dict)
        path = assets_root / str(row["name"])
        if not path.is_file():
            raise ReleaseEvidenceError("RELEASE_ASSET_MISSING")
        if path.stat().st_size != row["size"]:
            raise ReleaseEvidenceError("RELEASE_ASSET_SIZE_MISMATCH")
        if sha256_file(path) != row["sha256"]:
            raise ReleaseEvidenceError("RELEASE_ASSET_HASH_MISMATCH")
    msi = assets["msi"]
    checksum = assets["checksum"]
    payload = assets["payload_manifest"]
    assert isinstance(msi, dict) and isinstance(checksum, dict) and isinstance(payload, dict)
    _verify_checksum_file(assets_root / str(checksum["name"]), str(msi["sha256"]))
    _verify_payload_identity(
        assets_root / str(payload["name"]),
        version=str(value["version"]),
        source_sha=str(value["source_sha"]),
        source_tree_sha=str(value["source_tree_sha"]),
    )


def _verify_acceptance_shape(receipt: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if set(receipt) != _ACCEPTANCE_KEYS:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_SCHEMA_INVALID")
    accepted_at = receipt.get("accepted_at")
    if not isinstance(accepted_at, str) or len(accepted_at) > 64:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_TIMESTAMP_INVALID")
    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_KEYS:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_INVALID")
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != _CHECK_KEYS:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CHECKS_INVALID")
    observations = checks.get("observations")
    if not isinstance(observations, dict) or set(observations) != set(REQUIRED_OBSERVATIONS):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_OBSERVATIONS_INVALID")
    if any(observations[name] is not True for name in REQUIRED_OBSERVATIONS):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_OBSERVATIONS_INVALID")
    try:
        validate_bits_resume_evidence(checks.get("background_download_resume"))
    except BitsResumeEvidenceError as exc:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_BITS_INVALID") from exc
    craig = checks.get("craig_fixture")
    if not isinstance(craig, dict) or set(craig) != _CRAIG_KEYS:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CRAIG_INVALID")
    zip_sha = craig.get("zip_sha256")
    track_count = craig.get("track_count")
    if not isinstance(zip_sha, str) or not _SHA256.fullmatch(zip_sha):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CRAIG_INVALID")
    if not isinstance(track_count, int) or isinstance(track_count, bool) or track_count < 1:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CRAIG_INVALID")
    diagnostics = checks.get("diagnostics")
    if not isinstance(diagnostics, dict) or set(diagnostics) != _DIAGNOSTIC_KEYS:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
    overall = diagnostics.get("overall")
    if not isinstance(overall, str) or not overall or len(overall) > 32:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
    capabilities = diagnostics.get("capabilities")
    if not isinstance(capabilities, dict) or not set(capabilities).issubset(_ALLOWED_CAPABILITIES):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
    for row in capabilities.values():
        if not isinstance(row, dict) or set(row) != _CAPABILITY_KEYS:
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
        if row.get("state") not in _ALLOWED_CAPABILITY_STATES or row.get("severity") not in _ALLOWED_SEVERITIES:
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
    return artifact, capabilities


def verify_acceptance_receipt(receipt: dict[str, Any], manifest: dict[str, Any]) -> None:
    candidate = verify_candidate_manifest(manifest)
    artifact, capabilities = _verify_acceptance_shape(receipt)
    if receipt.get("schema") != INSTALLED_ACCEPTANCE_SCHEMA:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_SCHEMA_INVALID")
    if receipt.get("pass") is not True or receipt.get("stage") != "completed":
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_NOT_PASSED")
    if receipt.get("version") != candidate["version"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_VERSION_MISMATCH")
    for key in ("contains_token", "contains_paths", "contains_transcript"):
        if receipt.get(key) is not False:
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_PRIVACY_INVALID")
    assets = candidate["assets"]
    assert isinstance(assets, dict)
    msi = assets["msi"]
    payload = assets["payload_manifest"]
    assert isinstance(msi, dict) and isinstance(payload, dict)
    if artifact.get("version") != candidate["version"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_VERSION_MISMATCH")
    if artifact.get("source_sha") != candidate["source_sha"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_SOURCE_MISMATCH")
    if artifact.get("source_tree_sha") != candidate["source_tree_sha"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_TREE_MISMATCH")
    if artifact.get("msi_sha256") != msi["sha256"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_MSI_MISMATCH")
    if artifact.get("payload_manifest_sha256") != payload["sha256"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_PAYLOAD_MISMATCH")
    for key in ("executable_sha256", "maintenance_helper_sha256"):
        value = artifact.get(key)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_HASH_INVALID")
    for name in _REQUIRED_CAPABILITIES:
        row = capabilities.get(name)
        if not isinstance(row, dict) or row.get("state") != "ready":
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CAPABILITY_NOT_READY")


def build_promotion_evidence(
    *,
    candidate_manifest_path: Path,
    acceptance_receipt_path: Path,
    assets_root: Path,
) -> dict[str, object]:
    candidate = _load_json(candidate_manifest_path, "RELEASE_CANDIDATE_JSON_INVALID")
    verify_candidate_files(candidate, assets_root)
    receipt = _load_json(acceptance_receipt_path, "RELEASE_ACCEPTANCE_JSON_INVALID")
    verify_acceptance_receipt(receipt, candidate)
    version = str(candidate["version"])
    return {
        "schema": PROMOTION_SCHEMA,
        "candidate_tag": candidate["tag"],
        "stable_tag": f"companion-v{version}",
        "version": version,
        "source_sha": candidate["source_sha"],
        "source_tree_sha": candidate["source_tree_sha"],
        "workflow_run_id": candidate["workflow_run_id"],
        "candidate_manifest_sha256": sha256_file(candidate_manifest_path),
        "acceptance_receipt_sha256": sha256_file(acceptance_receipt_path),
        "assets": candidate["assets"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tda_companion.release_evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    candidate = sub.add_parser("candidate-manifest")
    candidate.add_argument("--source-sha", required=True)
    candidate.add_argument("--source-tree-sha", required=True)
    candidate.add_argument("--workflow-run-id", required=True, type=int)
    candidate.add_argument("--msi", required=True, type=Path)
    candidate.add_argument("--checksum", required=True, type=Path)
    candidate.add_argument("--zip", required=True, type=Path)
    candidate.add_argument("--payload-manifest", required=True, type=Path)
    candidate.add_argument("--output", required=True, type=Path)
    promote = sub.add_parser("verify-promotion")
    promote.add_argument("--candidate-manifest", required=True, type=Path)
    promote.add_argument("--acceptance-receipt", required=True, type=Path)
    promote.add_argument("--assets-root", required=True, type=Path)
    promote.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "candidate-manifest":
            manifest = build_candidate_manifest(
                source_sha=args.source_sha,
                source_tree_sha=args.source_tree_sha,
                workflow_run_id=args.workflow_run_id,
                msi_path=args.msi,
                checksum_path=args.checksum,
                zip_path=args.zip,
                payload_manifest_path=args.payload_manifest,
            )
            _atomic_json(args.output, manifest)
            print(str(manifest["tag"]))
            return 0
        evidence = build_promotion_evidence(
            candidate_manifest_path=args.candidate_manifest,
            acceptance_receipt_path=args.acceptance_receipt,
            assets_root=args.assets_root,
        )
        _atomic_json(args.output, evidence)
        print(str(evidence["stable_tag"]))
        return 0
    except ReleaseEvidenceError as exc:
        print(exc.code)
        return 66


if __name__ == "__main__":
    raise SystemExit(main())
