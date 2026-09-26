from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .atomic_storage import AtomicStorageError, atomic_write

from .transcription_runs import TranscriptionRunError, load_run, load_verified_transcript_snapshot
from .review_text import count_words_v1, valid_review_string_v1

REVIEW_SCHEMA_VERSION = "tda_local_review_draft_v1"
REVIEW_RESPONSE_SCHEMA_VERSION = "tda_local_review_v1"
REVIEW_SUMMARY_SCHEMA_VERSION = "tda_local_review_summary_v1"
REVIEW_APPROVAL_SCHEMA_VERSION = "tda_local_review_approval_v1"
SNAPSHOT_CONTRACT = "tda_local_review_cas_v1"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,196}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ALLOWED_STATUS = frozenset({"draft", "reviewed", "approved_local"})
_MAX_DRAFT_BYTES = 32 * 1024 * 1024
_MAX_SUMMARY_BYTES = 8 * 1024
_MAX_APPROVAL_BYTES = 4 * 1024
_MAX_SEGMENTS = 100_000

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class LocalReviewError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _atomic_json(path: Path, value: dict[str, Any]) -> bytes:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _atomic_payload(path, payload)


def _atomic_payload(path: Path, payload: bytes) -> bytes:
    if len(payload) <= 0 or len(payload) > _MAX_DRAFT_BYTES:
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_TOO_LARGE")
    try:
        atomic_write(path, payload)
    except AtomicStorageError as exc:
        if exc.ambiguous:
            raise LocalReviewError("LOCAL_REVIEW_WRITE_UNCONFIRMED") from exc
        raise
    return payload


def _review_path(package_root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise LocalReviewError("LOCAL_REVIEW_RUN_ID_INVALID")
    package = package_root.resolve()
    revisions = (package / "revisions").resolve()
    if revisions.parent != package:
        raise LocalReviewError("LOCAL_REVIEW_ROOT_INVALID")
    directory = (revisions / run_id).resolve()
    if directory.parent != revisions:
        raise LocalReviewError("LOCAL_REVIEW_PATH_INVALID")
    return directory / "draft.json"


def _bounded_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_SYMLINK")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_MISSING") from exc
    if size <= 0 or size > _MAX_DRAFT_BYTES:
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_SIZE_INVALID")
    try:
        with path.open("rb") as handle:
            payload = handle.read(size + 1)
        if len(payload) != size:
            raise LocalReviewError("LOCAL_REVIEW_DRAFT_SIZE_INVALID")
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_INVALID") from exc
    if not isinstance(value, dict):
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_INVALID")
    return value, payload


def _summary_path(draft_path: Path) -> Path:
    return draft_path.with_name("summary.json")


def _approval_path(draft_path: Path) -> Path:
    return draft_path.with_name("approval.json")


def _approval_bytes(value: dict[str, Any]) -> bytes:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) <= 0 or len(payload) > _MAX_APPROVAL_BYTES:
        raise LocalReviewError("LOCAL_REVIEW_APPROVAL_TOO_LARGE")
    return payload


def _write_approval(
    draft_path: Path,
    *,
    draft: dict[str, Any],
    draft_sha256: str,
) -> dict[str, Any]:
    value = {
        "schema_version": REVIEW_APPROVAL_SCHEMA_VERSION,
        "source_id": draft["source_id"],
        "run_id": draft["run_id"],
        "base_transcript_sha256": draft["base_transcript_sha256"],
        "approved_draft_revision": draft["draft_revision"],
        "approved_draft_sha256": draft_sha256,
        "approved_at": utc_now(),
    }
    try:
        atomic_write(
            _approval_path(draft_path),
            _approval_bytes(value),
            storage_class="authoritative",
        )
    except AtomicStorageError as exc:
        if exc.ambiguous:
            raise LocalReviewError("LOCAL_REVIEW_APPROVAL_WRITE_UNCONFIRMED") from exc
        raise
    return value


