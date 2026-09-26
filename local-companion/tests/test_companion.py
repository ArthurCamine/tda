import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.api as api_module
from fastapi.testclient import TestClient

from tda_companion.api import (
    LOCAL_JSON_BODY_MAX_BYTES,
    TRANSCRIPTION_TEXT_MAX_CHARS,
    create_app,
)
from tda_companion.attempt_fence import claim_attempt_outcome, read_attempt_outcome
from tda_companion.craig import ingest_craig_zip
from tda_companion.craig_runtime import load_craig_package
from tda_companion.legacy.publication import build_publication_bundle
from tda_companion.store import Conflict, Store
from tda_companion.transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)
from tda_companion.transcription_runs import write_completed_run
from tda_companion.worker_supervisor import WorkerOutcome, WorkerSupervisor

TOKEN = "s" * 43
ORIGIN = "https://panel.example"
BODY = dict(
    kind="synthetic.fixture",
    campaign_id="synthetic-campaign",
    session_id="synthetic-session",
    source_id="synthetic-source",
    units=3,
)
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Origin": ORIGIN,
    "Content-Type": "application/json",
}


def _running_transcription(client, *, key: str):
    data_root = client.app.state.data_root
    source = data_root.parent / f"{key}.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-attempt-fence")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_id = f"craig-{source_sha}"
    package_root = data_root / "staging" / source_id
    ingest_craig_zip(source, package_root)
    body = {
        "kind": "transcription.craig",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": source_id,
        "profile_id": "whisper-turbo",
        "glossary": "",
        "context": "",
        "cpu": False,
        "units": 1,
    }
    job = client.app.state.store.submit(key, body)
    claim = client.app.state.store.claim()
    assert claim == (job["id"], 1)
    return job, package_root


def _recovery_document(package) -> TranscriptDocument:
    source_track = package.tracks[0]
    word = TranscriptWord(
        text="recuperado",
        start=0.1,
        end=0.8,
        confidence=0.95,
    )
    segment = TranscriptSegment(
        id="1-0",
        start=0.1,
        end=0.8,
        text="recuperado",
        words=(word,),
    )
    track = TranscriptTrack(
        number=source_track.number,
        speaker=source_track.speaker,
        source_filename=source_track.filename,
        source_sha256=source_track.sha256,
        duration_seconds=1.0,
        segments=(segment,),
        timeline_offset_seconds=source_track.timeline_offset_seconds,
        identity=None,
    )
    return TranscriptDocument(
        recording_id=package.recording_id,
        source_sha256=package.source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="faster-whisper",
            model="large-v3-turbo",
            profile="whisper-turbo",
            device="cuda",
            compute_type="float16",
            alignment="native",
            model_revision="test-revision",
        ),
        tracks=(track,),
        stats=stats_for_tracks((track,), processing_seconds=1.0),
    )


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def test_shutdown_waits_past_fast_window_until_preparation_thread_exits(
    monkeypatch,
    tmp_path,
):
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=False)
    calls: list[float | None] = []

    def fake_wait(timeout=None):
        calls.append(timeout)
        return len(calls) > 1

    monkeypatch.setattr(app.state.preparation_manager, "wait", fake_wait)

    with TestClient(app, base_url="http://127.0.0.1:8765"):
        pass

    assert calls == [8.0, None]


