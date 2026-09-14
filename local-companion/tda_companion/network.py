from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class NetworkFailure:
    code: str
    status: int | None = None


class NetworkError(RuntimeError):
    def __init__(self, code: str, *, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def _reason(exc: BaseException) -> BaseException:
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return exc.reason
    return exc


def classify_network_error(exc: BaseException) -> NetworkFailure:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 407:
            return NetworkFailure("PROXY_FAILED", status=407)
        return NetworkFailure("HTTP_ERROR", status=exc.code)

    reason = _reason(exc)
    winerror = getattr(reason, "winerror", None)
    error_number = getattr(reason, "errno", None)

    if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
        return NetworkFailure("TLS_FAILED")
    if isinstance(reason, socket.gaierror) or winerror in {11001, 11002, 11003, 11004}:
        return NetworkFailure("DNS_FAILED")
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return NetworkFailure("CONNECT_TIMEOUT")
    if isinstance(reason, OSError) and (
        winerror in {10050, 10051, 10052, 10064, 10065}
        or error_number in {errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH}
    ):
        return NetworkFailure("OFFLINE")

    text = str(reason).casefold()
    if "proxy" in text:
        return NetworkFailure("PROXY_FAILED")
    return NetworkFailure("HTTP_ERROR")


class NetworkClient:
    """Small typed transport boundary for loopback and Internet traffic.

    Loopback explicitly bypasses proxies. Internet mode preserves the user's
    configured urllib/system proxy discovery. Callers receive stable product
    error codes rather than platform-specific socket/WinError strings.
    """

    def __init__(
        self,
        *,
        mode: str,
        opener: Any | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> None:
        if mode not in {"loopback", "internet"}:
            raise ValueError("INVALID_NETWORK_MODE")
        self.mode = mode
        if mode == "loopback":
            self.proxies: dict[str, str] = {}
        else:
            self.proxies = dict(urllib.request.getproxies() if proxies is None else proxies)
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler(self.proxies)
        )

    @classmethod
    def loopback(cls, *, opener: Any | None = None) -> "NetworkClient":
        return cls(mode="loopback", opener=opener)

    @classmethod
    def internet(
        cls,
        *,
        opener: Any | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> "NetworkClient":
        return cls(mode="internet", opener=opener, proxies=proxies)

    def open(self, request: urllib.request.Request, *, timeout: float):
        try:
            return self.opener.open(request, timeout=timeout)
        except NetworkError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ssl.SSLError) as exc:
            failure = classify_network_error(exc)
            raise NetworkError(failure.code, status=failure.status) from exc
