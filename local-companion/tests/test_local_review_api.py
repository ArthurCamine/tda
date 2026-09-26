from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from tda_companion.api import create_app
from tda_companion.attempt_fence import claim_attempt_outcome
from tda_companion.craig_ingest_http import CraigIngestBoundary
from tda_companion.craig_runtime import load_craig_package
from tda_companion.publication_target import bind_publication_target
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import write_completed_run

TOKEN = "r" * 43
ORIGIN = "https://dnd.faysk.dev"


def _payload() -> bytes:
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-alice-review")
    return value.getvalue()


def _client(tmp_path: Path) -> TestClient:
    root = tmp_path / "Data"
    root.mkdir()
    api = create_app(root, TOKEN, {ORIGIN}, run_worker=False)
    app = CraigIngestBoundary(
        api,
        data_root=root,
        token=TOKEN,
        origins=frozenset({ORIGIN}),
        port=8765,
        browser_sessions=api.state.browser_sessions,
        source_gate=api.state.source_gate,
        source_running=api.state.source_in_use,
        run_visible=api.state.transcription_run_visible,
    )
    return TestClient(app, base_url="http://127.0.0.1:8765")


def _document(package) -> TranscriptDocument:
    source = package.tracks[0]
    segment = TranscriptSegment(
        id="1-0",
        start=0.1,
        end=0.9,
        text="SEGREDO EDITORIAL LOCAL",
        words=(
            TranscriptWord(
                text="SEGREDO",
                start=0.1,
                end=0.4,
                confidence=0.91,
            ),
        ),
    )
    track = TranscriptTrack(
        number=source.number,
        speaker="Alice",
        source_filename=source.filename,
        source_sha256=source.sha256,
        duration_seconds=1.0,
        segments=(segment,),
        timeline_offset_seconds=source.timeline_offset_seconds,
    )
    return TranscriptDocument(
        recording_id=package.recording_id,
        source_sha256=package.source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3",
            profile="whisper-detailed",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="review-test",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=1.5),
        warnings=("LOW_CONFIDENCE",),
    )


def _stage_and_run(client: TestClient, tmp_path: Path, *, job_id: str = "job-review-api"):
    upload = client.post(
        "/api/v1/sources/craig",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Origin": ORIGIN,
            "Content-Type": "application/zip",
        },
        content=_payload(),
    )
    assert upload.status_code == 200
    source_id = upload.json()["source_id"]
    package_root = tmp_path / "Data" / "staging" / source_id
    package = load_craig_package(package_root, verify_tracks=True)
    run = write_completed_run(
        package_root,
        _document(package),
        job_id=job_id,
        attempt=1,
    )
    return source_id, package_root, run


def _browser_headers(client: TestClient) -> dict[str, str]:
    session = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        json={},
    )
    assert session.status_code == 200
    return {
        "Authorization": f"Bearer {session.json()['token']}",
        "Origin": ORIGIN,
    }


def test_review_api_loads_only_on_explicit_selection_and_persists_draft(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, package_root, run = _stage_and_run(client, tmp_path)
        headers = _browser_headers(client)
        raw_path = package_root / "runs" / run["run_id"] / "transcript.json"
        raw_before = raw_path.read_bytes()

        listing = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers=headers,
        )
        assert listing.status_code == 200
        assert "SEGREDO EDITORIAL LOCAL" not in json.dumps(listing.json())
        assert listing.json()["runs"][0]["review"] is None

        review = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers=headers,
        )
        assert review.status_code == 200
        opened = review.json()
        assert opened["schema_version"] == "tda_local_review_v1"
        assert opened["segments"][0]["text"] == "SEGREDO EDITORIAL LOCAL"
        assert opened["sync"] == {"status": "not_configured"}
        assert str(tmp_path) not in json.dumps(opened)

        after_open = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers=headers,
        )
        assert after_open.status_code == 200
        assert after_open.json()["runs"][0]["review"] is None
        assert "SEGREDO EDITORIAL LOCAL" not in json.dumps(after_open.json())

        segments = [dict(item) for item in opened["segments"]]
        segments[0]["text"] = "Texto revisado"
        segments[0]["speaker"] = "Sense"
        segments[0]["reviewed"] = True
        saved = client.post(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={**headers, "Content-Type": "application/json"},
            json={
                **_expected(opened),
                "status": "reviewed",
                "segments": segments,
            },
        )
        assert saved.status_code == 200
        saved_value = saved.json()
        assert saved_value["draft_revision"] == 1
        assert saved_value["status"] == "reviewed"
        assert saved_value["approval_current"] is False

        approved = client.post(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={**headers, "Content-Type": "application/json"},
            json={
                **_expected(saved_value),
                "status": "approved_local",
                "segments": saved_value["segments"],
            },
        )
        assert approved.status_code == 200
        value = approved.json()
        assert value["draft_revision"] == 1
        assert value["status"] == "approved_local"
        assert value["approval_current"] is True
        assert value["approved_at"]
        assert value["review"]["review_percent"] == 100.0
        assert value["review"]["edited_segments"] == 1
        assert raw_path.read_bytes() == raw_before

        after_save = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers=headers,
        )
        assert after_save.status_code == 200
        assert after_save.json()["runs"][0]["review"] == {
            "status": "approved_local",
            "draft_revision": 1,
            "review_percent": 100.0,
            "updated_at": value["updated_at"],
        }
        assert "Texto revisado" not in json.dumps(after_save.json())

        reopened = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers=headers,
        )
        assert reopened.status_code == 200
        assert reopened.json()["draft_revision"] == 1
        assert reopened.json()["segments"][0]["text"] == "Texto revisado"


