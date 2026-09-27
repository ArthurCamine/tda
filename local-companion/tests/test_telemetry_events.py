import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import tda_companion.telemetry as telemetry_module
from tda_companion.api import create_app
from tda_companion.store import Conflict, Store
from tda_companion.system_log import SystemLog
from tda_companion.telemetry import SystemTelemetry
from tda_companion.worker_protocol import WorkerMessage
from tda_companion.worker_supervisor import WorkerOutcome, WorkerSupervisor

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


def test_store_rejects_non_finite_worker_event_values(tmp_path):
    store = Store(tmp_path)
    job = store.submit(
        "finite-event-values",
        {
            "kind": "synthetic.fixture",
            "campaign_id": "campaign",
            "session_id": "session",
            "source_id": "source",
            "units": 1,
        },
    )
    job_id, attempt = store.claim()
    assert job_id == job["id"]

    with pytest.raises(Conflict, match="WORKER_EVENT_DATA_INVALID"):
        store.record_worker_event(
            job_id,
            attempt,
            "GPU_SAMPLE",
            {"percent": float("nan")},
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

        @staticmethod
        def nvmlDeviceGetCudaComputeCapability(_handle: int) -> tuple[int, int]:
            return (8, 9)

        @staticmethod
        def nvmlSystemGetDriverVersion() -> bytes:
            return b"600.12"

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
            "compute_capability": "8.9",
            "driver_version": "600.12",
            "uuid": None,
            "pci_bus_id": None,
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
            "attempt": 1,
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
        assert all(
            set(event) == {"seq", "attempt", "code", "at", "level", "data"}
            for event in events
        )
        assert next(event for event in events if event["code"] == "QUEUED")["attempt"] is None


def test_high_frequency_worker_events_are_throttled_before_sqlite(monkeypatch, tmp_path):
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
        del self, completed, is_cancelled
        assert on_event is not None
        on_event(
            WorkerMessage.create(
                job_id=job_id,
                attempt=attempt,
                seq=0,
                type="ready",
                payload={"kind": "synthetic.fixture"},
            )
        )
        seq = 1
        for window in range(10):
            on_event(
                WorkerMessage.create(
                    job_id=job_id,
                    attempt=attempt,
                    seq=seq,
                    type="event",
                    payload={
                        "code": "QWEN_WINDOW_TRANSCRIBED",
                        "stage": "transcription",
                        "track": 1,
                        "total_tracks": units,
                        "speaker": "Fixture speaker",
                        "window": window,
                    },
                )
            )
            seq += 1
        for current in range(1, units + 1):
            on_progress(
                WorkerMessage.create(
                    job_id=job_id,
                    attempt=attempt,
                    seq=seq,
                    type="progress",
                    payload={
                        "completed": current,
                        "total": units,
                        "unit": "items",
                        "stage": "fixture",
                    },
                )
            )
            seq += 1
        return WorkerOutcome(
            terminal="result",
            payload={"kind": "synthetic.fixture", "units": units},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_fixture", fake_run_fixture)
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        job = client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "throttled-worker-events"},
            json=BODY,
        ).json()

        deadline = __import__("time").monotonic() + 3.0
        state = job
        while __import__("time").monotonic() < deadline:
            state = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
            if state["status"] == "succeeded":
                break
            __import__("time").sleep(0.02)

        assert state["status"] == "succeeded"
        events = client.get(
            f"/api/v1/jobs/{job['id']}/events",
            headers=HEADERS,
        ).json()["events"]
        noisy = [event for event in events if event["code"] == "QWEN_WINDOW_TRANSCRIBED"]
        assert len(noisy) == 1
        assert any(event["code"] == "SUCCEEDED" for event in events)


def test_worker_diagnostics_do_not_log_speaker_identity(monkeypatch, tmp_path):
    system_log = SystemLog(tmp_path / "logs")

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
        del self, completed, is_cancelled
        assert on_event is not None
        on_event(
            WorkerMessage.create(
                job_id=job_id,
                attempt=attempt,
                seq=0,
                type="event",
                payload={
                    "code": "QWEN_WINDOW_TRANSCRIBED",
                    "stage": "transcription",
                    "track": 1,
                    "total_tracks": units,
                    "window": 7,
                    "speaker": "Nome Privado",
                },
            )
        )
        for current in range(1, units + 1):
            on_progress(
                WorkerMessage.create(
                    job_id=job_id,
                    attempt=attempt,
                    seq=current,
                    type="progress",
                    payload={
                        "completed": current,
                        "total": units,
                        "unit": "items",
                        "stage": "fixture",
                    },
                )
            )
        return WorkerOutcome(
            terminal="result",
            payload={"kind": "synthetic.fixture", "units": units},
            returncode=0,
        )

    monkeypatch.setattr(WorkerSupervisor, "run_fixture", fake_run_fixture)
    app = create_app(
        tmp_path / "Data",
        TOKEN,
        {ORIGIN},
        run_worker=True,
        system_log=system_log,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        job = client.post(
            "/api/v1/jobs",
            headers={**HEADERS, "Idempotency-Key": "private-speaker-log"},
            json=BODY,
        ).json()
        deadline = __import__("time").monotonic() + 3.0
        while __import__("time").monotonic() < deadline:
            current = client.get(f"/api/v1/jobs/{job['id']}", headers=HEADERS).json()
            if current["status"] == "succeeded":
                break
            __import__("time").sleep(0.01)
        events = client.get(
            f"/api/v1/jobs/{job['id']}/events",
            headers=HEADERS,
        ).json()["events"]

    detail = next(event for event in events if event["code"] == "QWEN_WINDOW_TRANSCRIBED")
    assert detail["data"]["speaker"] == "Nome Privado"

    rows = [
        row
        for row in system_log.tail(limit=100)
        if row["code"] == "QWEN_WINDOW_TRANSCRIBED"
    ]
    assert len(rows) == 1
    assert rows[0]["context"]["track"] == 1
    assert rows[0]["context"]["window"] == 7
    assert "speaker" not in rows[0]["context"]
    assert "Nome Privado" not in (tmp_path / "logs" / "companion.log").read_text(
        encoding="utf-8"
    )


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
        event_columns = {row[1] for row in db.execute("PRAGMA table_info(events)").fetchall()}
        job_columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
    assert version == 8
    assert {"level", "data", "attempt"} <= event_columns
    assert "error_recoverable" in job_columns
    with sqlite3.connect(path) as db:
        assert {
            row[1]
            for row in db.execute("PRAGMA table_info(idempotency_keys)").fetchall()
        } == {"key", "job_id", "signature"}
