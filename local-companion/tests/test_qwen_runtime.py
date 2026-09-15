from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.qwen_runtime import (
    QwenRuntimeInstallError,
    current_qwen_worker,
    inspect_qwen_runtime,
    install_qwen_runtime_archive,
)
from tda_companion.runtime_compat import MIN_COMPATIBLE_QWEN_RUNTIME_VERSION


def _runtime_zip(path: Path, *, member: str = "TDAQwenWorker.exe", payload: bytes = b"worker") -> str:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.writestr(member, payload)
        archive.writestr("_internal/torch.dll", b"dll")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_qwen_runtime_installs_versioned_and_switches_current_atomically(tmp_path: Path):
    archive = tmp_path / "runtime.zip"
    digest = _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION

    marker = install_qwen_runtime_archive(
        archive,
        runtime_root,
        version=version,
        expected_sha256=digest,
    )

    worker = runtime_root / "qwen" / version / "TDAQwenWorker.exe"
    assert worker.read_bytes() == b"worker"
    assert marker["archive_sha256"] == digest
    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    assert state["status"] == "ready"
    assert state["version"] == version
    assert current_qwen_worker(runtime_root) == worker.resolve()
    selector = json.loads((runtime_root / "qwen" / "current.json").read_text(encoding="utf-8"))
    assert selector["version"] == version


def test_pre_runs_qwen_runtime_is_valid_but_incompatible(tmp_path: Path):
    archive = tmp_path / "runtime-old.zip"
    digest = _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    install_qwen_runtime_archive(
        archive,
        runtime_root,
        version="1.0.1",
        expected_sha256=digest,
    )

    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    assert state == {"status": "incompatible", "version": "1.0.1", "worker": None}
    assert current_qwen_worker(runtime_root) is None


def test_qwen_runtime_hash_mismatch_does_not_materialize_runtime(tmp_path: Path):
    archive = tmp_path / "runtime.zip"
    _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    with pytest.raises(QwenRuntimeInstallError, match="QWEN_RUNTIME_HASH_MISMATCH"):
        install_qwen_runtime_archive(
            archive,
            runtime_root,
            version="1.0.0",
            expected_sha256="0" * 64,
        )
    assert inspect_qwen_runtime(runtime_root)["status"] == "missing"


def test_qwen_runtime_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    digest = _runtime_zip(archive, member="../TDAQwenWorker.exe")
    with pytest.raises(QwenRuntimeInstallError, match="QWEN_RUNTIME_ARCHIVE_PATH_INVALID"):
        install_qwen_runtime_archive(
            archive,
            tmp_path / "Runtime",
            version="1.0.0",
            expected_sha256=digest,
        )


def test_qwen_runtime_requires_expected_worker_and_detects_tamper(tmp_path: Path):
    archive = tmp_path / "wrong.zip"
    digest = _runtime_zip(archive, member="something.exe")
    runtime_root = tmp_path / "Runtime"
    with pytest.raises(QwenRuntimeInstallError, match="QWEN_RUNTIME_WORKER_MISSING"):
        install_qwen_runtime_archive(
            archive,
            runtime_root,
            version="1.0.0",
            expected_sha256=digest,
        )

    good = tmp_path / "good.zip"
    good_digest = _runtime_zip(good)
    version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
    install_qwen_runtime_archive(
        good,
        runtime_root,
        version=version,
        expected_sha256=good_digest,
    )
    worker = runtime_root / "qwen" / version / "TDAQwenWorker.exe"
    worker.write_bytes(b"tampered")
    assert inspect_qwen_runtime(runtime_root, verify_worker=True)["status"] == "corrupt"
    assert current_qwen_worker(runtime_root) is None


def test_qwen_runtime_can_atomically_repair_corrupt_current_version(tmp_path: Path):
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
    first = tmp_path / "first.zip"
    first_digest = _runtime_zip(first, payload=b"worker-v1-corrupt-me")
    install_qwen_runtime_archive(
        first,
        runtime_root,
        version=version,
        expected_sha256=first_digest,
    )
    worker = runtime_root / "qwen" / version / "TDAQwenWorker.exe"
    worker.write_bytes(b"tampered")
    assert inspect_qwen_runtime(runtime_root, verify_worker=True)["status"] == "corrupt"

    replacement = tmp_path / "replacement.zip"
    replacement_digest = _runtime_zip(replacement, payload=b"worker-v1-repaired")
    marker = install_qwen_runtime_archive(
        replacement,
        runtime_root,
        version=version,
        expected_sha256=replacement_digest,
        replace_corrupt=True,
    )

    assert worker.read_bytes() == b"worker-v1-repaired"
    assert marker["archive_sha256"] == replacement_digest
    state = inspect_qwen_runtime(runtime_root, verify_worker=True)
    assert state["status"] == "ready"
    assert state["version"] == version
    assert not list((runtime_root / "qwen").glob("*.backup"))
    assert not list((runtime_root / "qwen").glob("*.partial"))


def test_qwen_runtime_refuses_repair_of_healthy_current_version(tmp_path: Path):
    runtime_root = tmp_path / "Runtime"
    archive = tmp_path / "runtime.zip"
    digest = _runtime_zip(archive)
    version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
    install_qwen_runtime_archive(
        archive,
        runtime_root,
        version=version,
        expected_sha256=digest,
    )

    with pytest.raises(QwenRuntimeInstallError, match="QWEN_RUNTIME_REPAIR_NOT_ALLOWED"):
        install_qwen_runtime_archive(
            archive,
            runtime_root,
            version=version,
            expected_sha256=digest,
            replace_corrupt=True,
        )
