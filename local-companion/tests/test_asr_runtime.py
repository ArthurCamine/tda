from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.asr_runtime import (
    AsrRuntimeError,
    current_whisper_worker,
    inspect_whisper_runtime,
    install_whisper_runtime_archive,
)
from tda_companion.runtime_compat import MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION


def _runtime_zip(path: Path, *, member: str = "TDAWhisperWorker.exe", payload: bytes = b"worker") -> str:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(member, payload)
        archive.writestr("_internal/runtime.dll", b"dll")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_runtime_installs_versioned_and_switches_current_atomically(tmp_path: Path):
    archive = tmp_path / "runtime.zip"
    digest = _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION

    marker = install_whisper_runtime_archive(
        archive,
        runtime_root,
        version=version,
        expected_sha256=digest,
    )

    worker = runtime_root / "whisper" / version / "TDAWhisperWorker.exe"
    assert worker.read_bytes() == b"worker"
    assert marker["archive_sha256"] == digest
    state = inspect_whisper_runtime(runtime_root, verify_worker=True)
    assert state["status"] == "ready"
    assert state["version"] == version
    assert current_whisper_worker(runtime_root) == worker.resolve()
    selector = json.loads((runtime_root / "whisper" / "current.json").read_text(encoding="utf-8"))
    assert selector["version"] == version


def test_pre_runs_whisper_runtime_is_valid_but_incompatible(tmp_path: Path):
    archive = tmp_path / "runtime-old.zip"
    digest = _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    install_whisper_runtime_archive(
        archive,
        runtime_root,
        version="1.1.1",
        expected_sha256=digest,
    )

    state = inspect_whisper_runtime(runtime_root, verify_worker=True)
    assert state == {"status": "incompatible", "version": "1.1.1", "worker": None}
    assert current_whisper_worker(runtime_root) is None


def test_runtime_archive_hash_mismatch_does_not_materialize_runtime(tmp_path: Path):
    archive = tmp_path / "runtime.zip"
    _runtime_zip(archive)
    runtime_root = tmp_path / "Runtime"
    with pytest.raises(AsrRuntimeError, match="ASR_RUNTIME_HASH_MISMATCH"):
        install_whisper_runtime_archive(
            archive,
            runtime_root,
            version="1.0.0",
            expected_sha256="0" * 64,
        )
    assert inspect_whisper_runtime(runtime_root)["status"] == "missing"


def test_runtime_archive_rejects_path_traversal_and_symlink_like_entries(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    digest = _runtime_zip(archive, member="../TDAWhisperWorker.exe")
    with pytest.raises(AsrRuntimeError, match="ASR_RUNTIME_ARCHIVE_PATH_INVALID"):
        install_whisper_runtime_archive(
            archive,
            tmp_path / "Runtime",
            version="1.0.0",
            expected_sha256=digest,
        )


def test_runtime_requires_expected_worker_and_detects_worker_tamper(tmp_path: Path):
    archive = tmp_path / "wrong.zip"
    digest = _runtime_zip(archive, member="something.exe")
    runtime_root = tmp_path / "Runtime"
    with pytest.raises(AsrRuntimeError, match="ASR_RUNTIME_WORKER_MISSING"):
        install_whisper_runtime_archive(
            archive,
            runtime_root,
            version="1.0.0",
            expected_sha256=digest,
        )

    good = tmp_path / "good.zip"
    good_digest = _runtime_zip(good)
    version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
    install_whisper_runtime_archive(
        good,
        runtime_root,
        version=version,
        expected_sha256=good_digest,
    )
    worker = runtime_root / "whisper" / version / "TDAWhisperWorker.exe"
    worker.write_bytes(b"tampered")
    assert inspect_whisper_runtime(runtime_root, verify_worker=True)["status"] == "corrupt"
