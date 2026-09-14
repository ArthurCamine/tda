from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tda_companion.craig import CraigPackageError, ingest_craig_zip, parse_info_text
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptValidationError,
    TranscriptWord,
    stats_for_tracks,
)


def _craig_info() -> str:
    return (
        "Recording 987654321\r\n"
        "\r\n"
        "Guild:\t\tTDA Guild (100)\r\n"
        "Channel:\tmesa (200)\r\n"
        "Requester:\tFaysk#0 (300)\r\n"
        "Start time:\t2026-09-11T18:00:00.000Z\r\n"
        "\r\n"
        "Tracks:\r\n"
        "\tYuhara#0 (111)\r\n"
        "\tFehh#0 (222)\r\n"
    )


def _write_craig_zip(path: Path, *, extras: dict[str, bytes] | None = None) -> None:
    files = {
        "1-yuhara.flac": b"fLaC" + b"a" * 128,
        "2-fehh.flac": b"fLaC" + b"b" * 256,
        "info.txt": _craig_info().encode("utf-8"),
        "raw.dat": b"raw-evidence",
    }
    files.update(extras or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)


def test_parse_info_text_preserves_track_order_and_metadata():
    value = parse_info_text(_craig_info())
    assert value["recording_id"] == "987654321"
    assert value["guild"] == "TDA Guild (100)"
    assert value["channel"] == "mesa (200)"
    assert value["requester"] == "Faysk#0 (300)"
    assert value["start_time"] == "2026-09-11T18:00:00.000Z"
    assert value["tracks"] == [
        {"username": "Yuhara", "discriminator": "0", "discord_id": "111"},
        {"username": "Fehh", "discriminator": "0", "discord_id": "222"},
    ]


def test_ingest_craig_zip_materializes_only_tracks_and_bounded_metadata(tmp_path: Path):
    source = tmp_path / "craig.zip"
    _write_craig_zip(source)
    destination = tmp_path / "session"

    package = ingest_craig_zip(source, destination)

    assert package.schema_version == "tda_craig_package_v1"
    assert package.recording_id == "987654321"
    assert package.info_present is True
    assert package.raw_dat_present is True
    assert [track.number for track in package.tracks] == [1, 2]
    assert [track.speaker for track in package.tracks] == ["yuhara", "fehh"]
    assert [track.identity.username for track in package.tracks if track.identity] == ["Yuhara", "Fehh"]
    assert all(track.timeline_offset_seconds == 0.0 for track in package.tracks)
    assert not (destination / "raw.dat").exists()
    assert (destination / "info.txt").is_file()
    assert (destination / "tracks" / "track-000001.flac").is_file()
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["tracks"][0]["sha256"] == hashlib.sha256(
        (destination / "tracks" / "track-000001.flac").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../escape.flac", "CRAIG_ARCHIVE_UNSAFE_PATH"),
        ("folder/1-user.flac", "CRAIG_ARCHIVE_NESTED_PATH"),
        ("unexpected.txt", "CRAIG_ARCHIVE_UNEXPECTED_FILE"),
    ],
)
def test_ingest_rejects_unsafe_or_unknown_members(tmp_path: Path, name: str, expected: str):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-user.flac", b"fLaC-data")
        archive.writestr(name, b"bad")
    with pytest.raises(CraigPackageError, match=expected):
        ingest_craig_zip(source, tmp_path / "output")


def test_ingest_rejects_duplicate_track_number_even_with_different_name(tmp_path: Path):
    source = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-yuhara.flac", b"fLaC-one")
        archive.writestr("1-fehh.flac", b"fLaC-two")
    with pytest.raises(CraigPackageError, match="CRAIG_TRACK_NUMBER_DUPLICATE"):
        ingest_craig_zip(source, tmp_path / "output")


def test_ingest_does_not_replace_existing_destination(tmp_path: Path):
    source = tmp_path / "craig.zip"
    _write_craig_zip(source)
    destination = tmp_path / "session"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(CraigPackageError, match="CRAIG_DESTINATION_EXISTS"):
        ingest_craig_zip(source, destination)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not any(path.name.endswith(".partial") for path in tmp_path.iterdir())


def _document() -> TranscriptDocument:
    words = (
        TranscriptWord(text="Eu", start=1.0, end=1.15, confidence=0.99),
        TranscriptWord(text="vou", start=1.16, end=1.32, confidence=0.97),
    )
    segment = TranscriptSegment(
        id="1-0",
        start=1.0,
        end=1.5,
        text="Eu vou",
        words=words,
    )
    track = TranscriptTrack(
        number=1,
        speaker="Yuhara",
        source_filename="1-yuhara.flac",
        source_sha256="a" * 64,
        duration_seconds=120.0,
        segments=(segment,),
        identity={"username": "Yuhara", "discriminator": "0", "discord_id": "111"},
    )
    return TranscriptDocument(
        recording_id="987654321",
        source_sha256="b" * 64,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3",
            profile="whisper-detailed",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="pinned-revision",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=12.0),
    )


def test_transcript_v1_validates_and_writes_atomically(tmp_path: Path):
    document = _document()
    document.validate()
    target = tmp_path / "transcript.json"
    document.write_atomic(target)
    value = json.loads(target.read_text(encoding="utf-8"))
    assert value["schema_version"] == "tda_transcript_v1"
    assert value["language"] == "pt"
    assert value["engine"]["profile"] == "whisper-detailed"
    assert value["tracks"][0]["segments"][0]["words"][0]["text"] == "Eu"
    assert value["stats"]["word_count"] == 2
    assert value["stats"]["track_count"] == 1
    assert not target.with_suffix(".json.partial").exists()


def test_transcript_rejects_word_outside_segment():
    segment = TranscriptSegment(
        id="bad",
        start=10.0,
        end=11.0,
        text="fora",
        words=(TranscriptWord(text="fora", start=9.0, end=9.5),),
    )
    with pytest.raises(TranscriptValidationError, match="word:BEFORE_SEGMENT"):
        segment.validate()


def test_transcript_rejects_stats_that_do_not_match_tracks():
    document = _document()
    broken = TranscriptDocument(
        recording_id=document.recording_id,
        source_sha256=document.source_sha256,
        language=document.language,
        engine=document.engine,
        tracks=document.tracks,
        stats=type(document.stats)(
            audio_work_seconds=document.stats.audio_work_seconds,
            session_duration_seconds=document.stats.session_duration_seconds,
            processing_seconds=document.stats.processing_seconds,
            word_count=999,
            segment_count=document.stats.segment_count,
            track_count=document.stats.track_count,
            rtf=document.stats.rtf,
        ),
    )
    with pytest.raises(TranscriptValidationError, match="WORD_COUNT_MISMATCH"):
        broken.validate()