def test_running_cancel_signals_active_worker_and_stays_cancelled(monkeypatch, tmp_path):
    started = threading.Event()
    cancel_seen = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def fake_run_fixture(
        self,
        *,
        job_id,
        attempt,
        units,
        completed,
        on_progress,
        on_event=None,
        is_cancelled=None,
    ):
        del self, job_id, attempt, units, completed, on_progress, on_event
        assert is_cancelled is not None
        started.set()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not is_cancelled():
            time.sleep(0.01)
        assert is_cancelled()
        cancel_seen.set()
        assert release.wait(2.0)
        stopped.set()
        return WorkerOutcome(
            terminal="cancelled",
            payload={"stage": "user_cancel", "forced": False},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_fixture", fake_run_fixture)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)

    with TestClient(app, base_url="http://127.0.0.1:8765") as live:
        response = live.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "cancel-running-job"},
            json={**BODY, "units": 10},
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        assert started.wait(2.0)

        cancelled = live.post(
            f"/api/v1/jobs/{job_id}/cancel",
            headers=HEADERS,
            json={},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancel_seen.wait(1.0)

        blocked_delete = live.post(
            f"/api/v1/jobs/{job_id}/delete",
            headers=HEADERS,
            json={},
        )
        assert blocked_delete.status_code == 409
        assert blocked_delete.json()["error"]["code"] == "JOB_ACTIVE"

        release.set()
        assert stopped.wait(2.0)
        assert live.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["status"] == "cancelled"

    persisted = Store(tmp_path).get(job_id)
    assert persisted["status"] == "cancelled"
    assert persisted["error"] is None


def test_worker_activity_count_survives_agent_trace_throttle(monkeypatch, tmp_path):
    emitted = threading.Event()

    def fake_run_craig(
        self,
        *,
        job_id,
        attempt,
        source_id,
        profile_id,
        glossary,
        context,
        cpu,
        on_progress,
        on_event=None,
        is_cancelled=None,
    ):
        del (
            self,
            job_id,
            attempt,
            source_id,
            profile_id,
            glossary,
            context,
            cpu,
            on_progress,
            is_cancelled,
        )
        assert on_event is not None
        for completed in range(1, 251):
            on_event(
                SimpleNamespace(
                    type="event",
                    payload={
                        "code": "QWEN_WINDOW_TRANSCRIBED",
                        "stage": "transcription",
                        "track": 1,
                        "total_tracks": 1,
                        "speaker": "Alice",
                        "window": completed,
                        "completed_window_count": completed,
                    },
                )
            )
        emitted.set()
        return WorkerOutcome(
            terminal="cancelled",
            payload={"stage": "test_complete", "forced": False},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_craig", fake_run_craig)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)
    job = app.state.store.submit(
        "activity-throttle",
        {
            "kind": "transcription.craig",
            "campaign_id": "campaign",
            "session_id": "session",
            "source_id": "activity-source",
            "profile_id": "qwen-fast",
            "glossary": "",
            "context": "",
            "cpu": False,
            "units": 1,
        },
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as live:
        assert emitted.wait(10.0)
        deadline = time.monotonic() + 5.0
        state = None
        while time.monotonic() < deadline:
            state = live.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
            if state["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert state is not None
        assert state["status"] == "cancelled"

        response = live.get(
            f"/api/v1/jobs/{job['id']}/activity",
            headers=HEADERS,
        )
        assert response.status_code == 200
        activity = response.json()
        assert activity["attempt"] == 1
        assert {
            (item["metric"], item["track"], item["value"])
            for item in activity["metrics"]
        } == {("qwen_windows_completed", 1, 250)}

        events = live.get(
            f"/api/v1/jobs/{job['id']}/events?limit=200",
            headers=HEADERS,
        ).json()["events"]
        samples = [
            event
            for event in events
            if event["code"] == "QWEN_WINDOW_TRANSCRIBED"
        ]
        assert 1 <= len(samples) < 250


def test_cancelled_craig_source_stays_owned_until_worker_exits(monkeypatch, tmp_path):
    started = threading.Event()
    cancel_seen = threading.Event()
    release = threading.Event()

    def fake_run_craig(
        self,
        *,
        job_id,
        attempt,
        source_id,
        profile_id,
        glossary,
        context,
        cpu,
        on_progress,
        on_event=None,
        is_cancelled=None,
    ):
        del (
            self,
            job_id,
            attempt,
            source_id,
            profile_id,
            glossary,
            context,
            cpu,
            on_progress,
            on_event,
        )
        assert is_cancelled is not None
        started.set()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not is_cancelled():
            time.sleep(0.01)
        assert is_cancelled()
        cancel_seen.set()
        assert release.wait(2.0)
        return WorkerOutcome(
            terminal="cancelled",
            payload={"stage": "user_cancel", "forced": False},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_craig", fake_run_craig)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)
    source = tmp_path / "cancelled-source-owner.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-cancelled-source-owner")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_id = f"craig-{source_sha}"
    ingest_craig_zip(source, tmp_path / "staging" / source_id)
    job = app.state.store.submit(
        "cancelled-craig-source-owner",
        {
            "kind": "transcription.craig",
            "campaign_id": "campaign",
            "session_id": "session",
            "source_id": source_id,
            "profile_id": "whisper-turbo",
            "glossary": "",
            "context": "",
            "cpu": False,
            "units": 1,
        },
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as live:
        assert started.wait(2.0)
        cancelled = live.post(
            f"/api/v1/jobs/{job['id']}/cancel",
            headers=HEADERS,
            json={},
        )
        assert cancelled.status_code == 200
        assert cancel_seen.wait(1.0)
        assert app.state.store.get(job["id"])["status"] == "cancelled"
        assert app.state.source_in_use(source_id) is True

        release.set()
        deadline = time.monotonic() + 2.0
        while app.state.source_in_use(source_id) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert app.state.source_in_use(source_id) is False


def test_agent_shutdown_waits_past_fast_window_until_worker_thread_exits(
    monkeypatch,
    tmp_path,
):
    started = threading.Event()
    cancel_seen = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def fake_run_fixture(
        self,
        *,
        job_id,
        attempt,
        units,
        completed,
        on_progress,
        on_event=None,
        is_cancelled=None,
    ):
        del self, job_id, attempt, units, completed, on_progress, on_event
        assert is_cancelled is not None
        started.set()
        while not is_cancelled():
            time.sleep(0.005)
        cancel_seen.set()
        assert release.wait(2.0)
        stopped.set()
        return WorkerOutcome(
            terminal="cancelled",
            payload={"stage": "shutdown", "forced": False},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_fixture", fake_run_fixture)
    monkeypatch.setattr(api_module, "_WORKER_SHUTDOWN_FAST_SECONDS", 0.05)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)
    live = TestClient(app, base_url="http://127.0.0.1:8765")
    live.__enter__()
    response = live.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": "slow-shutdown-worker"},
        json={**BODY, "units": 10},
    )
    assert response.status_code == 200
    assert started.wait(2.0)

    shutdown_done = threading.Event()

    def close_client():
        try:
            live.__exit__(None, None, None)
        finally:
            shutdown_done.set()

    closer = threading.Thread(target=close_client)
    closer.start()
    assert cancel_seen.wait(1.0)
    time.sleep(0.1)
    assert shutdown_done.is_set() is False

    release.set()
    assert stopped.wait(1.0)
    closer.join(timeout=2.0)
    assert shutdown_done.is_set() is True


def test_agent_shutdown_stops_active_worker_and_leaves_job_retryable(monkeypatch, tmp_path):
    started = threading.Event()
    stopped = threading.Event()

    def fake_run_fixture(
        self,
        *,
        job_id,
        attempt,
        units,
        completed,
        on_progress,
        on_event=None,
        is_cancelled=None,
    ):
        del self, job_id, attempt, units, completed, on_progress, on_event
        assert is_cancelled is not None
        started.set()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not is_cancelled():
            time.sleep(0.01)
        assert is_cancelled()
        stopped.set()
        return WorkerOutcome(
            terminal="cancelled",
            payload={"stage": "shutdown", "forced": False},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_fixture", fake_run_fixture)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)

    with TestClient(app, base_url="http://127.0.0.1:8765") as live:
        response = live.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "shutdown-job"},
            json={**BODY, "units": 10},
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        assert started.wait(2.0)

    assert stopped.wait(2.0)
    recovered = Store(tmp_path).get(job_id)
    assert recovered["status"] == "interrupted"
    assert recovered["stage"] == "interrupted"
    assert recovered["error"] == {"code": "PROCESS_INTERRUPTED", "recoverable": True}
    assert recovered["attempt"] == 1


def test_security_and_validation(client):
    health = client.get("/api/v1/health").json()
    assert set(health) == {
        "product_id",
        "api_version",
        "service_version",
        "pid",
        "port",
        "lifecycle",
    }
    assert health["product_id"] == "tda-companion"
    assert health["api_version"] == "1"
    assert health["port"] == 8765
    assert isinstance(health["pid"], int) and health["pid"] > 0
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/v1/health", headers={"Origin": "null"}).status_code == 403
    for headers, code in [
        ({**HEADERS, "Origin": "https://evil.example"}, 403),
        ({"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, 403),
        ({**HEADERS, "Content-Type": "text/plain"}, 415),
    ]:
        assert client.post("/api/v1/jobs", headers=headers, json=BODY).status_code == code
    response = client.post(
        "/api/v1/jobs",
        headers=HEADERS,
        json={**BODY, "private": "secret-content"},
    )
    assert response.status_code == 422 and "secret-content" not in response.text
    assert (
        client.post(
            "/api/v1/jobs",
            headers=HEADERS,
            content="x" * (LOCAL_JSON_BODY_MAX_BYTES + 1),
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "key"},
            json={**BODY, "units": True},
        ).status_code
        == 422
    )
    response = client.options(
        "/api/v1/jobs",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    assert client.get("/api/v1/jobs/", headers=HEADERS).status_code == 404


def test_cancel_wins_fence_before_worker_commit_and_is_idempotent(client):
    job, package_root = _running_transcription(client, key="cancel-wins-fence")

    response = client.post(
        f"/api/v1/jobs/{job['id']}/cancel",
        headers=HEADERS,
        json={},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert read_attempt_outcome(package_root, job["id"], 1) == "cancel"
    assert claim_attempt_outcome(package_root, job["id"], 1, "commit") == "cancel"

    repeated = client.post(
        f"/api/v1/jobs/{job['id']}/cancel",
        headers=HEADERS,
        json={},
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"


def test_commit_fence_rejects_late_cancel_without_reclassifying_job(client):
    job, package_root = _running_transcription(client, key="commit-wins-fence")
    assert claim_attempt_outcome(package_root, job["id"], 1, "commit") == "commit"

    response = client.post(
        f"/api/v1/jobs/{job['id']}/cancel",
        headers=HEADERS,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "JOB_COMMIT_IN_PROGRESS",
        "recoverable": True,
    }
    assert client.app.state.store.get(job["id"])["status"] == "running"
    assert read_attempt_outcome(package_root, job["id"], 1) == "commit"


def test_cancel_fence_survives_store_restart(client):
    job, package_root = _running_transcription(client, key="cancel-fence-restart")
    response = client.post(
        f"/api/v1/jobs/{job['id']}/cancel",
        headers=HEADERS,
        json={},
    )
    assert response.status_code == 200

    reopened = Store(client.app.state.data_root)
    assert reopened.get(job["id"])["status"] == "cancelled"
    assert read_attempt_outcome(package_root, job["id"], 1) == "cancel"


def test_committed_run_wins_restart_reconciliation_before_late_cancel(tmp_path):
    data_root = tmp_path / "Data"
    store = Store(data_root)
    source = tmp_path / "restart-commit.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-restart-commit")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_id = f"craig-{source_sha}"
    package_root = data_root / "staging" / source_id
    package = ingest_craig_zip(source, package_root)
    body = {
        "kind": "transcription.craig",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": source_id,
        "profile_id": "whisper-turbo",
        "glossary": "",
        "context": "",
        "cpu": False,
        "units": 1,
    }
    job = store.submit("restart-commit", body)
    assert store.claim() == (job["id"], 1)
    assert claim_attempt_outcome(package_root, job["id"], 1, "commit") == "commit"

    manifest = write_completed_run(
        package_root,
        _recovery_document(package),
        job_id=job["id"],
        attempt=1,
        context="",
        glossary="",
    )
    assert (package_root / "runs" / manifest["run_id"] / "run.json").is_file()
    assert store.get(job["id"])["status"] == "running"

    app = create_app(data_root, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as restarted:
        state = restarted.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
        assert state["status"] == "succeeded"
        assert state["result_available"] is True
        assert state["attempt"] == 1

        late_cancel = restarted.post(
            f"/api/v1/jobs/{job['id']}/cancel",
            headers=HEADERS,
            json={},
        )
        assert late_cancel.status_code == 409
        assert late_cancel.json()["error"]["code"] == "JOB_TERMINAL"

    assert read_attempt_outcome(package_root, job["id"], 1) == "commit"


def test_restart_recovers_commit_winner_before_queue_recovery(tmp_path):
    data_root = tmp_path / "Data"
    data_root.mkdir()
    first = create_app(data_root, TOKEN, {ORIGIN}, run_worker=False)

    source = tmp_path / "commit-winner-restart.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-commit-winner")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    source_id = f"craig-{source_sha}"
    package_root = data_root / "staging" / source_id
    package = ingest_craig_zip(source, package_root)

    body = {
        "kind": "transcription.craig",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": source_id,
        "profile_id": "whisper-turbo",
        "glossary": "",
        "context": "",
        "cpu": False,
        "units": 1,
    }
    job = first.state.store.submit("restart-commit-winner", body)
    assert first.state.store.claim() == (job["id"], 1)

    run = write_completed_run(
        package_root,
        _recovery_document(package),
        job_id=job["id"],
        attempt=1,
        before_commit=lambda: (
            claim_attempt_outcome(package_root, job["id"], 1, "commit") == "commit"
            or (_ for _ in ()).throw(AssertionError("commit fence lost"))
        ),
    )
    assert (package_root / "runs" / run["run_id"] / "run.json").is_file()
    assert first.state.store.get(job["id"])["status"] == "running"
    assert read_attempt_outcome(package_root, job["id"], 1) == "commit"

    restarted = create_app(data_root, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(
        restarted,
        base_url="http://127.0.0.1:8765",
    ) as live:
        recovered = live.get(
            f"/api/v1/jobs/{job['id']}",
            headers=HEADERS,
        )
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "succeeded"
        assert recovered.json()["result_available"] is True
        assert recovered.json()["attempt"] == 1

        result = live.get(
            f"/api/v1/jobs/{job['id']}/result",
            headers=HEADERS,
        )
        assert result.status_code == 200
        assert result.json()["transcription"]["run_id"] == run["run_id"]

        late_cancel = live.post(
            f"/api/v1/jobs/{job['id']}/cancel",
            headers=HEADERS,
            json={},
        )
        assert late_cancel.status_code == 409
        assert late_cancel.json()["error"]["code"] == "JOB_TERMINAL"

    persisted = Store(data_root).get(job["id"])
    assert persisted["status"] == "succeeded"
    assert read_attempt_outcome(package_root, job["id"], 1) == "commit"


def test_json_body_budget_accepts_exact_utf8_boundary_and_rejects_next_byte(client):
    headers = {
        "Origin": ORIGIN,
        "Content-Type": "application/json",
    }
    exact = b"{}" + b" " * (LOCAL_JSON_BODY_MAX_BYTES - 2)
    assert len(exact) == LOCAL_JSON_BODY_MAX_BYTES

    accepted = client.post("/api/v1/session", headers=headers, content=exact)
    assert accepted.status_code == 200

    rejected = client.post("/api/v1/session", headers=headers, content=exact + b" ")
    assert rejected.status_code == 413
    assert rejected.json() == {
        "error": {"code": "BODY_TOO_LARGE", "recoverable": False}
    }


def test_transcription_text_limit_remains_a_semantic_guard_below_byte_limit(client):
    payload = {
        "kind": "transcription.craig",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": "craig-" + "a" * 64,
        "profile_id": "whisper-turbo",
        "glossary": "",
        "context": "a" * (TRANSCRIPTION_TEXT_MAX_CHARS + 1),
        "cpu": False,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) < LOCAL_JSON_BODY_MAX_BYTES

    response = client.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": "text-char-limit"},
        content=encoded,
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "INVALID_REQUEST", "recoverable": False}
    }


def test_conflict_recoverability_matches_whether_repeating_can_help(client):
    first = client.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": "conflict-contract"},
        json=BODY,
    )
    assert first.status_code == 200
    job_id = first.json()["id"]

    idem_conflict = client.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": "conflict-contract"},
        json={**BODY, "units": 4},
    )
    assert idem_conflict.status_code == 409
    assert idem_conflict.json() == {
        "error": {"code": "IDEMPOTENCY_CONFLICT", "recoverable": False}
    }

    retry_queued = client.post(
        f"/api/v1/jobs/{job_id}/retry",
        headers=HEADERS,
        json={},
    )
    assert retry_queued.status_code == 409
    assert retry_queued.json() == {
        "error": {"code": "JOB_NOT_RETRYABLE", "recoverable": False}
    }

    delete_active = client.post(
        f"/api/v1/jobs/{job_id}/delete",
        headers=HEADERS,
        json={},
    )
    assert delete_active.status_code == 409
    assert delete_active.json() == {
        "error": {"code": "JOB_ACTIVE", "recoverable": True}
    }


def test_browser_session_bootstraps_without_exposing_master_token(client):
    response = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        json={},
    )
    assert response.status_code == 200
    value = response.json()
    assert value["schema"] == "tda_loopback_session_v1"
    assert isinstance(value["token"], str) and len(value["token"]) >= 32
    assert value["token"] != TOKEN
    assert value["expires_in_seconds"] >= 60
    assert TOKEN not in response.text

    browser_headers = {
        "Authorization": f"Bearer {value['token']}",
        "Origin": ORIGIN,
    }
    jobs = client.get("/api/v1/jobs", headers=browser_headers)
    assert jobs.status_code == 200
    assert jobs.json() == {"jobs": []}

    # Browser-scoped credentials require the exact issuing Origin.
    assert client.get(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {value['token']}"},
    ).status_code == 401
    assert client.get(
        "/api/v1/jobs",
        headers={**browser_headers, "Origin": "https://evil.example"},
    ).status_code == 403

    # The temporary browser credential is intentionally narrower than the
    # master token: Web processing endpoints are allowed, local administration is not.
    logs = client.get("/api/v1/logs", headers=browser_headers)
    assert logs.status_code == 403
    assert logs.json() == {
        "error": {"code": "BROWSER_SESSION_SCOPE_REJECTED", "recoverable": False}
    }
    agent = client.get("/api/v1/agent", headers=browser_headers)
    assert agent.status_code == 403
    control = client.post(
        "/api/v1/agent/control",
        headers={**browser_headers, "Content-Type": "application/json"},
        json={"action": "shutdown", "force": False},
    )
    assert control.status_code == 403
    assert client.get("/api/v1/logs", headers=HEADERS).status_code == 200

    assert client.post(
        "/api/v1/session",
        headers={"Content-Type": "application/json"},
        json={},
    ).status_code == 403
    assert client.post(
        "/api/v1/session",
        headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
        json={},
    ).status_code == 403


def test_profile_preparation_api_is_authenticated_and_returns_sanitized_status(
    client,
    monkeypatch,
):
    source_id = "craig-" + "a" * 64
    state = {
        "schema": "tda_profile_preparation_v1",
        "state": "running",
        "active": True,
        "operation_id": "op123",
        "source_id": source_id,
        "profile_id": "qwen-quality",
        "engine": "qwen3",
        "stage": "qwen_probe",
        "title": "Verificando CUDA e runtime…",
        "detail": "Validação local.",
        "sequence": 2,
        "error_code": None,
        "elapsed_seconds": 1.5,
    }
    manager = client.app.state.preparation_manager
    monkeypatch.setattr(manager, "start", lambda source, profile: state)
    monkeypatch.setattr(manager, "snapshot", lambda: state)

    assert client.get("/api/v1/preparation").status_code == 401

    response = client.get("/api/v1/preparation", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == state
    assert "path" not in response.text.casefold()
    assert "token" not in response.text.casefold()

    response = client.post(
        "/api/v1/preparation",
        headers=HEADERS,
        json={"source_id": source_id, "profile_id": "qwen-quality"},
    )
    assert response.status_code == 200
    assert response.json()["operation_id"] == "op123"


def test_preparation_validation_errors_are_non_recoverable(client):
    invalid_source = client.post(
        "/api/v1/preparation",
        headers=HEADERS,
        json={
            "source_id": "not-a-craig-source",
            "profile_id": "qwen-quality",
        },
    )
    assert invalid_source.status_code == 422
    assert invalid_source.json()["error"] == {
        "code": "INVALID_REQUEST",
        "recoverable": False,
    }

    invalid_profile = client.post(
        "/api/v1/preparation",
        headers=HEADERS,
        json={
            "source_id": "craig-" + "a" * 64,
            "profile_id": "whisper-magic",
        },
    )
    assert invalid_profile.status_code == 422
    assert invalid_profile.json()["error"] == {
        "code": "INVALID_REQUEST",
        "recoverable": False,
    }


def test_preparation_cannot_jump_a_queued_transcription(client, monkeypatch):
    source_id = "craig-" + "a" * 64
    queued = client.app.state.store.submit(
        "queued-before-preparation",
        {
            "kind": "transcription.craig",
            "campaign_id": "campaign",
            "session_id": "session",
            "source_id": source_id,
            "profile_id": "qwen-quality",
            "glossary": "",
            "context": "",
            "cpu": False,
            "units": 2,
        },
    )
    assert queued["status"] == "queued"

    manager = client.app.state.preparation_manager
    monkeypatch.setattr(
        manager,
        "start",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("preparation must not start ahead of queued transcription")
        ),
    )

    response = client.post(
        "/api/v1/preparation",
        headers=HEADERS,
        json={"source_id": source_id, "profile_id": "qwen-quality"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "TRANSCRIPTION_PREPARATION_BLOCKED_BY_ACTIVE_JOB",
        "recoverable": True,
    }


def test_synthetic_queue_does_not_block_profile_preparation(client, monkeypatch):
    queued = client.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": "synthetic-before-preparation"},
        json=BODY,
    )
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    manager = client.app.state.preparation_manager
    monkeypatch.setattr(
        manager,
        "start",
        lambda source_id, profile_id: {
            "schema": "tda_profile_preparation_v1",
            "state": "running",
            "active": True,
            "operation_id": "synthetic-does-not-block",
            "source_id": source_id,
            "profile_id": profile_id,
            "engine": "qwen3",
            "stage": "starting",
            "title": "Iniciando preparação…",
            "detail": "",
            "sequence": 1,
            "error_code": None,
            "elapsed_seconds": 0.0,
        },
    )

    response = client.post(
        "/api/v1/preparation",
        headers=HEADERS,
        json={
            "source_id": "craig-" + "b" * 64,
            "profile_id": "qwen-quality",
        },
    )

    assert response.status_code == 200
    assert response.json()["operation_id"] == "synthetic-does-not-block"


def test_api_lifecycle_result(client):
    headers = {**HEADERS, "Idempotency-Key": "fixture-1"}
    job = client.post("/api/v1/jobs", headers=headers, json=BODY).json()
    assert job["status"] == "queued"
    assert client.post("/api/v1/jobs", headers=headers, json=BODY).json()["id"] == job["id"]
    assert (
        client.post(
            "/api/v1/jobs",
            headers=headers,
            json={**BODY, "units": 4},
        ).status_code
        == 409
    )
    store = client.app.state.store
    client.post("/api/v1/lifecycle", headers=HEADERS, json={"action": "pause"})
    assert store.claim() is None
    client.post("/api/v1/lifecycle", headers=HEADERS, json={"action": "resume"})
    claimed = store.claim()
    while store.step(*claimed):
        pass
    result = client.get(f"/api/v1/jobs/{job['id']}/result", headers=HEADERS).json()
    assert result["publication_bundle"]["schema_version"] == "publication_bundle_v1"
    assert result["source_id"] == result["publication_bundle"]["session"]["source_id"]
    assert result["sync"]["status"] == "not_configured"
    artifacts = result["import_artifacts"]
    assert (
        hashlib.sha256(artifacts["publication_payload_json"].encode("utf-8")).hexdigest()
        == result["publication_bundle"]["publication_id"]
    )
    assert (
        hashlib.sha256(artifacts["transcript_json"].encode("utf-8")).hexdigest()
        == result["publication_bundle"]["source_manifest"]["transcript_sha256"]
    )
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=HEADERS, json={}).status_code == 409
    assert client.get("/api/v1/capabilities", headers=HEADERS).json()["sync"] is False


def test_duplicate_claim_race_and_fence(tmp_path):
    store = Store(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: store.submit("same", BODY), range(16)))
        claims = list(pool.map(lambda _: store.claim(), range(8)))
    assert len({j["id"] for j in jobs}) == 1
    assert len([c for c in claims if c]) == 1
    claim = next(c for c in claims if c)
    store.step(*claim)
    store.recover()
    assert store.get(claim[0])["status"] == "interrupted"
    store.action(claim[0], "retry")
    new_claim = store.claim()
    assert not store.step(*claim)
    assert store.step(*new_claim)
    store.action(claim[0], "cancel")
    assert not store.step(*new_claim)
    assert store.get(claim[0])["status"] == "cancelled"
    with pytest.raises(Conflict):
        store.result(claim[0])


def test_abrupt_process_exit_and_checkpoint(tmp_path):
    script = """
import os, sys
from pathlib import Path
from tda_companion.store import Store
store=Store(Path(sys.argv[1]))
job=store.submit('crash', {'kind':'synthetic.fixture','campaign_id':'c','session_id':'s','source_id':'r','units':3})
claim=store.claim()
store.step(*claim)
os._exit(23)
"""
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=False)
    assert child.returncode == 23
    store = Store(tmp_path)
    store.recover()
    job = store.jobs()[0]
    assert job["progress"]["completed"] == 1 and job["status"] == "interrupted"
    store.action(job["id"], "retry")
    claim = store.claim()
    while store.step(*claim):
        pass
    assert store.get(job["id"])["progress"]["completed"] == 3
    assert len(store.jobs()) == 1


