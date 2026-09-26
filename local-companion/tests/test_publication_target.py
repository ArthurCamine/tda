from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion.publication_target import (
    PublicationTargetError,
    bind_publication_target,
    load_publication_target,
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


def _document(source_sha256: str) -> TranscriptDocument:
    segment = TranscriptSegment(
        id="1-0",
        start=0.0,
        end=1.0,
        text="conteudo local",
        words=(
            TranscriptWord(
                text="conteudo",
                start=0.0,
                end=0.5,
                confidence=0.99,
            ),
        ),
    )
    track = TranscriptTrack(
        number=1,
        speaker="Alice",
        source_filename="1-Alice.flac",
        source_sha256="a" * 64,
        duration_seconds=1.0,
        segments=(segment,),
    )
    return TranscriptDocument(
        recording_id="recording",
        source_sha256=source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3",
            profile="whisper-detailed",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="target-test",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=1.0),
    )


def _run(tmp_path: Path):
    source_sha = "b" * 64
    source_id = f"craig-{source_sha}"
    root = tmp_path / source_id
    root.mkdir()
    manifest = write_completed_run(
        root,
        _document(source_sha),
        job_id="job-target",
        attempt=1,
    )
    return root, source_id, manifest


def test_publication_target_is_immutable_idempotent_and_contains_no_transcript(
    tmp_path: Path,
):
    root, source_id, run = _run(tmp_path)
    expected = dict(
        run_id=run["run_id"],
        job_id="job-target",
        attempt=1,
        campaign_slug="yuhara-main",
        source_session_id="sessao-00001",
        source_id=source_id,
        transcript_sha256=run["transcript_sha256"],
    )

    first = bind_publication_target(root, **expected)
    second = bind_publication_target(root, **expected)

    assert first == second
    assert first["schema_version"] == "tda_publication_target_v1"
    assert first["campaign_slug"] == "yuhara-main"
    assert first["source_session_id"] == "sessao-00001"
    encoded = json.dumps(first, ensure_ascii=False)
    assert "conteudo local" not in encoded
    assert str(tmp_path) not in encoded
    assert load_publication_target(root, run["run_id"]) == first


def test_publication_target_rejects_divergent_rebind(tmp_path: Path):
    root, source_id, run = _run(tmp_path)
    base = dict(
        run_id=run["run_id"],
        job_id="job-target",
        attempt=1,
        campaign_slug="yuhara-main",
        source_session_id="sessao-00001",
        source_id=source_id,
        transcript_sha256=run["transcript_sha256"],
    )
    bind_publication_target(root, **base)

    with pytest.raises(PublicationTargetError, match="PUBLICATION_TARGET_CONFLICT"):
        bind_publication_target(
            root,
            **{**base, "source_session_id": "sessao-00002"},
        )


def test_publication_target_rejects_run_identity_mismatch(tmp_path: Path):
    root, source_id, run = _run(tmp_path)

    with pytest.raises(
        PublicationTargetError,
        match="PUBLICATION_TARGET_RUN_MISMATCH",
    ):
        bind_publication_target(
            root,
            run_id=run["run_id"],
            job_id="other-job",
            attempt=1,
            campaign_slug="yuhara-main",
            source_session_id="sessao-00001",
            source_id=source_id,
            transcript_sha256=run["transcript_sha256"],
        )


def test_unbound_legacy_style_run_is_not_publishable(tmp_path: Path):
    root, _source_id, run = _run(tmp_path)

    assert load_publication_target(root, run["run_id"]) is None


def test_tampered_target_fails_closed(tmp_path: Path):
    root, source_id, run = _run(tmp_path)
    bind_publication_target(
        root,
        run_id=run["run_id"],
        job_id="job-target",
        attempt=1,
        campaign_slug="yuhara-main",
        source_session_id="sessao-00001",
        source_id=source_id,
        transcript_sha256=run["transcript_sha256"],
    )
    path = root / "runs" / run["run_id"] / "publication-target.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["transcript_sha256"] = "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        PublicationTargetError,
        match="PUBLICATION_TARGET_RUN_MISMATCH",
    ):
        load_publication_target(root, run["run_id"])


