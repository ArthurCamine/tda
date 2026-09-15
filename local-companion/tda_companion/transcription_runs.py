from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .transcript import TranscriptDocument

RUN_SCHEMA_VERSION = "tda_transcription_run_v1"
RUN_LIST_SCHEMA_VERSION = "tda_transcription_runs_v1"
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,196}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_TRANSCRIPT_BYTES = 512 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024


class TranscriptionRunError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_id_for(job_id: str, attempt: int) -> str:
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_JOB_ID_INVALID")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 1_000_000:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ATTEMPT_INVALID")
    value = f"run-{job_id}-a{attempt}"
    if not _RUN_ID.fullmatch(value):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ID_INVALID")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    _atomic_bytes(path, payload)


def _bounded_json(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_MISSING") from exc
    if size <= 0 or size > _MAX_MANIFEST_BYTES:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_SIZE_INVALID")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_INVALID") from exc
    if not isinstance(value, dict):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_INVALID")
    return value


def _bounded_transcript(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_MISSING") from exc
    if size <= 0 or size > _MAX_TRANSCRIPT_BYTES:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_INVALID")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_READ_FAILED") from exc


def _runs_root(package_root: Path) -> Path:
    root = package_root.resolve()
    result = (root / "runs").resolve()
    if result.parent != root:
        raise TranscriptionRunError("TRANSCRIPTION_RUNS_ROOT_INVALID")
    return result


def run_root(package_root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ID_INVALID")
    root = _runs_root(package_root)
    result = (root / run_id).resolve()
    if result.parent != root:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_PATH_INVALID")
    return result


def _source_id(package_root: Path, explicit: str | None = None) -> str:
    value = explicit if explicit is not None else package_root.resolve().name
    if not isinstance(value, str) or not _SOURCE_ID.fullmatch(value):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_SOURCE_ID_INVALID")
    return value


def _manifest_for_document(
    document: TranscriptDocument,
    *,
    source_id: str,
    run_id: str,
    job_id: str,
    attempt: int,
    transcript_sha256: str,
    transcript_size_bytes: int,
    glossary: str,
    context: str,
) -> dict[str, Any]:
    document.validate()
    engine = document.engine
    stats = document.stats
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "origin": "asr",
        "status": "completed",
        "source_id": source_id,
        "source_sha256": document.source_sha256.lower(),
        "job_id": job_id,
        "attempt": attempt,
        "profile_id": engine.profile,
        "engine": engine.engine,
        "model": engine.model,
        "model_revision": engine.model_revision,
        "device": engine.device,
        "compute_type": engine.compute_type,
        "alignment": engine.alignment,
        "language": document.language,
        "context_sha256": _sha256_text(context),
        "glossary_sha256": _sha256_text(glossary),
        "transcript_schema_version": document.schema_version,
        "artifact": "transcript.json",
        "transcript_sha256": transcript_sha256,
        "transcript_size_bytes": transcript_size_bytes,
        "created_at": document.created_at,
        "completed_at": utc_now(),
        "stats": {
            "processing_seconds": stats.processing_seconds,
            "rtf": stats.rtf,
            "word_count": stats.word_count,
            "segment_count": stats.segment_count,
            "track_count": stats.track_count,
            "turn_count": stats.turn_count,
            "deduplicated_segment_count": stats.deduplicated_segment_count,
        },
    }


def write_completed_run(
    package_root: Path,
    document: TranscriptDocument,
    *,
    job_id: str,
    attempt: int,
    source_id: str | None = None,
    glossary: str = "",
    context: str = "",
) -> dict[str, Any]:
    """Persist one immutable completed ASR run.

    The manifest is written last. A run without a valid manifest is never listed as
    completed, so crashes between transcript creation and manifest commit fail closed.
    """
    resolved_source_id = _source_id(package_root, source_id)
    run_id = run_id_for(job_id, attempt)
    destination = run_root(package_root, run_id)
    if destination.exists():
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ALREADY_EXISTS")
    destination.mkdir(parents=True, exist_ok=False)
    transcript = destination / "transcript.json"
    document.write_atomic(transcript)
    digest = _sha256_file(transcript)
    size = transcript.stat().st_size
    manifest = _manifest_for_document(
        document,
        source_id=resolved_source_id,
        run_id=run_id,
        job_id=job_id,
        attempt=attempt,
        transcript_sha256=digest,
        transcript_size_bytes=size,
        glossary=glossary,
        context=context,
    )
    _atomic_json(destination / "run.json", manifest)
    return manifest


def write_compatibility_mirror(package_root: Path, run_id: str) -> str:
    """Update legacy <source>/transcript.json without making it the source of truth."""
    source = run_root(package_root, run_id) / "transcript.json"
    payload = _bounded_transcript(source)
    target = package_root.resolve() / "transcript.json"
    _atomic_bytes(target, payload)
    return hashlib.sha256(payload).hexdigest()


def _validate_manifest(
    package_root: Path,
    value: dict[str, Any],
    *,
    verify_content: bool,
) -> dict[str, Any]:
    if value.get("schema_version") != RUN_SCHEMA_VERSION or value.get("status") != "completed":
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_SCHEMA_INVALID")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ID_INVALID")
    source_id = value.get("source_id")
    source_sha256 = value.get("source_sha256")
    if (
        not isinstance(source_id, str)
        or not _SOURCE_ID.fullmatch(source_id)
        or source_id != package_root.resolve().name
        or not isinstance(source_sha256, str)
        or not _SHA256.fullmatch(source_sha256)
    ):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_SOURCE_INVALID")
    profile_id = value.get("profile_id")
    if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile_id):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_PROFILE_INVALID")
    digest = value.get("transcript_sha256")
    size = value.get("transcript_size_bytes")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_HASH_INVALID")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > _MAX_TRANSCRIPT_BYTES:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_INVALID")
    root = run_root(package_root, run_id)
    transcript = root / "transcript.json"
    try:
        actual_size = transcript.stat().st_size
    except OSError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_MISSING") from exc
    if actual_size != size:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_MISMATCH")
    if verify_content and _sha256_file(transcript) != digest:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_HASH_MISMATCH")
    return value


