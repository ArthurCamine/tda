from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
from dataclasses import replace

import pytest

from tda_companion.local_review import (
    LocalReviewError,
    open_review,
    review_summary,
    save_review,
)
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import write_completed_run


def _document(source_sha: str, text: str = "Texto original") -> TranscriptDocument:
    first = TranscriptSegment(
        id="1-0",
        start=0.0,
        end=1.0,
        text=text,
        words=(TranscriptWord(text="Texto", start=0.0, end=0.4, confidence=0.9),),
    )
    second = TranscriptSegment(
        id="1-1",
        start=1.2,
        end=2.2,
        text="Segunda fala",
        words=(TranscriptWord(text="Segunda", start=1.2, end=1.6, confidence=0.8),),
    )
    track = TranscriptTrack(
        number=1,
        speaker="Alice",
        source_filename="1-Alice.flac",
        source_sha256="a" * 64,
        duration_seconds=3.0,
        segments=(first, second),
    )
    return TranscriptDocument(
        recording_id="recording",
        source_sha256=source_sha,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3",
            profile="whisper-detailed",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="test",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=2.0),
        warnings=("LOW_CONFIDENCE",),
    )


def _package(tmp_path: Path) -> tuple[Path, str, dict]:
    source_sha = "b" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    run = write_completed_run(
        package_root,
        _document(source_sha),
        job_id="job-review",
        attempt=1,
    )
    return package_root, source_id, run


def test_open_review_is_pure_without_mutating_raw_run(tmp_path: Path):
    package_root, source_id, run = _package(tmp_path)
    transcript = package_root / "runs" / run["run_id"] / "transcript.json"
    raw_before = transcript.read_bytes()

    review = open_review(
        package_root,
        source_id=source_id,
        run_id=run["run_id"],
    )
    assert review["stats"]["audio_work_seconds"] == 3.0
    assert review["stats"]["session_duration_seconds"] == 3.0
    assert review["lineage"]["execution_lineage"] is None

    assert review["schema_version"] == "tda_local_review_v1"
    assert review["source_id"] == source_id
    assert review["run_id"] == run["run_id"]
    assert review["base_transcript_sha256"] == run["transcript_sha256"]
    assert review["draft_revision"] is None
    assert review["draft_sha256"] is None
    assert review["persistence"] == "ephemeral_base"
    assert review["status"] == "draft"
    assert review["review"] == {
        "reviewed_segments": 0,
        "total_segments": 2,
        "review_percent": 0.0,
        "edited_segments": 0,
        "word_count": 4,
        "warning_count": 1,
    }
    assert review["sync"] == {"status": "not_configured"}
    assert [item["segment_id"] for item in review["segments"]] == ["1-0", "1-1"]
    assert transcript.read_bytes() == raw_before
    assert not (package_root / "revisions").exists()


def test_save_review_is_atomic_recoverable_and_keeps_run_immutable(
    monkeypatch,
    tmp_path: Path,
):
    package_root, source_id, run = _package(tmp_path)
    transcript = package_root / "runs" / run["run_id"] / "transcript.json"
    raw_before = transcript.read_bytes()
    opened = open_review(package_root, source_id=source_id, run_id=run["run_id"])
    segments = [dict(item) for item in opened["segments"]]
    segments[0]["text"] = "Texto corrigido"
    segments[0]["speaker"] = "Sense"
    segments[0]["reviewed"] = True

    saved = save_review(
        package_root,
        source_id=source_id,
        run_id=run["run_id"],
        value={
            **_expected(opened),
            "status": "reviewed",
            "segments": segments,
        },
    )

    assert saved["draft_revision"] == 1
    assert saved["status"] == "reviewed"
    assert saved["review"]["reviewed_segments"] == 1
    assert saved["review"]["edited_segments"] == 1
    assert saved["segments"][0]["text"] == "Texto corrigido"
    assert saved["segments"][0]["speaker"] == "Sense"
    assert transcript.read_bytes() == raw_before

    reopened = open_review(package_root, source_id=source_id, run_id=run["run_id"])
    assert reopened["draft_revision"] == 1
    assert reopened["draft_sha256"] == saved["draft_sha256"]
    assert reopened["segments"][0]["text"] == "Texto corrigido"

    import tda_companion.atomic_storage as review_module

    original_replace = review_module._replace

    def fail_replace(source, target, storage_class):
        if str(target).endswith("draft.json"):
            raise OSError("synthetic disk failure")
        return original_replace(source, target, storage_class)

    monkeypatch.setattr(review_module, "_replace", fail_replace)
    changed = [dict(item) for item in reopened["segments"]]
    changed[1]["reviewed"] = True
    with pytest.raises(OSError, match="LOCAL_WRITE_FAILED"):
        save_review(
            package_root,
            source_id=source_id,
            run_id=run["run_id"],
            value={
                **_expected(reopened),
                "status": "reviewed",
                "segments": changed,
            },
        )

    monkeypatch.setattr(review_module, "_replace", original_replace)
    after_failure = open_review(
        package_root,
        source_id=source_id,
        run_id=run["run_id"],
    )
    assert after_failure["draft_revision"] == 1
    assert after_failure["draft_sha256"] == saved["draft_sha256"]
    assert not list((package_root / "revisions" / run["run_id"]).glob("*.partial"))