def test_root_lock_released_by_crash(tmp_path):
    from tda_companion.__main__ import RootLock

    script = "from tda_companion.__main__ import RootLock; from pathlib import Path; import sys; RootLock(Path(sys.argv[1])).__enter__()"
    with RootLock(tmp_path):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True)
        assert result.returncode != 0 and b"DATA_ROOT_IN_USE" in result.stderr
    assert subprocess.run([sys.executable, "-c", script, str(tmp_path)]).returncode == 0


def test_legacy_publication_stable_identity():
    session = {"recording_id": "fixture-source", "transcript": [{"end": 1, "text": "private"}]}
    first = build_publication_bundle(session, {})
    second = build_publication_bundle(session, {})
    assert first["publication_id"] == second["publication_id"]
    assert "private" not in json.dumps(first)


def test_shared_fixture_contract():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "companion-v1.json").read_text(encoding="utf-8")
    )
    result = fixture["result"]
    assert result["job_id"] == fixture["job"]["id"]
    assert result["source_id"] == result["publication_bundle"]["session"]["source_id"]
    payload = result["import_artifacts"]["publication_payload_json"]
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == result["publication_bundle"]["publication_id"]
    assert result["import_artifacts"]["transcript_json"] == "[]"
    assert result["publication_bundle"]["source_manifest"]["recording_format"] == "synthetic.fixture"


