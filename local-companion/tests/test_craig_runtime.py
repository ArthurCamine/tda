from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.craig import CraigPackageError, ingest_craig_zip
from tda_companion.craig_runtime import load_craig_package


def _stage_package(tmp_path: Path) -> Path:
    source = tmp_path / "craig.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-alice")
        archive.writestr("2-Bob.flac", b"fLaC-bob")
        archive.writestr(
            "info.txt",
            (
                "Recording 123\n"
                "Guild: TDA\n"
                "Channel: mesa\n"
                "Requester: Alice#0 (1)\n"
                "Tracks:\n"
                "Alice#0 (1)\n"
                "Bob#0 (2)\n"
            ).encode("utf-8"),
        )
    destination = tmp_path / "Data" / "staging" / "source-123"
    ingest_craig_zip(source, destination)
    return destination


def test_load_staged_package_revalidates_tracks_and_hashes(tmp_path: Path):
    root = _stage_package(tmp_path)
    package = load_craig_package(root)
    assert package.recording_id == "123"
    assert [track.number for track in package.tracks] == [1, 2]
    assert [track.speaker for track in package.tracks] == ["Alice", "Bob"]
    assert package.tracks[0].path == "tracks/track-000001.flac"
    assert package.tracks[0].identity is not None
    assert package.tracks[0].identity.discord_id == "1"


def test_load_staged_package_rejects_manifest_path_override(tmp_path: Path):
    root = _stage_package(tmp_path)
    manifest_path = root / "manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["tracks"][0]["path"] = "../outside.flac"
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_TRACK_PATH_INVALID"):
        load_craig_package(root)


def test_load_staged_package_rejects_track_tampering(tmp_path: Path):
    root = _stage_package(tmp_path)
    (root / "tracks" / "track-000001.flac").write_bytes(b"changed!!!")
    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_TRACK_(SIZE|HASH)_MISMATCH"):
        load_craig_package(root)


def test_load_staged_package_rejects_manifest_source_path(tmp_path: Path):
    root = _stage_package(tmp_path)
    manifest_path = root / "manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["source_zip"] = "../private.zip"
    manifest_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_SOURCE_INVALID"):
        load_craig_package(root)
