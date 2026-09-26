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


def _client(tmp_path: Path) -> tuple[TestClient, Store]:
    data = tmp_path / "Data"
    data.mkdir(parents=True, exist_ok=True)
    app = create_app(data, TOKEN, {ORIGIN}, run_worker=False)
    return TestClient(app, base_url="http://127.0.0.1:8765"), Store(data)


def _seed_events(store: Store, count: int = 250) -> str:
    job_id = store.submit("event-page-key", BODY)["id"]
    with store.tx() as db:
        for index in range(1, count + 1):
            store.event(
                db,
                job_id,
                "SYNTHETIC_EVENT",
                {"index": index},
            )
    return job_id


def test_job_events_api_paginates_latest_older_and_live_tail_without_loss(tmp_path: Path):
    client, store = _client(tmp_path)
    job_id = _seed_events(store)

    with client:
        latest = client.get(
            f"/api/v1/jobs/{job_id}/events?limit=100",
            headers=HEADERS,
        )
        assert latest.status_code == 200
        latest_page = latest.json()
        latest_events = latest_page["events"]
        assert len(latest_events) == 100
        assert [event["seq"] for event in latest_events] == sorted(
            (event["seq"] for event in latest_events),
            reverse=True,
        )
        assert latest_page["has_more"] is True
        assert latest_page["next_before_seq"] == latest_events[-1]["seq"]
        assert latest_page["next_after_seq"] == latest_events[0]["seq"]

        middle = client.get(
            f"/api/v1/jobs/{job_id}/events"
            f"?before_seq={latest_page['next_before_seq']}&limit=100",
            headers=HEADERS,
        )
        assert middle.status_code == 200
        middle_page = middle.json()
        assert len(middle_page["events"]) == 100
        assert middle_page["has_more"] is True
        assert middle_page["events"][-1]["seq"] < latest_events[0]["seq"]

        oldest = client.get(
            f"/api/v1/jobs/{job_id}/events"
            f"?before_seq={middle_page['next_before_seq']}&limit=100",
            headers=HEADERS,
        )
        assert oldest.status_code == 200
        oldest_page = oldest.json()
        assert oldest_page["has_more"] is False

        all_events = [
            *oldest_page["events"],
            *middle_page["events"],
            *latest_events,
        ]
        assert len(all_events) == 251  # QUEUED + 250 synthetic events
        seqs = [event["seq"] for event in all_events]
        assert len(set(seqs)) == len(seqs)
        assert sorted(seqs) == list(range(min(seqs), max(seqs) + 1))

        live = client.get(
            f"/api/v1/jobs/{job_id}/events?after_seq={min(seqs)}&limit=100",
            headers=HEADERS,
        )
        assert live.status_code == 200
        live_page = live.json()
        assert len(live_page["events"]) == 100
        assert live_page["has_more"] is True
        assert live_page["events"][0]["seq"] > min(seqs)


def test_job_events_api_rejects_ambiguous_or_unbounded_cursor_requests(tmp_path: Path):
    client, store = _client(tmp_path)
    job_id = _seed_events(store, count=1)

    with client:
        both = client.get(
            f"/api/v1/jobs/{job_id}/events?after_seq=0&before_seq=2",
            headers=HEADERS,
        )
        assert both.status_code == 422
        assert both.json()["error"]["code"] == "INVALID_REQUEST"

        too_large = client.get(
            f"/api/v1/jobs/{job_id}/events?limit=201",
            headers=HEADERS,
        )
        assert too_large.status_code == 422
        assert too_large.json()["error"]["code"] == "INVALID_REQUEST"

        negative = client.get(
            f"/api/v1/jobs/{job_id}/events?after_seq=-1",
            headers=HEADERS,
        )
        assert negative.status_code == 422
        assert negative.json()["error"]["code"] == "INVALID_REQUEST"