@pytest.mark.parametrize("status,percent", [("draft", 0.0), ("reviewed", 50.0), ("approved_local", 100.0)])
def test_review_summary_tracks_saved_status_without_get_mutations(tmp_path, status, percent):
    package, source_id, run = _package(tmp_path)
    manifest = package / "runs" / run["run_id"] / "run.json"
    before = manifest.read_bytes()
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert review_summary(package, run["run_id"]) is None
    assert not (package / "revisions").exists()
    for index, segment in enumerate(opened["segments"]):
        segment["reviewed"] = status == "approved_local" or (status == "reviewed" and index == 0)
    initial_status = "reviewed" if status == "approved_local" else status
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": initial_status, "segments": opened["segments"],
    })
    if status == "approved_local":
        saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(saved), "status": "approved_local", "segments": saved["segments"],
        })
    assert review_summary(package, run["run_id"]) == {
        "status": status, "draft_revision": 1, "review_percent": percent, "updated_at": saved["updated_at"],
    }
    assert manifest.read_bytes() == before
    directory = package / "revisions" / run["run_id"]
    files_before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
    open_review(package, source_id=source_id, run_id=run["run_id"])
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()} == files_before


def test_approval_binds_exact_saved_draft_and_edits_invalidate_it(tmp_path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])

    changed = [dict(item) for item in opened["segments"]]
    changed[0]["text"] = "Texto aprovado"

    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_APPROVAL_REQUIRES_SAVED_DRAFT"):
        save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(opened),
            "status": "approved_local",
            "segments": changed,
        })

    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened),
        "status": "reviewed",
        "segments": changed,
    })
    draft_path = package / "revisions" / run["run_id"] / "draft.json"
    draft_before = draft_path.read_bytes()

    approved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(saved),
        "status": "approved_local",
        "segments": saved["segments"],
    })
    assert approved["status"] == "approved_local"
    assert approved["approval_current"] is True
    assert approved["approved_at"]
    assert approved["draft_revision"] == saved["draft_revision"]
    assert approved["draft_sha256"] == saved["draft_sha256"]
    assert draft_path.read_bytes() == draft_before

    approval = json.loads(draft_path.with_name("approval.json").read_bytes())
    assert approval["approved_draft_revision"] == saved["draft_revision"]
    assert approval["approved_draft_sha256"] == saved["draft_sha256"]

    edited_segments = [dict(item) for item in approved["segments"]]
    edited_segments[1]["text"] = "Nova edição"
    edited = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(approved),
        "status": "reviewed",
        "segments": edited_segments,
    })
    assert edited["draft_revision"] == approved["draft_revision"] + 1
    assert edited["status"] == "reviewed"
    assert edited["approval_current"] is False
    assert edited["approved_at"] is None


