from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tda_companion.store import Conflict, Store


def _body(*, units: int = 3) -> dict[str, object]:
    return {
        "kind": "synthetic.fixture",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": "source",
        "units": units,
    }


def _event_by_code(events: list[dict], code: str) -> list[dict]:
    return [event for event in events if event["code"] == code]


def test_attempt_scoped_events_keep_exact_attempt_across_retry(tmp_path: Path):
    store = Store(tmp_path)
    job = store.submit("key-a", _body())
    job_id = job["id"]

    claimed = store.claim()
    assert claimed == (job_id, 1)
    assert store.record_worker_event(
        job_id,
        1,
        "QWEN_WINDOW_TRANSCRIBED",
        {"track": 1, "window": 1},
    )
    store.set_stage(job_id, 1, "transcription")
    store.progress(job_id, 1, completed=1, total=3, stage="transcription")
    store.fail(job_id, 1, "SYNTHETIC_FAILURE")

    store.action(job_id, "retry")
    assert store.claim() == (job_id, 2)
    assert store.record_worker_event(
        job_id,
        2,
        "QWEN_WINDOW_TRANSCRIBED",
        {"track": 1, "window": 1},
    )

    events = store.events(job_id)

    running = _event_by_code(events, "RUNNING")
    assert {event["attempt"] for event in running} == {1, 2}

    worker = _event_by_code(events, "QWEN_WINDOW_TRANSCRIBED")
    assert {event["attempt"] for event in worker} == {1, 2}

    assert _event_by_code(events, "STAGE_CHANGED")[0]["attempt"] == 1
    assert _event_by_code(events, "UNIT_COMMITTED")[0]["attempt"] == 1
    assert _event_by_code(events, "SYNTHETIC_FAILURE")[0]["attempt"] == 1

    queued = _event_by_code(events, "QUEUED")
    assert len(queued) == 2
    assert all(event["attempt"] is None for event in queued)


def test_stale_worker_event_remains_rejected_after_next_attempt(tmp_path: Path):
    store = Store(tmp_path)
    job_id = store.submit("key-a", _body())["id"]

    assert store.claim() == (job_id, 1)
    store.fail(job_id, 1, "SYNTHETIC_FAILURE")
    store.action(job_id, "retry")
    assert store.claim() == (job_id, 2)

    before = len(store.events(job_id))
    assert (
        store.record_worker_event(
            job_id,
            1,
            "QWEN_WINDOW_TRANSCRIBED",
            {"track": 1, "window": 99},
        )
        is False
    )
    after = store.events(job_id)

    assert len(after) == before
    assert not any(
        event["code"] == "QWEN_WINDOW_TRANSCRIBED"
        and event["data"].get("window") == 99
        for event in after
    )


def test_running_cancel_is_attempt_scoped_but_queued_cancel_is_job_scoped(
    tmp_path: Path,
):
    running_store = Store(tmp_path / "running")
    running_id = running_store.submit("key-running", _body())["id"]
    assert running_store.claim() == (running_id, 1)
    running_store.action(running_id, "cancel")
    assert _event_by_code(running_store.events(running_id), "CANCELLED")[0][
        "attempt"
    ] == 1

    queued_store = Store(tmp_path / "queued")
    queued_id = queued_store.submit("key-queued", _body())["id"]
    queued_store.action(queued_id, "cancel")
    assert _event_by_code(queued_store.events(queued_id), "CANCELLED")[0][
        "attempt"
    ] is None


def test_recovery_preserves_interrupted_attempt_identity(tmp_path: Path):
    store = Store(tmp_path)
    job_id = store.submit("key-a", _body())["id"]
    assert store.claim() == (job_id, 1)

    store.recover()

    event = _event_by_code(store.events(job_id), "PROCESS_INTERRUPTED")[0]
    assert event["attempt"] == 1


def test_v4_event_rows_migrate_to_nullable_attempt_without_inference(tmp_path: Path):
    store = Store(tmp_path)
    job_id = store.submit("key-a", _body())["id"]
    assert _event_by_code(store.events(job_id), "QUEUED")[0]["attempt"] is None

    with sqlite3.connect(store.path) as db:
        db.executescript(
            """
            ALTER TABLE events RENAME TO events_v5;
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                code TEXT NOT NULL,
                at TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                data TEXT
            );
            INSERT INTO events(seq,job_id,code,at,level,data)
            SELECT seq,job_id,code,at,level,data FROM events_v5;
            DROP TABLE events_v5;
            PRAGMA user_version=4;
            """
        )

    migrated = Store(tmp_path)
    with sqlite3.connect(migrated.path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(events)").fetchall()
        }

    assert version == 7
    assert "attempt" in columns
    event = _event_by_code(migrated.events(job_id), "QUEUED")[0]
    assert event["attempt"] is None


def test_direct_event_attempt_rejects_zero_bool_and_negative(tmp_path: Path):
    store = Store(tmp_path)
    job_id = store.submit("key-a", _body())["id"]

    for attempt in (0, -1, True):
        with pytest.raises(Conflict, match="JOB_EVENT_ATTEMPT_INVALID"):
            with store.tx() as db:
                store.event(db, job_id, "INVALID_ATTEMPT_TEST", attempt=attempt)