def _read_current_approval(
    draft_path: Path,
    *,
    draft: dict[str, Any],
    draft_sha256: str | None,
) -> dict[str, Any] | None:
    if draft_sha256 is None:
        return None
    path = _approval_path(draft_path)
    try:
        before = path.lstat()
    except (FileNotFoundError, OSError):
        return None
    if (
        path.is_symlink()
        or path.is_junction()
        or not stat.S_ISREG(before.st_mode)
        or not 0 < before.st_size <= _MAX_APPROVAL_BYTES
    ):
        return None
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_APPROVAL_BYTES + 1)
        if len(payload) != before.st_size:
            return None
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "source_id",
        "run_id",
        "base_transcript_sha256",
        "approved_draft_revision",
        "approved_draft_sha256",
        "approved_at",
    }:
        return None
    revision = value.get("approved_draft_revision")
    approved_at = value.get("approved_at")
    if (
        value.get("schema_version") != REVIEW_APPROVAL_SCHEMA_VERSION
        or value.get("source_id") != draft.get("source_id")
        or value.get("run_id") != draft.get("run_id")
        or value.get("base_transcript_sha256") != draft.get("base_transcript_sha256")
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision != draft.get("draft_revision")
        or value.get("approved_draft_sha256") != draft_sha256
        or not isinstance(approved_at, str)
        or not 0 < len(approved_at) <= 64
    ):
        return None
    try:
        parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _atomic_summary_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) <= 0 or len(payload) > _MAX_SUMMARY_BYTES:
        raise LocalReviewError("LOCAL_REVIEW_SUMMARY_TOO_LARGE")
    atomic_write(path, payload, storage_class="projection")


def _public_unknown_summary() -> dict[str, Any]:
    return {
        "status": "unknown",
        "draft_revision": None,
        "review_percent": None,
        "updated_at": None,
    }


def _refresh_review_summary(draft_path: Path, draft: dict[str, Any]) -> None:
    segments = draft.get("segments")
    if not isinstance(segments, list):
        return
    reviewed = sum(
        1
        for item in segments
        if isinstance(item, dict) and item.get("reviewed") is True
    )
    total = len(segments)
    try:
        draft_stat = draft_path.lstat()
        if not stat.S_ISREG(draft_stat.st_mode):
            return
        _, draft_payload = _bounded_json(draft_path)
        draft_sha256 = hashlib.sha256(draft_payload).hexdigest()
        _atomic_summary_json(
            _summary_path(draft_path),
            {
                "schema_version": REVIEW_SUMMARY_SCHEMA_VERSION,
                "source_id": draft.get("source_id"),
                "run_id": draft.get("run_id"),
                "base_transcript_sha256": draft.get("base_transcript_sha256"),
                "draft_revision": draft.get("draft_revision"),
                "draft_sha256": draft_sha256,
                "status": draft.get("status"),
                "review_percent": round((reviewed / total) * 100, 1) if total else 100.0,
                "updated_at": draft.get("updated_at"),
                "draft_fingerprint": _draft_fingerprint(draft_stat),
            },
        )
    except (OSError, LocalReviewError):
        # The review draft is authoritative. A missing/stale projection degrades
        # the library to "unknown" and must never make an already-persisted save
        # appear to have failed.
        return


def _draft_fingerprint(value: os.stat_result) -> dict[str, int]:
    return {"size": value.st_size, "mtime_ns": value.st_mtime_ns,
            "ctime_ns": value.st_ctime_ns, "inode": value.st_ino, "device": value.st_dev}


def _summary_file_identity(value: os.stat_result) -> tuple[int, ...]:
    # Windows path stat and handle fstat can expose different ctime semantics.
    # Compare the file identity, byte extent and modification time across APIs.
    return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns


