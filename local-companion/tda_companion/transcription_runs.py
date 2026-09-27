from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .atomic_storage import AtomicStorageError, atomic_write, confirm_existing_file

from .transcript import TranscriptDocument, TranscriptValidationError

RUN_SCHEMA_VERSION = "tda_transcription_run_v1"
RUN_LIST_SCHEMA_VERSION = "tda_transcription_runs_v1"
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,196}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_TRANSCRIPT_BYTES = 512 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024
_ROOT_STATE_SCHEMA = "tda_root_transcript_state_v1"


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
    atomic_write(path, payload)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    _atomic_bytes(path, payload)


def _bounded_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise TranscriptionRunError("TRANSCRIPTION_RUN_MANIFEST_SYMLINK")
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
    if path.is_symlink():
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SYMLINK")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_MISSING") from exc
    if size <= 0 or size > _MAX_TRANSCRIPT_BYTES:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_INVALID")
    try:
        with path.open("rb") as handle:
            # Reading the global 512 MiB ceiling makes BufferedReader allocate
            # that ceiling even for small files on Windows. Bound by the size
            # just checked, plus one byte to detect concurrent growth.
            payload = handle.read(size + 1)
        if len(payload) != size or len(payload) > _MAX_TRANSCRIPT_BYTES:
            raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_MISMATCH")
        return payload
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
    execution_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document.validate()
    engine = document.engine
    stats = document.stats
    manifest = {
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
            "audio_work_seconds": stats.audio_work_seconds,
            "processing_seconds": stats.processing_seconds,
            "session_duration_seconds": stats.session_duration_seconds,
            "duration_semantics": stats.duration_semantics,
            "rtf": stats.rtf,
            "word_count": stats.word_count,
            "segment_count": stats.segment_count,
            "track_count": stats.track_count,
            "turn_count": stats.turn_count,
            "deduplicated_segment_count": stats.deduplicated_segment_count,
            "warning_count": len(document.warnings),
            "processing_metrics": stats.processing_metrics,
        },
    }
    if execution_lineage is not None:
        manifest["execution_lineage"] = execution_lineage
    return manifest


def write_completed_run(
    package_root: Path,
    document: TranscriptDocument,
    *,
    job_id: str,
    attempt: int,
    source_id: str | None = None,
    glossary: str = "",
    context: str = "",
    execution_lineage: dict[str, Any] | None = None,
    before_commit: Callable[[], None] | None = None,
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
    try:
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
            execution_lineage=execution_lineage,
        )
        # The caller may reserve the cross-process attempt outcome immediately
        # before the immutable run.json commit marker is written. If cancellation
        # already won, the callback raises and this uncommitted directory is
        # removed by the existing fail-closed cleanup below.
        if before_commit is not None:
            before_commit()
        _atomic_json(destination / "run.json", manifest)
        return manifest
    except BaseException as exc:
        # The manifest is the immutable commit marker. Before it exists, this
        # directory is incomplete and cannot become a completed run.
        if not (isinstance(exc, AtomicStorageError) and exc.ambiguous) and not (destination / "run.json").is_file():
            shutil.rmtree(destination, ignore_errors=True)
        raise


def remove_incomplete_run(package_root: Path, run_id: str) -> bool:
    """Remove only an uncommitted run directory (no run.json commit marker)."""
    destination = run_root(package_root, run_id)
    if not destination.is_dir() or (destination / "run.json").exists():
        return False
    try:
        shutil.rmtree(destination)
    except OSError:
        return False
    return not destination.exists()


def remove_incomplete_runs(package_root: Path) -> int:
    """Remove only orphan run directories that never reached the run.json commit marker."""
    root = _runs_root(package_root)
    if not root.is_dir():
        return 0
    removed = 0
    for candidate in root.iterdir():
        if (
            candidate.is_dir()
            and not candidate.is_symlink()
            and _RUN_ID.fullmatch(candidate.name)
            and not (candidate / "run.json").exists()
        ):
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue
            if not candidate.exists():
                removed += 1
    return removed