def load_run(package_root: Path, run_id: str, *, verify_content: bool = True) -> dict[str, Any]:
    root = run_root(package_root, run_id)
    value = _bounded_json(root / "run.json")
    if value.get("run_id") != run_id:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_ID_MISMATCH")
    return _validate_manifest(package_root, value, verify_content=verify_content)


def _public_summary(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": value["run_id"],
        "origin": value.get("origin"),
        "status": "completed",
        "source_id": value["source_id"],
        "profile_id": value["profile_id"],
        "engine": value.get("engine"),
        "model": value.get("model"),
        "model_revision": value.get("model_revision"),
        "device": value.get("device"),
        "compute_type": value.get("compute_type"),
        "alignment": value.get("alignment"),
        "language": value.get("language"),
        "job_id": value.get("job_id"),
        "attempt": value.get("attempt"),
        "transcript_sha256": value["transcript_sha256"],
        "transcript_size_bytes": value["transcript_size_bytes"],
        "created_at": value.get("created_at"),
        "completed_at": value.get("completed_at"),
        "stats": value.get("stats") if isinstance(value.get("stats"), dict) else {},
    }


def list_runs(package_root: Path, *, verify_content: bool = False) -> list[dict[str, Any]]:
    root = _runs_root(package_root)
    if not root.is_dir():
        return []
    values: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or not _RUN_ID.fullmatch(candidate.name):
            continue
        try:
            manifest = load_run(package_root, candidate.name, verify_content=verify_content)
        except TranscriptionRunError:
            continue
        values.append(_public_summary(manifest))
    values.sort(key=lambda item: str(item.get("completed_at") or item.get("created_at") or ""), reverse=True)
    return values


def migrate_legacy_transcript(package_root: Path, *, source_id: str, source_sha256: str) -> dict[str, Any] | None:
    """Preserve a valid legacy root transcript as an immutable historical run.

    The original root file is deliberately retained. Invalid legacy files are left
    untouched and ignored rather than blocking a new ASR run. If the root file is
    already the compatibility mirror of an immutable run, that run is reused instead
    of creating a duplicate legacy entry.
    """
    legacy = package_root.resolve() / "transcript.json"
    if not legacy.is_file():
        return None
    try:
        payload = _bounded_transcript(legacy)
        value = json.loads(payload.decode("utf-8"))
    except (TranscriptionRunError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != "tda_transcript_v1":
        return None
    if value.get("source_sha256") != source_sha256:
        return None
    engine = value.get("engine")
    stats = value.get("stats")
    if not isinstance(engine, dict) or not isinstance(stats, dict):
        return None
    profile_id = engine.get("profile")
    if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile_id):
        return None

    digest = hashlib.sha256(payload).hexdigest()
    # Once 0.3.x starts mirroring the newest immutable run back to the historical
    # root path, do not mistake that mirror for a new legacy result.
    for existing in list_runs(package_root, verify_content=False):
        if existing.get("transcript_sha256") == digest:
            try:
                return load_run(package_root, str(existing["run_id"]), verify_content=True)
            except TranscriptionRunError:
                continue

    run_id = f"legacy-{digest}"
    destination = run_root(package_root, run_id)
    if destination.exists():
        try:
            return load_run(package_root, run_id, verify_content=True)
        except TranscriptionRunError:
            return None
    destination.mkdir(parents=True, exist_ok=False)
    _atomic_bytes(destination / "transcript.json", payload)
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "origin": "legacy_transcript_v1",
        "status": "completed",
        "source_id": _source_id(package_root, source_id),
        "source_sha256": source_sha256,
        "job_id": None,
        "attempt": None,
        "profile_id": profile_id,
        "engine": engine.get("engine"),
        "model": engine.get("model"),
        "model_revision": engine.get("model_revision"),
        "device": engine.get("device"),
        "compute_type": engine.get("compute_type"),
        "alignment": engine.get("alignment"),
        "language": value.get("language"),
        "context_sha256": None,
        "glossary_sha256": None,
        "transcript_schema_version": "tda_transcript_v1",
        "artifact": "transcript.json",
        "transcript_sha256": digest,
        "transcript_size_bytes": len(payload),
        "created_at": value.get("created_at"),
        "completed_at": value.get("created_at") or utc_now(),
        "stats": {
            key: stats.get(key)
            for key in (
                "processing_seconds",
                "rtf",
                "word_count",
                "segment_count",
                "track_count",
                "turn_count",
                "deduplicated_segment_count",
            )
            if key in stats
        },
    }
    _atomic_json(destination / "run.json", manifest)
    return manifest


def ensure_legacy_and_list(
    package_root: Path,
    *,
    source_id: str,
    source_sha256: str,
    verify_content: bool = False,
) -> dict[str, Any]:
    migrate_legacy_transcript(
        package_root,
        source_id=source_id,
        source_sha256=source_sha256,
    )
    return {
        "schema_version": RUN_LIST_SCHEMA_VERSION,
        "source_id": source_id,
        "runs": list_runs(package_root, verify_content=verify_content),
    }
