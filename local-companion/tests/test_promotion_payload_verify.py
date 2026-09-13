from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion import VERSION
from tda_companion.payload_evidence import create_payload_manifest
from tda_companion.promotion_payload_verify import PromotionPayloadError, verify_promotion_payload
from tda_companion.release_evidence import build_candidate_manifest, sha256_file

SOURCE_SHA = "1" * 40
TREE_SHA = "a" * 40


def _fixture(tmp_path: Path):
    app = tmp_path / "app"
    app.mkdir()
    for index, name in enumerate((
        "TDACompanion.exe",
        "TDACompanionMaintenance.exe",
        "run-physical-acceptance.ps1",
        "run-installed-acceptance.ps1",
        "install-rc-runtimes.ps1",
    ), start=1):
        (app / name).write_bytes(f"payload-{index}-{name}".encode())
    payload = tmp_path / "TDACompanion-payload-manifest.json"
    payload_value = create_payload_manifest(
        app,
        version=VERSION,
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        destination=payload,
    )
    msi = tmp_path / "TDACompanion-x64.msi"
    msi.write_bytes(b"msi")
    checksum = tmp_path / "TDACompanion-x64.msi.sha256"
    checksum.write_text(f"{sha256_file(msi)}  TDACompanion-x64.msi", encoding="ascii")
    archive = tmp_path / f"TDACompanion-{VERSION}-windows-x64.zip"
    archive.write_bytes(b"zip")
    candidate = build_candidate_manifest(
        source_sha=SOURCE_SHA,
        source_tree_sha=TREE_SHA,
        workflow_run_id=123,
        msi_path=msi,
        checksum_path=checksum,
        zip_path=archive,
        payload_manifest_path=payload,
    )
    manifest_path = tmp_path / "TDACompanion-candidate.json"
    manifest_path.write_text(json.dumps(candidate), encoding="utf-8")
    files = payload_value["files"]
    receipt = {
        "artifact": {
            "version": VERSION,
            "source_sha": SOURCE_SHA,
            "source_tree_sha": TREE_SHA,
            "payload_manifest_sha256": sha256_file(payload),
            "executable_sha256": files["TDACompanion.exe"]["sha256"],
            "maintenance_helper_sha256": files["TDACompanionMaintenance.exe"]["sha256"],
        }
    }
    receipt_path = tmp_path / "TDACompanion-acceptance.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return manifest_path, receipt_path


def test_promotion_payload_accepts_exact_installed_binary_hashes(tmp_path: Path):
    manifest, receipt = _fixture(tmp_path)
    verify_promotion_payload(manifest, receipt, tmp_path)


def test_promotion_payload_rejects_fabricated_executable_hash(tmp_path: Path):
    manifest, receipt = _fixture(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["artifact"]["executable_sha256"] = "f" * 64
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PromotionPayloadError, match="PROMOTION_INSTALLED_BINARY_MISMATCH"):
        verify_promotion_payload(manifest, receipt, tmp_path)


def test_promotion_payload_rejects_fabricated_helper_hash(tmp_path: Path):
    manifest, receipt = _fixture(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["artifact"]["maintenance_helper_sha256"] = "e" * 64
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PromotionPayloadError, match="PROMOTION_INSTALLED_BINARY_MISMATCH"):
        verify_promotion_payload(manifest, receipt, tmp_path)
