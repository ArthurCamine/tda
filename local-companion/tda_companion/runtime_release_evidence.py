from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .asr_runtime import WHISPER_RUNTIME_ID, inspect_whisper_runtime, whisper_version_root
from .qwen_physical_gate import GATE_SCHEMA as QWEN_GATE_SCHEMA
from .qwen_runtime import QWEN_RUNTIME_ID, inspect_qwen_runtime, qwen_version_root
from .qwen_runtime_bundle import parse_qwen_runtime_bundle_manifest

CANDIDATE_SCHEMA = "tda_runtime_candidate_v1"
ACCEPTANCE_SCHEMA = "tda_runtime_physical_acceptance_v1"
PROMOTION_SCHEMA = "tda_runtime_promotion_v1"
PLATFORM = "windows-x64"
WHISPER_ACCEPTANCE_SCHEMA = "tda_whisper_gpu_acceptance_v1"
WHISPER_PROFILES = ("whisper-turbo", "whisper-detailed")
QWEN_PROFILES = ("qwen-fast", "qwen-quality")
MAX_JSON_BYTES = 512 * 1024
_COPY_CHUNK = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_WHISPER_ARCHIVE_RE = re.compile(r"^TDAWhisperRuntime-([0-9]+\.[0-9]+\.[0-9]+)-windows-x64\.zip$")
_QWEN_BUNDLE_RE = re.compile(r"^TDAQwenRuntimeBundle-([0-9]+\.[0-9]+\.[0-9]+)-windows-x64\.json$")


class RuntimeReleaseEvidenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.partial")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        stat = path.stat()
        if stat.st_size <= 0 or stat.st_size > MAX_JSON_BYTES:
            raise RuntimeReleaseEvidenceError(code)
        value = json.loads(path.read_text(encoding="utf-8"))
    except RuntimeReleaseEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeReleaseEvidenceError(code) from exc
    if not isinstance(value, dict):
        raise RuntimeReleaseEvidenceError(code)
    return value