@pytest.mark.parametrize("damage", ["missing", "malformed"])
def test_repair_recovers_original_binding_after_queue_cleanup(tmp_path, damage):
    from tda_companion.publication_target import repair_publication_target, publication_target_state
    root, source_id, run = _run(tmp_path)
    expected = bind_publication_target(root, run_id=run["run_id"], job_id="job-target",
        attempt=1, campaign_slug="yuhara-main", source_session_id="sessao-00001",
        source_id=source_id, transcript_sha256=run["transcript_sha256"])
    path = root / "runs" / run["run_id"] / "publication-target.json"
    immutable = (path.parent / "run.json").read_bytes()
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("broken json")
    assert publication_target_state(root, run["run_id"])["publication_target_state"] == "invalid"
    assert repair_publication_target(root, run["run_id"]) == expected
    assert (path.parent / "run.json").read_bytes() == immutable
    assert publication_target_state(root, run["run_id"])["publication_target_state"] == "valid"


def test_repair_without_proof_never_invents_destination(tmp_path):
    from tda_companion.publication_target import repair_publication_target
    root, _, run = _run(tmp_path)
    with pytest.raises(PublicationTargetError, match="PROVENANCE_UNAVAILABLE"):
        repair_publication_target(root, run["run_id"])


def test_repair_checks_succeeded_job_and_full_identity(tmp_path):
    from tda_companion.publication_target import repair_publication_target
    root, source_id, run = _run(tmp_path)
    job = {"id": "job-target", "attempt": 1, "status": "succeeded"}
    body = {"kind": "transcription.craig", "campaign_id": "yuhara-main",
        "session_id": "sessao-00001", "source_id": source_id,
        "profile_id": "whisper-detailed", "units": 1}
    result = {"job_id": job["id"], "campaign_id": body["campaign_id"],
        "session_id": body["session_id"], "source_id": source_id,
        "transcription": {"run_id": run["run_id"], "sha256": run["transcript_sha256"],
        "profile_id": body["profile_id"]}}
    args = dict(job=job, body=body, result=result, source_sha256="b" * 64, track_count=1)
    for changes in ({"status": "failed"}, {"attempt": 2}, {"id": "other"}):
        with pytest.raises(PublicationTargetError, match="PROVENANCE_MISMATCH"):
            repair_publication_target(root, run["run_id"], **{**args, "job": {**job, **changes}})
    for changes in ({"source_id": "other"}, {"profile_id": "qwen-fast"},
                    {"context": "changed"}, {"session_id": "other"}, {"units": 2}):
        with pytest.raises(PublicationTargetError, match="PROVENANCE_MISMATCH"):
            repair_publication_target(root, run["run_id"], **{**args, "body": {**body, **changes}})
    target = repair_publication_target(root, run["run_id"], **args)
    assert target["source_session_id"] == body["session_id"]
    path = root / "runs" / run["run_id"] / "publication-target.json"
    path.unlink()
    # Queue is gone; minimal durable origin survives.
    assert repair_publication_target(root, run["run_id"]) == target


def test_repair_never_rebinds_valid_divergent_target(tmp_path):
    from tda_companion.publication_target import repair_publication_target
    root, source_id, run = _run(tmp_path)
    expected = bind_publication_target(root, run_id=run["run_id"], job_id="job-target",
        attempt=1, campaign_slug="yuhara-main", source_session_id="sessao-00001",
        source_id=source_id, transcript_sha256=run["transcript_sha256"])
    path = root / "runs" / run["run_id"] / "publication-target.json"
    path.write_text(json.dumps({**expected, "source_session_id": "other"}))
    with pytest.raises(PublicationTargetError, match="PUBLICATION_TARGET_CONFLICT"):
        repair_publication_target(root, run["run_id"])
