from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from . import VERSION
from .installed_acceptance import REQUIRED_OBSERVATIONS

CANDIDATE_SCHEMA = "tda_companion_candidate_v1"
PROMOTION_SCHEMA = "tda_companion_promotion_v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_SHA = re.compile(r"^[a-f0-9]{40}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RC_TAG = re.compile(r"^companion-rc-v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<prefix>[a-f0-9]{12})$")
_REQUIRED_CAPABILITIES = ("core", "network", "maintenance")


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


def _normalize_source_sha(value: str) -> str:
    normalized = value.strip().casefold()
    if not _SOURCE_SHA.fullmatch(normalized):
        raise ReleaseEvidenceError("RELEASE_SOURCE_SHA_INVALID")
    return normalized


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


def build_candidate_manifest(
    *,
    source_sha: str,
    workflow_run_id: int,
    msi_path: Path,
    checksum_path: Path,
    zip_path: Path,
) -> dict[str, object]:
    source = _normalize_source_sha(source_sha)
    if not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise ReleaseEvidenceError("RELEASE_WORKFLOW_RUN_INVALID")
    if VERSION != str(VERSION) or not _VERSION.fullmatch(VERSION):
        raise ReleaseEvidenceError("RELEASE_VERSION_INVALID")

    if msi_path.name != "TDACompanion-x64.msi":
        raise ReleaseEvidenceError("RELEASE_MSI_NAME_INVALID")
    if checksum_path.name != "TDACompanion-x64.msi.sha256":
        raise ReleaseEvidenceError("RELEASE_CHECKSUM_NAME_INVALID")
    expected_zip = f"TDACompanion-{VERSION}-windows-x64.zip"
    if zip_path.name != expected_zip:
        raise ReleaseEvidenceError("RELEASE_ZIP_NAME_INVALID")

    msi = _asset_record(msi_path)
    checksum = _asset_record(checksum_path)
    zip_asset = _asset_record(zip_path)
    _verify_checksum_file(checksum_path, str(msi["sha256"]))

    return {
        "schema": CANDIDATE_SCHEMA,
        "channel": "rc",
        "tag": _candidate_tag(VERSION, source),
        "version": VERSION,
        "source_sha": source,
        "workflow_run_id": workflow_run_id,
        "assets": {
            "msi": msi,
            "checksum": checksum,
            "zip": zip_asset,
        },
    }


def verify_candidate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != CANDIDATE_SCHEMA or value.get("channel") != "rc":
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_SCHEMA_INVALID")
    version = value.get("version")
    source_sha = value.get("source_sha")
    tag = value.get("tag")
    run_id = value.get("workflow_run_id")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_VERSION_INVALID")
    if version != VERSION:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_VERSION_MISMATCH")
    if not isinstance(source_sha, str):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_SOURCE_INVALID")
    source = _normalize_source_sha(source_sha)
    if tag != _candidate_tag(version, source):
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_TAG_MISMATCH")
    if not isinstance(tag, str) or _RC_TAG.fullmatch(tag) is None:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_TAG_INVALID")
    if not isinstance(run_id, int) or run_id <= 0:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_RUN_INVALID")

    assets = value.get("assets")
    if not isinstance(assets, dict) or set(assets) != {"msi", "checksum", "zip"}:
        raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSETS_INVALID")
    expected_names = {
        "msi": "TDACompanion-x64.msi",
        "checksum": "TDACompanion-x64.msi.sha256",
        "zip": f"TDACompanion-{version}-windows-x64.zip",
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
        if not isinstance(size, int) or size <= 0:
            raise ReleaseEvidenceError("RELEASE_CANDIDATE_ASSET_SIZE_INVALID")
    return value


def verify_candidate_files(manifest: dict[str, Any], assets_root: Path) -> None:
    value = verify_candidate_manifest(manifest)
    assets = value["assets"]
    assert isinstance(assets, dict)
    for key in ("msi", "checksum", "zip"):
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
    assert isinstance(msi, dict)
    checksum = assets["checksum"]
    assert isinstance(checksum, dict)
    _verify_checksum_file(assets_root / str(checksum["name"]), str(msi["sha256"]))


def verify_acceptance_receipt(receipt: dict[str, Any], manifest: dict[str, Any]) -> None:
    candidate = verify_candidate_manifest(manifest)
    if receipt.get("schema") != "tda_installed_acceptance_v1":
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_SCHEMA_INVALID")
    if receipt.get("pass") is not True or receipt.get("stage") != "completed":
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_NOT_PASSED")
    if receipt.get("version") != candidate["version"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_VERSION_MISMATCH")
    for key in ("contains_token", "contains_paths", "contains_transcript"):
        if receipt.get(key) is not False:
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_PRIVACY_INVALID")

    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_INVALID")
    assets = candidate["assets"]
    assert isinstance(assets, dict)
    msi = assets["msi"]
    assert isinstance(msi, dict)
    if artifact.get("version") != candidate["version"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_VERSION_MISMATCH")
    if artifact.get("source_sha") != candidate["source_sha"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_SOURCE_MISMATCH")
    if artifact.get("msi_sha256") != msi["sha256"]:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_MSI_MISMATCH")
    for key in (
        "executable_sha256",
        "maintenance_helper_sha256",
        "craig_zip_sha256",
    ):
        value = artifact.get(key)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_ARTIFACT_HASH_INVALID")
    track_count = artifact.get("craig_track_count")
    if not isinstance(track_count, int) or isinstance(track_count, bool) or track_count < 1:
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CRAIG_TRACKS_INVALID")

    checks = receipt.get("checks")
    if not isinstance(checks, dict):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_CHECKS_INVALID")
    observations = checks.get("observations")
    if not isinstance(observations, dict) or set(observations) != set(REQUIRED_OBSERVATIONS):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_OBSERVATIONS_INVALID")
    if any(observations[name] is not True for name in REQUIRED_OBSERVATIONS):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_OBSERVATIONS_INVALID")

    diagnostics = checks.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
    capabilities = diagnostics.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ReleaseEvidenceError("RELEASE_ACCEPTANCE_DIAGNOSTICS_INVALID")
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
    candidate.add_argument("--workflow-run-id", required=True, type=int)
    candidate.add_argument("--msi", required=True, type=Path)
    candidate.add_argument("--checksum", required=True, type=Path)
    candidate.add_argument("--zip", required=True, type=Path)
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
                workflow_run_id=args.workflow_run_id,
                msi_path=args.msi,
                checksum_path=args.checksum,
                zip_path=args.zip,
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