def test_missing_or_corrupt_approval_never_preserves_approved_authority(tmp_path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "reviewed", "segments": opened["segments"],
    })
    approved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(saved), "status": "approved_local", "segments": saved["segments"],
    })
    assert approved["status"] == "approved_local"

    approval_path = package / "revisions" / run["run_id"] / "approval.json"
    approval_path.unlink()
    reopened = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert reopened["status"] == "reviewed"
    assert reopened["approval_current"] is False
    assert review_summary(package, run["run_id"])["status"] == "unknown"

    # Legacy approved_local embedded in draft bytes without an exact sidecar is
    # presentation-only history, never current approval authority.
    draft_path = approval_path.with_name("draft.json")
    legacy = json.loads(draft_path.read_bytes())
    legacy["status"] = "approved_local"
    draft_path.write_text(json.dumps(legacy), encoding="utf-8")
    reopened_legacy = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert reopened_legacy["status"] == "reviewed"
    assert reopened_legacy["approval_current"] is False


def _persist_summary_fixture(tmp_path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    return package, source_id, run, package / "revisions" / run["run_id"] / "summary.json"


def test_review_summary_never_reads_large_payloads_and_stale_metadata_fails_safe(monkeypatch, tmp_path):
    package, _, run, _ = _persist_summary_fixture(tmp_path)
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        assert path.name not in {"draft.json", "transcript.json"}, "listing opened large payload"
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    for _ in range(100):
        assert review_summary(package, run["run_id"], base_transcript_sha256=run["transcript_sha256"])["status"] == "draft"
    draft = package / "revisions" / run["run_id"] / "draft.json"
    original = draft.stat()
    os.utime(draft, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    assert review_summary(package, run["run_id"])["status"] == "unknown"


def test_summary_projection_failure_does_not_fail_authoritative_review_save(monkeypatch, tmp_path):
    import tda_companion.local_review as module
    package, source_id, run = _package(tmp_path)
    def fail(*args, **kwargs): raise OSError("synthetic projection failure")
    monkeypatch.setattr(module, "_atomic_summary_json", fail)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "reviewed", "segments": opened["segments"],
    })
    assert saved["draft_revision"] == 1
    assert open_review(package, source_id=source_id, run_id=run["run_id"])["draft_sha256"] == saved["draft_sha256"]
    assert review_summary(package, run["run_id"])["status"] == "unknown"


@pytest.mark.parametrize("field,value", [
    ("base_transcript_sha256", "f" * 64), ("source_id", "other"), ("run_id", "other"),
    ("draft_revision", True), ("review_percent", float("nan")), ("review_percent", float("inf")),
    ("review_percent", 10 ** 400), ("status", []), ("updated_at", "2026-09-26"),
    ("draft_fingerprint", {"size": True}),
])
def test_bad_summary_identity_and_metadata_degrade_without_failing_catalog(tmp_path, field, value):
    package, _, run, path = _persist_summary_fixture(tmp_path)
    data = json.loads(path.read_bytes()); data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    assert review_summary(package, run["run_id"])["status"] == "unknown"


@pytest.mark.parametrize("kind", ["directory", "oversized", "missing", "malformed", "deep-json"])
def test_summary_reader_rejects_invalid_files(tmp_path, kind):
    package, _, run, path = _persist_summary_fixture(tmp_path)
    path.unlink()
    if kind == "directory": path.mkdir()
    elif kind == "oversized": path.write_bytes(b" " * 8193)
    elif kind == "malformed": path.write_bytes(b"{")
    elif kind == "deep-json": path.write_bytes(b"[" * 3000 + b"]" * 3000)
    assert review_summary(package, run["run_id"])["status"] == "unknown"


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO/link guard")
@pytest.mark.parametrize("name", ["draft.json", "summary.json"])
@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_nonregular_summary_and_draft_never_open_or_block(tmp_path, name, kind):
    package, _, run, summary = _persist_summary_fixture(tmp_path)
    path = summary.with_name(name); path.unlink()
    if kind == "fifo": os.mkfifo(path)
    else: path.symlink_to(summary.parent / "nonexistent")
    assert review_summary(package, run["run_id"])["status"] == "unknown"


