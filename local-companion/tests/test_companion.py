import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tda_companion.api import create_app
from tda_companion.legacy.publication import build_publication_bundle
from tda_companion.store import Conflict, Store

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


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, TOKEN, {ORIGIN}, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


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
    assert client.post("/api/v1/jobs", headers=HEADERS, content="x" * 4097).status_code == 413
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