def test_review_api_exposes_only_sanitized_durable_publication_target(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, package_root, run = _stage_and_run(
            client,
            tmp_path,
            job_id="job-publish-target",
        )
        bind_publication_target(
            package_root,
            run_id=run["run_id"],
            job_id="job-publish-target",
            attempt=1,
            campaign_slug="yuhara-main",
            source_session_id="sessao-00001",
            source_id=source_id,
            transcript_sha256=run["transcript_sha256"],
        )
        headers = _browser_headers(client)

        listing = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers=headers,
        )
        assert listing.status_code == 200
        target = listing.json()["runs"][0]["publication_target"]
        assert target == {
            "schema_version": "tda_publication_target_v1",
            "campaign_slug": "yuhara-main",
            "source_session_id": "sessao-00001",
            "source_id": source_id,
            "run_id": run["run_id"],
            "job_id": "job-publish-target",
            "attempt": 1,
            "transcript_sha256": run["transcript_sha256"],
        }

        review = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers=headers,
        )
        assert review.status_code == 200
        assert review.json()["publication_target"] == target
        encoded = json.dumps(review.json(), ensure_ascii=False)
        assert str(tmp_path) not in encoded


def test_review_api_conflicts_on_stale_draft_revision(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, _package_root, run = _stage_and_run(client, tmp_path)
        headers = _browser_headers(client)
        opened = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers=headers,
        ).json()
        first = [dict(item) for item in opened["segments"]]
        first[0]["text"] = "Primeiro save"

        saved = client.post(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={**headers, "Content-Type": "application/json"},
            json={
                **_expected(opened),
                "status": "draft",
                "segments": first,
            },
        )
        assert saved.status_code == 200

        stale = [dict(item) for item in opened["segments"]]
        stale[0]["text"] = "Save obsoleto"
        conflict = client.post(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={**headers, "Content-Type": "application/json"},
            json={
                **_expected(opened),
                "status": "draft",
                "segments": stale,
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"] == {
            "code": "LOCAL_REVIEW_DRAFT_CONFLICT",
            "recoverable": True,
        }


def test_review_api_never_opens_run_hidden_by_cancel_fence(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, package_root, run = _stage_and_run(
            client,
            tmp_path,
            job_id="job-hidden-review",
        )
        assert claim_attempt_outcome(
            package_root,
            "job-hidden-review",
            1,
            "cancel",
        ) == "cancel"
        headers = _browser_headers(client)

        listing = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers=headers,
        )
        assert listing.status_code == 200
        assert listing.json()["runs"] == []

        review = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers=headers,
        )
        assert review.status_code == 404
        assert review.json()["error"]["code"] == "LOCAL_REVIEW_RUN_NOT_VISIBLE"


def test_review_api_requires_authorization_and_origin_for_writes(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, _package_root, run = _stage_and_run(client, tmp_path)

        unauthorized = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={"Authorization": "Bearer invalid", "Origin": ORIGIN},
        )
        assert unauthorized.status_code == 401

        opened = client.get(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN},
        ).json()
        no_origin = client.post(
            f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                **_expected(opened),
                "status": "draft",
                "segments": opened["segments"],
            },
        )
        assert no_origin.status_code == 403
        assert no_origin.json()["error"]["code"] == "ORIGIN_REQUIRED"