def write_compatibility_mirror(package_root: Path, run_id: str) -> str:
    """Update legacy <source>/transcript.json without making it the source of truth."""
    with _root_transcript_lock(package_root):
        manifest = load_run(package_root, run_id, verify_content=False)
        source = run_root(package_root, run_id) / "transcript.json"
        payload = _bounded_transcript(source)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != manifest["transcript_sha256"]:
            raise TranscriptionRunError("TRANSCRIPTION_RUN_HASH_MISMATCH")
        target = package_root.resolve() / "transcript.json"
        if target.exists() or target.is_symlink():
            # The projection is never permission to discard the existing bytes.
            # Revalidate/preserve them under the same cross-process lock as replace.
            preserved = _migrate_legacy_transcript(package_root, source_id=manifest["source_id"],
                                                   source_sha256=manifest["source_sha256"])
            if preserved is None:
                _record_root_state(package_root, "invalid_legacy_preserved", None)
                raise TranscriptionRunError("TRANSCRIPTION_LEGACY_PRESERVED_IN_PLACE")
        _atomic_bytes(target, payload)
        _record_root_state(package_root, "compatibility_mirror", manifest)
        return digest


@contextmanager
def _root_transcript_lock(package_root: Path):
    """One maintenance/replace owner across Agent and isolated worker processes."""
    path = package_root.resolve() / ".root-transcript.lock"
    if path.is_symlink():
        raise TranscriptionRunError("TRANSCRIPTION_ROOT_LOCK_INVALID")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + 10
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TranscriptionRunError("TRANSCRIPTION_ROOT_BUSY") from exc
                time.sleep(0.01)
        yield
    finally:
        os.close(descriptor)


def _root_fingerprint(package_root: Path) -> dict[str, int] | None:
    target = package_root.resolve() / "transcript.json"
    try:
        value = target.lstat()
    except FileNotFoundError:
        return None
    return {"size": value.st_size, "mtime_ns": value.st_mtime_ns,
            "ctime_ns": value.st_ctime_ns, "inode": value.st_ino}


def _record_root_state(package_root: Path, kind: str, manifest: dict[str, Any] | None) -> None:
    # Rebuildable projection only. No consumer may use it to authorize overwrite.
    _atomic_json(package_root.resolve() / "root-transcript-state.json", {
        "schema_version": _ROOT_STATE_SCHEMA, "kind": kind,
        "fingerprint": _root_fingerprint(package_root),
        "run_id": manifest["run_id"] if manifest else None,
        "transcript_sha256": manifest["transcript_sha256"] if manifest else None,
    })


def root_transcript_state(package_root: Path) -> dict[str, Any]:
    """Small metadata/stat projection; never opens or hashes transcript content."""
    try:
        fingerprint = _root_fingerprint(package_root)
    except OSError:
        return {"kind": "unclassified_legacy_candidate"}
    if fingerprint is None:
        return {"kind": "absent"}
    try:
        state = _bounded_json(package_root.resolve() / "root-transcript-state.json")
    except TranscriptionRunError:
        return {"kind": "unclassified_legacy_candidate"}
    if (state.get("schema_version") != _ROOT_STATE_SCHEMA or state.get("fingerprint") != fingerprint
            or state.get("kind") not in {"legacy_preserved", "compatibility_mirror", "invalid_legacy_preserved"}):
        return {"kind": "unclassified_legacy_candidate"}
    kind = state["kind"]
    if kind != "invalid_legacy_preserved":
        try:
            manifest = load_run(package_root, state.get("run_id"), verify_content=False)
            if manifest["transcript_sha256"] != state.get("transcript_sha256"):
                return {"kind": "unclassified_legacy_candidate"}
        except TranscriptionRunError:
            return {"kind": "unclassified_legacy_candidate"}
    return {"kind": kind}


def preserve_root_during_source_repair(existing: Path, replacement: Path) -> None:
    """The compatibility consumer must retain even invalid historical evidence."""
    with _root_transcript_lock(existing):
        root = existing / "transcript.json"
        if not root.exists() and not root.is_symlink():
            return
        payload = _bounded_transcript(root)
        copied = replacement / "transcript.json"
        _atomic_bytes(copied, payload)
        if _bounded_transcript(copied) != payload:
            raise TranscriptionRunError("TRANSCRIPTION_LEGACY_COPY_MISMATCH")


