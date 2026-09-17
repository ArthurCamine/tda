from __future__ import annotations

from email.message import Message
from urllib.request import Request

import pytest

import tda_companion.release_download as release_download
from tda_companion.release_download import ReleaseRedirectError, _ReleaseRedirectHandler


EXPECTED = (
    "https://github.com/Faysk/tda/releases/download/companion-qwen-runtime-v1.0.0/"
    "TDAQwenRuntime-1.0.0-windows-x64.zip.part001"
)
START = (
    "https://dnd.faysk.dev/api/downloads/companion/windows/qwen-runtime/"
    "TDAQwenRuntime-1.0.0-windows-x64.zip.part001"
)


def _redirect(handler, request: Request, target: str) -> Request:
    value = handler.redirect_request(request, None, 307, "Temporary Redirect", Message(), target)
    assert isinstance(value, Request)
    return value


def test_release_redirect_accepts_exact_github_asset_then_github_storage():
    handler = _ReleaseRedirectHandler(EXPECTED)
    github = _redirect(handler, Request(START), EXPECTED)
    storage_url = "https://release-assets.githubusercontent.com/github-production-release-asset/x?sig=abc"
    storage = _redirect(handler, github, storage_url)
    assert storage.full_url == storage_url


def test_open_verified_release_marks_direct_exact_github_request_as_reached(monkeypatch):
    captured = {}

    class Opener:
        def open(self, request, timeout):  # noqa: ANN001
            captured["request"] = request
            captured["timeout"] = timeout
            return object()

    def build_opener(handler):  # noqa: ANN001
        captured["handler"] = handler
        return Opener()

    monkeypatch.setattr(release_download.urllib.request, "build_opener", build_opener)
    request = Request(EXPECTED)
    result = release_download.open_verified_release(
        request,
        expected_github_url=EXPECTED,
        timeout=7.0,
    )

    assert result is not None
    assert captured["handler"].reached_github is True
    storage_url = "https://release-assets.githubusercontent.com/github-production-release-asset/x?sig=abc"
    redirected = _redirect(captured["handler"], request, storage_url)
    assert redirected.full_url == storage_url


def test_release_redirect_rejects_any_first_hop_other_than_exact_expected_asset():
    handler = _ReleaseRedirectHandler(EXPECTED)
    with pytest.raises(ReleaseRedirectError, match="RELEASE_REDIRECT_REJECTED"):
        _redirect(handler, Request(START), "https://github.com/Faysk/tda/releases/download/other/file")


def test_release_redirect_rejects_external_or_insecure_storage_hops():
    handler = _ReleaseRedirectHandler(EXPECTED)
    github = _redirect(handler, Request(START), EXPECTED)
    with pytest.raises(ReleaseRedirectError, match="RELEASE_REDIRECT_REJECTED"):
        _redirect(handler, github, "https://example.com/runtime.zip")

    handler = _ReleaseRedirectHandler(EXPECTED)
    github = _redirect(handler, Request(START), EXPECTED)
    with pytest.raises(ReleaseRedirectError, match="RELEASE_REDIRECT_REJECTED"):
        _redirect(handler, github, "http://release-assets.githubusercontent.com/file")


def test_release_redirect_rejects_non_official_expected_url():
    with pytest.raises(ReleaseRedirectError, match="RELEASE_EXPECTED_URL_INVALID"):
        _ReleaseRedirectHandler("https://example.com/runtime.zip")
