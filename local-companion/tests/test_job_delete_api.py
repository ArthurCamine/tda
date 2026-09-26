from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tda_companion.api import create_app
from tda_companion.store import Store


TOKEN = "t" * 43
ORIGIN = "https://dnd.faysk.dev"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Origin": ORIGIN,
}
BODY = {
    "kind": "synthetic.fixture",
    "campaign_id": "synthetic-campaign",
    "session_id": "synthetic-session",
    "source_id": "synthetic-source",
    "units": 1,
}


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "Data"
    data.mkdir(parents=True, exist_ok=True)
    app = create_app(data, TOKEN, {ORIGIN}, run_worker=False)
    return TestClient(app, base_url="http://127.0.0.1:8765"), data


def _submit(client: TestClient, key: str) -> dict:
    response = client.post(
        "/api/v1/jobs",
        headers={**HEADERS, "Idempotency-Key": key},
        json=BODY,
    )
    assert response.status_code == 200
    return response.json()


def test_terminal_job_can_be_deleted_through_local_api(tmp_path: Path):
    client, data = _client(tmp_path)
    with client:
        job = _submit(client, "delete-terminal-api")
        store = Store(data)
        claim = store.claim()
        assert claim is not None
        store.fail(*claim, "WORKER_EXECUTION_FAILED")

        response = client.post(
            f"/api/v1/jobs/{job['id']}/delete",
            headers=HEADERS,
            json={},
        )

        assert response.status_code == 200
        assert response.json() == {"deleted": True, "id": job["id"]}
        missing = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_active_job_cannot_be_deleted_through_local_api(tmp_path: Path):
    client, _data = _client(tmp_path)
    with client:
        job = _submit(client, "delete-active-api")
        response = client.post(
            f"/api/v1/jobs/{job['id']}/delete",
            headers=HEADERS,
            json={},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "JOB_ACTIVE"
        still_there = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS)
        assert still_there.status_code == 200


def _visibility_package(data: Path) -> Path:
    package = data / "staging" / BODY["source_id"]
    package.mkdir(parents=True, exist_ok=True)
    return package


def test_failed_run_without_commit_authority_stays_hidden_after_queue_cleanup(tmp_path: Path):
    client, data = _client(tmp_path)
    package = _visibility_package(data)
    with client:
        job = _submit(client, "visibility-failed-cleanup")
        store = Store(data)
        claim = store.claim()
        assert claim is not None
        store.fail(*claim, "WORKER_EXECUTION_FAILED")
        summary = {"job_id": job["id"], "attempt": claim[1]}

        visible = client.app.state.transcription_run_visible
        assert visible(package, summary) is False

        deleted = client.post(
            f"/api/v1/jobs/{job['id']}/delete",
            headers=HEADERS,
            json={},
        )
        assert deleted.status_code == 200
        assert visible(package, summary) is False


def test_retry_does_not_promote_ambiguous_older_attempt(tmp_path: Path):
    client, data = _client(tmp_path)
    package = _visibility_package(data)
    with client:
        job = _submit(client, "visibility-retry")
        store = Store(data)
        first = store.claim()
        assert first is not None
        store.fail(*first, "WORKER_EXECUTION_FAILED")
        summary = {"job_id": job["id"], "attempt": first[1]}

        visible = client.app.state.transcription_run_visible
        assert visible(package, summary) is False

        store.action(job["id"], "retry")
        second = store.claim()
        assert second is not None
        assert second[1] == first[1] + 1
        assert visible(package, summary) is False


def test_pre_fence_succeeded_run_keeps_visibility_after_queue_cleanup(tmp_path: Path):
    client, data = _client(tmp_path)
    package = _visibility_package(data)
    with client:
        job = _submit(client, "visibility-legacy-succeeded")
        store = Store(data)
        claim = store.claim()
        assert claim is not None
        assert store.step(*claim) is False
        summary = {"job_id": job["id"], "attempt": claim[1]}

        visible = client.app.state.transcription_run_visible
        assert visible(package, summary) is True

        deleted = client.post(
            f"/api/v1/jobs/{job['id']}/delete",
            headers=HEADERS,
            json={},
        )
        assert deleted.status_code == 200
        assert visible(package, summary) is True