def maintain_legacy_transcripts(data_root: Path) -> dict[str, int]:
    """One-time startup maintenance; regular catalog reads never do this work."""
    from .craig_runtime import load_craig_package
    from .craig import CraigPackageError
    counts = {"preserved": 0, "invalid_preserved": 0, "failed": 0}
    staging = data_root.resolve() / "staging"
    if not staging.is_dir():
        return counts
    for package_root in staging.iterdir():
        if (not re.fullmatch(r"craig-[a-f0-9]{64}", package_root.name)
                or package_root.is_symlink() or getattr(package_root, "is_junction", lambda: False)()
                or not package_root.is_dir()):
            continue
        if root_transcript_state(package_root)["kind"] != "unclassified_legacy_candidate":
            continue
        try:
            package = load_craig_package(package_root, verify_tracks=False)
            result = migrate_legacy_transcript(package_root, source_id=package_root.name,
                                                source_sha256=package.source_sha256)
            counts["preserved" if result is not None else "invalid_preserved"] += 1
        except (OSError, TranscriptionRunError, CraigPackageError):
            counts["failed"] += 1
    return counts


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
    # A corrupt historical summary must not poison every sibling in the Web
    # response. This is metadata-only; listing never needs to parse the transcript.
    for name, maximum in (("engine", 64), ("model", 256), ("model_revision", 256),
                          ("device", 64), ("compute_type", 64), ("alignment", 128),
                          ("language", 32)):
        item = value.get(name)
        if item is not None and (
            not isinstance(item, str) or not item.strip() or len(item) > maximum
            or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in item)
        ):
            raise TranscriptionRunError("TRANSCRIPTION_RUN_METADATA_INVALID")
    for name in ("created_at", "completed_at"):
        item = value.get(name)
        if item is not None:
            try:
                if not isinstance(item, str) or datetime.fromisoformat(item.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError("timestamp invalid")
            except ValueError as exc:
                raise TranscriptionRunError("TRANSCRIPTION_RUN_METADATA_INVALID") from exc
    stats = value.get("stats")
    if not isinstance(stats, dict):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_STATS_INVALID")
    from .engine_metrics import validate_engine_metrics
    try:
        validate_engine_metrics(stats.get("processing_metrics"))
        metrics = stats.get("processing_metrics")
        if metrics is not None and (metrics["total_tracks"] != stats.get("track_count") or
            not isinstance(stats.get("audio_work_seconds"), (int, float)) or
            not math.isclose(metrics["fresh_audio_work_seconds"] + metrics["reused_audio_work_seconds"], stats["audio_work_seconds"], abs_tol=0.001)):
            raise ValueError("ENGINE_METRICS_WORK_MISMATCH")
    except ValueError as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_STATS_INVALID") from exc
    for name in ("audio_work_seconds", "processing_seconds", "session_duration_seconds", "rtf",
                 "word_count", "segment_count", "track_count", "turn_count",
                 "deduplicated_segment_count", "warning_count"):
        item = stats.get(name)
        if item is None:
            continue
        count = name.endswith("count")
        if (isinstance(item, bool) or not isinstance(item, int if count else (int, float))
                or item < 0 or item > 2**53 - 1 or not math.isfinite(item)):
            raise TranscriptionRunError("TRANSCRIPTION_RUN_STATS_INVALID")
    digest = value.get("transcript_sha256")
    size = value.get("transcript_size_bytes")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_HASH_INVALID")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > _MAX_TRANSCRIPT_BYTES:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_INVALID")
    root = run_root(package_root, run_id)
    transcript = root / "transcript.json"
    if transcript.is_symlink():
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SYMLINK")
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


