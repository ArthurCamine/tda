from __future__ import annotations

from typing import Any

from .agent_connection import AgentConnection, AgentConnectionError, AgentTransportError

_IDEMPOTENT_POST_PATHS = frozenset({"/lifecycle"})
_INSTALLED = False


def _retry_safe(
    method: str,
    path: str,
    *,
    idempotency_key: str | None,
) -> bool:
    if method == "GET":
        return True
    if method == "POST" and idempotency_key:
        return True
    return method == "POST" and path in _IDEMPOTENT_POST_PATHS


def _safe_request(
    self: AgentConnection,
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
        # Recover the transport so subsequent reads/actions see a usable Agent,
        # but never replay a mutation whose server-side result may already have
        # committed. Only GET, keyed mutations and explicitly idempotent lifecycle
        # actions are safe to issue again after an ambiguous transport failure.
        self._recover()
        self._ensure_verified(mutate=mutate)
        if not _retry_safe(method, path, idempotency_key=idempotency_key):
            raise AgentConnectionError("AGENT_MUTATION_RESULT_UNCERTAIN") from None
        return self._request_once(method, path, body, idempotency_key=idempotency_key)


def install_agent_retry_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    AgentConnection._request = _safe_request
    _INSTALLED = True
