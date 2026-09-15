from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tda_companion.asr_runtime import WHISPER_RUNTIME_ID
from tda_companion.qwen_physical_gate import GATE_SCHEMA as QWEN_GATE_SCHEMA
from tda_companion.qwen_runtime import QWEN_RUNTIME_ID
from tda_companion.runtime_compat import (
    MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
    MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
)
from tda_companion.runtime_release_evidence import (
    ACCEPTANCE_SCHEMA,
    RuntimeReleaseEvidenceError,
    create_candidate,
    seal_physical,
    verify_promotion,
)

SOURCE_SHA = "1" * 40
TREE_SHA = "2" * 40


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _whisper_assets(
    root: Path,
    *,
    version: str = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    archive = root / f"TDAWhisperRuntime-{version}-windows-x64.zip"
    archive.write_bytes(b"whisper-runtime")
    digest = _sha(archive.read_bytes())
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive, digest


def _qwen_assets(
    root: Path,
    *,
    version: str = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    part_name = f"TDAQwenRuntime-{version}-windows-x64.zip.part001"
    part = root / part_name
    part.write_bytes(b"qwen-runtime")
    archive_sha = _sha(part.read_bytes())
    manifest = {
        "schema": "tda_qwen_runtime_bundle_v1",
        "runtime_id": QWEN_RUNTIME_ID,
        "platform": "windows-x64",
        "version": version,
        "archive": {
            "name": f"TDAQwenRuntime-{version}-windows-x64.zip",
            "size": part.stat().st_size,
            "sha256": archive_sha,
        },
        "parts": [{"index": 1, "name": part_name, "size": part.stat().st_size, "sha256": archive_sha}],
    }
    manifest_path = root / f"TDAQwenRuntimeBundle-{version}-windows-x64.json"
    _json(manifest_path, manifest)
    return manifest_path, archive_sha


def _runtime_marker(root: Path, family: str, version: str, archive_sha: str) -> None:
    worker_name = "TDAWhisperWorker.exe" if family == "whisper" else "TDAQwenWorker.exe"
    runtime_id = WHISPER_RUNTIME_ID if family == "whisper" else QWEN_RUNTIME_ID
    base = root / family
    version_root = base / version
    version_root.mkdir(parents=True)
    worker = version_root / worker_name
    worker.write_bytes(b"worker")
    worker_sha = _sha(worker.read_bytes())
    _json(
        version_root / ".tda-runtime.json",
        {
            "schema": "tda_asr_runtime_v1",
            "runtime_id": runtime_id,
            "version": version,
            "worker": worker_name,
            "worker_sha256": worker_sha,
            "archive_sha256": archive_sha,
        },
    )
    _json(base / "current.json", {"schema": "tda_asr_runtime_v1", "runtime_id": runtime_id, "version": version})


def _whisper_receipt(path: Path, profile: str) -> Path:
    _json(
        path,
        {
            "schema": "tda_whisper_gpu_acceptance_v1",
            "pass": True,
            "profile_id": profile,
            "model_content_sha256": "a" * 64,
            "model_integrity": "sha256-full",
            "gpu": {"name": "NVIDIA GeForce RTX 4070 Laptop GPU", "required_name_match": True},
            "inference": {"device": "cuda", "rtf": 0.4},
        },
    )
    return path


def _qwen_gate(path: Path, profile: str, version: str, archive_sha: str) -> None:
    _json(
        path,
        {
            "schema": QWEN_GATE_SCHEMA,
            "profile_id": profile,
            "runtime": {
                "runtime_id": QWEN_RUNTIME_ID,
                "version": version,
                "worker_sha256": "b" * 64,
                "archive_sha256": archive_sha,
            },
            "binding_sha256": "c" * 64,
            "acceptance_sha256": "d" * 64,
            "gpu": {"name": "NVIDIA GeForce RTX 4070 Laptop GPU"},
        },
    )


def test_whisper_candidate_binds_exact_archive_and_sidecar(tmp_path: Path) -> None:
    archive, digest = _whisper_assets(tmp_path)
    candidate = create_candidate(
        "whisper",
        tmp_path,
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=123,
    )

    version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
    assert candidate["runtime_archive_sha256"] == digest
    assert candidate["candidate_tag"] == f"companion-whisper-runtime-rc-v{version}-{SOURCE_SHA[:12]}"
    assert candidate["stable_tag"] == f"companion-whisper-runtime-v{version}"
    assert {item["name"] for item in candidate["assets"]} == {archive.name, archive.name + ".sha256"}


def test_whisper_candidate_rejects_forged_sidecar(tmp_path: Path) -> None:
    archive, _digest = _whisper_assets(tmp_path)
    archive.with_name(archive.name + ".sha256").write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_WHISPER_DIGEST_MISMATCH"):
        create_candidate("whisper", tmp_path, source_sha=SOURCE_SHA, source_tree_sha=TREE_SHA, workflow_run_id=1)


def test_qwen_candidate_rejects_tampered_part(tmp_path: Path) -> None:
    manifest, _archive_sha = _qwen_assets(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    part = tmp_path / value["parts"][0]["name"]
    part.write_bytes(b"tampered")
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_QWEN_PART_MISMATCH"):
        create_candidate("qwen", tmp_path, source_sha=SOURCE_SHA, source_tree_sha=TREE_SHA, workflow_run_id=2)


def test_whisper_physical_seal_requires_exact_installed_runtime_and_both_profiles(tmp_path: Path) -> None:
    _archive, archive_sha = _whisper_assets(tmp_path / "assets")
    candidate = create_candidate(
        "whisper",
        tmp_path / "assets",
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=3,
    )
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
    _runtime_marker(runtime_root, "whisper", version, archive_sha)
    turbo = _whisper_receipt(tmp_path / "turbo.json", "whisper-turbo")

    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_WHISPER_EVIDENCE_INCOMPLETE"):
        seal_physical(candidate, runtime_root, whisper_receipts=[turbo])

    detailed = _whisper_receipt(tmp_path / "detailed.json", "whisper-detailed")
    receipt = seal_physical(candidate, runtime_root, whisper_receipts=[turbo, detailed])
    assert receipt["schema"] == ACCEPTANCE_SCHEMA
    assert receipt["pass"] is True
    assert receipt["runtime_archive_sha256"] == archive_sha
    assert [item["profile_id"] for item in receipt["profiles"]] == ["whisper-turbo", "whisper-detailed"]

    wrong_root = tmp_path / "WrongRuntime"
    _runtime_marker(wrong_root, "whisper", version, "f" * 64)
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_PHYSICAL_ARCHIVE_MISMATCH"):
        seal_physical(candidate, wrong_root, whisper_receipts=[turbo, detailed])


def test_qwen_physical_seal_requires_both_gates_bound_to_same_archive(tmp_path: Path) -> None:
    _manifest, archive_sha = _qwen_assets(tmp_path / "assets")
    candidate = create_candidate(
        "qwen",
        tmp_path / "assets",
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=4,
    )
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
    _runtime_marker(runtime_root, "qwen", version, archive_sha)
    state_root = tmp_path / "State"
    gate_root = state_root / "qwen-physical-gates"
    _qwen_gate(gate_root / "qwen-fast.json", "qwen-fast", version, archive_sha)

    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_PHYSICAL_EVIDENCE_INVALID"):
        seal_physical(candidate, runtime_root, qwen_state_root=state_root)

    _qwen_gate(gate_root / "qwen-quality.json", "qwen-quality", version, archive_sha)
    receipt = seal_physical(candidate, runtime_root, qwen_state_root=state_root)
    assert [item["profile_id"] for item in receipt["profiles"]] == ["qwen-fast", "qwen-quality"]

    _qwen_gate(gate_root / "qwen-quality.json", "qwen-quality", version, "e" * 64)
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_QWEN_EVIDENCE_INVALID"):
        seal_physical(candidate, runtime_root, qwen_state_root=state_root)


def test_promotion_rehashes_release_assets_and_rejects_identity_drift(tmp_path: Path) -> None:
    _archive, archive_sha = _whisper_assets(tmp_path / "assets")
    candidate = create_candidate(
        "whisper",
        tmp_path / "assets",
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=5,
    )
    runtime_root = tmp_path / "Runtime"
    version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
    _runtime_marker(runtime_root, "whisper", version, archive_sha)
    receipts = [
        _whisper_receipt(tmp_path / "turbo.json", "whisper-turbo"),
        _whisper_receipt(tmp_path / "detailed.json", "whisper-detailed"),
    ]
    acceptance = seal_physical(candidate, runtime_root, whisper_receipts=receipts)
    promotion = verify_promotion(candidate, acceptance, tmp_path / "assets")
    assert promotion["stable_tag"] == f"companion-whisper-runtime-v{version}"

    archive = tmp_path / "assets" / f"TDAWhisperRuntime-{version}-windows-x64.zip"
    archive.write_bytes(b"changed-after-physical-test")
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_CANDIDATE_ASSET_MISMATCH"):
        verify_promotion(candidate, acceptance, tmp_path / "assets")

    drift = dict(acceptance)
    drift["source_sha"] = "3" * 40
    with pytest.raises(RuntimeReleaseEvidenceError, match="RUNTIME_PROMOTION_IDENTITY_MISMATCH"):
        verify_promotion(candidate, drift, tmp_path / "assets")
