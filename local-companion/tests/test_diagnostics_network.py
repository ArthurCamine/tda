from __future__ import annotations

import tda_companion.diagnostics as diagnostics
from tda_companion.network import NetworkError
from tda_companion.updates import UpdateManifest


class _Response:
    def __init__(self, status: int = 200, *, size: int | None = None, body: bytes = b"{}"):
        self.status = status
        self.headers = {} if size is None else {"Content-Length": str(size)}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self, _limit: int = -1):
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


def test_asset_diagnostic_uses_head_and_validates_manifest_size():
    manifest = _manifest()
    client = _Client(_Response(status=200, size=manifest.size))

    result = diagnostics._asset_check(client, manifest)

    assert result["status"] == "pass"
    request, timeout = client.requests[0]
    assert request.get_method() == "HEAD"
    assert request.full_url == manifest.url
    assert timeout == 6.0


def test_asset_diagnostic_rejects_size_mismatch():
    manifest = _manifest(size=1234)
    result = diagnostics._asset_check(_Client(_Response(status=200, size=999)), manifest)
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