def test_explicit_summary_rebuild_preserves_authority_and_get_stays_read_only(tmp_path):
    from tda_companion.local_review import rebuild_review_summary
    package, source_id, run, summary = _persist_summary_fixture(tmp_path)
    draft = summary.with_name("draft.json")
    before = draft.read_bytes(), draft.stat().st_mtime_ns
    summary.unlink()
    open_review(package, source_id=source_id, run_id=run["run_id"])
    assert not summary.exists()
    assert review_summary(package, run["run_id"])["status"] == "unknown"
    assert rebuild_review_summary(package, source_id=source_id, run_id=run["run_id"])["status"] == "draft"
    assert (draft.read_bytes(), draft.stat().st_mtime_ns) == before


def test_stale_review_save_conflicts_without_overwrite(tmp_path: Path):
    package_root, source_id, run = _package(tmp_path)
    opened = open_review(package_root, source_id=source_id, run_id=run["run_id"])
    first = [dict(item) for item in opened["segments"]]
    first[0]["text"] = "Vencedor"
    saved = save_review(
        package_root,
        source_id=source_id,
        run_id=run["run_id"],
        value={
            **_expected(opened),
            "status": "draft",
            "segments": first,
        },
    )

    stale = [dict(item) for item in opened["segments"]]
    stale[0]["text"] = "Perdedor"
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_DRAFT_CONFLICT"):
        save_review(
            package_root,
            source_id=source_id,
            run_id=run["run_id"],
            value={
                **_expected(opened),
                "status": "draft",
                "segments": stale,
            },
        )

    current = open_review(package_root, source_id=source_id, run_id=run["run_id"])
    assert current["draft_revision"] == saved["draft_revision"]
    assert current["segments"][0]["text"] == "Vencedor"


def test_segment_identity_and_timing_are_not_editable(tmp_path: Path):
    package_root, source_id, run = _package(tmp_path)
    opened = open_review(package_root, source_id=source_id, run_id=run["run_id"])

    for patch, code in [
        ({"segment_id": "other"}, "LOCAL_REVIEW_SEGMENT_IDENTITY_MISMATCH"),
        ({"start": 99.0}, "LOCAL_REVIEW_SEGMENT_TIMING_IMMUTABLE"),
        ({"end": 99.0}, "LOCAL_REVIEW_SEGMENT_TIMING_IMMUTABLE"),
    ]:
        segments = [dict(item) for item in opened["segments"]]
        segments[0].update(patch)
        with pytest.raises(LocalReviewError, match=code):
            save_review(
                package_root,
                source_id=source_id,
                run_id=run["run_id"],
                value={
                    **_expected(opened),
                    "status": "draft",
                    "segments": segments,
                },
            )


def test_two_runs_keep_independent_review_drafts(tmp_path: Path):
    source_sha = "c" * 64
    source_id = f"craig-{source_sha}"
    package_root = tmp_path / source_id
    package_root.mkdir()
    first = write_completed_run(
        package_root,
        _document(source_sha, "Run A"),
        job_id="job-a",
        attempt=1,
    )
    second = write_completed_run(
        package_root,
        _document(source_sha, "Run B"),
        job_id="job-b",
        attempt=1,
    )

    a = open_review(package_root, source_id=source_id, run_id=first["run_id"])
    b = open_review(package_root, source_id=source_id, run_id=second["run_id"])
    edited = [dict(item) for item in a["segments"]]
    edited[0]["text"] = "Somente A"
    save_review(
        package_root,
        source_id=source_id,
        run_id=first["run_id"],
        value={
            **_expected(a),
            "status": "draft",
            "segments": edited,
        },
    )

    current_b = open_review(package_root, source_id=source_id, run_id=second["run_id"])
    assert current_b["draft_revision"] is None
    assert current_b["segments"][0]["text"] == b["segments"][0]["text"] == "Run B"


def test_tampered_base_run_cannot_be_reviewed(tmp_path: Path):
    package_root, source_id, run = _package(tmp_path)
    transcript = package_root / "runs" / run["run_id"] / "transcript.json"
    payload = bytearray(transcript.read_bytes())
    payload[-2] = ord(" ")
    transcript.write_bytes(bytes(payload))

    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_BASE_RUN_INVALID"):
        open_review(package_root, source_id=source_id, run_id=run["run_id"])


