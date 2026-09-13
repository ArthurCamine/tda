from __future__ import annotations

import hashlib
import io
import json

import pytest

from tda_companion.network import NetworkError
from tda_companion.release_download import ReleaseRedirectError
from tda_companion.updates import (
    UpdateManifest,
    download_update,
    fetch_manifest,
    parse_manifest,
)


def _manifest(payload: bytes) -> UpdateManifest:
    return UpdateManifest(
        version="0.3.2",
        tag="companion-v0.3.2",
        minimum_api="1",
        url="https://dnd.faysk.dev/api/downloads/companion/windows?version=0.3.2",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


def _manifest_json(payload: bytes = b"fake-msi-payload") -> dict[str, object]:
    return {
        "channel": "stable",
        "version": "0.3.2",
        "tag": "companion-v0.3.2",
        "minimum_api": "1",
        "asset": {
            "url": "/api/downloads/companion/windows?version=0.3.2",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        },
    }


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 200):
        super().__init__(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


class _Client:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout: float):
        self.request = request
        self.timeout = timeout
        return _Response(self.payload, self.status)


def test_parse_manifest_requires_version_locked_download_url():
    manifest = parse_manifest(_manifest_json())
    assert manifest.url.endswith("/api/downloads/companion/windows?version=0.3.2")

    generic = _manifest_json()
    generic["asset"] = {**generic["asset"], "url": "/api/downloads/companion/windows"}  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_UPDATE_URL"):
        parse_manifest(generic)

    mismatched = _manifest_json()
    mismatched["asset"] = {
        **mismatched["asset"],  # type: ignore[arg-type]
        "url": "/api/downloads/companion/windows?version=0.3.1",
    }
    with pytest.raises(ValueError, match="INVALID_UPDATE_URL"):
        parse_manifest(mismatched)


def test_fetch_manifest_uses_no_store_and_typed_invalid_manifest_error():
    client = _Client(json.dumps(_manifest_json()).encode("utf-8"))
    result = fetch_manifest(timeout=4.5, client=client)  # type: ignore[arg-type]

    assert result.version == "0.3.2"
    assert client.timeout == 4.5
    assert client.request.get_header("Cache-control") == "no-store"
    assert client.request.get_header("Pragma") == "no-cache"

    with pytest.raises(NetworkError, match="^MANIFEST_INVALID$"):
        fetch_manifest(client=_Client(b"not-json"))  # type: ignore[arg-type]


def test_download_update_uses_verified_release_chain(monkeypatch, tmp_path):
    payload = b"fake-msi-payload"
    manifest = _manifest(payload)
    seen: dict[str, object] = {}

    def fake_open(request, *, expected_github_url: str, timeout: float):
        seen["request_url"] = request.full_url
        seen["expected_github_url"] = expected_github_url
        seen["timeout"] = timeout
        return io.BytesIO(payload)

    monkeypatch.setattr("tda_companion.updates.open_verified_release", fake_open)

    target = download_update(manifest, tmp_path, timeout=12.5, prefer_bits=False)

    assert target.read_bytes() == payload
    assert seen == {
        "request_url": manifest.url,
        "expected_github_url": (
            "https://github.com/Faysk/tda/releases/download/companion-v0.3.2/"
            "TDACompanion-x64.msi"
        ),
        "timeout": 12.5,
    }
    assert not target.with_name(target.name + ".partial").exists()


def test_download_update_maps_rejected_release_chain_to_stable_error(monkeypatch, tmp_path):
    manifest = _manifest(b"fake-msi-payload")

    def reject(*args, **kwargs):  # noqa: ANN002, ANN003
        raise ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")

    monkeypatch.setattr("tda_companion.updates.open_verified_release", reject)

    with pytest.raises(RuntimeError, match="^UPDATE_REDIRECT_REJECTED$"):
        download_update(manifest, tmp_path, prefer_bits=False)

    target = tmp_path / "updates" / manifest.version / "TDACompanion-x64.msi"
    assert not target.exists()
    assert not target.with_name(target.name + ".partial").exists()


def test_download_update_reports_hash_mismatch_as_typed_network_error(monkeypatch, tmp_path):
    expected = b"expected-msi"
    manifest = _manifest(expected)
    actual = b"tampered-msi"
    manifest = UpdateManifest(
        version=manifest.version,
        tag=manifest.tag,
        minimum_api=manifest.minimum_api,
        url=manifest.url,
        sha256=manifest.sha256,
        size=len(actual),
    )
    monkeypatch.setattr(
        "tda_companion.updates.open_verified_release",
        lambda *args, **kwargs: io.BytesIO(actual),
    )

    with pytest.raises(NetworkError, match="^HASH_MISMATCH$"):
        download_update(manifest, tmp_path, prefer_bits=False)
