from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion import VERSION
from tda_companion.installed_acceptance import REQUIRED_OBSERVATIONS
from tda_companion.payload_evidence import create_payload_manifest
from tda_companion.release_evidence import (
    ReleaseEvidenceError,
    build_candidate_manifest,
    build_promotion_evidence,
    sha256_file,
    verify_acceptance_receipt,
    verify_candidate_files,
)

SOURCE_SHA = "1" * 40
TREE_SHA = "a" * 40


def _candidate_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    msi = tmp_path / "TDACompanion-x64.msi"
    msi.write_bytes(b"candidate-msi-bytes")
    checksum = tmp_path / "TDACompanion-x64.msi.sha256"
    checksum.write_text(f"{sha256_file(msi)}  TDACompanion-x64.msi", encoding="ascii")
    archive = tmp_path / f"TDACompanion-{VERSION}-windows-x64.zip"
    archive.write_bytes(b"candidate-zip-bytes")
    app = tmp_path / "app"
    app.mkdir()
    for index, name in enumerate(
        (
            "TDACompanion.exe",
            "TDACompanionMaintenance.exe",
            "run-physical-acceptance.ps1",
            "run-installed-acceptance.ps1",
            "install-rc-runtimes.ps1",
        ),
        start=1,
    ):
        (app / name).write_bytes(f"payload-{index}-{name}".encode())
    payload = tmp_path / "TDACompanion-payload-manifest.json"
    create_payload_manifest(
        app,
        version=VERSION,
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        destination=payload,
    )
    return msi, checksum, archive, payload


def _manifest(tmp_path: Path) -> dict[str, object]:
    msi, checksum, archive, payload = _candidate_files(tmp_path)
    return build_candidate_manifest(
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=12345,
        msi_path=msi,
        checksum_path=checksum,
        zip_path=archive,
        payload_manifest_path=payload,
    )


def _receipt(manifest: dict[str, object]) -> dict[str, object]:
    assets = manifest["assets"]
    assert isinstance(assets, dict)
    msi = assets["msi"]
    payload = assets["payload_manifest"]
    assert isinstance(msi, dict) and isinstance(payload, dict)
    return {
        "schema": "tda_installed_acceptance_v2",
        "pass": True,
        "accepted_at": "2026-09-13T20:00:00+00:00",
        "stage": "completed",
        "version": VERSION,
        "contains_token": False,
        "contains_paths": False,
        "contains_transcript": False,
        "artifact": {
            "version": VERSION,
            "source_sha": manifest["source_sha"],
            "source_tree_sha": manifest["source_tree_sha"],
            "msi_sha256": msi["sha256"],
            "payload_manifest_sha256": payload["sha256"],
            "executable_sha256": "2" * 64,
            "maintenance_helper_sha256": "3" * 64,
        },
        "checks": {
            "observations": {name: True for name in REQUIRED_OBSERVATIONS},
            "craig_fixture": {"track_count": 4, "zip_sha256": "4" * 64},
            "diagnostics": {
                "overall": "degraded",
                "capabilities": {
                    "core": {"state": "ready", "severity": "info"},
                    "network": {"state": "ready", "severity": "info"},
                    "maintenance": {"state": "ready", "severity": "info"},
                    "whisper": {"state": "degraded", "severity": "degraded"},
                    "qwen": {"state": "degraded", "severity": "degraded"},
                },
            },
        },
    }


def test_candidate_manifest_pins_source_tree_and_all_distribution_bytes(tmp_path: Path):
    manifest = _manifest(tmp_path)
    assert manifest["tag"] == f"companion-rc-v{VERSION}-{'1' * 12}"
    assert manifest["source_sha"] == SOURCE_SHA
    assert manifest["source_tree_sha"] == TREE_SHA
    verify_candidate_files(manifest, tmp_path)


