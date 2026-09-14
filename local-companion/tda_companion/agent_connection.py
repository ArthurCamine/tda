from __future__ import annotations

import errno
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from . import VERSION

PRODUCT_ID = "tda-companion"
API_VERSION = "1"
_HEALTH_LIMIT = 64 * 1024
_RESPONSE_LIMIT = 2 * 1024 * 1024
_RECOVERY_BACKOFF_SECONDS = (3.0, 5.0, 10.0, 30.0)


class AgentConnectionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AgentTransportError(AgentConnectionError):
    pass


@dataclass(frozen=True)
class AgentProbe:
    state: str
    payload: dict[str, Any] | None = None
    code: str | None = None

    @property
    def usable(self) -> bool:
        return self.state in {"exact", "compatible"}


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/v1/health"


def loopback_opener():
    """Return an opener that never routes loopback traffic through user/system proxies."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _transport_code(exc: BaseException) -> str:
    value: BaseException = exc
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        value = exc.reason
    if isinstance(value, (socket.timeout, TimeoutError)):
        return "AGENT_CONNECTION_TIMEOUT"
    if isinstance(value, ConnectionRefusedError):
        return "AGENT_CONNECTION_REFUSED"
    if isinstance(value, OSError):
        if getattr(value, "winerror", None) == 10061 or value.errno == errno.ECONNREFUSED:
            return "AGENT_CONNECTION_REFUSED"
    return "AGENT_CONNECTION_FAILED"


def _decode_json(response: Any, limit: int) -> dict[str, Any]:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise AgentConnectionError("AGENT_RESPONSE_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AgentConnectionError("AGENT_RESPONSE_INVALID") from exc
    if not isinstance(value, dict):
        raise AgentConnectionError("AGENT_RESPONSE_INVALID")
    return value


def probe_agent(
    port: int,
    *,
    expected_version: str | None = None,
    timeout: float = 0.5,
    opener: Any | None = None,
) -> AgentProbe:
    client = opener or loopback_opener()
    request = urllib.request.Request(
        health_url(port),
        headers={"Accept": "application/json", "Cache-Control": "no-store"},
        method="GET",
    )
    try:
        with client.open(request, timeout=timeout) as response:
            if response.status != 200:
                return AgentProbe("foreign", code=f"AGENT_PORT_HTTP_{response.status}")
            try:
                payload = _decode_json(response, _HEALTH_LIMIT)
            except AgentConnectionError as exc:
                return AgentProbe("foreign", code=exc.code)
    except urllib.error.HTTPError as exc:
        return AgentProbe("foreign", code=f"AGENT_PORT_HTTP_{exc.code}")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return AgentProbe("unavailable", code=_transport_code(exc))

    if payload.get("product_id") != PRODUCT_ID:
        return AgentProbe("foreign", payload=payload, code="AGENT_IDENTITY_MISMATCH")
    if str(payload.get("api_version") or "") != API_VERSION:
        return AgentProbe("incompatible", payload=payload, code="AGENT_API_INCOMPATIBLE")
    service_version = payload.get("service_version")
    pid = payload.get("pid")
    reported_port = payload.get("port")
    if (
        not isinstance(service_version, str)
        or not service_version.strip()
        or not isinstance(pid, int)
        or pid <= 0
        or reported_port != port
    ):
        return AgentProbe("foreign", payload=payload, code="AGENT_IDENTITY_INVALID")
    if expected_version is not None and service_version != expected_version:
        return AgentProbe("compatible", payload=payload, code="AGENT_VERSION_MISMATCH")
    return AgentProbe("exact", payload=payload)


class AgentConnection:
    """Verified, recoverable connection to the per-user loopback Agent.

    Every authenticated request first proves the process listening on the port is
    the TDA Agent. Recovery is serialized and bounded so concurrent UI polling
    cannot create a spawn storm.
    """

    def __init__(
        self,
        token: str,
        port: int,
        start_agent: Callable[[], Any],
        *,
        expected_version: str = VERSION,
        opener: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = token
        self.port = port
        self.base = f"http://127.0.0.1:{port}/api/v1"
        self.expected_version = expected_version
        self.start_agent = start_agent
        self.opener = opener or loopback_opener()
        self.clock = clock
        self.sleep = sleep
        self._recovery_lock = threading.Lock()
        self._manual_stop = False
        self._failure_count = 0
        self._next_recovery_at = 0.0
        self._state = "starting"
        self._compatibility = "unknown"
        self._last_error: str | None = None
        self._last_probe: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        remaining = max(0.0, self._next_recovery_at - self.clock())
        return {
            "state": self._state,
            "compatibility": self._compatibility,
            "error": self._last_error,
            "retry_after_seconds": round(remaining, 1) if remaining else 0.0,
            "service_version": (self._last_probe or {}).get("service_version"),
            "pid": (self._last_probe or {}).get("pid"),
            "port": self.port,
        }

    def _record_probe(self, probe: AgentProbe) -> None:
        self._last_probe = probe.payload
        if probe.state == "exact":
            self._state = "ready"
            self._compatibility = "exact"
            self._last_error = None
        elif probe.state == "compatible":
            self._state = "ready"
            self._compatibility = "compatible"
            self._last_error = probe.code
        elif probe.state == "incompatible":
            self._state = "incompatible"
            self._compatibility = "incompatible"
            self._last_error = probe.code
        elif probe.state == "foreign":
            self._state = "port_conflict"
            self._compatibility = "foreign"
            self._last_error = probe.code
        elif self._manual_stop:
            self._state = "stopped_by_user"
            self._compatibility = "unknown"
            self._last_error = "AGENT_STOPPED_BY_USER"
        else:
            self._state = "unavailable"
            self._compatibility = "unknown"
            self._last_error = probe.code

    def probe(self, *, timeout: float = 0.5) -> AgentProbe:
        probe = probe_agent(
            self.port,
            expected_version=self.expected_version,
            timeout=timeout,
            opener=self.opener,
        )
        self._record_probe(probe)
        return probe

    def _register_recovery_failure(self, code: str) -> None:
        index = min(self._failure_count, len(_RECOVERY_BACKOFF_SECONDS) - 1)
        self._next_recovery_at = self.clock() + _RECOVERY_BACKOFF_SECONDS[index]
        self._failure_count += 1
        self._state = "unavailable"
        self._compatibility = "unknown"
        self._last_error = code

    def _mark_recovered(self, probe: AgentProbe) -> None:
        self._failure_count = 0
        self._next_recovery_at = 0.0
        self._manual_stop = False
        self._record_probe(probe)

    def _wait_for_agent(self, timeout: float, *, require_exact: bool = False) -> AgentProbe:
        deadline = self.clock() + timeout
        last = AgentProbe("unavailable", code="AGENT_CONNECTION_TIMEOUT")
        while self.clock() < deadline:
            last = self.probe(timeout=min(0.4, max(0.05, deadline - self.clock())))
            if last.state == "exact" or (last.state == "compatible" and not require_exact):
                return last
            if last.state in {"foreign", "incompatible"}:
                return last
            self.sleep(0.1)
        return last

    def _recover(self) -> None:
        if self._manual_stop:
            self._state = "stopped_by_user"
            raise AgentConnectionError("AGENT_STOPPED_BY_USER")
        with self._recovery_lock:
            current = self.probe(timeout=0.25)
            if current.usable:
                self._mark_recovered(current)
                return
            if current.state == "foreign":
                raise AgentConnectionError("AGENT_PORT_CONFLICT")
            if current.state == "incompatible":
                raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
            now = self.clock()
            if now < self._next_recovery_at:
                raise AgentConnectionError("AGENT_RECONNECT_BACKOFF")

            self._state = "reconnecting"
            self._last_error = current.code
            try:
                self.start_agent()
            except BaseException as exc:
                self._register_recovery_failure("AGENT_START_FAILED")
                raise AgentConnectionError("AGENT_START_FAILED") from exc

            ready = self._wait_for_agent(10.0)
            if ready.usable:
                self._mark_recovered(ready)
                return
            if ready.state == "foreign":
                self._record_probe(ready)
                raise AgentConnectionError("AGENT_PORT_CONFLICT")
            if ready.state == "incompatible":
                self._record_probe(ready)
                raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
            self._register_recovery_failure(ready.code or "AGENT_RECOVERY_FAILED")
            raise AgentConnectionError("AGENT_RECOVERY_FAILED")

    def _ensure_verified(self, *, mutate: bool) -> None:
        if self._manual_stop:
            self._state = "stopped_by_user"
            raise AgentConnectionError("AGENT_STOPPED_BY_USER")
        probe = self.probe(timeout=0.35)
        if probe.state == "exact":
            return
        if probe.state == "compatible":
            if mutate:
                raise AgentConnectionError("AGENT_VERSION_MISMATCH")
            return
        if probe.state == "foreign":
            raise AgentConnectionError("AGENT_PORT_CONFLICT")
        if probe.state == "incompatible":
            raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
        self._recover()
        probe = self.probe(timeout=0.35)
        if probe.state == "compatible" and mutate:
            raise AgentConnectionError("AGENT_VERSION_MISMATCH")
        if not probe.usable:
            raise AgentConnectionError(probe.code or "AGENT_UNAVAILABLE")

    def _request_once(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Cache-Control": "no-store",
        }
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Origin"] = "https://dnd.faysk.dev"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(_RESPONSE_LIMIT + 1)
                if len(raw) > _RESPONSE_LIMIT:
                    raise AgentConnectionError("AGENT_RESPONSE_TOO_LARGE")
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise AgentConnectionError("AGENT_RESPONSE_INVALID") from exc
        except urllib.error.HTTPError as exc:
            code = f"HTTP_{exc.code}"
            try:
                payload = json.loads(exc.read(8192).decode("utf-8"))
                code = str(payload.get("error", {}).get("code") or code)
            except Exception:
                pass
            raise AgentConnectionError(code) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise AgentTransportError(_transport_code(exc)) from None

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        mutate = method != "GET" and path != "/agent/control"
        self._ensure_verified(mutate=mutate)
        try:
            return self._request_once(method, path, body, idempotency_key=idempotency_key)
        except AgentTransportError:
            self._recover()
            self._ensure_verified(mutate=mutate)
            return self._request_once(method, path, body, idempotency_key=idempotency_key)

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        return self._request("POST", path, body, idempotency_key=idempotency_key)

    def mark_stopped_by_user(self) -> None:
        self._manual_stop = True
        self._state = "stopped_by_user"
        self._compatibility = "unknown"
        self._last_error = "AGENT_STOPPED_BY_USER"

    def resume_auto_recovery(self) -> None:
        self._manual_stop = False
        self._state = "starting"
        self._last_error = None
        self._next_recovery_at = 0.0

    def stop_by_user(self, *, force: bool = False) -> dict[str, Any]:
        probe = self.probe(timeout=0.35)
        if probe.state == "unavailable":
            self.mark_stopped_by_user()
            return {"accepted": False, "already_stopped": True}
        if probe.state == "foreign":
            raise AgentConnectionError("AGENT_PORT_CONFLICT")
        if probe.state == "incompatible":
            raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
        try:
            value = self._request_once(
                "POST",
                "/agent/control",
                {"action": "shutdown", "force": bool(force)},
            )
        except AgentTransportError:
            value = {"accepted": False, "already_stopped": True}
        self.mark_stopped_by_user()
        return value if isinstance(value, dict) else {"accepted": True}

    def restart(self) -> bool:
        with self._recovery_lock:
            self._manual_stop = False
            probe = self.probe(timeout=0.35)
            if probe.state == "foreign":
                raise AgentConnectionError("AGENT_PORT_CONFLICT")
            if probe.state == "incompatible":
                raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
            if probe.usable:
                try:
                    self._request_once(
                        "POST",
                        "/agent/control",
                        {"action": "shutdown", "force": False},
                    )
                except AgentTransportError:
                    pass
                deadline = self.clock() + 8.0
                while self.clock() < deadline:
                    if self.probe(timeout=0.2).state == "unavailable":
                        break
                    self.sleep(0.1)
                else:
                    raise AgentConnectionError("AGENT_SHUTDOWN_TIMEOUT")

            self._state = "starting"
            self._last_error = None
            try:
                self.start_agent()
            except BaseException as exc:
                self._register_recovery_failure("AGENT_START_FAILED")
                raise AgentConnectionError("AGENT_START_FAILED") from exc
            ready = self._wait_for_agent(10.0, require_exact=True)
            if ready.state != "exact":
                if ready.state == "compatible":
                    raise AgentConnectionError("AGENT_RESTART_VERSION_MISMATCH")
                if ready.state == "foreign":
                    raise AgentConnectionError("AGENT_PORT_CONFLICT")
                if ready.state == "incompatible":
                    raise AgentConnectionError("AGENT_API_INCOMPATIBLE")
                self._register_recovery_failure(ready.code or "AGENT_RESTART_FAILED")
                raise AgentConnectionError("AGENT_RESTART_FAILED")
            self._mark_recovered(ready)
            return True
