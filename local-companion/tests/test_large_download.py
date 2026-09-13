from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest

from tda_companion.large_download import (
    LargeDownloadError,
    download_verified_release_asset,
    github_release_asset_url,
    validate_github_release_asset_url,
)
from tda_companion.network import NetworkError


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _url() -> str:
    return github_release_asset_url("companion-v0.3.3", "TDACompanion-x64.msi")


def _download(
    tmp_path: Path,
    payload: bytes,
    *,
    fallback_payload: bytes | None = None,
    prefer_bits: bool = False,
):
    target = tmp_path / "TDACompanion-x64.msi"
    fallback = payload if fallback_payload is None else fallback_payload
    return download_verified_release_asset(
        target=target,
        github_url=_url(),
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        timeout=2.0,
        fallback_open=lambda: io.BytesIO(fallback),
        prefer_bits=prefer_bits,
        size_exceeded_code="TEST_SIZE_EXCEEDED",
        size_mismatch_code="TEST_SIZE_MISMATCH",
    )


def test_release_asset_url_is_derived_from_exact_github_namespace():
    url = _url()
    assert validate_github_release_asset_url(url) == url

    for invalid in (
        "http://github.com/Faysk/tda/releases/download/companion-v0.3.3/TDACompanion-x64.msi",
        "https://github.com/Other/tda/releases/download/companion-v0.3.3/TDACompanion-x64.msi",
        "https://github.com/Faysk/tda/releases/download/companion-v0.3.3/TDACompanion-x64.msi?x=1",
        "https://github.com@evil.example/Faysk/tda/releases/download/companion-v0.3.3/TDACompanion-x64.msi",
    ):
        with pytest.raises(ValueError, match="INVALID_RELEASE_ASSET_URL"):
            validate_github_release_asset_url(invalid)

    with pytest.raises(ValueError, match="INVALID_RELEASE_TAG"):
        github_release_asset_url("../companion-v0.3.3", "TDACompanion-x64.msi")
    with pytest.raises(ValueError, match="INVALID_RELEASE_ASSET"):
        github_release_asset_url("companion-v0.3.3", "../TDACompanion-x64.msi")


def test_fallback_transport_still_verifies_hash_and_atomically_materializes(tmp_path: Path):
    payload = b"verified-msi"
    target = _download(tmp_path, payload)

    assert target.read_bytes() == payload
    assert not target.with_name(target.name + ".partial").exists()


def test_valid_final_or_partial_bytes_are_reused_without_network(tmp_path: Path):
    payload = b"already-downloaded"
    target = tmp_path / "TDACompanion-x64.msi"
    target.write_bytes(payload)

    result = download_verified_release_asset(
        target=target,
        github_url=_url(),
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        timeout=2.0,
        fallback_open=lambda: (_ for _ in ()).throw(AssertionError("network should not run")),
        prefer_bits=False,
        size_exceeded_code="TEST_SIZE_EXCEEDED",
        size_mismatch_code="TEST_SIZE_MISMATCH",
    )
    assert result == target.resolve()

    target.unlink()
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(payload)
    result = download_verified_release_asset(
        target=target,
        github_url=_url(),
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        timeout=2.0,
        fallback_open=lambda: (_ for _ in ()).throw(AssertionError("network should not run")),
        prefer_bits=False,
        size_exceeded_code="TEST_SIZE_EXCEEDED",
        size_mismatch_code="TEST_SIZE_MISMATCH",
    )
    assert result.read_bytes() == payload
    assert not partial.exists()


def test_fallback_hash_mismatch_never_materializes_final_file(tmp_path: Path):
    expected = b"expected-bytes"
    actual = b"tampered-bytes"
    assert len(expected) == len(actual)

    with pytest.raises(NetworkError, match="^HASH_MISMATCH$"):
        _download(tmp_path, expected, fallback_payload=actual)

    target = tmp_path / "TDACompanion-x64.msi"
    assert not target.exists()
    assert not target.with_name(target.name + ".partial").exists()


@pytest.mark.skipif(os.name != "nt", reason="BITS is a Windows transport")
def test_bits_complete_uses_direct_github_asset_and_still_verifies_bytes(
    tmp_path: Path,
    monkeypatch,
):
    payload = b"bits-complete"
    seen: dict[str, object] = {}

    def complete(source_url: str, destination: Path, *, timeout: float) -> str:
        seen["source"] = source_url
        seen["destination"] = destination.name
        seen["timeout"] = timeout
        destination.write_bytes(payload)
        return "complete"

    monkeypatch.setattr("tda_companion.large_download._run_bits_transfer", complete)
    target = download_verified_release_asset(
        target=tmp_path / "TDACompanion-x64.msi",
        github_url=_url(),
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        timeout=3.0,
        fallback_open=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
        prefer_bits=True,
        size_exceeded_code="TEST_SIZE_EXCEEDED",
        size_mismatch_code="TEST_SIZE_MISMATCH",
    )

    assert target.read_bytes() == payload
    assert seen == {
        "source": _url(),
        "destination": "TDACompanion-x64.msi.partial",
        "timeout": 3.0,
    }


@pytest.mark.skipif(os.name != "nt", reason="BITS is a Windows transport")
def test_bits_pending_keeps_job_owned_transfer_for_later_retry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "tda_companion.large_download._run_bits_transfer",
        lambda *_args, **_kwargs: "pending",
    )

    with pytest.raises(NetworkError, match="^DOWNLOAD_CONTINUES_IN_BACKGROUND$"):
        download_verified_release_asset(
            target=tmp_path / "TDACompanion-x64.msi",
            github_url=_url(),
            expected_size=10,
            expected_sha256="a" * 64,
            timeout=1.0,
            fallback_open=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
            prefer_bits=True,
            size_exceeded_code="TEST_SIZE_EXCEEDED",
            size_mismatch_code="TEST_SIZE_MISMATCH",
        )


@pytest.mark.skipif(os.name != "nt", reason="BITS is a Windows transport")
def test_bits_unavailable_falls_back_to_existing_verified_transport(tmp_path: Path, monkeypatch):
    payload = b"safe-fallback"
    monkeypatch.setattr(
        "tda_companion.large_download._run_bits_transfer",
        lambda *_args, **_kwargs: "unavailable",
    )

    target = _download(tmp_path, payload, prefer_bits=True)
    assert target.read_bytes() == payload


@pytest.mark.skipif(os.name != "nt", reason="BITS is a Windows transport")
def test_bits_corrupt_completion_is_rejected_after_transport(tmp_path: Path, monkeypatch):
    expected = b"expected-bits"
    actual = b"tampered-bits"
    assert len(expected) == len(actual)

    def corrupt(_source_url: str, destination: Path, *, timeout: float) -> str:
        assert timeout == 2.0
        destination.write_bytes(actual)
        return "complete"

    monkeypatch.setattr("tda_companion.large_download._run_bits_transfer", corrupt)
    with pytest.raises(NetworkError, match="^HASH_MISMATCH$"):
        _download(tmp_path, expected, prefer_bits=True)

    target = tmp_path / "TDACompanion-x64.msi"
    assert not target.exists()
    assert not target.with_name(target.name + ".partial").exists()


def test_fallback_size_mismatch_is_typed_and_cleaned(tmp_path: Path):
    expected = b"123456"
    actual = b"123"
    with pytest.raises(LargeDownloadError, match="^TEST_SIZE_MISMATCH$"):
        _download(tmp_path, expected, fallback_payload=actual)
    assert not (tmp_path / "TDACompanion-x64.msi.partial").exists()
