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
