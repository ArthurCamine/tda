from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import (
    TranscriptionRunError,
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
        execution_lineage={
            "schema_version": "tda_execution_lineage_v1",
            "companion_version": "0.3.14",
            "runtime_family": "whisper",
            "runtime_version": "1.1.5",
            "device": "cuda",
            "compute_type": "float16",
            "gpu": {
                "vendor": "NVIDIA",
                "index": 0,
                "model": "NVIDIA Test GPU",
                "vram_total_bytes": 8 * 1024**3,
                "compute_capability": "8.9",
                "driver_version": "600.12",
            },
        },
    )
    first_path = package_root / "runs" / first["run_id"] / "transcript.json"
    first_bytes = first_path.read_bytes()
    assert first["stats"]["audio_work_seconds"] == 60.0
    assert first["stats"]["session_duration_seconds"] == 60.0
    assert first["execution_lineage"]["gpu"]["model"] == "NVIDIA Test GPU"
    listed = list_runs(package_root, verify_content=True)
    assert listed[0]["execution_lineage"]["runtime_version"] == "1.1.5"

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


def test_before_commit_fence_runs_after_transcript_but_before_run_marker(tmp_path: Path):
    source_sha = "9" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()
    run_id = run_id_for("job-fence", 1)
    observed = {}

    def before_commit():
        run_root = package_root / "runs" / run_id
        observed["transcript_exists"] = (run_root / "transcript.json").is_file()
        observed["run_marker_exists"] = (run_root / "run.json").exists()

    manifest = write_completed_run(
        package_root,
        _document(source_sha, "whisper-turbo", "fenced"),
        job_id="job-fence",
        attempt=1,
        before_commit=before_commit,
    )

    assert observed == {
        "transcript_exists": True,
        "run_marker_exists": False,
    }
    assert (package_root / "runs" / manifest["run_id"] / "run.json").is_file()


def test_failed_before_commit_fence_cleans_uncommitted_run(tmp_path: Path):
    source_sha = "8" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()

    def cancelled():
        raise RuntimeError("cancel won")

    with pytest.raises(RuntimeError, match="cancel won"):
        write_completed_run(
            package_root,
            _document(source_sha, "qwen-fast", "never committed"),
            job_id="job-cancel",
            attempt=1,
            before_commit=cancelled,
        )

    assert not (package_root / "runs" / run_id_for("job-cancel", 1)).exists()
    assert list_runs(package_root, verify_content=True) == []


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


def test_interrupted_legacy_migration_is_rebuilt_from_root_transcript(tmp_path: Path):
    source_sha = "d" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    legacy = package_root / "transcript.json"
    _document(source_sha, "whisper-detailed", "legado interrompido").write_atomic(legacy)
    payload = legacy.read_bytes()
    run_id = f"legacy-{hashlib.sha256(payload).hexdigest()}"
    incomplete = package_root / "runs" / run_id
    incomplete.mkdir(parents=True)
    (incomplete / "transcript.json.partial").write_bytes(b"incomplete")

    migrated = migrate_legacy_transcript(
        package_root,
        source_id=source_id,
        source_sha256=source_sha,
    )

    assert migrated is not None
    assert migrated["run_id"] == run_id
    assert (incomplete / "run.json").is_file()
    assert (incomplete / "transcript.json").read_bytes() == payload
    assert not (incomplete / "transcript.json.partial").exists()
    assert legacy.read_bytes() == payload


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


def test_symlinked_run_transcript_is_rejected(tmp_path: Path):
    source_sha = "3" * 64
    package_root = tmp_path / f"craig-{source_sha}"
    package_root.mkdir()
    run = write_completed_run(
        package_root,
        _document(source_sha, "whisper-detailed", "original"),
        job_id="job-symlink",
        attempt=1,
    )
    transcript = package_root / "runs" / run["run_id"] / "transcript.json"
    external = tmp_path / "external-transcript.json"
    external.write_bytes(transcript.read_bytes())
    transcript.unlink()
    try:
        transcript.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(TranscriptionRunError, match="TRANSCRIPTION_RUN_TRANSCRIPT_SYMLINK"):
        load_run(package_root, run["run_id"], verify_content=True)
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