def test_review_parses_exact_bytes_verified_even_if_path_changes(monkeypatch, tmp_path: Path):
    import tda_companion.transcription_runs as runs
    package, source_id, run = _package(tmp_path)
    path = package / "runs" / run["run_id"] / "transcript.json"
    original_read = runs._bounded_transcript

    def replace_after_read(target):
        payload = original_read(target)
        value = json.loads(payload)
        value["tracks"][0]["segments"][0]["text"] = "Different base"
        path.write_text(json.dumps(value), encoding="utf-8")
        return payload

    monkeypatch.setattr(runs, "_bounded_transcript", replace_after_read)
    review = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert review["segments"][0]["text"] == "Texto original"
    assert review["base_transcript_sha256"] == run["transcript_sha256"]


def test_save_reads_one_base_snapshot(monkeypatch, tmp_path: Path):
    import tda_companion.local_review as reviews
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    original = reviews.load_verified_transcript_snapshot
    reads = []

    def count(*args):
        reads.append(args)
        return original(*args)

    monkeypatch.setattr(reviews, "load_verified_transcript_snapshot", count)
    save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    assert len(reads) == 1


def test_semantically_invalid_historical_run_fails_before_creating_draft(tmp_path: Path):
    package, source_id, run = _package(tmp_path)
    path = package / "runs" / run["run_id"] / "transcript.json"
    value = json.loads(path.read_bytes())
    value["stats"]["word_count"] = 999
    payload = json.dumps(value).encode()
    path.write_bytes(payload)
    run.update(origin="legacy_transcript_v1", transcript_sha256=hashlib.sha256(payload).hexdigest(), transcript_size_bytes=len(payload))
    (path.parent / "run.json").write_text(json.dumps(run))
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_BASE_RUN_INVALID"):
        open_review(package, source_id=source_id, run_id=run["run_id"])
    assert not (package / "revisions").exists()


def test_reordered_save_is_noop_and_real_edits_use_immutable_base_order(tmp_path: Path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    opened = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    reversed_segments = list(reversed(opened["segments"]))
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": reversed_segments,
    })
    assert saved["draft_revision"] == opened["draft_revision"]
    assert saved["draft_sha256"] == opened["draft_sha256"]
    reversed_segments[0]["text"] = "Real edit"
    edited = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": reversed_segments,
    })
    assert [row["segment_id"] for row in edited["segments"]] == ["1-0", "1-1"]
    assert edited["segments"][1]["text"] == "Real edit"
    assert edited["review"]["edited_segments"] == 1


@pytest.mark.parametrize("count", [0, 1, 999, 1000, 1001, 5000])
def test_warning_projection_preserves_factual_total(tmp_path: Path, count: int):
    package = tmp_path / "source"
    package.mkdir()
    document = replace(_document("a" * 64), warnings=tuple(f"WARNING_{i}" for i in range(count)))
    run = write_completed_run(package, document, job_id="warnings", attempt=1)
    review = open_review(package, source_id="source", run_id=run["run_id"])
    assert len(review["warnings"]) == min(count, 1000)
    assert review["review"]["warning_count"] == run["stats"]["warning_count"] == count
    assert review["warning_summary"] == {"total_count": count, "displayed_count": min(count, 1000), "truncated": count > 1000}


def test_editorial_word_count_uses_canonical_whitespace_without_rewrite(tmp_path: Path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    opened["segments"][0]["text"] = "a\u0085b\ufeffc"
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    assert saved["review"]["word_count"] == 4
    assert saved["segments"][0]["text"] == "a\u0085b\ufeffc"


def _expected(review):
    expected = ({"persistence": "ephemeral_base", "base_transcript_sha256": review["base_transcript_sha256"]}
                if review["persistence"] == "ephemeral_base" else
                {"persistence": "persisted", "draft_revision": review["draft_revision"], "draft_sha256": review["draft_sha256"]})
    return {"snapshot_contract": "tda_local_review_cas_v1", "expected": expected}


def test_repeated_open_is_stable_without_editorial_storage(tmp_path):
    package, source_id, run = _package(tmp_path)
    before = {str(p.relative_to(package)): (p.stat().st_mtime_ns, p.read_bytes())
              for p in package.rglob("*") if p.is_file()}
    a = open_review(package, source_id=source_id, run_id=run["run_id"])
    b = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert a == b
    assert a["created_at"] is a["updated_at"] is None
    assert before == {str(p.relative_to(package)): (p.stat().st_mtime_ns, p.read_bytes())
                      for p in package.rglob("*") if p.is_file()}
    assert not (package / "revisions").exists()


def test_two_first_saves_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])

    def save(text):
        segments = [dict(item) for item in opened["segments"]]
        segments[0]["text"] = text
        try:
            return save_review(package, source_id=source_id, run_id=run["run_id"], value={
                **_expected(opened), "status": "draft", "segments": segments,
            })
        except LocalReviewError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["First", "Second"]))
    assert results.count("LOCAL_REVIEW_DRAFT_CONFLICT") == 1
    winner = next(item for item in results if isinstance(item, dict))
    assert winner["draft_revision"] == 1
    assert open_review(package, source_id=source_id, run_id=run["run_id"]) == winner


