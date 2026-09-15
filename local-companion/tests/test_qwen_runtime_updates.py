from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tda_companion.network import NetworkError
from tda_companion.qwen_runtime_bundle import QwenRuntimePart, build_qwen_runtime_bundle_manifest
from tda_companion.qwen_runtime_updates import (
    QwenRuntimeDownloadManifest,
    download_qwen_runtime,
    fetch_qwen_runtime_manifest,
    parse_qwen_runtime_download_manifest,
    qwen_runtime_update_available,
)
from tda_companion.release_download import ReleaseRedirectError


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _part(version: str, index: int, payload: bytes) -> QwenRuntimePart:
    return QwenRuntimePart(
        index=index,
        name=f"TDAQwenRuntime-{version}-windows-x64.zip.part{index:03d}",
        size=len(payload),
        sha256=_sha(payload),
    )


def _manifest(version: str = "1.2.3", payloads: tuple[bytes, ...] = (b"one", b"two")) -> QwenRuntimeDownloadManifest:
    parts = tuple(_part(version, index, payload) for index, payload in enumerate(payloads, start=1))
    bundle = build_qwen_runtime_bundle_manifest(
        version=version,
        archive_sha256=_sha(b"".join(payloads)),
        parts=parts,
    )
    return QwenRuntimeDownloadManifest(
        version=version,
        tag=f"companion-qwen-runtime-v{version}",
        bundle=bundle,
    )


def _manifest_value(manifest: QwenRuntimeDownloadManifest) -> dict:
    return {
        "channel": "stable",
        "runtime_id": "qwen3-transformers",
        "version": manifest.version,
        "tag": manifest.tag,
        "bundle": manifest.bundle.as_dict(),
    }


def test_qwen_download_manifest_accepts_only_matching_stable_identity_and_bundle():
    manifest = _manifest()
    parsed = parse_qwen_runtime_download_manifest(_manifest_value(manifest))
    assert parsed == manifest

    wrong = _manifest_value(manifest)
    wrong["runtime_id"] = "other"
    with pytest.raises(ValueError, match="INVALID_QWEN_RUNTIME_CHANNEL"):
        parse_qwen_runtime_download_manifest(wrong)

    wrong = _manifest_value(manifest)
    wrong["tag"] = "companion-qwen-runtime-v9.9.9"
    with pytest.raises(ValueError, match="INVALID_QWEN_RUNTIME_TAG"):
        parse_qwen_runtime_download_manifest(wrong)

    wrong = _manifest_value(manifest)
    wrong["bundle"]["version"] = "1.2.4"
    with pytest.raises(ValueError, match="INVALID_QWEN_RUNTIME_BUNDLE"):
        parse_qwen_runtime_download_manifest(wrong)


def test_qwen_runtime_update_comparison_handles_missing_semver_and_compatibility_floor():
    manifest = _manifest()
    assert qwen_runtime_update_available(None, manifest) is True
    assert qwen_runtime_update_available("1.2.2", manifest) is True
    assert qwen_runtime_update_available("1.2.3", manifest) is False
    assert qwen_runtime_update_available("2.0.0", manifest) is False

    obsolete = _manifest(version="1.0.1", payloads=(b"old",))
    assert qwen_runtime_update_available(None, obsolete) is False
    assert qwen_runtime_update_available("1.0.1", obsolete) is False


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


def test_qwen_manifest_fetch_is_no_store_and_invalid_payload_is_typed():
    manifest = _manifest()
    client = FakeClient(json.dumps(_manifest_value(manifest)).encode("utf-8"))

    parsed = fetch_qwen_runtime_manifest(timeout=4.0, client=client)  # type: ignore[arg-type]

    assert parsed == manifest
    assert client.timeout == 4.0
    assert client.request.get_header("Cache-control") == "no-store"
    assert client.request.get_header("Pragma") == "no-cache"

    with pytest.raises(NetworkError, match="^MANIFEST_INVALID$"):
        fetch_qwen_runtime_manifest(client=FakeClient(b"not-json"))  # type: ignore[arg-type]