def test_candidate_files_fail_when_msi_changes_after_manifest(tmp_path: Path):
    manifest = _manifest(tmp_path)
    (tmp_path / "TDACompanion-x64.msi").write_bytes(b"changed")
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ASSET_"):
        verify_candidate_files(manifest, tmp_path)


def test_candidate_rejects_payload_manifest_for_other_source_tree(tmp_path: Path):
    msi, checksum, archive, payload = _candidate_files(tmp_path)
    value = json.loads(payload.read_text(encoding="utf-8"))
    value["source_tree_sha"] = "b" * 40
    payload.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_PAYLOAD_TREE_MISMATCH"):
        build_candidate_manifest(
            source_sha=SOURCE_SHA,
            source_tree_sha=TREE_SHA,
            workflow_run_id=12345,
            msi_path=msi,
            checksum_path=checksum,
            zip_path=archive,
            payload_manifest_path=payload,
        )


def test_acceptance_receipt_must_match_candidate_source_msi_tree_and_payload(tmp_path: Path):
    manifest = _manifest(tmp_path)
    receipt = _receipt(manifest)
    receipt["artifact"]["msi_sha256"] = "f" * 64
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_MSI_MISMATCH"):
        verify_acceptance_receipt(receipt, manifest)

    receipt = _receipt(manifest)
    receipt["artifact"]["source_tree_sha"] = "b" * 40
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_TREE_MISMATCH"):
        verify_acceptance_receipt(receipt, manifest)

    receipt = _receipt(manifest)
    receipt["artifact"]["payload_manifest_sha256"] = "f" * 64
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_PAYLOAD_MISMATCH"):
        verify_acceptance_receipt(receipt, manifest)


def test_acceptance_receipt_requires_every_physical_observation(tmp_path: Path):
    manifest = _manifest(tmp_path)
    receipt = _receipt(manifest)
    receipt["checks"]["observations"]["agent_recovery"] = False
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_OBSERVATIONS_INVALID"):
        verify_acceptance_receipt(receipt, manifest)


def test_acceptance_receipt_requires_operational_core_network_and_maintenance(tmp_path: Path):
    manifest = _manifest(tmp_path)
    receipt = _receipt(manifest)
    receipt["checks"]["diagnostics"]["capabilities"]["network"]["state"] = "blocked"
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_CAPABILITY_NOT_READY"):
        verify_acceptance_receipt(receipt, manifest)


def test_acceptance_receipt_rejects_extra_top_level_or_nested_payload(tmp_path: Path):
    manifest = _manifest(tmp_path)
    receipt = _receipt(manifest)
    receipt["extra"] = "must-not-be-carried-into-release-evidence"
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_SCHEMA_INVALID"):
        verify_acceptance_receipt(receipt, manifest)
    receipt = _receipt(manifest)
    receipt["checks"]["craig_fixture"]["speaker_names"] = ["private"]
    with pytest.raises(ReleaseEvidenceError, match="RELEASE_ACCEPTANCE_CRAIG_INVALID"):
        verify_acceptance_receipt(receipt, manifest)


def test_promotion_evidence_reuses_exact_candidate_bytes(tmp_path: Path):
    manifest = _manifest(tmp_path)
    receipt = _receipt(manifest)
    manifest_path = tmp_path / "TDACompanion-candidate.json"
    receipt_path = tmp_path / "TDACompanion-acceptance.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    evidence = build_promotion_evidence(
        candidate_manifest_path=manifest_path,
        acceptance_receipt_path=receipt_path,
        assets_root=tmp_path,
    )
    assert evidence["candidate_tag"] == manifest["tag"]
    assert evidence["stable_tag"] == f"companion-v{VERSION}"
    assert evidence["source_sha"] == manifest["source_sha"]
    assert evidence["source_tree_sha"] == manifest["source_tree_sha"]
    assert evidence["acceptance_receipt_sha256"] == sha256_file(receipt_path)
    assert evidence["assets"] == manifest["assets"]
