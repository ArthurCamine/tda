from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .runtime_compat import qwen_runtime_version_compatible

RUNTIME_SCHEMA = "tda_asr_runtime_v1"
QWEN_RUNTIME_ID = "qwen3-transformers"
QWEN_WORKER_EXE = "TDAQwenWorker.exe"
MAX_RUNTIME_ARCHIVE_ENTRIES = 16_384
MAX_RUNTIME_UNCOMPRESSED_BYTES = 12 * 1024**3
_COPY_CHUNK = 1024 * 1024
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class QwenRuntimeInstallError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qwen_root(runtime_root: Path) -> Path:
    return runtime_root.resolve() / "qwen"


def qwen_version_root(runtime_root: Path, version: str) -> Path:
    if not _VERSION.fullmatch(version):
        raise QwenRuntimeInstallError("QWEN_RUNTIME_VERSION_INVALID")
    return qwen_root(runtime_root) / version


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    value = info.filename.replace("\\", "/")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_PATH_INVALID")
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_SYMLINK")
    return path


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.partial")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def inspect_qwen_runtime(runtime_root: Path, *, verify_worker: bool = False) -> dict[str, str | None]:
    parent = qwen_root(runtime_root)
    current = parent / "current.json"
    try:
        selector = json.loads(current.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "missing", "version": None, "worker": None}
    except (OSError, json.JSONDecodeError):
        return {"status": "corrupt", "version": None, "worker": None}
    if not isinstance(selector, dict) or selector.get("schema") != RUNTIME_SCHEMA:
        return {"status": "corrupt", "version": None, "worker": None}
    if selector.get("runtime_id") != QWEN_RUNTIME_ID:
        return {"status": "corrupt", "version": None, "worker": None}
    version = selector.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        return {"status": "corrupt", "version": None, "worker": None}
    version_root = parent / version
    marker_path = version_root / ".tda-runtime.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "corrupt", "version": version, "worker": None}
    if (
        not isinstance(marker, dict)
        or marker.get("schema") != RUNTIME_SCHEMA
        or marker.get("runtime_id") != QWEN_RUNTIME_ID
        or marker.get("version") != version
        or marker.get("worker") != QWEN_WORKER_EXE
        or not isinstance(marker.get("worker_sha256"), str)
        or not _SHA256.fullmatch(marker["worker_sha256"])
    ):
        return {"status": "corrupt", "version": version, "worker": None}
    worker = version_root / QWEN_WORKER_EXE
    if not worker.is_file():
        return {"status": "corrupt", "version": version, "worker": None}
    if verify_worker and _sha256_file(worker) != marker["worker_sha256"]:
        return {"status": "corrupt", "version": version, "worker": None}
    if not qwen_runtime_version_compatible(version):
        return {"status": "incompatible", "version": version, "worker": None}
    return {"status": "ready", "version": version, "worker": str(worker.resolve())}


def install_qwen_runtime_archive(
    archive_path: Path,
    runtime_root: Path,
    *,
    version: str,
    expected_sha256: str,
    replace_corrupt: bool = False,
) -> dict[str, str]:
    """Install or atomically repair a prebuilt Qwen worker without global machine changes."""
    archive = archive_path.resolve()
    if not archive.is_file():
        raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_NOT_FOUND")
    if not _VERSION.fullmatch(version):
        raise QwenRuntimeInstallError("QWEN_RUNTIME_VERSION_INVALID")
    if not _SHA256.fullmatch(expected_sha256):
        raise QwenRuntimeInstallError("QWEN_RUNTIME_HASH_INVALID")
    actual_archive_sha = _sha256_file(archive)
    if actual_archive_sha != expected_sha256:
        raise QwenRuntimeInstallError("QWEN_RUNTIME_HASH_MISMATCH")

    target = qwen_version_root(runtime_root, version)
    replacing = target.exists()
    if replacing:
        if not replace_corrupt:
            raise QwenRuntimeInstallError("QWEN_RUNTIME_VERSION_EXISTS")
        current = inspect_qwen_runtime(runtime_root, verify_worker=True)
        if current.get("status") != "corrupt" or current.get("version") != version:
            raise QwenRuntimeInstallError("QWEN_RUNTIME_REPAIR_NOT_ALLOWED")

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{version}-{uuid4().hex}.partial"
    staging.mkdir(parents=False, exist_ok=False)
    backup: Path | None = None
    promoted = False

    try:
        try:
            package = zipfile.ZipFile(archive, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_INVALID") from exc
        with package:
            infos = [item for item in package.infolist() if not item.is_dir()]
            if not infos or len(infos) > MAX_RUNTIME_ARCHIVE_ENTRIES:
                raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_ENTRY_LIMIT")
            total = 0
            seen: set[str] = set()
            for info in infos:
                relative = _safe_member(info)
                key = relative.as_posix().casefold()
                if key in seen:
                    raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_DUPLICATE")
                seen.add(key)
                if info.file_size < 0:
                    raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_SIZE_INVALID")
                total += info.file_size
                if total > MAX_RUNTIME_UNCOMPRESSED_BYTES:
                    raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_SIZE_LIMIT")
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with package.open(info, "r") as source, destination.open("wb") as output:
                    while True:
                        chunk = source.read(_COPY_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:
                            raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_SIZE_MISMATCH")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if written != info.file_size:
                    raise QwenRuntimeInstallError("QWEN_RUNTIME_ARCHIVE_SIZE_MISMATCH")

        worker = staging / QWEN_WORKER_EXE
        if not worker.is_file():
            raise QwenRuntimeInstallError("QWEN_RUNTIME_WORKER_MISSING")
        worker_sha = _sha256_file(worker)
        marker = {
            "schema": RUNTIME_SCHEMA,
            "runtime_id": QWEN_RUNTIME_ID,
            "version": version,
            "worker": QWEN_WORKER_EXE,
            "worker_sha256": worker_sha,
            "archive_sha256": actual_archive_sha,
        }
        _atomic_json(staging / ".tda-runtime.json", marker)

        if replacing:
            backup = parent / f".{version}-{uuid4().hex}.backup"
            os.replace(target, backup)
        try:
            os.replace(staging, target)
            promoted = True
            _atomic_json(
                parent / "current.json",
                {
                    "schema": RUNTIME_SCHEMA,
                    "runtime_id": QWEN_RUNTIME_ID,
                    "version": version,
                },
            )
        except BaseException:
            if promoted:
                shutil.rmtree(target, ignore_errors=True)
            if backup is not None and backup.exists():
                os.replace(backup, target)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return marker
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def current_qwen_worker(runtime_root: Path) -> Path | None:
    # Supervisor execution is an integrity and compatibility boundary: never
    # return a worker until its bytes and minimum runtime version are accepted.
    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    worker = state.get("worker")
    return Path(worker) if state.get("status") == "ready" and isinstance(worker, str) else None