def test_qwen_runtime_download_uses_verified_release_chain_and_assembles_parts(tmp_path: Path, monkeypatch):
    payloads = (b"first-runtime-part", b"second-runtime-part")
    manifest = _manifest(payloads=payloads)
    responses = [FakeResponse(payload) for payload in payloads]
    expected_urls: list[str] = []

    def verified(_request, *, expected_github_url, timeout):
        expected_urls.append(expected_github_url)
        assert timeout == 300.0
        return responses.pop(0)

    monkeypatch.setattr("tda_companion.qwen_runtime_updates.open_verified_release", verified)
    target = download_qwen_runtime(manifest, tmp_path / "Cache", prefer_bits=False)

    assert target.name == "TDAQwenRuntime-1.2.3-windows-x64.zip"
    assert target.read_bytes() == b"".join(payloads)
    assert expected_urls == [
        f"https://github.com/Faysk/tda/releases/download/{manifest.tag}/{part.name}"
        for part in manifest.bundle.parts
    ]
    assert not list((tmp_path / "Cache").rglob("*.partial"))


def test_qwen_runtime_download_rejects_bad_release_chain_and_cleans_partial(tmp_path: Path, monkeypatch):
    payload = b"runtime-part"
    manifest = _manifest(payloads=(payload,))
    monkeypatch.setattr(
        "tda_companion.qwen_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ReleaseRedirectError("RELEASE_REDIRECT_REJECTED")),
    )

    with pytest.raises(RuntimeError, match="QWEN_RUNTIME_REDIRECT_REJECTED"):
        download_qwen_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert not list((tmp_path / "Cache").rglob("*.partial"))
    assert not list((tmp_path / "Cache").rglob("*.part001"))


def test_qwen_runtime_reuses_only_verified_cached_parts(tmp_path: Path, monkeypatch):
    payload = b"verified-cache"
    manifest = _manifest(payloads=(payload,))
    part = manifest.bundle.parts[0]
    parts_root = tmp_path / "Cache" / "runtime" / "qwen" / manifest.version / "parts"
    parts_root.mkdir(parents=True)
    cached = parts_root / part.name
    cached.write_bytes(payload)

    monkeypatch.setattr(
        "tda_companion.qwen_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network should not run")),
    )
    target = download_qwen_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert target.read_bytes() == payload


def test_qwen_runtime_replaces_tampered_cache_only_after_verified_download(tmp_path: Path, monkeypatch):
    payload = b"correct-runtime-part"
    manifest = _manifest(payloads=(payload,))
    part = manifest.bundle.parts[0]
    parts_root = tmp_path / "Cache" / "runtime" / "qwen" / manifest.version / "parts"
    parts_root.mkdir(parents=True)
    cached = parts_root / part.name
    cached.write_bytes(b"tampered-cache")
    monkeypatch.setattr(
        "tda_companion.qwen_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )

    target = download_qwen_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert cached.read_bytes() == payload
    assert target.read_bytes() == payload


def test_qwen_runtime_bad_download_never_materializes_part(tmp_path: Path, monkeypatch):
    payload = b"expected-runtime-part"
    manifest = _manifest(payloads=(payload,))
    part = manifest.bundle.parts[0]
    bad = b"corrupt-runtime-part!"
    assert len(bad) == part.size
    monkeypatch.setattr(
        "tda_companion.qwen_runtime_updates.open_verified_release",
        lambda *_args, **_kwargs: FakeResponse(bad),
    )

    with pytest.raises(NetworkError, match="^HASH_MISMATCH$"):
        download_qwen_runtime(manifest, tmp_path / "Cache", prefer_bits=False)
    assert not list((tmp_path / "Cache").rglob("*.part001"))
    assert not list((tmp_path / "Cache").rglob("*.partial"))