@pytest.mark.parametrize("field,bad", [
    (("stats", "word_count"), "oops"),
    (("stats", "word_count"), 2),
    (("stats", "segment_count"), 2),
    (("stats", "audio_work_seconds"), -1),
    (("stats", "processing_seconds"), float("nan")),
    (("stats", "rtf"), float("inf")),
    (("tracks",), None),
    (("tracks", 0, "number"), True),
    (("tracks", 0, "segments", 0, "id"), 123),
    (("tracks", 0, "segments", 0, "start"), -1),
    (("tracks", 0, "segments", 0, "end"), 0),
    (("tracks", 0, "segments", 0, "text"), "bad\0text"),
    (("tracks", 0, "segments", 0, "text"), "\ud800"),
    (("tracks", 0, "segments", 0, "words"), {}),
    (("engine", "model"), 7),
    (("engine", "device"), "bad\nmetadata"),
    (("warnings",), [42]),
    (("warnings",), "warning"),
    (("created_at",), "not-a-date"),
])
def test_semantically_invalid_legacy_never_commits(tmp_path: Path, field, bad):
    package = tmp_path / "source"
    package.mkdir()
    value = json.loads(json.dumps(_document("a" * 64, "whisper-detailed", "legacy").as_dict()))
    current = value
    for key in field[:-1]:
        current = current[key]
    current[field[-1]] = bad
    original = json.dumps(value).encode()
    (package / "transcript.json").write_bytes(original)
    assert migrate_legacy_transcript(package, source_id="source", source_sha256="a" * 64) is None
    assert (package / "transcript.json").read_bytes() == original
    assert not list(package.glob("runs/*/run.json"))


@pytest.mark.parametrize("mutation", ["missing_tracks", "duplicate_track", "missing_turn_ref", "duplicate_turn_ref"])
def test_legacy_cross_field_validation(tmp_path: Path, mutation):
    package = tmp_path / "source"
    package.mkdir()
    value = json.loads(json.dumps(_document("a" * 64, "whisper-detailed", "legacy").as_dict()))
    if mutation == "missing_tracks":
        del value["tracks"]
    elif mutation == "duplicate_track":
        value["tracks"] *= 2
        value["stats"].update(track_count=2, word_count=2, segment_count=2)
    else:
        ref = {"track_number": 1, "segment_id": "missing" if mutation == "missing_turn_ref" else "1-0"}
        value["turns"] = [{"id": "turn", "speaker": "Alice", "start": 1.0, "end": 1.5,
                           "text": "legacy", "segments": [ref] if mutation == "missing_turn_ref" else [ref, ref]}]
        value["stats"]["turn_count"] = 1
    original = json.dumps(value).encode()
    (package / "transcript.json").write_bytes(original)
    assert migrate_legacy_transcript(package, source_id="source", source_sha256="a" * 64) is None
    assert (package / "transcript.json").read_bytes() == original
    assert not list(package.glob("runs/*/run.json"))


def test_invalid_historical_summary_is_reported_without_hiding_valid_run(tmp_path: Path):
    package = tmp_path / "source"
    package.mkdir()
    valid = write_completed_run(package, _document("a" * 64, "whisper-detailed", "ok"), job_id="good", attempt=1)
    invalid = write_completed_run(package, _document("a" * 64, "whisper-detailed", "bad"), job_id="bad", attempt=1)
    invalid["stats"]["word_count"] = "oops"
    (package / "runs" / invalid["run_id"] / "run.json").write_text(json.dumps(invalid))
    response = ensure_legacy_and_list(package, source_id="source", source_sha256="a" * 64)
    assert [run["run_id"] for run in response["runs"]] == [valid["run_id"]]
    assert response["invalid_runs"] == [{"run_id": invalid["run_id"], "integrity": "invalid", "reason": "TRANSCRIPTION_RUN_STATS_INVALID"}]


def test_legacy_parser_preserves_original_strings_and_formatted_bytes(tmp_path: Path):
    package = tmp_path / "source"
    package.mkdir()
    document = _document("a" * 64, "whisper-detailed", "  cafe\u0301 😀  ")
    payload = json.dumps(document.as_dict(), indent=4, ensure_ascii=False).encode()
    parsed = TranscriptDocument.from_dict(json.loads(payload))
    assert parsed.tracks[0].segments[0].text == document.tracks[0].segments[0].text
    (package / "transcript.json").write_bytes(payload)
    result = migrate_legacy_transcript(package, source_id="source", source_sha256="a" * 64)
    assert (package / "runs" / result["run_id"] / "transcript.json").read_bytes() == payload


