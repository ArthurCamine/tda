from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from tda_companion.api import create_app
from tda_companion.craig_ingest_http import CraigIngestBoundary

TOKEN = "i" * 43
ORIGIN = "https://dnd.faysk.dev"


def _payload() -> bytes:
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-alice")
    return value.getvalue()


def _client(tmp_path: Path) -> TestClient:
    root = tmp_path / "Data"
    root.mkdir()
    api = create_app(root, TOKEN, {ORIGIN}, run_worker=False)
    app = CraigIngestBoundary(
        api,
        data_root=root,
        token=TOKEN,
        origins=frozenset({ORIGIN}),
        port=8765,
    )
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_boundary_accepts_zip_and_rejects_bad_credentials_or_media(tmp_path: Path):
    payload = _payload()
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN, "Content-Type": "application/zip"}
    with _client(tmp_path) as client:
        response = client.post("/api/v1/sources/craig", headers=headers, content=payload)
        assert response.status_code == 200
        assert response.json()["schema_version"] == "tda_craig_ingest_v1"

        unauthorized = client.post(
            "/api/v1/sources/craig",
            headers={**headers, "Authorization": "Bearer invalid"},
            content=payload,
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"

        wrong_media = client.post(
            "/api/v1/sources/craig",
            headers={**headers, "Content-Type": "application/json"},
            content=payload,
        )
        assert wrong_media.status_code == 415
        assert wrong_media.json()["error"]["code"] == "CRAIG_ZIP_REQUIRED"


def test_boundary_preflight_is_narrow_and_private_network_aware(tmp_path: Path):
    with _client(tmp_path) as client:
        response = client.options(
            "/api/v1/sources/craig",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["access-control-allow-private-network"] == "true"

        rejected = client.options(
            "/api/v1/sources/craig",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, x-file-path",
            },
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "PREFLIGHT_REJECTED"


def test_run_discovery_migrates_legacy_result_and_never_returns_transcript_or_path(tmp_path: Path):
    payload = _payload()
    upload_headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Origin": ORIGIN,
        "Content-Type": "application/zip",
    }
    get_headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with _client(tmp_path) as client:
        staged = client.post("/api/v1/sources/craig", headers=upload_headers, content=payload)
        assert staged.status_code == 200
        source = staged.json()
        source_id = source["source_id"]
        source_sha = source["source_sha256"]
        package_root = tmp_path / "Data" / "staging" / source_id
        secret = "SEGREDO QUE NAO PODE IR PARA A LISTAGEM"
        legacy = {
            "schema_version": "tda_transcript_v1",
            "source_sha256": source_sha,
            "created_at": "2026-09-15T15:00:00.000Z",
            "language": "pt",
            "engine": {
                "engine": "faster-whisper",
                "model": "large-v3",
                "profile": "whisper-detailed",
                "device": "cuda",
                "compute_type": "float16",
                "alignment": "native",
                "model_revision": "test",
            },
            "stats": {
                "processing_seconds": 12.0,
                "rtf": 0.2,
                "word_count": 1,
                "segment_count": 1,
                "track_count": 1,
            },
            "tracks": [{"text": secret}],
        }
        (package_root / "transcript.json").write_text(
            json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

        response = client.get(f"/api/v1/sources/{source_id}/runs", headers=get_headers)
        assert response.status_code == 200
        value = response.json()
        assert value["schema_version"] == "tda_transcription_runs_v1"
        assert value["source_id"] == source_id
        assert len(value["runs"]) == 1
        assert value["runs"][0]["origin"] == "legacy_transcript_v1"
        encoded = json.dumps(value, ensure_ascii=False)
        assert secret not in encoded
        assert str(tmp_path) not in encoded
        assert (package_root / "transcript.json").is_file()

        unauthorized = client.get(
            f"/api/v1/sources/{source_id}/runs",
            headers={"Authorization": "Bearer invalid", "Origin": ORIGIN},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"


def test_run_discovery_preflight_allows_only_get_authorization(tmp_path: Path):
    payload = _payload()
    with _client(tmp_path) as client:
        staged = client.post(
            "/api/v1/sources/craig",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Origin": ORIGIN,
                "Content-Type": "application/zip",
            },
            content=payload,
        )
        source_id = staged.json()["source_id"]
        response = client.options(
            f"/api/v1/sources/{source_id}/runs",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-private-network"] == "true"

        rejected = client.options(
            f"/api/v1/sources/{source_id}/runs",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "PREFLIGHT_REJECTED"
