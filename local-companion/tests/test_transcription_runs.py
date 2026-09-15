from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import (
    ensure_legacy_and_list,
    list_runs,
    load_run,
    migrate_legacy_transcript,
    run_id_for,
    write_compatibility_mirror,
    write_completed_run,
)


def _document(source_sha256: str, profile: str, text: str) -> TranscriptDocument:
    words = (TranscriptWord(text=text, start=1.0, end=1.4, confidence=0.99),)
    segment = TranscriptSegment(
        id="1-0",
        start=1.0,
        end=1.5,
        text=text,
        words=words,
    )
    track = TranscriptTrack(
        number=1,
        speaker="Alice",
        source_filename="1-Alice.flac",
        source_sha256="a" * 64,
        duration_seconds=60.0,
        segments=(segment,),
    )
    return TranscriptDocument(
        recording_id="recording",
        source_sha256=source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper" if profile.startswith("whisper-") else "qwen3",
            model="model-for-test",
            profile=profile,
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="test-revision",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=12.0),
    )


def test_two_completed_runs_coexist_without_overwrite(tmp_path: Path):
    source_sha = "b" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()

    first = write_completed_run(
        package_root,
        _document(source_sha, "whisper-detailed", "primeiro"),
        job_id="job-one",
        attempt=1,
        context="contexto A",
        glossary="Valyndra",
    )
    first_path = package_root / "runs" / first["run_id"] / "transcript.json"
    first_bytes = first_path.read_bytes()

    second = write_completed_run(
        package_root,
        _document(source_sha, "qwen-quality", "segundo"),
        job_id="job-two",
        attempt=1,
        context="contexto B",
        glossary="Neverwinter",
    )

    assert first["run_id"] != second["run_id"]
    assert first_path.read_bytes() == first_bytes
    assert len(list_runs(package_root, verify_content=True)) == 2
    assert load_run(package_root, first["run_id"])["transcript_sha256"] == hashlib.sha256(
        first_bytes
    ).hexdigest()


def test_retry_attempt_gets_distinct_run_identity(tmp_path: Path):
    source_sha = "c" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()

    one = write_completed_run(
        package_root,
        _document(source_sha, "whisper-turbo", "tentativa um"),
        job_id="same-job",
        attempt=1,
    )
    two = write_completed_run(
        package_root,
        _document(source_sha, "whisper-turbo", "tentativa dois"),
        job_id="same-job",
        attempt=2,
    )

    assert one["run_id"] == run_id_for("same-job", 1)
    assert two["run_id"] == run_id_for("same-job", 2)
    assert one["run_id"] != two["run_id"]


def test_compatibility_mirror_can_change_without_mutating_runs(tmp_path: Path):
    source_sha = "d" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()
    first = write_completed_run(
        package_root,
        _document(source_sha, "whisper-detailed", "A"),
        job_id="job-a",
        attempt=1,
    )
    second = write_completed_run(
        package_root,
        _document(source_sha, "qwen-quality", "B"),
        job_id="job-b",
        attempt=1,
    )
    first_path = package_root / "runs" / first["run_id"] / "transcript.json"
    first_bytes = first_path.read_bytes()

    assert write_compatibility_mirror(package_root, first["run_id"]) == first["transcript_sha256"]
    assert (package_root / "transcript.json").read_bytes() == first_bytes
    assert write_compatibility_mirror(package_root, second["run_id"]) == second["transcript_sha256"]
    assert first_path.read_bytes() == first_bytes
    assert (package_root / "transcript.json").read_bytes() != first_bytes


def test_valid_legacy_transcript_is_copied_idempotently_and_original_is_retained(tmp_path: Path):
    source_sha = "e" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    legacy = package_root / "transcript.json"
    document = _document(source_sha, "whisper-detailed", "legado")
    document.write_atomic(legacy)
    original = legacy.read_bytes()

    first = migrate_legacy_transcript(
        package_root,
        source_id=source_id,
        source_sha256=source_sha,
    )
    second = migrate_legacy_transcript(
        package_root,
        source_id=source_id,
        source_sha256=source_sha,
    )

    assert first is not None
    assert second is not None
    assert first["run_id"] == second["run_id"]
    assert first["origin"] == "legacy_transcript_v1"
    assert legacy.read_bytes() == original
    migrated = package_root / "runs" / first["run_id"] / "transcript.json"
    assert migrated.read_bytes() == original
    assert len(list_runs(package_root, verify_content=True)) == 1


def test_invalid_legacy_transcript_is_never_promoted_or_deleted(tmp_path: Path):
    source_sha = "f" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    legacy = package_root / "transcript.json"
    legacy.write_text('{"schema_version":"wrong","private":"keep"}', encoding="utf-8")
    original = legacy.read_bytes()

    assert (
        migrate_legacy_transcript(
            package_root,
            source_id=source_id,
            source_sha256=source_sha,
        )
        is None
    )
    assert legacy.read_bytes() == original
    assert list_runs(package_root, verify_content=True) == []


def test_tampered_run_is_excluded_when_content_verification_is_requested(tmp_path: Path):
    source_sha = "1" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    run = write_completed_run(
        package_root,
        _document(source_sha, "whisper-detailed", "original"),
        job_id="job-tamper",
        attempt=1,
    )
    transcript = package_root / "runs" / run["run_id"] / "transcript.json"
    payload = json.loads(transcript.read_text(encoding="utf-8"))
    payload["tracks"][0]["segments"][0]["text"] = "alterado!"
    changed = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Keep file size compatible with the manifest so only the hash verification can reject it.
    original_size = transcript.stat().st_size
    encoded = changed.encode("utf-8")
    if len(encoded) < original_size:
        encoded += b" " * (original_size - len(encoded))
    elif len(encoded) > original_size:
        encoded = encoded[:original_size]
    transcript.write_bytes(encoded)

    assert list_runs(package_root, verify_content=False) != []
    assert list_runs(package_root, verify_content=True) == []


def test_run_listing_is_sanitized_and_contains_no_transcript_text_or_local_path(tmp_path: Path):
    source_sha = "2" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    write_completed_run(
        package_root,
        _document(source_sha, "whisper-detailed", "SEGREDO-DO-TRANSCRIPT"),
        job_id="job-summary",
        attempt=1,
    )

    result = ensure_legacy_and_list(
        package_root,
        source_id=source_id,
        source_sha256=source_sha,
        verify_content=True,
    )
    encoded = json.dumps(result, ensure_ascii=False)
    assert result["schema_version"] == "tda_transcription_runs_v1"
    assert len(result["runs"]) == 1
    assert "SEGREDO-DO-TRANSCRIPT" not in encoded
    assert str(tmp_path) not in encoded
