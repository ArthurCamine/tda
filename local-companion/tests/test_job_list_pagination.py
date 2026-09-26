from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tda_companion.api import create_app
from tda_companion.store import Conflict, Store


TOKEN = "t" * 43
ORIGIN = "https://dnd.faysk.dev"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Origin": ORIGIN,
}


def _body(index: int) -> dict[str, object]:
    return {
        "kind": "synthetic.fixture",
        "campaign_id": "campaign",
        "session_id": f"session-{index}",
        "source_id": f"source-{index}",
        "units": 1,
    }


def _seed(store: Store, count: int) -> list[str]:
    return [
        store.submit(f"queue-page-{index}", _body(index))["id"]
        for index in range(count)
    ]


def _collect(store: Store, scope: str, limit: int = 37) -> list[dict]:
    values: list[dict] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        page = store.jobs_page(scope=scope, cursor=cursor, limit=limit)
        values.extend(page["jobs"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        cursor = page["next_cursor"]
        assert isinstance(cursor, str)
        assert cursor not in seen
        seen.add(cursor)
    return values


def test_job_list_pages_traverse_more_than_legacy_window_without_loss(tmp_path: Path):
    store = Store(tmp_path)
    expected = set(_seed(store, 251))

    assert len(store.jobs()) == 100

    active = _collect(store, "active")
    assert len(active) == 251
    assert {job["id"] for job in active} == expected
    assert len({job["id"] for job in active}) == len(active)

    page = store.jobs_page(scope="active", limit=37)
    assert page["schema_version"] == "tda_job_page_v1"
    assert page["total_matching"] == 251
    assert page["counts"]["queued"] == 251
    assert page["counts"].get("running", 0) == 0


def test_job_list_keyset_uses_id_tie_break_when_updated_matches(tmp_path: Path):
    store = Store(tmp_path)
    expected = set(_seed(store, 121))
    with store.tx() as db:
        db.execute("UPDATE jobs SET updated='2026-09-26T12:00:00Z'")

    rows = _collect(store, "active", limit=11)
    ids = [job["id"] for job in rows]

    assert set(ids) == expected
    assert len(ids) == 121
    assert ids == sorted(ids, reverse=True)


def test_job_list_scope_cursor_is_not_reusable_across_queries(tmp_path: Path):
    store = Store(tmp_path)
    _seed(store, 3)
    page = store.jobs_page(scope="active", limit=1)
    cursor = page["next_cursor"]
    assert isinstance(cursor, str)

    with pytest.raises(Conflict, match="JOB_LIST_CURSOR_INVALID"):
        store.jobs_page(scope="history", cursor=cursor, limit=1)


def test_job_list_active_and_history_are_independently_complete(tmp_path: Path):
    store = Store(tmp_path)
    ids = _seed(store, 12)
    for job_id in ids[:5]:
        store.action(job_id, "cancel")

    active = _collect(store, "active", limit=3)
    history = _collect(store, "history", limit=2)

    assert {job["id"] for job in active} == set(ids[5:])
    assert {job["id"] for job in history} == set(ids[:5])
    assert all(job["status"] in {"queued", "running"} for job in active)
    assert all(job["status"] not in {"queued", "running"} for job in history)


def test_job_list_api_preserves_legacy_wire_and_exposes_cursor_capability(tmp_path: Path):
    data = tmp_path / "Data"
    data.mkdir(parents=True)
    app = create_app(data, TOKEN, {ORIGIN}, run_worker=False)
    store = Store(data)
    _seed(store, 205)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        legacy = client.get("/api/v1/jobs", headers=HEADERS)
        assert legacy.status_code == 200
        assert set(legacy.json()) == {"jobs"}
        assert len(legacy.json()["jobs"]) == 100

        capabilities = client.get("/api/v1/capabilities", headers=HEADERS)
        assert capabilities.status_code == 200
        assert "job.list.cursor" in capabilities.json()["capabilities"]

        first = client.get(
            "/api/v1/jobs?scope=active&limit=200",
            headers=HEADERS,
        )
        assert first.status_code == 200
        page = first.json()
        assert page["schema_version"] == "tda_job_page_v1"
        assert len(page["jobs"]) == 200
        assert page["has_more"] is True
        assert isinstance(page["next_cursor"], str)

        second = client.get(
            f"/api/v1/jobs?scope=active&limit=200&cursor={page['next_cursor']}",
            headers=HEADERS,
        )
        assert second.status_code == 200
        assert len(second.json()["jobs"]) == 5
        assert second.json()["has_more"] is False

        invalid = client.get(
            "/api/v1/jobs?scope=active&cursor=not-a-valid-cursor",
            headers=HEADERS,
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "JOB_LIST_CURSOR_INVALID"
