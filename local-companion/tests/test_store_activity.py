from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tda_companion.store import Conflict, Store


def _body(*, units: int = 2) -> dict[str, object]:
    return {
        "kind": "synthetic.fixture",
        "campaign_id": "campaign",
        "session_id": "session",
        "source_id": "source",
        "units": units,
    }


def _claimed_store(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path)
    job_id = store.submit("activity-key", _body())["id"]
    assert store.claim() == (job_id, 1)
    return store, job_id


def _metric(activity: dict, metric: str, *, track: int | None = None) -> int:
    matches = [
        item["value"]
        for item in activity["metrics"]
        if item["metric"] == metric and item["track"] == track
    ]
    assert len(matches) == 1
    return int(matches[0])


def test_qwen_activity_is_monotonic_even_when_trace_can_be_sampled(tmp_path: Path):
    store, job_id = _claimed_store(tmp_path)

    for completed in range(1, 251):
        assert store.record_worker_activity(
            job_id,
            1,
            "QWEN_WINDOW_TRANSCRIBED",
            {
                "track": 1,
                "window": completed - 1,
                "completed_window_count": completed,
            },
        )

    # A delayed/stale activity sample must never move the authoritative state backwards.
    assert store.record_worker_activity(
        job_id,
        1,
        "QWEN_WINDOW_TRANSCRIBED",
        {"track": 1, "window": 119, "completed_window_count": 120},
    )

    activity = store.activity(job_id)
    assert activity["schema_version"] == "tda_job_activity_v1"
    assert activity["attempt"] == 1
    assert _metric(activity, "qwen_windows_completed", track=1) == 250


def test_track_completion_flushes_zero_or_tail_counts_without_inventing_reuse(
    tmp_path: Path,
):
    store, job_id = _claimed_store(tmp_path)

    assert store.record_worker_activity(
        job_id,
        1,
        "WHISPER_SEGMENT_TRANSCRIBED",
        {"track": 1, "segment": 80, "completed_segment_count": 80},
    )
    assert store.record_worker_activity(
        job_id,
        1,
        "TRACK_COMPLETED",
        {"track": 1, "completed_segment_count": 97},
    )
    assert store.record_worker_activity(
        job_id,
        1,
        "TRACK_COMPLETED",
        {"track": 2, "completed_segment_count": 0},
    )

    activity = store.activity(job_id)
    assert _metric(activity, "whisper_segments_completed", track=1) == 97
    assert _metric(activity, "whisper_segments_completed", track=2) == 0


def test_download_activity_is_latest_value_gauge_not_additive(tmp_path: Path):
    store, job_id = _claimed_store(tmp_path)

    for downloaded in (10, 20, 30, 25):
        assert store.record_worker_activity(
            job_id,
            1,
            "MODEL_DOWNLOAD_PROGRESS",
            {"downloaded_bytes": downloaded},
        )

    activity = store.activity(job_id)
    assert _metric(activity, "model_downloaded_bytes") == 25


def test_activity_is_attempt_scoped_and_stale_attempt_cannot_mutate_retry(
    tmp_path: Path,
):
    store, job_id = _claimed_store(tmp_path)
    assert store.record_worker_activity(
        job_id,
        1,
        "QWEN_WINDOW_TRANSCRIBED",
        {"track": 1, "window": 199, "completed_window_count": 200},
    )
    store.fail(job_id, 1, "SYNTHETIC_FAILURE")
    store.action(job_id, "retry")
    assert store.claim() == (job_id, 2)

    assert (
        store.record_worker_activity(
            job_id,
            1,
            "QWEN_WINDOW_TRANSCRIBED",
            {"track": 1, "window": 249, "completed_window_count": 250},
        )
        is False
    )
    assert store.record_worker_activity(
        job_id,
        2,
        "QWEN_WINDOW_TRANSCRIBED",
        {"track": 1, "window": 49, "completed_window_count": 50},
    )

    assert _metric(
        store.activity(job_id, attempt=1),
        "qwen_windows_completed",
        track=1,
    ) == 200
    assert _metric(store.activity(job_id), "qwen_windows_completed", track=1) == 50


def test_schema_v6_upgrades_to_activity_v7_without_reinterpreting_old_events(
    tmp_path: Path,
):
    store = Store(tmp_path)
    job_id = store.submit("activity-key", _body())["id"]

    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE job_activity")
        db.execute("PRAGMA user_version=6")

    migrated = Store(tmp_path)
    with sqlite3.connect(migrated.path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(job_activity)").fetchall()
        }

    assert version == 7
    assert {"job_id", "attempt", "track", "metric", "value", "updated"} <= columns
    assert migrated.activity(job_id)["metrics"] == []


def test_activity_validation_rejects_unknown_metric_and_invalid_track(tmp_path: Path):
    store, job_id = _claimed_store(tmp_path)

    with pytest.raises(Conflict, match="JOB_ACTIVITY_INVALID"):
        store.record_activity(job_id, 1, "unknown", 1, track=1)
    with pytest.raises(Conflict, match="JOB_ACTIVITY_INVALID"):
        store.record_activity(
            job_id,
            1,
            "qwen_windows_completed",
            1,
            track=0,
        )
