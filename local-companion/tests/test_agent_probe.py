from __future__ import annotations

import json
import urllib.error

from tda_companion.agent_connection import probe_agent


class _Response:
    def __init__(self, payload: object, status: int = 200):
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._raw[:size] if size >= 0 else self._raw


class _Opener:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _health(version: str = "0.3.2") -> dict[str, object]:
    return {
        "product_id": "tda-companion",
        "api_version": "1",
        "service_version": version,
        "pid": 321,
        "port": 8765,
        "lifecycle": "ready",
    }


def test_probe_accepts_exact_verified_agent():
    opener = _Opener(_Response(_health()))

    probe = probe_agent(8765, expected_version="0.3.2", opener=opener)

    assert probe.state == "exact"
    assert probe.usable is True
    request, _timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:8765/api/v1/health"
    assert request.get_header("Authorization") is None


def test_probe_classifies_same_api_different_version_as_compatible():
    probe = probe_agent(
        8765,
        expected_version="0.3.3",
        opener=_Opener(_Response(_health("0.3.2"))),
    )

    assert probe.state == "compatible"
    assert probe.code == "AGENT_VERSION_MISMATCH"


def test_probe_rejects_http_200_from_foreign_process():
    probe = probe_agent(
        8765,
        expected_version="0.3.2",
        opener=_Opener(_Response({"status": "ok"})),
    )

    assert probe.state == "foreign"
    assert probe.code == "AGENT_IDENTITY_MISMATCH"


def test_probe_rejects_incompatible_api():
    payload = _health()
    payload["api_version"] = "2"

    probe = probe_agent(8765, opener=_Opener(_Response(payload)))

    assert probe.state == "incompatible"
    assert probe.code == "AGENT_API_INCOMPATIBLE"


def test_probe_maps_connection_refused_to_unavailable():
    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))

    probe = probe_agent(8765, opener=_Opener(refused))

    assert probe.state == "unavailable"
    assert probe.code == "AGENT_CONNECTION_REFUSED"