def load_verified_transcript_snapshot(
    package_root: Path, run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hash and parse one bounded read; never reopen bytes after verification."""
    manifest = load_run(package_root, run_id, verify_content=False)
    payload = _bounded_transcript(run_root(package_root, run_id) / "transcript.json")
    if len(payload) != manifest["transcript_size_bytes"]:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_SIZE_MISMATCH")
    if hashlib.sha256(payload).hexdigest() != manifest["transcript_sha256"]:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_HASH_MISMATCH")
    try:
        value = json.loads(payload)
        # Release the raw buffer before building the validated object graph.
        del payload
        document = TranscriptDocument.from_dict(value)
    except (UnicodeDecodeError, json.JSONDecodeError, TranscriptValidationError) as exc:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_TRANSCRIPT_INVALID") from exc
    if document.source_sha256 != manifest["source_sha256"]:
        raise TranscriptionRunError("TRANSCRIPTION_RUN_SOURCE_INVALID")
    if len(document.warnings) != manifest["stats"].get("warning_count"):
        raise TranscriptionRunError("TRANSCRIPTION_RUN_WARNING_COUNT_MISMATCH")
    return manifest, value


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
        "execution_lineage": (
            value.get("execution_lineage")
            if isinstance(value.get("execution_lineage"), dict)
            else None
        ),
    }


def list_runs(
    package_root: Path, *, verify_content: bool = False,
    invalid_runs: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    root = _runs_root(package_root)
    if not root.is_dir():
        return []
    values: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or not _RUN_ID.fullmatch(candidate.name):
            continue
        try:
            manifest = load_run(package_root, candidate.name, verify_content=verify_content)
        except TranscriptionRunError as exc:
            if invalid_runs is not None:
                invalid_runs.append({"run_id": candidate.name, "integrity": "invalid", "reason": str(exc)})
            continue
        values.append(_public_summary(manifest))
    values.sort(key=lambda item: str(item.get("completed_at") or item.get("created_at") or ""), reverse=True)
    return values


def migrate_legacy_transcript(package_root: Path, *, source_id: str, source_sha256: str) -> dict[str, Any] | None:
    with _root_transcript_lock(package_root):
        manifest = _migrate_legacy_transcript(package_root, source_id=source_id, source_sha256=source_sha256)
        if manifest is not None:
            kind = "legacy_preserved" if manifest.get("origin") == "legacy_transcript_v1" else "compatibility_mirror"
            _record_root_state(package_root, kind, manifest)
        elif (package_root / "transcript.json").exists() or (package_root / "transcript.json").is_symlink():
            _record_root_state(package_root, "invalid_legacy_preserved", None)
        return manifest


def _migrate_legacy_transcript(package_root: Path, *, source_id: str, source_sha256: str) -> dict[str, Any] | None:
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
    try:
        document = TranscriptDocument.from_dict(value)
    except TranscriptValidationError:
        return None
    if document.source_sha256 != source_sha256:
        return None
    validated = document.as_dict()
    engine = validated["engine"]
    stats = validated["stats"]
    profile_id = document.engine.profile

    digest = hashlib.sha256(payload).hexdigest()
    # Once 0.3.x starts mirroring the newest immutable run back to the historical
    # root path, do not mistake that mirror for a new legacy result.
    for existing in list_runs(package_root, verify_content=False):
        if existing.get("transcript_sha256") == digest:
            try:
                return _confirmed_preserved_run(package_root, str(existing["run_id"]))
            except TranscriptionRunError:
                continue

    run_id = f"legacy-{digest}"
    destination = run_root(package_root, run_id)
    if destination.exists():
        try:
            return _confirmed_preserved_run(package_root, run_id)
        except TranscriptionRunError:
            # A directory without run.json is only an interrupted migration, not
            # an immutable commit. Rebuild it from the still-valid root legacy
            # transcript instead of permanently abandoning migration.
            if not remove_incomplete_run(package_root, run_id):
                return None

    destination.mkdir(parents=True, exist_ok=False)
    try:
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
            "language": document.language,
            "context_sha256": None,
            "glossary_sha256": None,
            "transcript_schema_version": "tda_transcript_v1",
            "artifact": "transcript.json",
            "transcript_sha256": digest,
            "transcript_size_bytes": len(payload),
            "created_at": document.created_at,
            "completed_at": document.created_at,
            "stats": {
                **{
                    key: stats.get(key)
                    for key in (
                        "audio_work_seconds",
                        "processing_seconds",
                        "session_duration_seconds",
                        "duration_semantics",
                        "rtf",
                        "word_count",
                        "segment_count",
                        "track_count",
                        "turn_count",
                        "deduplicated_segment_count",
                    )
                    if key in stats
                },
                "warning_count": len(document.warnings),
            },
        }
        _validate_manifest(package_root, manifest, verify_content=True)
        _atomic_json(destination / "run.json", manifest)
        return manifest
    except BaseException as exc:
        if not (isinstance(exc, AtomicStorageError) and exc.ambiguous) and not (destination / "run.json").is_file():
            shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, TranscriptionRunError):
            return None
        raise


def _confirmed_preserved_run(package_root: Path, run_id: str) -> dict[str, Any]:
    manifest = load_run(package_root, run_id, verify_content=True)
    # A previous process may have stopped after replace but before the namespace
    # fence. Re-establish the current policy before authorizing root overwrite.
    root = run_root(package_root, run_id)
    confirm_existing_file(root / "transcript.json")
    confirm_existing_file(root / "run.json")
    return manifest


def ensure_legacy_and_list(
    package_root: Path,
    *,
    source_id: str,
    source_sha256: str,
    verify_content: bool = False,
) -> dict[str, Any]:
    # Compatibility name retained for callers; listing never runs maintenance.
    invalid_runs: list[dict[str, str]] = []
    runs = list_runs(package_root, verify_content=verify_content, invalid_runs=invalid_runs)
    return {
        "schema_version": RUN_LIST_SCHEMA_VERSION,
        "source_id": source_id,
        "runs": runs,
        "invalid_runs": invalid_runs,
        "root_transcript": root_transcript_state(package_root),
    }
