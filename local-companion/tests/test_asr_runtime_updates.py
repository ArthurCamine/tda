from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from tda_companion.asr_runtime_updates import (
    MAX_RUNTIME_DOWNLOAD_BYTES,
    WhisperRuntimeManifest,
    download_whisper_runtime,
    fetch_whisper_runtime_manifest,
    parse_whisper_runtime_manifest,
    whisper_runtime_update_available,
)
from tda_companion.network import NetworkError
from tda_companion.release_download import ReleaseRedirectError


def manifest_value(*, url: str | None = None, digest: str | None = None, size: int = 123) -> dict:
    return {
        "channel": "stable",
        "runtime_id": "whisper-ctranslate2",
        "version": "1.2.3",
        "tag": "companion-whisper-runtime-v1.2.3",
        "asset": {
            "url": url or "/api/downloads/companion/windows/whisper-runtime?version=1.2.3",
            "sha256": digest or "a" * 64,
            "size": size,
        },
    }


def test_runtime_manifest_requires_version_locked_tda_endpoint():
    value = parse_whisper_runtime_manifest(manifest_value())
    assert value.version == "1.2.3"
    assert value.url == (
        "https://dnd.faysk.dev/api/downloads/companion/windows/"
        "whisper-runtime?version=1.2.3"
    )

    with pytest.raises(ValueError, match="INVALID_RUNTIME_URL"):
        parse_whisper_runtime_manifest(manifest_value(url="https://example.com/runtime.zip"))
    with pytest.raises(ValueError, match="INVALID_RUNTIME_URL"):
        parse_whisper_runtime_manifest(
            manifest_value(url="/api/downloads/companion/windows/whisper-runtime")
        )
    with pytest.raises(ValueError, match="INVALID_RUNTIME_URL"):
        parse_whisper_runtime_manifest(
            manifest_value(
                url="/api/downloads/companion/windows/whisper-runtime?version=1.2.2"
            )
        )


def test_runtime_manifest_rejects_wrong_identity_digest_and_size():
    wrong = manifest_value()
    wrong["runtime_id"] = "other"
    with pytest.raises(ValueError, match="INVALID_RUNTIME_CHANNEL"):
        parse_whisper_runtime_manifest(wrong)
    with pytest.raises(ValueError, match="INVALID_RUNTIME_DIGEST"):
        parse_whisper_runtime_manifest(manifest_value(digest="sha256:bad"))
    with pytest.raises(ValueError, match="INVALID_RUNTIME_SIZE"):
        parse_whisper_runtime_manifest(manifest_value(size=MAX_RUNTIME_DOWNLOAD_BYTES + 1))


def test_runtime_update_comparison_handles_missing_semver_and_compatibility_floor():
    value = parse_whisper_runtime_manifest(manifest_value())
    assert whisper_runtime_update_available(None, value) is True
    assert whisper_runtime_update_available("1.2.2", value) is True
    assert whisper_runtime_update_available("1.2.3", value) is False
    assert whisper_runtime_update_available("2.0.0", value) is False

    obsolete = WhisperRuntimeManifest(
        version="1.1.1",
        tag="companion-whisper-runtime-v1.1.1",
        url="https://dnd.faysk.dev/api/downloads/companion/windows/whisper-runtime?version=1.1.1",
        sha256="a" * 64,
        size=123,
    )
    assert whisper_runtime_update_available(None, obsolete) is False
    assert whisper_runtime_update_available("1.1.1", obsolete) is False


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.offset = 0
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.payload):
            return b""
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeClient:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout: float):
        self.request = request
        self.timeout = timeout
        return FakeResponse(self.payload)


def test_runtime_manifest_fetch_is_no_store_and_invalid_payload_is_typed():
    payload = json.dumps(manifest_value()).encode("utf-8")
    client = FakeClient(payload)

    manifest = fetch_whisper_runtime_manifest(timeout=4.0, client=client)  # type: ignore[arg-type]

    assert manifest.version == "1.2.3"
    assert client.timeout == 4.0
    assert client.request.get_header("Cache-control") == "no-store"
    assert client.request.get_header("Pragma") == "no-cache"

    with pytest.raises(NetworkError, match="^MANIFEST_INVALID$"):
        fetch_whisper_runtime_manifest(client=FakeClient(b"not-json"))  # type: ignore[arg-type]


def test_runtime_download_uses_verified_release_chain_and_hash(tmp_path: Path, monkeypatch):
    payload = b"verified-runtime"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = WhisperRuntimeManifest(
        version="1.2.3",
        tag="companion-whisper-runtime-v1.2.3",
        url="https://dnd.faysk.dev/api/downloads/companion/windows/whisper-runtime?version=1.2.3",
        sha256=digest,
        size=len(payload),
    )
    expected = (
        "https://github.com/Faysk/tda/releases/download/companion-whisper-runtime-v1.2.3/"
        "TDAWhisperRuntime-1.2.3-windows-x64.zip"
    )
    calls: dict[str, object] = {}

    def verified(request, *, expected_github_url, timeout):
        calls["request_url"] = request.full_url
        calls["url"] = expected_github_url
        calls["timeout"] = timeout
        return FakeResponse(payload)

    monkeypatch.setattr("tda_companion.asr_runtime_updates.open_verified_release", verified)
    target = download_whisper_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert target.read_bytes() == payload
    assert calls["request_url"] == manifest.url
    assert calls["url"] == expected
    assert not target.with_name(target.name + ".partial").exists()


def test_runtime_download_maps_rejected_release_chain_to_stable_error(tmp_path: Path, monkeypatch):
    payload = b"verified-runtime"
    manifest = WhisperRuntimeManifest(
        version="1.2.3",
        tag="companion-whisper-runtime-v1.2.3",
        url="https://dnd.faysk.dev/api/downloads/companion/windows/whisper-runtime?version=1.2.3",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )
    monkeypatch.setattr(
        "tda_companion.asr_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")),
    )
    with pytest.raises(RuntimeError, match="RUNTIME_REDIRECT_REJECTED"):
        download_whisper_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert not any((tmp_path / "Cache").rglob("*.partial"))


def test_runtime_download_reports_hash_mismatch_as_typed_error(tmp_path: Path, monkeypatch):
    actual = b"different-runtime"
    manifest = WhisperRuntimeManifest(
        version="1.2.3",
        tag="companion-whisper-runtime-v1.2.3",
        url="https://dnd.faysk.dev/api/downloads/companion/windows/whisper-runtime?version=1.2.3",
        sha256=hashlib.sha256(b"expected-runtime").hexdigest(),
        size=len(actual),
    )
    monkeypatch.setattr(
        "tda_companion.asr_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: FakeResponse(actual),
    )

    with pytest.raises(NetworkError, match="^HASH_MISMATCH$"):
        download_whisper_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert not any((tmp_path / "Cache").rglob("*.partial"))
