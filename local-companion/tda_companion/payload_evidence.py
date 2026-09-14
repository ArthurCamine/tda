from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

PAYLOAD_SCHEMA = "tda_companion_payload_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_FILES = (
    "TDACompanion.exe",
    "TDACompanionMaintenance.exe",
    "run-physical-acceptance.ps1",
    "run-installed-acceptance.ps1",
    "install-rc-runtimes.ps1",
)


class PayloadEvidenceError(RuntimeError):
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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def create_payload_manifest(
    app_root: Path,
    *,
    version: str,
    source_sha: str,
    source_tree_sha: str,
    destination: Path,
) -> dict[str, object]:
    root = app_root.resolve()
    source = source_sha.strip().casefold()
    tree = source_tree_sha.strip().casefold()
    if not _GIT_SHA.fullmatch(source) or not _GIT_SHA.fullmatch(tree):
        raise PayloadEvidenceError("PAYLOAD_SOURCE_IDENTITY_INVALID")
    files: dict[str, dict[str, object]] = {}
    for name in _FILES:
        path = root / name
        if not path.is_file():
            raise PayloadEvidenceError("PAYLOAD_FILE_MISSING")
        files[name] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    value: dict[str, object] = {
        "schema": PAYLOAD_SCHEMA,
        "version": version,
        "source_sha": source,
        "source_tree_sha": tree,
        "files": files,
    }
    _atomic_json(destination.resolve(), value)
    return value


def load_payload_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema", "version", "source_sha", "source_tree_sha", "files"
    }:
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    if value.get("schema") != PAYLOAD_SCHEMA:
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    if not isinstance(value.get("version"), str):
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    if not isinstance(value.get("source_sha"), str) or not _GIT_SHA.fullmatch(str(value["source_sha"])):
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    if not isinstance(value.get("source_tree_sha"), str) or not _GIT_SHA.fullmatch(str(value["source_tree_sha"])):
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(_FILES):
        raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    for name in _FILES:
        row = files.get(name)
        if not isinstance(row, dict) or set(row) != {"sha256", "size"}:
            raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
        if not isinstance(row.get("sha256"), str) or not _SHA256.fullmatch(row["sha256"]):
            raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
        if not isinstance(row.get("size"), int) or isinstance(row.get("size"), bool) or row["size"] <= 0:
            raise PayloadEvidenceError("PAYLOAD_MANIFEST_INVALID")
    return value


def verify_installed_payload(
    app_root: Path,
    manifest_path: Path,
    *,
    expected_version: str,
    expected_source_sha: str,
) -> dict[str, object]:
    root = app_root.resolve()
    manifest = load_payload_manifest(manifest_path)
    if manifest["version"] != expected_version:
        raise PayloadEvidenceError("PAYLOAD_VERSION_MISMATCH")
    if manifest["source_sha"] != expected_source_sha.strip().casefold():
        raise PayloadEvidenceError("PAYLOAD_SOURCE_MISMATCH")
    files = manifest["files"]
    assert isinstance(files, dict)
    observed: dict[str, dict[str, object]] = {}
    for name in _FILES:
        row = files[name]
        assert isinstance(row, dict)
        path = root / name
        if not path.is_file():
            raise PayloadEvidenceError("PAYLOAD_FILE_MISSING")
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != row["size"] or digest != row["sha256"]:
            raise PayloadEvidenceError("PAYLOAD_HASH_MISMATCH")
        observed[name] = {"sha256": digest, "size": size}
    return {
        "schema": PAYLOAD_SCHEMA,
        "source_sha": manifest["source_sha"],
        "source_tree_sha": manifest["source_tree_sha"],
        "manifest_sha256": sha256_file(manifest_path.resolve()),
        "files": observed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    create_payload_manifest(
        args.app_root,
        version=args.version,
        source_sha=args.source_sha,
        source_tree_sha=args.source_tree_sha,
        destination=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