def _regular_summary_bytes(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_SUMMARY_BYTES:
        raise ValueError("SUMMARY_FILE_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _summary_file_identity(opened) != _summary_file_identity(before):
            raise ValueError("SUMMARY_FILE_CHANGED")
        # Fixed allocation even if a file grows after lstat; never read_text/read_bytes.
        with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as handle:
            payload = handle.read(_MAX_SUMMARY_BYTES + 1)
        if (len(payload) != opened.st_size
                or _draft_fingerprint(os.fstat(descriptor)) != _draft_fingerprint(opened)
                or _summary_file_identity(path.lstat()) != _summary_file_identity(opened)):
            raise ValueError("SUMMARY_FILE_CHANGED")
        return payload
    finally:
        os.close(descriptor)


def review_summary(package_root: Path, run_id: str, *, base_transcript_sha256: str | None = None) -> dict[str, Any] | None:
    try:
        raw_revisions = package_root / "revisions"
        raw_directory = raw_revisions / run_id
        if any(path.is_symlink() or path.is_junction() for path in (raw_revisions, raw_directory)):
            return _public_unknown_summary()
        draft_path = _review_path(package_root, run_id)
    except (OSError, LocalReviewError):
        return _public_unknown_summary()
    with _lock_for(draft_path):
        try:
            draft_stat = draft_path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            return _public_unknown_summary()
        if not stat.S_ISREG(draft_stat.st_mode) or not 0 < draft_stat.st_size <= _MAX_DRAFT_BYTES:
            return _public_unknown_summary()
        try:
            if base_transcript_sha256 is None:
                base_transcript_sha256 = load_run(package_root, run_id, verify_content=False)["transcript_sha256"]
            value = json.loads(_regular_summary_bytes(_summary_path(draft_path)))
        except (OSError, ValueError, RecursionError, TranscriptionRunError):
            return _public_unknown_summary()
        if not isinstance(value, dict):
            return _public_unknown_summary()
        revision, status = value.get("draft_revision"), value.get("status")
        draft_sha256 = value.get("draft_sha256")
        percent, updated_at = value.get("review_percent"), value.get("updated_at")
        fingerprint = value.get("draft_fingerprint")
        if (
            value.get("schema_version") != REVIEW_SUMMARY_SCHEMA_VERSION
            or value.get("source_id") != package_root.resolve().name
            or value.get("run_id") != run_id
            or not isinstance(base_transcript_sha256, str)
            or not _SHA256.fullmatch(base_transcript_sha256)
            or value.get("base_transcript_sha256") != base_transcript_sha256
            or isinstance(revision, bool) or not isinstance(revision, int) or revision < 0
            or not isinstance(status, str) or status not in _ALLOWED_STATUS
            or isinstance(percent, bool) or not isinstance(percent, (int, float))
            or not 0 <= percent <= 100 or not math.isfinite(percent)
            or not isinstance(updated_at, str) or not 0 < len(updated_at) <= 64
            or not isinstance(fingerprint, dict)
            or any(type(item) is not int for item in fingerprint.values())
            or fingerprint != _draft_fingerprint(draft_stat)
        ):
            return _public_unknown_summary()
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if _draft_fingerprint(draft_path.lstat()) != _draft_fingerprint(draft_stat):
                return _public_unknown_summary()
        except (OSError, ValueError):
            return _public_unknown_summary()
        if parsed.tzinfo is None:
            return _public_unknown_summary()
        if status == "approved_local":
            if (
                not isinstance(draft_sha256, str)
                or not _SHA256.fullmatch(draft_sha256)
                or _read_current_approval(
                    draft_path,
                    draft={
                        "source_id": value.get("source_id"),
                        "run_id": value.get("run_id"),
                        "base_transcript_sha256": value.get("base_transcript_sha256"),
                        "draft_revision": revision,
                    },
                    draft_sha256=draft_sha256,
                )
                is None
            ):
                return _public_unknown_summary()
        return {"status": status, "draft_revision": revision,
                "review_percent": float(percent), "updated_at": updated_at}


def rebuild_review_summary(package_root: Path, *, source_id: str, run_id: str) -> dict[str, Any] | None:
    """Explicit maintenance only; GET and listing never rebuild projections."""
    path = _review_path(package_root, run_id)
    with _lock_for(path):
        review = open_review(package_root, source_id=source_id, run_id=run_id)
        if review["persistence"] == "persisted":
            _refresh_review_summary(path, review)
        return review_summary(package_root, run_id, base_transcript_sha256=review["base_transcript_sha256"])


def _load_base(package_root: Path, source_id: str, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise LocalReviewError("LOCAL_REVIEW_SOURCE_ID_INVALID")
    if package_root.resolve().name != source_id:
        raise LocalReviewError("LOCAL_REVIEW_SOURCE_MISMATCH")
    try:
        return load_verified_transcript_snapshot(package_root, run_id)
    except TranscriptionRunError as exc:
        raise LocalReviewError("LOCAL_REVIEW_BASE_RUN_INVALID") from exc


def _base_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    tracks = transcript.get("tracks")
    if not isinstance(tracks, list):
        raise LocalReviewError("LOCAL_REVIEW_BASE_TRACKS_INVALID")
    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for track in tracks:
        if not isinstance(track, dict):
            raise LocalReviewError("LOCAL_REVIEW_BASE_TRACK_INVALID")
        number = track.get("number")
        speaker = track.get("speaker")
        raw_segments = track.get("segments")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise LocalReviewError("LOCAL_REVIEW_BASE_TRACK_INVALID")
        if not valid_review_string_v1(speaker, "speaker"):
            raise LocalReviewError("LOCAL_REVIEW_BASE_TRACK_INVALID")
        if not isinstance(raw_segments, list):
            raise LocalReviewError("LOCAL_REVIEW_BASE_SEGMENTS_INVALID")
        for segment in raw_segments:
            if not isinstance(segment, dict):
                raise LocalReviewError("LOCAL_REVIEW_BASE_SEGMENT_INVALID")
            segment_id = segment.get("id")
            start = segment.get("start")
            end = segment.get("end")
            text = segment.get("text")
            if (
                not isinstance(segment_id, str)
                or not segment_id
                or len(segment_id) > 256
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or float(end) < float(start)
                or not valid_review_string_v1(text, "text")
            ):
                raise LocalReviewError("LOCAL_REVIEW_BASE_SEGMENT_INVALID")
            key = (number, segment_id)
            if key in seen:
                raise LocalReviewError("LOCAL_REVIEW_BASE_SEGMENT_DUPLICATE")
            seen.add(key)
            segments.append(
                {
                    "track_number": number,
                    "segment_id": segment_id,
                    "start": float(start),
                    "end": float(end),
                    "text": text,
                    "speaker": speaker,
                    "reviewed": False,
                }
            )
            if len(segments) > _MAX_SEGMENTS:
                raise LocalReviewError("LOCAL_REVIEW_SEGMENT_LIMIT")
    return segments


def _warnings(transcript: dict[str, Any]) -> list[str]:
    raw = transcript.get("warnings", [])
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for value in raw:
        if isinstance(value, str) and value and len(value) <= 1024:
            values.append(value)
    return values


def _validate_segment_payload(
    candidate: Any,
    base: dict[tuple[int, str], dict[str, Any]],
    *, canonicalize: bool = True, validate_editorial: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(candidate, list) or len(candidate) != len(base):
        raise LocalReviewError("LOCAL_REVIEW_SEGMENTS_INVALID")
    values: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for raw in candidate:
        if not isinstance(raw, dict):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_INVALID")
        number = raw.get("track_number")
        segment_id = raw.get("segment_id")
        text = raw.get("text")
        speaker = raw.get("speaker")
        reviewed = raw.get("reviewed")
        if isinstance(number, bool) or not isinstance(number, int):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_INVALID")
        if not isinstance(segment_id, str):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_INVALID")
        key = (number, segment_id)
        original = base.get(key)
        if original is None or key in seen:
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_IDENTITY_MISMATCH")
        seen.add(key)
        if raw.get("start") != original["start"] or raw.get("end") != original["end"]:
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_TIMING_IMMUTABLE")
        if not isinstance(text, str) or (validate_editorial and not valid_review_string_v1(text, "text")):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_TEXT_INVALID")
        if not isinstance(speaker, str) or (validate_editorial and not valid_review_string_v1(speaker, "speaker")):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_SPEAKER_INVALID")
        if not isinstance(reviewed, bool):
            raise LocalReviewError("LOCAL_REVIEW_SEGMENT_REVIEWED_INVALID")
        values.append(
            {
                "track_number": number,
                "segment_id": segment_id,
                "start": original["start"],
                "end": original["end"],
                "text": text,
                "speaker": speaker,
                "reviewed": reviewed,
            }
        )
    if seen != set(base):
        raise LocalReviewError("LOCAL_REVIEW_SEGMENT_IDENTITY_MISMATCH")
    if canonicalize:
        by_identity = {(item["track_number"], item["segment_id"]): item for item in values}
        return [by_identity[key] for key in base]
    return values


def _summary(segments: list[dict[str, Any]], base_segments: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    base = {
        (item["track_number"], item["segment_id"]): item
        for item in base_segments
    }
    reviewed = sum(1 for item in segments if item["reviewed"])
    edited = 0
    word_count = 0
    for item in segments:
        original = base[(item["track_number"], item["segment_id"])]
        if item["text"] != original["text"] or item["speaker"] != original["speaker"]:
            edited += 1
        word_count += count_words_v1(item["text"])
    total = len(segments)
    return {
        "reviewed_segments": reviewed,
        "total_segments": total,
        "review_percent": round((reviewed / total) * 100, 1) if total else 100.0,
        "edited_segments": edited,
        "word_count": word_count,
        "warning_count": len(warnings),
    }


def _response(
    draft: dict[str, Any],
    payload: bytes | None,
    *,
    draft_path: Path,
    manifest: dict[str, Any],
    base_segments: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    segments = draft.get("segments")
    if not isinstance(segments, list):
        raise LocalReviewError("LOCAL_REVIEW_DRAFT_INVALID")
    stats = manifest.get("stats") if isinstance(manifest.get("stats"), dict) else {}
    draft_sha256 = hashlib.sha256(payload).hexdigest() if payload is not None else None
    approval = _read_current_approval(
        draft_path,
        draft=draft,
        draft_sha256=draft_sha256,
    )
    stored_status = draft["status"]
    effective_status = (
        "approved_local"
        if approval is not None
        else "reviewed"
        if stored_status == "approved_local"
        else stored_status
    )
    return {
        "schema_version": REVIEW_RESPONSE_SCHEMA_VERSION,
        "snapshot_contract": SNAPSHOT_CONTRACT,
        "persistence": "persisted" if payload is not None else "ephemeral_base",
        "source_id": draft["source_id"],
        "run_id": draft["run_id"],
        "base_transcript_sha256": draft["base_transcript_sha256"],
        "draft_revision": draft["draft_revision"],
        "draft_sha256": draft_sha256,
        "status": effective_status,
        "approval_current": approval is not None,
        "approved_at": approval.get("approved_at") if approval is not None else None,
        "created_at": draft["created_at"],
        "updated_at": draft["updated_at"],
        "lineage": {
            "profile_id": manifest.get("profile_id"),
            "engine": manifest.get("engine"),
            "model": manifest.get("model"),
            "model_revision": manifest.get("model_revision"),
            "device": manifest.get("device"),
            "compute_type": manifest.get("compute_type"),
            "alignment": manifest.get("alignment"),
            "completed_at": manifest.get("completed_at"),
            "execution_lineage": (
                manifest.get("execution_lineage")
                if isinstance(manifest.get("execution_lineage"), dict)
                else None
            ),
        },
        "stats": {
            "audio_work_seconds": stats.get("audio_work_seconds"),
            "processing_seconds": stats.get("processing_seconds"),
            "session_duration_seconds": stats.get("session_duration_seconds"),
            "duration_semantics": stats.get("duration_semantics"),
            "rtf": stats.get("rtf"),
            "word_count": stats.get("word_count"),
            "segment_count": stats.get("segment_count"),
            "track_count": stats.get("track_count"),
        },
        "warnings": warnings[:1000],
        "warning_summary": {
            "total_count": len(warnings),
            "displayed_count": min(len(warnings), 1000),
            "truncated": len(warnings) > 1000,
        },
        "review": _summary(segments, base_segments, warnings),
        "segments": segments,
        "sync": {"status": "not_configured"},
    }


def open_review(package_root: Path, *, source_id: str, run_id: str) -> dict[str, Any]:
    path = _review_path(package_root, run_id)
    with _lock_for(path):
        manifest, transcript = _load_base(package_root, source_id, run_id)
        return _open_from_snapshot(path, source_id, run_id, manifest, transcript)


def _open_from_snapshot(
    path: Path, source_id: str, run_id: str,
    manifest: dict[str, Any], transcript: dict[str, Any],
    *, allow_legacy_editorial: bool = False,
    draft_snapshot: tuple[dict[str, Any], bytes] | None = None,
) -> dict[str, Any]:
    base_segments = _base_segments(transcript)
    warnings = _warnings(transcript)
    if path.exists():
        draft, payload = draft_snapshot if draft_snapshot is not None else _bounded_json(path)
        if (
            draft.get("schema_version") != REVIEW_SCHEMA_VERSION
            or draft.get("source_id") != source_id
            or draft.get("run_id") != run_id
            or draft.get("base_transcript_sha256") != manifest.get("transcript_sha256")
            or isinstance(draft.get("draft_revision"), bool)
            or not isinstance(draft.get("draft_revision"), int)
            or draft.get("draft_revision") < 0
            or draft.get("status") not in _ALLOWED_STATUS
        ):
            raise LocalReviewError("LOCAL_REVIEW_DRAFT_INVALID")
        base_map = {
            (item["track_number"], item["segment_id"]): item
            for item in base_segments
        }
        try:
            draft["segments"] = _validate_segment_payload(draft.get("segments"), base_map,
                                                         canonicalize=False, validate_editorial=not allow_legacy_editorial)
        except LocalReviewError as exc:
            if str(exc) in {"LOCAL_REVIEW_SEGMENT_TEXT_INVALID", "LOCAL_REVIEW_SEGMENT_SPEAKER_INVALID"}:
                raise LocalReviewError("LOCAL_REVIEW_LEGACY_STRING_REPAIR_REQUIRED") from exc
            raise
        return _response(
            draft,
            payload,
            draft_path=path,
            manifest=manifest,
            base_segments=base_segments,
            warnings=warnings,
        )

    draft = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "source_id": source_id,
        "run_id": run_id,
        "base_transcript_sha256": manifest["transcript_sha256"],
        "draft_revision": None,
        "status": "draft",
        "created_at": None,
        "updated_at": None,
        "segments": base_segments,
    }
    return _response(
        draft,
        None,
        draft_path=path,
        manifest=manifest,
        base_segments=base_segments,
        warnings=warnings,
    )


def save_review(
    package_root: Path,
    *,
    source_id: str,
    run_id: str,
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LocalReviewError("LOCAL_REVIEW_REQUEST_INVALID")
    if value.get("snapshot_contract") != SNAPSHOT_CONTRACT:
        raise LocalReviewError("LOCAL_REVIEW_SNAPSHOT_CONTRACT_REQUIRED")
    expected = value.get("expected")
    status = value.get("status")
    if not isinstance(expected, dict):
        raise LocalReviewError("LOCAL_REVIEW_EXPECTED_SNAPSHOT_INVALID")
    absent = expected.get("persistence") == "ephemeral_base"
    if absent:
        valid = (set(expected) == {"persistence", "base_transcript_sha256"}
                 and isinstance(expected.get("base_transcript_sha256"), str)
                 and _SHA256.fullmatch(expected["base_transcript_sha256"]))
    else:
        revision, digest = expected.get("draft_revision"), expected.get("draft_sha256")
        valid = (set(expected) == {"persistence", "draft_revision", "draft_sha256"}
                 and expected.get("persistence") == "persisted"
                 and isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0
                 and isinstance(digest, str) and _SHA256.fullmatch(digest))
    if not valid:
        raise LocalReviewError("LOCAL_REVIEW_EXPECTED_SNAPSHOT_INVALID")
    if status not in _ALLOWED_STATUS:
        raise LocalReviewError("LOCAL_REVIEW_STATUS_INVALID")

    path = _review_path(package_root, run_id)
    with _lock_for(path):
        manifest, transcript = _load_base(package_root, source_id, run_id)
        current = _open_from_snapshot(path, source_id, run_id, manifest, transcript)
        if (current["persistence"] != expected["persistence"]
                or (absent and current["base_transcript_sha256"] != expected["base_transcript_sha256"])
                or (not absent and (current["draft_revision"] != expected["draft_revision"]
                                    or current["draft_sha256"] != expected["draft_sha256"]))):
            raise LocalReviewError("LOCAL_REVIEW_DRAFT_CONFLICT")

        base_segments = _base_segments(transcript)
        base_map = {
            (item["track_number"], item["segment_id"]): item
            for item in base_segments
        }
        segments = _validate_segment_payload(value.get("segments"), base_map)
        current_segments = _validate_segment_payload(current["segments"], base_map)

        # Approval is an explicit action over an already-persisted exact draft.
        # A request that also changes editorial content must save first and only
        # then approve the resulting revision in a second CAS-fenced action.
        if status == "approved_local":
            if absent or segments != current_segments:
                raise LocalReviewError("LOCAL_REVIEW_APPROVAL_REQUIRES_SAVED_DRAFT")
            draft, payload = _bounded_json(path)
            draft_sha256 = hashlib.sha256(payload).hexdigest()
            _write_approval(path, draft=draft, draft_sha256=draft_sha256)
            _refresh_review_summary(path, {
                **draft,
                "status": "approved_local",
            })
            return _response(
                draft,
                payload,
                draft_path=path,
                manifest=manifest,
                base_segments=base_segments,
                warnings=_warnings(transcript),
            )

        # Presentation order alone is not a new editorial revision. Historical
        # bytes and their SHA remain unchanged until an actual field edit.
        if not absent and status == current["status"] and segments == current_segments:
            return current
        now = utc_now()
        draft = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "source_id": source_id,
            "run_id": run_id,
            "base_transcript_sha256": manifest["transcript_sha256"],
            "draft_revision": 1 if absent else expected["draft_revision"] + 1,
            "status": status,
            "created_at": now if absent else current["created_at"],
            "updated_at": now,
            "segments": segments,
        }
        payload = _atomic_json(path, draft)
        _refresh_review_summary(path, draft)
        return _response(
            draft,
            payload,
            draft_path=path,
            manifest=manifest,
            base_segments=base_segments,
            warnings=_warnings(transcript),
        )


def repair_legacy_review(
    package_root: Path, *, source_id: str, run_id: str,
    expected_revision: int, expected_sha256: str, segments: Any,
) -> dict[str, Any]:
    """Explicit offline repair; retains byte-exact evidence before replacement.

    Run only with the Companion stopped, because its process RootLock is not held
    by offline tooling. A new save still validates every replacement field.
    """
    path = _review_path(package_root, run_id)
    with _lock_for(path):
        manifest, transcript = _load_base(package_root, source_id, run_id)
        snapshot = _bounded_json(path)
        current = _open_from_snapshot(path, source_id, run_id, manifest, transcript,
                                      allow_legacy_editorial=True, draft_snapshot=snapshot)
        if (isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
                or current["draft_revision"] != expected_revision
                or current["draft_sha256"] != expected_sha256):
            raise LocalReviewError("LOCAL_REVIEW_DRAFT_CONFLICT")
        if all(valid_review_string_v1(row[field], field)
               for row in current["segments"] for field in ("text", "speaker")):
            raise LocalReviewError("LOCAL_REVIEW_REPAIR_NOT_REQUIRED")
        base_segments = _base_segments(transcript)
        base_map = {(item["track_number"], item["segment_id"]): item for item in base_segments}
        replacement = _validate_segment_payload(segments, base_map)
        backup = path.with_name(f"draft-before-repair-{expected_sha256}.json")
        if backup.is_symlink():
            raise LocalReviewError("LOCAL_REVIEW_REPAIR_BACKUP_INVALID")
        if backup.exists():
            if _bounded_json(backup)[1] != snapshot[1]:
                raise LocalReviewError("LOCAL_REVIEW_REPAIR_BACKUP_INVALID")
        else:
            _atomic_payload(backup, snapshot[1])
        draft = {**snapshot[0], "segments": replacement, "status": "draft",
                 "draft_revision": expected_revision + 1, "updated_at": utc_now()}
        payload = _atomic_json(path, draft)
        _refresh_review_summary(path, draft)
        return _response(draft, payload, draft_path=path, manifest=manifest, base_segments=base_segments,
                         warnings=_warnings(transcript))
