from __future__ import annotations

import hmac
import re
from pathlib import Path
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .craig import CraigPackageError
from .craig_ingest import CRAIG_UPLOAD_MEDIA_TYPES, CraigUploadError, ingest_craig_request
from .craig_runtime import load_craig_package
from .system_log import SystemLog
from .transcription_runs import TranscriptionRunError, ensure_legacy_and_list

CRAIG_INGEST_PATH = "/api/v1/sources/craig"
CRAIG_RUNS_PATH = re.compile(r"^/api/v1/sources/(?P<source_id>[A-Za-z0-9_-]{1,128})/runs$")
_ALLOWED_PREFLIGHT_HEADERS = frozenset({"authorization", "content-type"})

ASGIApp = Callable[[dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]], Awaitable[None]]


def _error(code: str, status: int, recoverable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "recoverable": recoverable}},
        status_code=status,
    )


def _cors_headers(origin: str | None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if origin:
        headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin"})
    return headers


class CraigIngestBoundary:
    """Own Craig source ingest and sanitized local run discovery.

    Large ZIP upload bypasses FastAPI's small JSON body guard. Run discovery lives at
    the same local-only boundary so the normal Agent API never needs filesystem paths
    or transcript bytes in browser-facing payloads.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        data_root: Path,
        token: str,
        origins: frozenset[str],
        port: int,
        system_log: SystemLog | None = None,
    ) -> None:
        self.app = app
        self.data_root = data_root.resolve()
        self.token = token
        self.origins = origins
        self.port = port
        self.system_log = system_log

    def _log(self, code: str, message: str, context: dict[str, object] | None = None) -> None:
        if self.system_log is not None:
            self.system_log.write("info", "ingest", code, message, context)

    async def _send_response(self, response: Response, scope, receive, send, origin: str | None) -> None:
        response.headers.update(_cors_headers(origin))
        await response(scope, receive, send)

    def _authorized(self, request: Request) -> bool:
        return hmac.compare_digest(
            request.headers.get("authorization", "").encode("utf-8"),
            f"Bearer {self.token}".encode("ascii"),
        )

    async def _common_guard(self, request: Request, scope, receive, send) -> tuple[str | None, bool]:
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if host != f"127.0.0.1:{self.port}":
            await self._send_response(_error("HOST_REJECTED", 403), scope, receive, send, origin)
            return origin, False
        if origin is not None and origin not in self.origins:
            await self._send_response(_error("ORIGIN_REJECTED", 403), scope, receive, send, origin)
            return origin, False
        return origin, True

    async def _runs(self, request: Request, source_id: str, scope, receive, send) -> None:
        origin, allowed = await self._common_guard(request, scope, receive, send)
        if not allowed:
            return
        if request.method == "OPTIONS":
            if not origin:
                await self._send_response(_error("ORIGIN_REQUIRED", 403), scope, receive, send, None)
                return
            requested_headers = {
                value.strip().lower()
                for value in request.headers.get("access-control-request-headers", "").split(",")
                if value.strip()
            }
            if (
                request.headers.get("access-control-request-method") != "GET"
                or not requested_headers <= {"authorization"}
            ):
                await self._send_response(_error("PREFLIGHT_REJECTED", 403), scope, receive, send, origin)
                return
            response = JSONResponse(
                {},
                headers={
                    "Access-Control-Allow-Methods": "GET",
                    "Access-Control-Allow-Headers": "Authorization",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Max-Age": "60",
                },
            )
            await self._send_response(response, scope, receive, send, origin)
            return
        if request.method != "GET":
            await self._send_response(_error("METHOD_NOT_ALLOWED", 405), scope, receive, send, origin)
            return
        if not self._authorized(request):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return

        staging_root = (self.data_root / "staging").resolve()
        package_root = (staging_root / source_id).resolve()
        if package_root.parent != staging_root:
            await self._send_response(_error("CRAIG_STAGING_PATH_INVALID", 409, True), scope, receive, send, origin)
            return
        try:
            package = load_craig_package(package_root, verify_tracks=False)
            value = ensure_legacy_and_list(
                package_root,
                source_id=source_id,
                source_sha256=package.source_sha256,
                verify_content=False,
            )
            response = JSONResponse(value)
        except CraigPackageError as exc:
            response = _error(str(exc), 404 if str(exc) == "CRAIG_MANIFEST_NOT_FOUND" else 409, True)
        except TranscriptionRunError as exc:
            response = _error(str(exc), 409, True)
        await self._send_response(response, scope, receive, send, origin)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        run_match = CRAIG_RUNS_PATH.fullmatch(path)
        if run_match is not None:
            request = Request(scope, receive=receive)
            await self._runs(request, run_match.group("source_id"), scope, receive, send)
            return
        if path != CRAIG_INGEST_PATH:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        origin, allowed = await self._common_guard(request, scope, receive, send)
        if not allowed:
            return

        if request.method == "OPTIONS":
            if not origin:
                await self._send_response(_error("ORIGIN_REQUIRED", 403), scope, receive, send, None)
                return
            requested_headers = {
                value.strip().lower()
                for value in request.headers.get("access-control-request-headers", "").split(",")
                if value.strip()
            }
            if (
                request.headers.get("access-control-request-method") != "POST"
                or not requested_headers <= _ALLOWED_PREFLIGHT_HEADERS
            ):
                await self._send_response(_error("PREFLIGHT_REJECTED", 403), scope, receive, send, origin)
                return
            response = JSONResponse(
                {},
                headers={
                    "Access-Control-Allow-Methods": "POST",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Max-Age": "60",
                },
            )
            await self._send_response(response, scope, receive, send, origin)
            return

        if request.method != "POST":
            await self._send_response(_error("METHOD_NOT_ALLOWED", 405), scope, receive, send, origin)
            return
        if not origin:
            await self._send_response(_error("ORIGIN_REQUIRED", 403), scope, receive, send, None)
            return
        if not self._authorized(request):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return

        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type not in CRAIG_UPLOAD_MEDIA_TYPES:
            await self._send_response(_error("CRAIG_ZIP_REQUIRED", 415), scope, receive, send, origin)
            return

        try:
            value = await ingest_craig_request(request, self.data_root)
            response = JSONResponse(value)
            self._log(
                "CRAIG_SOURCE_REUSED" if value.get("reused") else "CRAIG_SOURCE_STAGED",
                "Craig source reused" if value.get("reused") else "Craig source staged",
                {
                    "source_id": value["source_id"],
                    "track_count": value["track_count"],
                    "size_bytes": value["size_bytes"],
                },
            )
        except CraigUploadError as exc:
            response = _error(exc.code, exc.status, exc.recoverable)
        await self._send_response(response, scope, receive, send, origin)