def test_same_revision_changed_bytes_conflict_and_preserve_restored_snapshot(tmp_path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    path = package / "revisions" / run["run_id"] / "draft.json"
    restored = json.loads(path.read_bytes())
    restored["segments"][0]["text"] = "Restored at the same revision"
    changed_bytes = json.dumps(restored).encode()
    path.write_bytes(changed_bytes)
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_DRAFT_CONFLICT"):
        save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(saved), "status": "reviewed", "segments": saved["segments"],
        })
    assert path.read_bytes() == changed_bytes
    latest = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert latest["draft_revision"] == saved["draft_revision"]
    assert latest["draft_sha256"] != saved["draft_sha256"]
    updated = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(latest), "status": "reviewed", "segments": latest["segments"],
    })
    assert updated["draft_revision"] == 2


@pytest.mark.parametrize("corruption", ["missing-contract", "missing-sha", "invalid-sha", "wrong-base"])
def test_missing_or_invalid_snapshot_precondition_never_creates_draft(tmp_path, corruption):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    request = {**_expected(opened), "status": "draft", "segments": opened["segments"]}
    if corruption == "missing-contract":
        request.pop("snapshot_contract")
    elif corruption == "wrong-base":
        request["expected"]["base_transcript_sha256"] = "f" * 64
    else:
        request["expected"] = {"persistence": "persisted", "draft_revision": 0}
        if corruption == "invalid-sha":
            request["expected"]["draft_sha256"] = "no-hash"
    with pytest.raises(LocalReviewError):
        save_review(package, source_id=source_id, run_id=run["run_id"], value=request)
    assert not (package / "revisions").exists()


def test_historical_revision_zero_remains_persisted_and_requires_its_exact_hash(tmp_path):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    path = package / "revisions" / run["run_id"] / "draft.json"
    legacy = json.loads(path.read_bytes())
    legacy["draft_revision"] = 0
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    historic = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert historic["persistence"] == "persisted"
    assert historic["draft_revision"] == 0
    assert historic["draft_sha256"] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_DRAFT_CONFLICT"):
        save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(opened), "status": "draft", "segments": opened["segments"],
        })


