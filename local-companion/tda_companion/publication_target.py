from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any
from .atomic_storage import AtomicStorageError, atomic_write

from .transcription_runs import TranscriptionRunError, load_run, run_root, _root_transcript_lock

PUBLICATION_TARGET_SCHEMA_VERSION = "tda_publication_target_v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,196}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 16 * 1024


class PublicationTargetError(RuntimeError):
    pass


def _target_path(package_root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_ID_INVALID")
    return run_root(package_root, run_id) / "publication-target.json"


def _validate_identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PublicationTargetError(code)
    return value


def _validate_attempt(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 1_000_000
    ):
        raise PublicationTargetError("PUBLICATION_TARGET_ATTEMPT_INVALID")
    return value


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_ID_INVALID")
    return value


def _validate_hash(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PublicationTargetError("PUBLICATION_TARGET_HASH_INVALID")
    return value


def _validate_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "campaign_slug",
        "source_session_id",
        "source_id",
        "run_id",
        "job_id",
        "attempt",
        "transcript_sha256",
    }:
        raise PublicationTargetError("PUBLICATION_TARGET_INVALID")
    if value.get("schema_version") != PUBLICATION_TARGET_SCHEMA_VERSION:
        raise PublicationTargetError("PUBLICATION_TARGET_SCHEMA_INVALID")
    return {
        "schema_version": PUBLICATION_TARGET_SCHEMA_VERSION,
        "campaign_slug": _validate_identifier(
            value.get("campaign_slug"),
            "PUBLICATION_TARGET_CAMPAIGN_INVALID",
        ),
        "source_session_id": _validate_identifier(
            value.get("source_session_id"),
            "PUBLICATION_TARGET_SESSION_INVALID",
        ),
        "source_id": _validate_identifier(
            value.get("source_id"),
            "PUBLICATION_TARGET_SOURCE_INVALID",
        ),
        "run_id": _validate_run_id(value.get("run_id")),
        "job_id": _validate_identifier(
            value.get("job_id"),
            "PUBLICATION_TARGET_JOB_ID_INVALID",
        ),
        "attempt": _validate_attempt(value.get("attempt")),
        "transcript_sha256": _validate_hash(value.get("transcript_sha256")),
    }


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise PublicationTargetError("PUBLICATION_TARGET_SYMLINK")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PublicationTargetError("PUBLICATION_TARGET_MISSING") from exc
    if size <= 0 or size > _MAX_BYTES:
        raise PublicationTargetError("PUBLICATION_TARGET_SIZE_INVALID")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationTargetError("PUBLICATION_TARGET_INVALID") from exc
    return _validate_payload(value)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        atomic_write(path, payload)
    except AtomicStorageError as exc:
        if exc.ambiguous:
            raise PublicationTargetError("PUBLICATION_TARGET_WRITE_UNCONFIRMED") from exc
        raise


def _bind_publication_target(
    package_root: Path,
    *,
    run_id: str,
    job_id: str,
    attempt: int,
    campaign_slug: str,
    source_session_id: str,
    source_id: str,
    transcript_sha256: str,
) -> dict[str, Any]:
    """Persist the intended cloud target beside, never inside, an immutable ASR run.

    The binding is derived from the accepted queue request only after the worker's
    immutable run has been verified. Replays are idempotent; any divergent binding
    for the same run fails closed.
    """
    expected = _validate_payload(
        {
            "schema_version": PUBLICATION_TARGET_SCHEMA_VERSION,
            "campaign_slug": campaign_slug,
            "source_session_id": source_session_id,
            "source_id": source_id,
            "run_id": run_id,
            "job_id": job_id,
            "attempt": attempt,
            "transcript_sha256": transcript_sha256,
        }
    )
    try:
        manifest = load_run(package_root, run_id, verify_content=True)
    except TranscriptionRunError as exc:
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_INVALID") from exc
    if (
        manifest.get("job_id") != expected["job_id"]
        or manifest.get("attempt") != expected["attempt"]
        or manifest.get("source_id") != expected["source_id"]
        or manifest.get("transcript_sha256") != expected["transcript_sha256"]
    ):
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_MISMATCH")

    path = _target_path(package_root, run_id)
    if path.is_symlink():
        raise PublicationTargetError("PUBLICATION_TARGET_SYMLINK")
    if path.exists():
        current = _read(path)
        if current != expected:
            raise PublicationTargetError("PUBLICATION_TARGET_CONFLICT")
        _preserve_origin(path, current)
        return current
    try:
        _preserve_origin(path, expected)
        _atomic_write(path, expected)
    except OSError as exc:
        raise PublicationTargetError("PUBLICATION_TARGET_WRITE_FAILED") from exc
    current = _read(path)
    if current != expected:
        raise PublicationTargetError("PUBLICATION_TARGET_CONFLICT")
    return current


def _preserve_origin(path: Path, expected: dict[str, Any]) -> None:
    origin = path.with_name("publication-origin.json")
    if origin.exists() or origin.is_symlink():
        if _read(origin) != expected:
            raise PublicationTargetError("PUBLICATION_TARGET_ORIGIN_CONFLICT")
    else:
        _atomic_write(origin, expected)
        if _read(origin) != expected:
            raise PublicationTargetError("PUBLICATION_TARGET_ORIGIN_CONFLICT")


def bind_publication_target(package_root: Path, **identity) -> dict[str, Any]:
    # Binding, repair and queue cleanup use the same cross-process source lock.
    with _root_transcript_lock(package_root):
        return _bind_publication_target(package_root, **identity)


def repair_publication_target(
    package_root: Path,
    run_id: str,
    *,
    job: dict | None = None,
    body: dict | None = None,
    result: dict | None = None,
    source_sha256: str | None = None,
    track_count: int | None = None,
) -> dict[str, Any]:
    """Restore only a proven original binding, never choose a new destination."""
    with _root_transcript_lock(package_root):
        manifest = load_run(package_root, run_id, verify_content=True)
        path = _target_path(package_root, run_id)
        origin_path = path.with_name("publication-origin.json")
        expected = None
        if origin_path.exists() or origin_path.is_symlink():
            expected = _read(origin_path)
        if job is not None:
            body = body or {}
            result = result or {}
            transcription = result.get("transcription") or {}
            digest_text = lambda value: hashlib.sha256(str(value or "").encode()).hexdigest()
            if (
                job.get("status") != "succeeded"
                or body.get("kind") != "transcription.craig"
                or job.get("id") != manifest.get("job_id")
                or job.get("attempt") != manifest.get("attempt")
                or body.get("source_id") != manifest.get("source_id")
                or body.get("profile_id") != manifest.get("profile_id")
                or source_sha256 != manifest.get("source_sha256")
                or body.get("units") != track_count
                or manifest.get("stats", {}).get("track_count") != track_count
                or digest_text(body.get("context")) != manifest.get("context_sha256")
                or digest_text(body.get("glossary")) != manifest.get("glossary_sha256")
                or result.get("job_id") != job.get("id")
                or result.get("source_id") != body.get("source_id")
                or result.get("campaign_id") != body.get("campaign_id")
                or result.get("session_id") != body.get("session_id")
                or transcription.get("run_id") != run_id
                or transcription.get("sha256") != manifest.get("transcript_sha256")
                or transcription.get("profile_id") != body.get("profile_id")
            ):
                raise PublicationTargetError("PUBLICATION_TARGET_PROVENANCE_MISMATCH")
            candidate = _validate_payload({
                "schema_version": PUBLICATION_TARGET_SCHEMA_VERSION,
                "campaign_slug": body.get("campaign_id"),
                "source_session_id": body.get("session_id"),
                "source_id": body.get("source_id"), "run_id": run_id,
                "job_id": job.get("id"), "attempt": job.get("attempt"),
                "transcript_sha256": manifest.get("transcript_sha256"),
            })
            if expected is not None and expected != candidate:
                raise PublicationTargetError("PUBLICATION_TARGET_ORIGIN_CONFLICT")
            expected = candidate
        if expected is None:
            raise PublicationTargetError("PUBLICATION_TARGET_PROVENANCE_UNAVAILABLE")
        if any(expected[key] != manifest.get(key) for key in (
            "run_id", "job_id", "attempt", "source_id", "transcript_sha256"
        )):
            raise PublicationTargetError("PUBLICATION_TARGET_RUN_MISMATCH")
        if path.is_symlink():
            raise PublicationTargetError("PUBLICATION_TARGET_SYMLINK")
        if path.exists():
            try:
                current = _read(path)
            except PublicationTargetError:
                current = None
            # A structurally valid divergent destination is not disk repair.
            if current is not None and current != expected:
                raise PublicationTargetError("PUBLICATION_TARGET_CONFLICT")
        _preserve_origin(path, expected)
        _atomic_write(path, expected)
        if load_publication_target(package_root, run_id) != expected:
            raise PublicationTargetError("PUBLICATION_TARGET_WRITE_UNCONFIRMED")
        return expected


def publication_target_state(package_root: Path, run_id: str) -> dict[str, Any]:
    try:
        target = load_publication_target(package_root, run_id)
        state = "valid" if target is not None else "unbound"
    except (PublicationTargetError, TranscriptionRunError):
        target, state = None, "invalid"
    origin = _target_path(package_root, run_id).with_name("publication-origin.json")
    if target is None and (origin.exists() or origin.is_symlink()):
        state = "invalid"
    return {"publication_target": target, "publication_target_state": state}


def load_publication_target(
    package_root: Path,
    run_id: str,
    *,
    verify_run: bool = True,
) -> dict[str, Any] | None:
    """Read a sanitized publication target. Legacy/unbound runs return None."""
    path = _target_path(package_root, run_id)
    if not path.exists() and not path.is_symlink():
        return None
    value = _read(path)
    if not verify_run:
        return value
    try:
        # Listing this sidecar must stay cheap. The immutable run is fully hashed
        # when the binding is created and again when a review is opened; here we
        # only re-check manifest identity/size so a 3-second Web refresh never
        # re-hashes hundreds of MiB of transcript JSON.
        manifest = load_run(package_root, run_id, verify_content=False)
    except TranscriptionRunError as exc:
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_INVALID") from exc
    if (
        manifest.get("job_id") != value["job_id"]
        or manifest.get("attempt") != value["attempt"]
        or manifest.get("source_id") != value["source_id"]
        or manifest.get("transcript_sha256") != value["transcript_sha256"]
    ):
        raise PublicationTargetError("PUBLICATION_TARGET_RUN_MISMATCH")
    origin = path.with_name("publication-origin.json")
    if origin.exists() or origin.is_symlink():
        if _read(origin) != value:
            raise PublicationTargetError("PUBLICATION_TARGET_ORIGIN_CONFLICT")
    return value
