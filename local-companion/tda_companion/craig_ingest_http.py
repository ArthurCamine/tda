from __future__ import annotations

import asyncio
import hmac
import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .craig import CraigPackageError
from .craig_ingest import CRAIG_UPLOAD_MEDIA_TYPES, CraigUploadError, ingest_craig_request
from .browser_session import BrowserSessionManager
from .craig_runtime import load_craig_package
from .local_review import LocalReviewError, open_review, review_summary, save_review
from .publication_target import publication_target_state
from .system_log import SystemLog
from .transcription_runs import (
    TranscriptionRunError,
    ensure_legacy_and_list,
    load_run,
)

CRAIG_INGEST_PATH = "/api/v1/sources/craig"
CRAIG_SOURCES_PATH = "/api/v1/sources"
CRAIG_RUNS_PATH = re.compile(r"^/api/v1/sources/(?P<source_id>[A-Za-z0-9_-]{1,128})/runs$")
CRAIG_REVIEW_PATH = re.compile(
    r"^/api/v1/sources/(?P<source_id>[A-Za-z0-9_-]{1,128})/runs/"
    r"(?P<run_id>[A-Za-z0-9_-]{1,196})/review$"
)
_ALLOWED_PREFLIGHT_HEADERS = frozenset({"authorization", "content-type"})
_LOCAL_REVIEW_BODY_MAX_BYTES = 32 * 1024 * 1024

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
        browser_sessions: BrowserSessionManager | None = None,
        source_gate: object | None = None,
        source_running: Callable[[str], bool] | None = None,
        run_visible: Callable[[Path, dict[str, object]], bool] | None = None,
    ) -> None:
        self.app = app
        self.data_root = data_root.resolve()
        self.token = token
        self.origins = origins
        self.port = port
        self.system_log = system_log
        self.browser_sessions = browser_sessions
        self.source_gate = source_gate
        self.source_running = source_running
        self.run_visible = run_visible

    def _log(self, code: str, message: str, context: dict[str, object] | None = None) -> None:
        if self.system_log is not None:
            self.system_log.write("info", "ingest", code, message, context)

    async def _send_response(self, response: Response, scope, receive, send, origin: str | None) -> None:
        response.headers.update(_cors_headers(origin))
        await response(scope, receive, send)

    def _authorized(self, request: Request, origin: str | None) -> bool:
        authorization = request.headers.get("authorization", "")
        if hmac.compare_digest(
            authorization.encode("utf-8"),
            f"Bearer {self.token}".encode("ascii"),
        ):
            return True
        if (
            self.browser_sessions is None
            or origin is None
            or not authorization.startswith("Bearer ")
        ):
            return False
        return self.browser_sessions.validate(
            authorization[len("Bearer "):],
            origin,
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

    def _source_listing(self) -> dict[str, object]:
        staging_root = (self.data_root / "staging").resolve()
        if not staging_root.is_dir():
            return {"schema_version": "tda_craig_sources_v1", "sources": []}
        gate = self.source_gate if self.source_gate is not None else nullcontext()
        values: list[dict[str, object]] = []
        with gate:
            for candidate in sorted(staging_root.iterdir(), key=lambda item: item.name):
                if (
                    not candidate.is_dir()
                    or candidate.is_symlink()
                    or re.fullmatch(r"craig-[0-9a-f]{64}", candidate.name) is None
                ):
                    continue
                try:
                    package = load_craig_package(candidate, verify_tracks=False)
                except CraigPackageError:
                    continue
                values.append(
                    {
                        "source_id": candidate.name,
                        "source_sha256": package.source_sha256,
                        "recording_id": package.recording_id,
                        "track_count": len(package.tracks),
                    }
                )
        return {"schema_version": "tda_craig_sources_v1", "sources": values}

    async def _sources(self, request: Request, scope, receive, send) -> None:
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
        if not self._authorized(request, origin):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return
        value = await asyncio.to_thread(self._source_listing)
        await self._send_response(JSONResponse(value), scope, receive, send, origin)

    def _run_listing(self, source_id: str) -> dict[str, object]:
        staging_root = (self.data_root / "staging").resolve()
        package_root = (staging_root / source_id).resolve()
        if package_root.parent != staging_root:
            raise CraigPackageError("CRAIG_STAGING_PATH_INVALID")
        gate = self.source_gate if self.source_gate is not None else nullcontext()
        with gate:
            package = load_craig_package(package_root, verify_tracks=False)
            value = ensure_legacy_and_list(
                package_root,
                source_id=source_id,
                source_sha256=package.source_sha256,
                verify_content=False,
            )
            runs = value.get("runs")
            if not isinstance(runs, list):
                return value
            visible_runs = [
                item
                for item in runs
                if isinstance(item, dict)
                and (
                    self.run_visible is None
                    or self.run_visible(package_root, item)
                )
            ]
            enriched = []
            for item in visible_runs:
                enriched.append(
                    {
                        **item,
                        **publication_target_state(package_root, str(item.get("run_id") or "")),
                        "review": review_summary(
                            package_root,
                            str(item.get("run_id") or ""),
                            base_transcript_sha256=str(item.get("transcript_sha256") or ""),
                        ),
                    }
                )
            return {**value, "runs": enriched}

    def _review_value(
        self,
        source_id: str,
        run_id: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        staging_root = (self.data_root / "staging").resolve()
        package_root = (staging_root / source_id).resolve()
        if package_root.parent != staging_root:
            raise CraigPackageError("CRAIG_STAGING_PATH_INVALID")
        gate = self.source_gate if self.source_gate is not None else nullcontext()
        with gate:
            load_craig_package(package_root, verify_tracks=False)
            try:
                manifest = load_run(package_root, run_id, verify_content=False)
            except TranscriptionRunError as exc:
                raise LocalReviewError("LOCAL_REVIEW_RUN_NOT_VISIBLE") from exc
            if self.run_visible is not None and not self.run_visible(package_root, manifest):
                raise LocalReviewError("LOCAL_REVIEW_RUN_NOT_VISIBLE")
            if payload is None:
                review = open_review(
                    package_root,
                    source_id=source_id,
                    run_id=run_id,
                )
            else:
                review = save_review(
                    package_root,
                    source_id=source_id,
                    run_id=run_id,
                    value=payload,
                )
            return {**review, **publication_target_state(package_root, run_id)}

    async def _read_review_body(self, request: Request) -> dict[str, object]:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > _LOCAL_REVIEW_BODY_MAX_BYTES:
                raise LocalReviewError("LOCAL_REVIEW_REQUEST_TOO_LARGE")
        try:
            value = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalReviewError("LOCAL_REVIEW_REQUEST_INVALID") from exc
        if not isinstance(value, dict):
            raise LocalReviewError("LOCAL_REVIEW_REQUEST_INVALID")
        return value

    async def _review(
        self,
        request: Request,
        source_id: str,
        run_id: str,
        scope,
        receive,
        send,
    ) -> None:
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
            requested_method = request.headers.get("access-control-request-method")
            if (
                requested_method not in {"GET", "POST"}
                or not requested_headers <= _ALLOWED_PREFLIGHT_HEADERS
            ):
                await self._send_response(_error("PREFLIGHT_REJECTED", 403), scope, receive, send, origin)
                return
            response = JSONResponse(
                {},
                headers={
                    "Access-Control-Allow-Methods": "GET, POST",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Max-Age": "60",
                },
            )
            await self._send_response(response, scope, receive, send, origin)
            return
        if request.method not in {"GET", "POST"}:
            await self._send_response(_error("METHOD_NOT_ALLOWED", 405), scope, receive, send, origin)
            return
        if not self._authorized(request, origin):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return
        if request.method == "POST":
            if not origin:
                await self._send_response(_error("ORIGIN_REQUIRED", 403), scope, receive, send, None)
                return
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                await self._send_response(_error("JSON_REQUIRED", 415), scope, receive, send, origin)
                return

        try:
            payload = await self._read_review_body(request) if request.method == "POST" else None
            value = await asyncio.to_thread(
                self._review_value,
                source_id,
                run_id,
                payload,
            )
            response = JSONResponse(value)
        except LocalReviewError as exc:
            code = str(exc)
            if code == "LOCAL_REVIEW_RUN_NOT_VISIBLE":
                response = _error(code, 404)
            elif code in {
                "LOCAL_REVIEW_REQUEST_INVALID",
                "LOCAL_REVIEW_EXPECTED_REVISION_INVALID",
                "LOCAL_REVIEW_EXPECTED_SNAPSHOT_INVALID",
                "LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED",
                "LOCAL_REVIEW_STATUS_INVALID",
                "LOCAL_REVIEW_SEGMENTS_INVALID",
                "LOCAL_REVIEW_SEGMENT_INVALID",
                "LOCAL_REVIEW_SEGMENT_IDENTITY_MISMATCH",
                "LOCAL_REVIEW_SEGMENT_TIMING_IMMUTABLE",
                "LOCAL_REVIEW_SEGMENT_TEXT_INVALID",
                "LOCAL_REVIEW_SEGMENT_SPEAKER_INVALID",
                "LOCAL_REVIEW_SEGMENT_REVIEWED_INVALID",
            }:
                response = _error(code, 422)
            elif code == "LOCAL_REVIEW_REQUEST_TOO_LARGE":
                response = _error(code, 413)
            else:
                response = _error(code, 409, code == "LOCAL_REVIEW_DRAFT_CONFLICT")
        except CraigPackageError as exc:
            response = _error(str(exc), 404 if str(exc) == "CRAIG_MANIFEST_NOT_FOUND" else 409, True)
        await self._send_response(response, scope, receive, send, origin)

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
        if not self._authorized(request, origin):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return

        try:
            value = await asyncio.to_thread(self._run_listing, source_id)
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
        if path == CRAIG_SOURCES_PATH:
            request = Request(scope, receive=receive)
            await self._sources(request, scope, receive, send)
            return
        review_match = CRAIG_REVIEW_PATH.fullmatch(path)
        if review_match is not None:
            request = Request(scope, receive=receive)
            await self._review(
                request,
                review_match.group("source_id"),
                review_match.group("run_id"),
                scope,
                receive,
                send,
            )
            return
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
        if not self._authorized(request, origin):
            await self._send_response(_error("UNAUTHORIZED", 401), scope, receive, send, origin)
            return

        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type not in CRAIG_UPLOAD_MEDIA_TYPES:
            await self._send_response(_error("CRAIG_ZIP_REQUIRED", 415), scope, receive, send, origin)
            return

        try:
            value = await ingest_craig_request(
                request,
                self.data_root,
                source_gate=self.source_gate,
                source_running=self.source_running,
            )
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