@pytest.mark.parametrize("fail_at", [1, 2])
def test_ambiguous_run_fence_preserves_evidence_and_orders_commit(monkeypatch, tmp_path, fail_at):
    import tda_companion.atomic_storage as storage
    package = tmp_path / "source"
    package.mkdir()
    fences = []
    def fence(directory):
        fences.append(directory)
        if len(fences) == fail_at:
            raise OSError("synthetic namespace failure")
    monkeypatch.setattr(storage, "sync_namespace", fence)
    with pytest.raises(storage.AtomicStorageError) as error:
        write_completed_run(package, _document("a" * 64, "whisper-detailed", "test"), job_id="durability", attempt=1)
    assert error.value.ambiguous
    root = package / "runs" / "run-durability-a1"
    assert (root / "transcript.json").is_file()
    assert (root / "run.json").exists() == (fail_at == 2)
    if fail_at == 1:
        assert list_runs(package) == []
    else:
        assert load_run(package, root.name)["run_id"] == root.name


def test_mirror_preserves_legacy_before_replacing_root_without_prior_listing(tmp_path):
    package = tmp_path / "source"
    package.mkdir()
    legacy = package / "transcript.json"
    _document("a" * 64, "whisper-detailed", "Historical A").write_atomic(legacy)
    original = legacy.read_bytes()
    newer = write_completed_run(package, _document("a" * 64, "qwen-quality", "New B"), job_id="new", attempt=1)
    write_compatibility_mirror(package, newer["run_id"])
    preserved = package / "runs" / f"legacy-{hashlib.sha256(original).hexdigest()}" / "transcript.json"
    assert preserved.read_bytes() == original
    assert legacy.read_bytes() == (package / "runs" / newer["run_id"] / "transcript.json").read_bytes()
    assert len(list_runs(package)) == 2


def test_invalid_root_is_preserved_even_with_forged_mirror_projection(tmp_path):
    import tda_companion.transcription_runs as runs
    package = tmp_path / "source"
    package.mkdir()
    root = package / "transcript.json"
    root.write_bytes(b'{"private":"invalid legacy"}')
    original = root.read_bytes()
    newer = write_completed_run(package, _document("a" * 64, "qwen-quality", "New B"), job_id="new", attempt=1)
    runs._record_root_state(package, "compatibility_mirror", newer)
    with pytest.raises(TranscriptionRunError, match="TRANSCRIPTION_LEGACY_PRESERVED_IN_PLACE"):
        write_compatibility_mirror(package, newer["run_id"])
    assert root.read_bytes() == original
    assert load_run(package, newer["run_id"])["status"] == "completed"
    assert runs.root_transcript_state(package) == {"kind": "invalid_legacy_preserved"}


def test_catalog_never_opens_transcripts_for_modern_or_legacy_sources(monkeypatch, tmp_path):
    package = tmp_path / "source"
    package.mkdir()
    modern = write_completed_run(package, _document("a" * 64, "qwen-quality", "Modern"), job_id="modern", attempt=1)
    write_compatibility_mirror(package, modern["run_id"])
    legacy_package = tmp_path / "legacy"
    legacy_package.mkdir()
    _document("b" * 64, "whisper-detailed", "Old").write_atomic(legacy_package / "transcript.json")
    original_open = Path.open
    def without_content(path, *args, **kwargs):
        assert path.name != "transcript.json", "catalog opened transcript content"
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", without_content)
    for _ in range(3):
        current = ensure_legacy_and_list(package, source_id="source", source_sha256="a" * 64)
        assert len(current["runs"]) == 1
        assert current["root_transcript"] == {"kind": "compatibility_mirror"}
        historical = ensure_legacy_and_list(legacy_package, source_id="legacy", source_sha256="b" * 64)
        assert historical["runs"] == []
        assert historical["root_transcript"] == {"kind": "unclassified_legacy_candidate"}
    assert not (legacy_package / "runs").exists()
    assert not (legacy_package / ".root-transcript.lock").exists()


