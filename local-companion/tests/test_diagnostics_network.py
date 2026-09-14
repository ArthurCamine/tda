from __future__ import annotations

import tda_companion.diagnostics as diagnostics
from tda_companion.network import NetworkError
from tda_companion.updates import UpdateManifest


class _Response:
    def __init__(
        self,
        status: int = 200,
        *,
        size: int | None = None,
        content_range: str | None = None,
        body: bytes = b"",
    ):
        self.status = status
        self.headers = {}
        if size is not None:
            self.headers["Content-Length"] = str(size)
        if content_range is not None:
            self.headers["Content-Range"] = content_range
        self._body = body
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self, _limit: int = -1):
        self.read_calls += 1
        return self._body


class _Client:
    def __init__(self, response: _Response | None = None, error: NetworkError | None = None):
        self.response = response or _Response()
        self.error = error
        self.requests = []

    def open(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def _manifest(size: int = 1234) -> UpdateManifest:
    return UpdateManifest(
        version="0.3.3",
        tag="companion-v0.3.3",
        minimum_api="1",
        url="https://dnd.faysk.dev/api/downloads/companion/windows?version=0.3.3",
        sha256="a" * 64,
        size=size,
    )


def test_asset_diagnostic_requests_only_first_byte_and_validates_total_size():
    manifest = _manifest()
    response = _Response(
        status=206,
        size=1,
        content_range=f"bytes 0-0/{manifest.size}",
    )
    client = _Client(response)

    result = diagnostics._asset_check(client, manifest)

    assert result["status"] == "pass"
    request, timeout = client.requests[0]
    assert request.get_method() == "GET"
    assert request.full_url == manifest.url
    assert request.get_header("Range") == "bytes=0-0"
    assert timeout == 6.0
    assert response.read_calls == 0


def test_asset_diagnostic_accepts_full_response_headers_without_reading_body():
    manifest = _manifest()
    response = _Response(status=200, size=manifest.size)
    result = diagnostics._asset_check(_Client(response), manifest)
    assert result["status"] == "pass"
    assert response.read_calls == 0


def test_asset_diagnostic_rejects_total_size_mismatch():
    manifest = _manifest(size=1234)
    response = _Response(status=206, size=1, content_range="bytes 0-0/999")
    result = diagnostics._asset_check(_Client(response), manifest)
    assert result["status"] == "fail"
    assert result["detail"] == "ASSET_SIZE_MISMATCH"


def test_https_diagnostic_preserves_stable_network_code():
    result = diagnostics._https_check(_Client(error=NetworkError("PROXY_FAILED")))
    assert result == {
        "code": "network_https",
        "status": "fail",
        "message": "Não foi possível conectar ao TDA por HTTPS",
        "detail": "PROXY_FAILED",
    }


def test_maintenance_channel_only_passes_with_validated_manifest():
    assert diagnostics._maintenance_channel_check(None)["status"] == "unavailable"
    ready = diagnostics._maintenance_channel_check(_manifest())
    assert ready["status"] == "pass"
    assert "companion-v0.3.3" in ready["detail"]
