from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import tda_companion.profile_preparation as preparation
from tda_companion.api import create_app


TOKEN = "t" * 43
ORIGIN = "https://dnd.faysk.dev"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Origin": ORIGIN,
}
SOURCE_ID = "craig-" + "a" * 64


def test_preparation_cancel_api_fences_stale_browser_operation(
    tmp_path: Path,
    monkeypatch,
):
    entered = threading.Event()

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )
    monkeypatch.setattr(
        preparation,
        "profile_catalog",
        lambda *_args: [
            {
                "id": "whisper-turbo",
                "engine": "whisper",
                "ready": False,
                "preparation_required": True,
                "reason": "WHISPER_RUNTIME_REQUIRED",
            }
        ],
    )

    def install(_runtime, _cache, *, is_cancelled=None):
        entered.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            preparation._check_cancelled(is_cancelled)
            time.sleep(0.005)
        raise AssertionError("cancel was not observed")

    monkeypatch.setattr(preparation, "_install_whisper_runtime", install)

    app = create_app(
        tmp_path / "Data",
        TOKEN,
        {ORIGIN},
        run_worker=False,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        started = client.post(
            "/api/v1/preparation",
            headers=HEADERS,
            json={"source_id": SOURCE_ID, "profile_id": "whisper-turbo"},
        )
        assert started.status_code == 200
        operation_id = started.json()["operation_id"]
        assert isinstance(operation_id, str) and len(operation_id) == 32
        assert entered.wait(timeout=1)

        stale = client.post(
            "/api/v1/preparation/cancel",
            headers=HEADERS,
            json={"expected_operation_id": "f" * 32},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "TRANSCRIPTION_PREPARATION_STALE_OPERATION"

        still_running = client.get("/api/v1/preparation", headers=HEADERS)
        assert still_running.status_code == 200
        assert still_running.json()["operation_id"] == operation_id
        assert still_running.json()["active"] is True

        cancelled = client.post(
            "/api/v1/preparation/cancel",
            headers=HEADERS,
            json={"expected_operation_id": operation_id},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["operation_id"] == operation_id

        deadline = time.monotonic() + 2
        terminal = None
        while time.monotonic() < deadline:
            terminal = client.get("/api/v1/preparation", headers=HEADERS).json()
            if terminal["active"] is False:
                break
            time.sleep(0.01)

        assert terminal is not None
        assert terminal["active"] is False
        assert terminal["error_code"] == "TRANSCRIPTION_PREPARATION_CANCELLED"

        repeated = client.post(
            "/api/v1/preparation/cancel",
            headers=HEADERS,
            json={"expected_operation_id": operation_id},
        )
        assert repeated.status_code == 200
        assert repeated.json()["operation_id"] == operation_id
        assert repeated.json()["active"] is False


def test_browser_session_can_use_fenced_preparation_cancel_route(tmp_path: Path):
    app = create_app(
        tmp_path / "Data",
        TOKEN,
        {ORIGIN},
        run_worker=False,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        session = client.post("/api/v1/session", headers={"Origin": ORIGIN}, json={})
        assert session.status_code == 200
        browser_token = session.json()["token"]
        response = client.post(
            "/api/v1/preparation/cancel",
            headers={
                "Authorization": f"Bearer {browser_token}",
                "Origin": ORIGIN,
            },
            json={"expected_operation_id": "a" * 32},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TRANSCRIPTION_PREPARATION_STALE_OPERATION"
