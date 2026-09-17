from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.rc_runtime_artifacts import (
    RC_QWEN_VERSION,
    RC_WHISPER_VERSION,
    RcRuntimeArtifactError,
    install_rc_runtime_artifact,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact_sha(path: Path) -> str:
    return _sha256(path.read_bytes())


def _runtime_zip(path: Path, worker_name: str, payload: bytes = b"worker") -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(worker_name, payload)
    return path.read_bytes()


def _whisper_actions_artifact(root: Path, *, version: str = RC_WHISPER_VERSION) -> Path:
    runtime = root / f"TDAWhisperRuntime-{version}-windows-x64.zip"
    runtime_bytes = _runtime_zip(runtime, "TDAWhisperWorker.exe")
    digest = _sha256(runtime_bytes)
    artifact = root / "whisper-actions.zip"
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr(runtime.name, runtime_bytes)
        package.writestr(runtime.name + ".sha256", f"{digest}  {runtime.name}")
    return artifact


def _qwen_actions_artifact(root: Path, *, version: str = RC_QWEN_VERSION, tamper_part: bool = False) -> Path:
    runtime = root / f"TDAQwenRuntime-{version}-windows-x64.zip"
    runtime_bytes = _runtime_zip(runtime, "TDAQwenWorker.exe", b"qwen-worker")
    part_name = runtime.name + ".part001"
    manifest = {
        "schema": "tda_qwen_runtime_bundle_v1",
        "runtime_id": "qwen3-transformers",
        "platform": "windows-x64",
        "version": version,
        "archive": {
            "name": runtime.name,
            "size": len(runtime_bytes),
            "sha256": _sha256(runtime_bytes),
        },
        "parts": [
            {
                "index": 1,
                "name": part_name,
                "size": len(runtime_bytes),
                "sha256": _sha256(runtime_bytes),
            }
        ],
    }
    artifact = root / "qwen-actions.zip"
    part_bytes = runtime_bytes + b"tamper" if tamper_part else runtime_bytes
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr(f"TDAQwenRuntimeBundle-{version}-windows-x64.json", json.dumps(manifest))
        package.writestr(part_name, part_bytes)
    return artifact


def _install(family: str, artifact: Path, root: Path) -> dict[str, object]:
    return install_rc_runtime_artifact(
        family,
        artifact,
        expected_artifact_sha256=_artifact_sha(artifact),
        runtime_root=root / "Runtime",
        cache_root=root / "Cache",
    )


def test_rc_versions_match_build_manifests() -> None:
    runtime_root = Path(__file__).resolve().parents[1] / "runtime"
    whisper = json.loads((runtime_root / "whisper-windows-x64.json").read_text(encoding="utf-8"))
    qwen = json.loads((runtime_root / "qwen-windows-x64.json").read_text(encoding="utf-8"))
    assert whisper["version"] == RC_WHISPER_VERSION
    assert qwen["version"] == RC_QWEN_VERSION


def test_install_whisper_actions_artifact_and_reuse(tmp_path: Path) -> None:
    artifact = _whisper_actions_artifact(tmp_path)
    first = _install("whisper", artifact, tmp_path)
    assert first["status"] == "ready"
    assert first["version"] == RC_WHISPER_VERSION
    assert first["reused"] is False
    assert first["repaired"] is False
    assert (tmp_path / "Runtime" / "whisper" / RC_WHISPER_VERSION / "TDAWhisperWorker.exe").is_file()

    second = _install("whisper", artifact, tmp_path)
    assert second == {
        "runtime": "whisper",
        "version": RC_WHISPER_VERSION,
        "status": "ready",
        "reused": True,
    }


def test_whisper_rc_setup_repairs_orphaned_target_directory(tmp_path: Path) -> None:
    artifact = _whisper_actions_artifact(tmp_path)
    orphan = tmp_path / "Runtime" / "whisper" / RC_WHISPER_VERSION
    orphan.mkdir(parents=True)
    (orphan / "TDAWhisperWorker.exe").write_bytes(b"stale")

    result = _install("whisper", artifact, tmp_path)

    assert result["status"] == "ready"
    assert result["repaired"] is True
    assert (orphan / ".tda-runtime.json").is_file()


def test_rejects_unpinned_whisper_runtime(tmp_path: Path) -> None:
    artifact = _whisper_actions_artifact(tmp_path, version="9.9.9")
    with pytest.raises(RcRuntimeArtifactError, match="RC_WHISPER_VERSION_MISMATCH"):
        _install("whisper", artifact, tmp_path)


def test_install_qwen_actions_artifact_and_reuse(tmp_path: Path) -> None:
    artifact = _qwen_actions_artifact(tmp_path)
    first = _install("qwen", artifact, tmp_path)
    assert first["status"] == "ready"
    assert first["version"] == RC_QWEN_VERSION
    assert first["part_count"] == 1
    assert first["reused"] is False
    assert first["repaired"] is False
    assert (tmp_path / "Runtime" / "qwen" / RC_QWEN_VERSION / "TDAQwenWorker.exe").is_file()

    second = _install("qwen", artifact, tmp_path)
    assert second == {
        "runtime": "qwen",
        "version": RC_QWEN_VERSION,
        "status": "ready",
        "reused": True,
    }


def test_qwen_rc_setup_repairs_orphaned_target_directory(tmp_path: Path) -> None:
    artifact = _qwen_actions_artifact(tmp_path)
    orphan = tmp_path / "Runtime" / "qwen" / RC_QWEN_VERSION
    orphan.mkdir(parents=True)
    (orphan / "TDAQwenWorker.exe").write_bytes(b"stale")

    result = _install("qwen", artifact, tmp_path)

    assert result["status"] == "ready"
    assert result["repaired"] is True
    assert (orphan / ".tda-runtime.json").is_file()


def test_rejects_unpinned_qwen_runtime(tmp_path: Path) -> None:
    artifact = _qwen_actions_artifact(tmp_path, version="9.9.9")
    with pytest.raises(RcRuntimeArtifactError, match="RC_QWEN_VERSION_MISMATCH"):
        _install("qwen", artifact, tmp_path)


def test_rejects_tampered_qwen_part(tmp_path: Path) -> None:
    artifact = _qwen_actions_artifact(tmp_path, tamper_part=True)
    with pytest.raises(RcRuntimeArtifactError, match="QWEN_BUNDLE_PART_SIZE_MISMATCH"):
        _install("qwen", artifact, tmp_path)


def test_rejects_outer_actions_artifact_digest_mismatch(tmp_path: Path) -> None:
    artifact = _whisper_actions_artifact(tmp_path)
    with pytest.raises(RcRuntimeArtifactError, match="RC_RUNTIME_ARTIFACT_HASH_MISMATCH"):
        install_rc_runtime_artifact(
            "whisper",
            artifact,
            expected_artifact_sha256="0" * 64,
            runtime_root=tmp_path / "Runtime",
            cache_root=tmp_path / "Cache",
        )


def test_rejects_invalid_outer_actions_artifact_digest(tmp_path: Path) -> None:
    artifact = _whisper_actions_artifact(tmp_path)
    with pytest.raises(RcRuntimeArtifactError, match="RC_RUNTIME_ARTIFACT_HASH_INVALID"):
        install_rc_runtime_artifact(
            "whisper",
            artifact,
            expected_artifact_sha256="nope",
            runtime_root=tmp_path / "Runtime",
            cache_root=tmp_path / "Cache",
        )


def test_rejects_actions_artifact_path_traversal(tmp_path: Path) -> None:
    artifact = tmp_path / "bad-actions.zip"
    with zipfile.ZipFile(artifact, "w") as package:
        package.writestr("../escape.txt", "nope")
    with pytest.raises(RcRuntimeArtifactError, match="RC_RUNTIME_ARTIFACT_PATH_INVALID"):
        _install("whisper", artifact, tmp_path)


def test_rejects_unknown_runtime_family(tmp_path: Path) -> None:
    artifact = tmp_path / "unused.zip"
    with pytest.raises(RcRuntimeArtifactError, match="RC_RUNTIME_FAMILY_INVALID"):
        install_rc_runtime_artifact(
            "other",
            artifact,
            expected_artifact_sha256="0" * 64,
            runtime_root=tmp_path / "Runtime",
            cache_root=tmp_path / "Cache",
        )