def test_review_preflight_is_narrow_for_get_and_post(tmp_path: Path):
    with _client(tmp_path) as client:
        source_id, _package_root, run = _stage_and_run(client, tmp_path)
        path = f"/api/v1/sources/{source_id}/runs/{run['run_id']}/review"

        get_ok = client.options(
            path,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert get_ok.status_code == 200
        assert get_ok.headers["access-control-allow-methods"] == "GET, POST"

        post_ok = client.options(
            path,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            },
        )
        assert post_ok.status_code == 200

        rejected = client.options(
            path,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "PREFLIGHT_REJECTED"


def test_source_catalog_survives_queue_history_and_never_exposes_paths_or_transcript(
    tmp_path: Path,
):
    with _client(tmp_path) as client:
        source_id, _package_root, _run = _stage_and_run(client, tmp_path)
        headers = _browser_headers(client)

        response = client.get("/api/v1/sources", headers=headers)

        assert response.status_code == 200
        value = response.json()
        assert value["schema_version"] == "tda_craig_sources_v1"
        assert len(value["sources"]) == 1
        source = value["sources"][0]
        assert source["source_id"] == source_id
        assert source["source_sha256"] == source_id.removeprefix("craig-")
        assert source["track_count"] == 1
        encoded = json.dumps(value, ensure_ascii=False)
        assert "SEGREDO EDITORIAL LOCAL" not in encoded
        assert str(tmp_path) not in encoded

        # Source discovery is filesystem-backed, not queue-history-backed.
        assert client.app.app.state.store.jobs() == []
        repeated = client.get("/api/v1/sources", headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["sources"][0]["source_id"] == source_id


def test_source_catalog_requires_auth_and_get_only_preflight(tmp_path: Path):
    with _client(tmp_path) as client:
        _stage_and_run(client, tmp_path)

        unauthorized = client.get(
            "/api/v1/sources",
            headers={"Authorization": "Bearer invalid", "Origin": ORIGIN},
        )
        assert unauthorized.status_code == 401

        allowed = client.options(
            "/api/v1/sources",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-private-network"] == "true"

        rejected = client.options(
            "/api/v1/sources",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "PREFLIGHT_REJECTED"


def _expected(review):
    expected = ({"persistence": "ephemeral_base", "base_transcript_sha256": review["base_transcript_sha256"]}
                if review["persistence"] == "ephemeral_base" else
                {"persistence": "persisted", "draft_revision": review["draft_revision"], "draft_sha256": review["draft_sha256"]})
    return {"snapshot_contract": "tda_local_review_cas_v1", "expected": expected}


def test_catalog_of_100_reviews_only_reads_bounded_metadata(monkeypatch, tmp_path):
    from tda_companion.local_review import open_review, save_review
    import tda_companion.local_review as review_module
    with _client(tmp_path) as client:
        source_id, package_root, first = _stage_and_run(client, tmp_path)
        package = load_craig_package(package_root, verify_tracks=False)
        for index in range(100):
            run = first if index == 0 else write_completed_run(
                package_root, _document(package), job_id=f"catalog-{index}", attempt=1,
            )
            # Explicit authority also keeps this fixture compatible with fail-closed cleanup.
            claim_attempt_outcome(package_root, str(run["job_id"]), 1, "commit")
            opened = open_review(package_root, source_id=source_id, run_id=run["run_id"])
            save_review(package_root, source_id=source_id, run_id=run["run_id"], value={
                **_expected(opened), "status": "draft", "segments": opened["segments"],
            })
        headers = _browser_headers(client)
        original_open = Path.open
        def guard(path, *args, **kwargs):
            assert path.name not in {"draft.json", "transcript.json"}, "catalog opened editorial payload"
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", guard)
        sizes = []
        bounded = review_module._regular_summary_bytes
        def counted(path):
            value = bounded(path)
            sizes.append(len(value))
            return value
        monkeypatch.setattr(review_module, "_regular_summary_bytes", counted)
        listing = client.get(f"/api/v1/sources/{source_id}/runs", headers=headers)
        assert listing.status_code == 200
        rows = listing.json()["runs"]
        assert len(rows) == len(sizes) == 100
        assert all(row["review"]["status"] == "draft" for row in rows)
        assert max(sizes) <= 8192
        assert "SEGREDO EDITORIAL LOCAL" not in listing.text