def test_failed_preservation_fence_never_authorizes_mirror_until_reconfirmed(monkeypatch, tmp_path):
    import tda_companion.transcription_runs as runs
    from tda_companion.atomic_storage import AtomicStorageError
    package = tmp_path / "source"
    package.mkdir()
    legacy = package / "transcript.json"
    _document("a" * 64, "whisper-detailed", "Historical A").write_atomic(legacy)
    original = legacy.read_bytes()
    newer = write_completed_run(package, _document("a" * 64, "qwen-quality", "New B"), job_id="new", attempt=1)
    original_write = runs._atomic_json
    def ambiguous(path, value):
        original_write(path, value)
        if path.name == "run.json":
            raise AtomicStorageError("namespace_sync", True)
    monkeypatch.setattr(runs, "_atomic_json", ambiguous)
    with pytest.raises(AtomicStorageError):
        write_compatibility_mirror(package, newer["run_id"])
    assert legacy.read_bytes() == original
    monkeypatch.setattr(runs, "_atomic_json", original_write)
    confirmations = []
    original_confirm = runs.confirm_existing_file
    def confirm(path):
        confirmations.append(path.name)
        original_confirm(path)
    monkeypatch.setattr(runs, "confirm_existing_file", confirm)
    write_compatibility_mirror(package, newer["run_id"])
    assert confirmations == ["transcript.json", "run.json"]
    assert (package / "runs" / f"legacy-{hashlib.sha256(original).hexdigest()}" / "transcript.json").read_bytes() == original


def test_concurrent_migration_and_mirror_serialize_with_one_root_lock(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    package = tmp_path / "source"
    package.mkdir()
    legacy = package / "transcript.json"
    _document("a" * 64, "whisper-detailed", "Historical A").write_atomic(legacy)
    original = legacy.read_bytes()
    newer = write_completed_run(package, _document("a" * 64, "qwen-quality", "New B"), job_id="new", attempt=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        migration = pool.submit(migrate_legacy_transcript, package, source_id="source", source_sha256="a" * 64)
        mirror = pool.submit(write_compatibility_mirror, package, newer["run_id"])
        assert migration.result() is not None
        assert mirror.result() == newer["transcript_sha256"]
    assert (package / "runs" / f"legacy-{hashlib.sha256(original).hexdigest()}" / "transcript.json").read_bytes() == original


def test_root_lock_serializes_an_independent_worker_process(tmp_path):
    import subprocess
    import sys
    import tda_companion.transcription_runs as runs
    package = tmp_path / "source"
    package.mkdir()
    _document("a" * 64, "whisper-detailed", "Old").write_atomic(package / "transcript.json")
    original = (package / "transcript.json").read_bytes()
    modern = write_completed_run(package, _document("a" * 64, "qwen-quality", "New"), job_id="new", attempt=1)
    script = """
import sys
from pathlib import Path
from tda_companion.transcription_runs import write_compatibility_mirror
print('ready', flush=True)
write_compatibility_mirror(Path(sys.argv[1]), sys.argv[2])
"""
    with runs._root_transcript_lock(package):
        process = subprocess.Popen([sys.executable, "-c", script, str(package), modern["run_id"]],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert process.stdout.readline().strip() == "ready"
        assert process.poll() is None
        assert (package / "transcript.json").read_bytes() == original
    stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stderr
    assert (package / "runs" / f"legacy-{hashlib.sha256(original).hexdigest()}" / "transcript.json").read_bytes() == original


def test_catalog_of_100_sources_reads_zero_transcript_bytes(monkeypatch, tmp_path):
    packages = []
    for index in range(100):
        package = tmp_path / f"source-{index}"
        package.mkdir()
        run = write_completed_run(package, _document("a" * 64, "qwen-quality", "synthetic"), job_id="run", attempt=1)
        write_compatibility_mirror(package, run["run_id"])
        packages.append(package)
    import threading
    test_thread = threading.get_ident()
    original_open = Path.open
    opened = []
    def metadata_only(path, *args, **kwargs):
        # Path.open is process-global: unrelated worker/runtime threads may still
        # perform legitimate I/O while this focused catalog assertion runs.
        # Observe only the synchronous call path under test.
        if threading.get_ident() == test_thread:
            assert path.name != "transcript.json"
            opened.append(path.name)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", metadata_only)
    for package in packages:
        result = ensure_legacy_and_list(package, source_id=package.name, source_sha256="a" * 64)
        assert len(result["runs"]) == 1
    assert set(opened) == {"run.json", "root-transcript-state.json"}