def _require_sha(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RuntimeReleaseEvidenceError(code)
    return value


def _require_source(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SOURCE_RE.fullmatch(value):
        raise RuntimeReleaseEvidenceError(code)
    return value


def _require_version(value: object, code: str) -> str:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise RuntimeReleaseEvidenceError(code)
    return value


def _one(root: Path, pattern: str, code: str) -> Path:
    matches = sorted(path for path in root.rglob(pattern) if path.is_file())
    if len(matches) != 1:
        raise RuntimeReleaseEvidenceError(code)
    return matches[0]


def _asset(path: Path) -> dict[str, object]:
    stat = path.stat()
    if stat.st_size <= 0:
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSET_EMPTY")
    return {"name": path.name, "size": stat.st_size, "sha256": _sha256_file(path)}


def _candidate_tags(family: str, version: str, source_sha: str) -> tuple[str, str]:
    if family == "whisper":
        return (
            f"companion-whisper-runtime-rc-v{version}-{source_sha[:12]}",
            f"companion-whisper-runtime-v{version}",
        )
    if family == "qwen":
        return (
            f"companion-qwen-runtime-rc-v{version}-{source_sha[:12]}",
            f"companion-qwen-runtime-v{version}",
        )
    raise RuntimeReleaseEvidenceError("RUNTIME_FAMILY_INVALID")


def _create_whisper_candidate(root: Path) -> tuple[str, str, str, list[dict[str, object]]]:
    archive = _one(root, "TDAWhisperRuntime-*-windows-x64.zip", "RUNTIME_WHISPER_ARCHIVE_AMBIGUOUS")
    match = _WHISPER_ARCHIVE_RE.fullmatch(archive.name)
    if match is None:
        raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_ARCHIVE_NAME_INVALID")
    version = match.group(1)
    sidecar = archive.with_name(archive.name + ".sha256")
    try:
        parts = sidecar.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeError) as exc:
        raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_DIGEST_MISSING") from exc
    if len(parts) != 2 or parts[1] != archive.name:
        raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_DIGEST_INVALID")
    expected = _require_sha(parts[0], "RUNTIME_WHISPER_DIGEST_INVALID")
    archive_asset = _asset(archive)
    if archive_asset["sha256"] != expected:
        raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_DIGEST_MISMATCH")
    return version, WHISPER_RUNTIME_ID, expected, [archive_asset, _asset(sidecar)]


def _create_qwen_candidate(root: Path) -> tuple[str, str, str, list[dict[str, object]]]:
    manifest_path = _one(root, "TDAQwenRuntimeBundle-*-windows-x64.json", "RUNTIME_QWEN_BUNDLE_AMBIGUOUS")
    match = _QWEN_BUNDLE_RE.fullmatch(manifest_path.name)
    if match is None:
        raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_BUNDLE_NAME_INVALID")
    raw = _read_json(manifest_path, "RUNTIME_QWEN_BUNDLE_INVALID")
    try:
        manifest = parse_qwen_runtime_bundle_manifest(raw)
    except Exception as exc:
        raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_BUNDLE_INVALID") from exc
    version = match.group(1)
    if manifest.version != version or manifest.runtime_id != QWEN_RUNTIME_ID:
        raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_BUNDLE_IDENTITY_MISMATCH")
    assets = [_asset(manifest_path)]
    for part in manifest.parts:
        path = manifest_path.parent / part.name
        if not path.is_file():
            raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_PART_MISSING")
        value = _asset(path)
        if value["size"] != part.size or value["sha256"] != part.sha256:
            raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_PART_MISMATCH")
        assets.append(value)
    return version, QWEN_RUNTIME_ID, manifest.archive_sha256, assets


def create_candidate(
    family: str,
    assets_root: Path,
    *,
    source_sha: str,
    source_tree_sha: str,
    workflow_run_id: int,
) -> dict[str, Any]:
    source = _require_source(source_sha, "RUNTIME_SOURCE_SHA_INVALID")
    tree = _require_source(source_tree_sha, "RUNTIME_SOURCE_TREE_SHA_INVALID")
    if isinstance(workflow_run_id, bool) or not isinstance(workflow_run_id, int) or workflow_run_id <= 0:
        raise RuntimeReleaseEvidenceError("RUNTIME_WORKFLOW_RUN_ID_INVALID")
    root = assets_root.resolve()
    if family == "whisper":
        version, runtime_id, archive_sha, assets = _create_whisper_candidate(root)
    elif family == "qwen":
        version, runtime_id, archive_sha, assets = _create_qwen_candidate(root)
    else:
        raise RuntimeReleaseEvidenceError("RUNTIME_FAMILY_INVALID")
    candidate_tag, stable_tag = _candidate_tags(family, version, source)
    return {
        "schema": CANDIDATE_SCHEMA,
        "family": family,
        "runtime_id": runtime_id,
        "platform": PLATFORM,
        "version": version,
        "source_sha": source,
        "source_tree_sha": tree,
        "workflow_run_id": workflow_run_id,
        "candidate_tag": candidate_tag,
        "stable_tag": stable_tag,
        "runtime_archive_sha256": archive_sha,
        "assets": assets,
    }


def _parse_candidate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != CANDIDATE_SCHEMA:
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_INVALID")
    family = value.get("family")
    if family not in {"whisper", "qwen"}:
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_FAMILY_INVALID")
    version = _require_version(value.get("version"), "RUNTIME_CANDIDATE_VERSION_INVALID")
    source = _require_source(value.get("source_sha"), "RUNTIME_CANDIDATE_SOURCE_INVALID")
    _require_source(value.get("source_tree_sha"), "RUNTIME_CANDIDATE_TREE_INVALID")
    archive_sha = _require_sha(value.get("runtime_archive_sha256"), "RUNTIME_CANDIDATE_ARCHIVE_HASH_INVALID")
    runtime_id = WHISPER_RUNTIME_ID if family == "whisper" else QWEN_RUNTIME_ID
    candidate_tag, stable_tag = _candidate_tags(family, version, source)
    if (
        value.get("runtime_id") != runtime_id
        or value.get("platform") != PLATFORM
        or value.get("candidate_tag") != candidate_tag
        or value.get("stable_tag") != stable_tag
        or archive_sha != value.get("runtime_archive_sha256")
    ):
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_IDENTITY_MISMATCH")
    assets = value.get("assets")
    if not isinstance(assets, list) or not assets:
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSETS_INVALID")
    seen: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSETS_INVALID")
        name = item.get("name")
        size = item.get("size")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name.casefold() in seen
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSETS_INVALID")
        seen.add(name.casefold())
        _require_sha(item.get("sha256"), "RUNTIME_CANDIDATE_ASSET_HASH_INVALID")
    return value


def verify_candidate_assets(candidate: object, assets_root: Path) -> None:
    value = _parse_candidate(candidate)
    root = assets_root.resolve()
    for item in value["assets"]:
        path = root / item["name"]
        if not path.is_file():
            raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSET_MISSING")
        stat = path.stat()
        if stat.st_size != item["size"] or _sha256_file(path) != item["sha256"]:
            raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_ASSET_MISMATCH")


def _runtime_marker(family: str, runtime_root: Path, version: str) -> dict[str, Any]:
    if family == "whisper":
        state = inspect_whisper_runtime(runtime_root, verify_worker=True)
        marker_path = whisper_version_root(runtime_root, version) / ".tda-runtime.json"
        runtime_id = WHISPER_RUNTIME_ID
    else:
        state = inspect_qwen_runtime(runtime_root, verify_worker=True)
        marker_path = qwen_version_root(runtime_root, version) / ".tda-runtime.json"
        runtime_id = QWEN_RUNTIME_ID
    if state.get("status") != "ready" or state.get("version") != version:
        raise RuntimeReleaseEvidenceError("RUNTIME_PHYSICAL_RUNTIME_NOT_READY")
    marker = _read_json(marker_path, "RUNTIME_PHYSICAL_MARKER_INVALID")
    if marker.get("runtime_id") != runtime_id or marker.get("version") != version:
        raise RuntimeReleaseEvidenceError("RUNTIME_PHYSICAL_MARKER_INVALID")
    _require_sha(marker.get("worker_sha256"), "RUNTIME_PHYSICAL_MARKER_INVALID")
    _require_sha(marker.get("archive_sha256"), "RUNTIME_PHYSICAL_MARKER_INVALID")
    return marker


def _receipt_digest(path: Path) -> tuple[dict[str, Any], str]:
    value = _read_json(path, "RUNTIME_PHYSICAL_EVIDENCE_INVALID")
    return value, _sha256_file(path)


def _seal_whisper(candidate: dict[str, Any], evidence_paths: Iterable[Path]) -> list[dict[str, Any]]:
    by_profile: dict[str, dict[str, Any]] = {}
    for path in evidence_paths:
        receipt, digest = _receipt_digest(path)
        profile = receipt.get("profile_id")
        if profile not in WHISPER_PROFILES or profile in by_profile:
            raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_EVIDENCE_PROFILE_INVALID")
        gpu = receipt.get("gpu") if isinstance(receipt.get("gpu"), dict) else {}
        inference = receipt.get("inference") if isinstance(receipt.get("inference"), dict) else {}
        if (
            receipt.get("schema") != WHISPER_ACCEPTANCE_SCHEMA
            or receipt.get("pass") is not True
            or receipt.get("model_integrity") != "sha256-full"
            or not _SHA256_RE.fullmatch(str(receipt.get("model_content_sha256") or ""))
            or gpu.get("required_name_match") is not True
            or inference.get("device") != "cuda"
        ):
            raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_EVIDENCE_INVALID")
        by_profile[str(profile)] = {
            "profile_id": profile,
            "receipt_sha256": digest,
            "gpu_name": str(gpu.get("name") or "")[:160],
            "model_content_sha256": str(receipt["model_content_sha256"]),
            "rtf": float(inference.get("rtf") or 0.0),
        }
    if tuple(sorted(by_profile)) != tuple(sorted(WHISPER_PROFILES)):
        raise RuntimeReleaseEvidenceError("RUNTIME_WHISPER_EVIDENCE_INCOMPLETE")
    return [by_profile[profile] for profile in WHISPER_PROFILES]


def _seal_qwen(candidate: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for profile in QWEN_PROFILES:
        path = state_root.resolve() / "qwen-physical-gates" / f"{profile}.json"
        gate, digest = _receipt_digest(path)
        runtime = gate.get("runtime") if isinstance(gate.get("runtime"), dict) else {}
        gpu = gate.get("gpu") if isinstance(gate.get("gpu"), dict) else {}
        if (
            gate.get("schema") != QWEN_GATE_SCHEMA
            or gate.get("profile_id") != profile
            or runtime.get("runtime_id") != QWEN_RUNTIME_ID
            or runtime.get("version") != candidate["version"]
            or runtime.get("archive_sha256") != candidate["runtime_archive_sha256"]
            or not _SHA256_RE.fullmatch(str(gate.get("binding_sha256") or ""))
            or not _SHA256_RE.fullmatch(str(gate.get("acceptance_sha256") or ""))
        ):
            raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_EVIDENCE_INVALID")
        result.append(
            {
                "profile_id": profile,
                "gate_sha256": digest,
                "binding_sha256": gate["binding_sha256"],
                "acceptance_sha256": gate["acceptance_sha256"],
                "gpu_name": str(gpu.get("name") or "")[:160],
            }
        )
    return result


def seal_physical(
    candidate: object,
    runtime_root: Path,
    *,
    whisper_receipts: Iterable[Path] = (),
    qwen_state_root: Path | None = None,
) -> dict[str, Any]:
    value = _parse_candidate(candidate)
    marker = _runtime_marker(value["family"], runtime_root.resolve(), value["version"])
    if marker.get("archive_sha256") != value["runtime_archive_sha256"]:
        raise RuntimeReleaseEvidenceError("RUNTIME_PHYSICAL_ARCHIVE_MISMATCH")
    if value["family"] == "whisper":
        profiles = _seal_whisper(value, whisper_receipts)
    else:
        if qwen_state_root is None:
            raise RuntimeReleaseEvidenceError("RUNTIME_QWEN_STATE_ROOT_REQUIRED")
        profiles = _seal_qwen(value, qwen_state_root)
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "pass": True,
        "family": value["family"],
        "runtime_id": value["runtime_id"],
        "platform": PLATFORM,
        "version": value["version"],
        "candidate_tag": value["candidate_tag"],
        "stable_tag": value["stable_tag"],
        "source_sha": value["source_sha"],
        "source_tree_sha": value["source_tree_sha"],
        "candidate_manifest_sha256": _sha256_json(value),
        "runtime_archive_sha256": value["runtime_archive_sha256"],
        "worker_sha256": marker["worker_sha256"],
        "accepted_at": _utc_now(),
        "profiles": profiles,
        "contains_audio": False,
        "contains_transcript": False,
        "contains_local_paths": False,
    }


def verify_promotion(candidate: object, acceptance: object, assets_root: Path) -> dict[str, Any]:
    value = _parse_candidate(candidate)
    if not isinstance(acceptance, dict) or acceptance.get("schema") != ACCEPTANCE_SCHEMA or acceptance.get("pass") is not True:
        raise RuntimeReleaseEvidenceError("RUNTIME_PROMOTION_ACCEPTANCE_INVALID")
    expected_fields = (
        "family",
        "runtime_id",
        "platform",
        "version",
        "candidate_tag",
        "stable_tag",
        "source_sha",
        "source_tree_sha",
        "runtime_archive_sha256",
    )
    for field in expected_fields:
        if acceptance.get(field) != value.get(field):
            raise RuntimeReleaseEvidenceError("RUNTIME_PROMOTION_IDENTITY_MISMATCH")
    if acceptance.get("candidate_manifest_sha256") != _sha256_json(value):
        raise RuntimeReleaseEvidenceError("RUNTIME_PROMOTION_CANDIDATE_HASH_MISMATCH")
    if acceptance.get("contains_audio") is not False or acceptance.get("contains_transcript") is not False:
        raise RuntimeReleaseEvidenceError("RUNTIME_PROMOTION_PRIVATE_EVIDENCE_REJECTED")
    profiles = acceptance.get("profiles")
    expected_profiles = WHISPER_PROFILES if value["family"] == "whisper" else QWEN_PROFILES
    if not isinstance(profiles, list) or [item.get("profile_id") for item in profiles if isinstance(item, dict)] != list(expected_profiles):
        raise RuntimeReleaseEvidenceError("RUNTIME_PROMOTION_PROFILE_EVIDENCE_INVALID")
    verify_candidate_assets(value, assets_root)
    return {
        "schema": PROMOTION_SCHEMA,
        "candidate_tag": value["candidate_tag"],
        "stable_tag": value["stable_tag"],
        "family": value["family"],
        "version": value["version"],
        "source_sha": value["source_sha"],
        "source_tree_sha": value["source_tree_sha"],
        "runtime_archive_sha256": value["runtime_archive_sha256"],
        "candidate_manifest_sha256": _sha256_json(value),
        "acceptance_receipt_sha256": _sha256_json(acceptance),
        "assets": value["assets"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runtime-release-evidence")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-candidate")
    create.add_argument("--family", required=True, choices=("whisper", "qwen"))
    create.add_argument("--assets-root", type=Path, required=True)
    create.add_argument("--source-sha", required=True)
    create.add_argument("--source-tree-sha", required=True)
    create.add_argument("--workflow-run-id", type=int, required=True)
    create.add_argument("--output", type=Path, required=True)

    seal = sub.add_parser("seal-physical")
    seal.add_argument("--candidate-manifest", type=Path, required=True)
    seal.add_argument("--runtime-root", type=Path, required=True)
    seal.add_argument("--whisper-receipt", type=Path, action="append", default=[])
    seal.add_argument("--qwen-state-root", type=Path)
    seal.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify-promotion")
    verify.add_argument("--candidate-manifest", type=Path, required=True)
    verify.add_argument("--acceptance-receipt", type=Path, required=True)
    verify.add_argument("--assets-root", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "create-candidate":
        value = create_candidate(
            args.family,
            args.assets_root,
            source_sha=args.source_sha,
            source_tree_sha=args.source_tree_sha,
            workflow_run_id=args.workflow_run_id,
        )
        _atomic_json(args.output.resolve(), value)
        print(value["candidate_tag"])
        return 0
    if args.command == "seal-physical":
        candidate = _read_json(args.candidate_manifest.resolve(), "RUNTIME_CANDIDATE_INVALID")
        value = seal_physical(
            candidate,
            args.runtime_root,
            whisper_receipts=args.whisper_receipt,
            qwen_state_root=args.qwen_state_root,
        )
        _atomic_json(args.output.resolve(), value)
        print(value["candidate_tag"])
        return 0
    candidate = _read_json(args.candidate_manifest.resolve(), "RUNTIME_CANDIDATE_INVALID")
    acceptance = _read_json(args.acceptance_receipt.resolve(), "RUNTIME_PROMOTION_ACCEPTANCE_INVALID")
    value = verify_promotion(candidate, acceptance, args.assets_root)
    _atomic_json(args.output.resolve(), value)
    print(value["stable_tag"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
