import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

import tda_companion.telemetry as telemetry_module
from tda_companion.api import create_app
from tda_companion.store import Store
from tda_companion.telemetry import SystemTelemetry

TOKEN = "s" * 43
ORIGIN = "https://panel.example"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Origin": ORIGIN,
    "Content-Type": "application/json",
}
BODY = dict(
    kind="synthetic.fixture",
    campaign_id="synthetic-campaign",
    session_id="synthetic-session",
    source_id="synthetic-source",
    units=3,
)


def test_system_telemetry_is_authenticated_and_best_effort(tmp_path):
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/system").status_code == 401
        response = client.get("/api/v1/system", headers=HEADERS)
        assert response.status_code == 200
        value = response.json()
        assert set(value) == {"sampled_at", "host", "cpu", "memory", "gpus"}
        assert set(value["host"]) == {"os", "cpu"}
        assert "hostname" not in value["host"]
        assert isinstance(value["gpus"], list)

        capabilities = client.get("/api/v1/capabilities", headers=HEADERS).json()
        assert "system.telemetry" in capabilities["capabilities"]
        assert "job.events" in capabilities["capabilities"]


def test_gpu_telemetry_recovers_after_transient_nvml_failure(monkeypatch):
    class RecoveringNvml:
        def __init__(self) -> None:
            self.init_calls = 0

        def nvmlInit(self) -> None:
            self.init_calls += 1
            if self.init_calls == 1:
                raise RuntimeError("transient driver reset")

        @staticmethod
        def nvmlDeviceGetCount() -> int:
            return 1

        @staticmethod
        def nvmlDeviceGetHandleByIndex(index: int) -> int:
            return index

        @staticmethod
        def nvmlDeviceGetName(_handle: int) -> bytes:
            return b"NVIDIA Test GPU"

        @staticmethod
        def nvmlDeviceGetMemoryInfo(_handle: int) -> SimpleNamespace:
            return SimpleNamespace(used=1024, total=4096)

        @staticmethod
        def nvmlDeviceGetUtilizationRates(_handle: int) -> SimpleNamespace:
            return SimpleNamespace(gpu=37)

    fake_nvml = RecoveringNvml()
    monkeypatch.setattr(telemetry_module, "pynvml", fake_nvml)

    telemetry = SystemTelemetry()
    assert telemetry._gpu_snapshot() == []
    assert fake_nvml.init_calls == 1

    assert telemetry._gpu_snapshot() == [
        {
            "index": 0,
            "name": "NVIDIA Test GPU",
            "utilization_percent": 37,
            "memory_used_bytes": 1024,
            "memory_total_bytes": 4096,
        }
    ]
    assert fake_nvml.init_calls == 2


def test_gpu_telemetry_stays_optional_without_pynvml(monkeypatch):
    monkeypatch.setattr(telemetry_module, "pynvml", None)
    assert SystemTelemetry()._gpu_snapshot() == []


def test_structured_events_keep_facts_and_job_context(tmp_path):
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        job = client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "events"},
            json=BODY,
        ).json()
        assert job["context"] == {
            "campaign_id": "synthetic-campaign",
            "session_id": "synthetic-session",
            "source_id": "synthetic-source",
        }
        assert job["attempt"] == 0

        store = client.app.state.store
        claim = store.claim()
        assert claim is not None
        while store.step(*claim):
            pass

        events = client.get(
            f"/api/v1/jobs/{job['id']}/events",
            headers=HEADERS,
        ).json()["events"]
        assert events[0] == {
            "seq": events[0]["seq"],
            "code": "SUCCEEDED",
            "at": events[0]["at"],
            "level": "info",
            "data": {"completed": 3, "total": 3},
        }
        assert any(
            event["code"] == "RUNNING"
            and event["data"] == {"attempt": 1, "total": 3}
            for event in events
        )
        assert all(set(event) == {"seq", "code", "at", "level", "data"} for event in events)


def test_v1_local_database_migrates_events_without_losing_jobs(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
                body TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT, result TEXT, updated TEXT NOT NULL);
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                code TEXT NOT NULL, at TEXT NOT NULL);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings VALUES ('device', 'legacy-device');
            INSERT INTO settings VALUES ('paused', 'false');
            PRAGMA user_version=1;
            """
        )

    Store(tmp_path)
    with sqlite3.connect(path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in db.execute("PRAGMA table_info(events)").fetchall()}
    assert version == 2
    assert {"level", "data"} <= columns