_STRING_CASES = json.loads((Path(__file__).resolve().parents[2] / "fixtures/transcript-review-strings-v1.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _STRING_CASES, ids=lambda case: case["name"])
def test_save_accepts_exact_shared_string_contract_before_write(tmp_path, case):
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    value = ("".join(chr(code) for code in case["codePoints"]) if "codePoints" in case else case["value"]) * case["repeat"]
    opened["segments"][0][case["field"]] = value
    request = {**_expected(opened), "status": "draft", "segments": opened["segments"]}
    if case["valid"]:
        saved = save_review(package, source_id=source_id, run_id=run["run_id"], value=request)
        # Includes JSON's real UTF-8 response path and reopen, not just validation.
        json.dumps(saved, ensure_ascii=False).encode("utf-8")
        assert saved["segments"][0][case["field"]] == value
        assert open_review(package, source_id=source_id, run_id=run["run_id"]) == saved
    else:
        with pytest.raises(LocalReviewError, match=f"LOCAL_REVIEW_SEGMENT_{case['field'].upper()}_INVALID"):
            save_review(package, source_id=source_id, run_id=run["run_id"], value=request)
        assert not (package / "revisions").exists()


def test_legacy_invalid_strings_require_explicit_repair_and_preserve_original(tmp_path):
    from tda_companion.local_review import repair_legacy_review
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    saved = save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(saved), "status": "approved_local", "segments": saved["segments"],
    })
    path = package / "revisions" / run["run_id"] / "draft.json"
    legacy = json.loads(path.read_bytes())
    legacy["segments"][0]["text"] = "PRIVATE\ud800"
    before = json.dumps(legacy).encode("utf-8")
    path.write_bytes(before)
    with pytest.raises(LocalReviewError, match="^LOCAL_REVIEW_LEGACY_STRING_REPAIR_REQUIRED$"):
        open_review(package, source_id=source_id, run_id=run["run_id"])
    assert path.read_bytes() == before
    digest = hashlib.sha256(before).hexdigest()
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_DRAFT_CONFLICT"):
        repair_legacy_review(package, source_id=source_id, run_id=run["run_id"],
                             expected_revision=1, expected_sha256="f" * 64, segments=opened["segments"])
    assert path.read_bytes() == before
    fixed = repair_legacy_review(package, source_id=source_id, run_id=run["run_id"],
                                 expected_revision=1, expected_sha256=digest, segments=opened["segments"])
    assert fixed["draft_revision"] == 2
    assert fixed["status"] == "draft"
    assert path.with_name(f"draft-before-repair-{digest}.json").read_bytes() == before
    assert open_review(package, source_id=source_id, run_id=run["run_id"]) == fixed


def test_offline_repair_cli_respects_agent_root_lock(tmp_path):
    import subprocess
    import sys
    from tda_companion.__main__ import RootLock
    staging = tmp_path / "staging"
    staging.mkdir()
    package, source_id, run = _package(staging)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    save_review(package, source_id=source_id, run_id=run["run_id"], value={
        **_expected(opened), "status": "draft", "segments": opened["segments"],
    })
    path = package / "revisions" / run["run_id"] / "draft.json"
    legacy = json.loads(path.read_bytes())
    legacy["segments"][0]["speaker"] = "Old\nName"
    before = json.dumps(legacy).encode()
    path.write_bytes(before)
    replacement = tmp_path / "repair-input.json"
    replacement.write_text(json.dumps({"segments": opened["segments"]}), encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "tools/repair_local_review.py"),
               "--data-root", str(tmp_path), "--package-root", str(package), "--run-id", run["run_id"],
               "--expected-revision", "1", "--expected-sha256", hashlib.sha256(before).hexdigest(),
               "--replacement-file", str(replacement)]
    with RootLock(tmp_path):
        blocked = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert blocked.returncode != 0
        assert path.read_bytes() == before
    repaired = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert repaired.returncode == 0, repaired.stderr
    assert json.loads(repaired.stdout)["original_preserved"] is True
    assert "Old" not in repaired.stdout
    assert open_review(package, source_id=source_id, run_id=run["run_id"])["draft_revision"] == 2


def test_review_reports_ambiguous_post_replace_without_losing_committed_text(monkeypatch, tmp_path):
    import tda_companion.atomic_storage as storage
    package, source_id, run = _package(tmp_path)
    opened = open_review(package, source_id=source_id, run_id=run["run_id"])
    opened["segments"][0]["text"] = "Survives an unconfirmed fence"
    def fail_namespace(_path):
        raise OSError("synthetic fence failure")
    monkeypatch.setattr(storage, "sync_namespace", fail_namespace)
    with pytest.raises(LocalReviewError, match="^LOCAL_REVIEW_WRITE_UNCONFIRMED$"):
        save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(opened), "status": "draft", "segments": opened["segments"],
        })
    confirmed = open_review(package, source_id=source_id, run_id=run["run_id"])
    assert confirmed["draft_revision"] == 1
    assert confirmed["segments"][0]["text"] == "Survives an unconfirmed fence"
    with pytest.raises(LocalReviewError, match="LOCAL_REVIEW_DRAFT_CONFLICT"):
        save_review(package, source_id=source_id, run_id=run["run_id"], value={
            **_expected(opened), "status": "draft", "segments": opened["segments"],
        })
