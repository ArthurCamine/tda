from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
import urllib.request

import pytest

from tda_companion.network import NetworkClient, NetworkError, classify_network_error


def test_loopback_transport_disables_proxies():
    client = NetworkClient.loopback()
    assert client.mode == "loopback"
    assert client.proxies == {}


def test_internet_transport_preserves_configured_proxies():
    client = NetworkClient.internet(proxies={"https": "http://127.0.0.1:8080"})
    assert client.mode == "internet"
    assert client.proxies == {"https": "http://127.0.0.1:8080"}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (urllib.error.URLError(socket.gaierror(11001, "name not known")), "DNS_FAILED"),
        (urllib.error.URLError(TimeoutError("timed out")), "CONNECT_TIMEOUT"),
        (urllib.error.URLError(OSError(errno.ENETUNREACH, "network unreachable")), "OFFLINE"),
        (urllib.error.URLError(ssl.SSLError("certificate verify failed")), "TLS_FAILED"),
        (urllib.error.URLError(OSError("proxy connection failed")), "PROXY_FAILED"),
    ],
)
def test_classify_transport_errors(error: BaseException, code: str):
    assert classify_network_error(error).code == code


def test_http_and_proxy_status_are_typed():
    request_url = "https://dnd.faysk.dev/health"
    assert classify_network_error(
        urllib.error.HTTPError(request_url, 503, "unavailable", {}, None)
    ).code == "HTTP_ERROR"
    proxy = classify_network_error(
        urllib.error.HTTPError(request_url, 407, "proxy auth", {}, None)
    )
    assert proxy.code == "PROXY_FAILED"
    assert proxy.status == 407


def test_client_exposes_stable_code_instead_of_platform_error():
    class FailingOpener:
        def open(self, _request, timeout=None):
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))

    client = NetworkClient.internet(opener=FailingOpener(), proxies={})
    request = urllib.request.Request("https://dnd.faysk.dev/api/version")

    with pytest.raises(NetworkError, match="^DNS_FAILED$") as exc:
        client.open(request, timeout=2.0)
    assert exc.value.code == "DNS_FAILED"