def test_worker_end_to_end(tmp_path):
    import time

    with TestClient(create_app(tmp_path, TOKEN, {ORIGIN}), base_url="http://127.0.0.1:8765") as client:
        job = client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "worker"},
            json=BODY,
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
            if state["status"] == "succeeded":
                break
            time.sleep(0.02)
        assert state["status"] == "succeeded"


def test_worker_failure_is_redacted_and_retryable(tmp_path, monkeypatch):
    import time

    app = create_app(tmp_path, TOKEN, {ORIGIN})

    def fail(*args):
        raise RuntimeError("private-path-and-token")

    monkeypatch.setattr(app.state.store, "step", fail)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        job = client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "failure"},
            json=BODY,
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS)
            if response.json()["status"] == "failed":
                break
            time.sleep(0.02)
        assert response.json()["error"] == {"code": "FIXTURE_EXECUTION_FAILED", "recoverable": True}
        assert "private-path-and-token" not in response.text


def test_incompatible_database_preserved(tmp_path):
    import sqlite3

    store = Store(tmp_path)
    job = store.submit("keep", BODY)
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="DATABASE_VERSION_UNSUPPORTED"):
        Store(tmp_path)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT id FROM jobs").fetchone()[0] == job["id"]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_cli_http_in_disposable_root(tmp_path):
    import socket
    import time

    import httpx

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token_path = tmp_path / "test-token"
    token_path.write_text(TOKEN, encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tda_companion",
            "--data-root",
            str(tmp_path / "data"),
            "--token-file",
            str(token_path),
            "--origin",
            ORIGIN,
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Windows hosted runners occasionally take >1s to flush a durable SQLite
        # transaction. Keep a bounded network timeout while avoiding scheduler flakes.
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
            startup_deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get("/api/v1/health")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < startup_deadline and process.poll() is None
                time.sleep(0.05)
            assert response.json()["api_version"] == "1"
            assert response.json()["product_id"] == "tda-companion"
            job = client.post(
                "/api/v1/jobs",
                headers={**HEADERS, "Idempotency-Key": "http"},
                json=BODY,
            ).json()
            job_deadline = time.monotonic() + 10
            while time.monotonic() < job_deadline:
                state = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
                if state["status"] == "succeeded":
                    break
                time.sleep(0.05)
            assert state["status"] == "succeeded"
    finally:
        # Own disposable synthetic subprocess only; never PID discovery/legacy.
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
        assert TOKEN.encode() not in stdout + stderr
