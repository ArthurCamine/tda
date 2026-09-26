from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Literal
from .atomic_storage import sync_namespace
from .local_state_paths import (
    LocalStatePathError,
    confined_directory,
    confined_regular_file,
)

AttemptOutcome = Literal["cancel", "commit"]

_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_ATTEMPT = 1_000_000
_MAX_FENCE_BYTES = 16
_FENCE_DIR = ".attempt-fences"


class AttemptFenceError(RuntimeError):
    pass


def _attempt_key(job_id: str, attempt: int) -> str:
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise AttemptFenceError("ATTEMPT_FENCE_JOB_ID_INVALID")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= _MAX_ATTEMPT:
        raise AttemptFenceError("ATTEMPT_FENCE_ATTEMPT_INVALID")
    return f"run-{job_id}-a{attempt}"


def _fence_path(
    package_root: Path,
    job_id: str,
    attempt: int,
    *,
    create_parent: bool = False,
) -> Path:
    try:
        root = confined_directory(
            package_root,
            (_FENCE_DIR,),
            create=create_parent,
        )
    except LocalStatePathError as exc:
        if str(exc) == "LOCAL_STATE_PATH_REPARSE":
            raise AttemptFenceError("ATTEMPT_FENCE_PATH_SYMLINK") from exc
        raise AttemptFenceError("ATTEMPT_FENCE_PATH_INVALID") from exc
    path = root / f"{_attempt_key(job_id, attempt)}.decision"
    try:
        return confined_regular_file(
            package_root,
            path,
            allow_missing=True,
        )
    except LocalStatePathError as exc:
        if str(exc) == "LOCAL_STATE_PATH_REPARSE":
            raise AttemptFenceError("ATTEMPT_FENCE_PATH_SYMLINK") from exc
        raise AttemptFenceError("ATTEMPT_FENCE_PATH_INVALID") from exc


def _read_fence(path: Path) -> AttemptOutcome:
    try:
        if path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)()):
            raise AttemptFenceError("ATTEMPT_FENCE_PATH_SYMLINK")
    except OSError as exc:
        raise AttemptFenceError("ATTEMPT_FENCE_READ_FAILED") from exc
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise AttemptFenceError("ATTEMPT_FENCE_NOT_FOUND") from exc
    except OSError as exc:
        raise AttemptFenceError("ATTEMPT_FENCE_READ_FAILED") from exc
    if stat.st_size <= 0:
        raise AttemptFenceError("ATTEMPT_FENCE_INCOMPLETE")
    if stat.st_size > _MAX_FENCE_BYTES:
        raise AttemptFenceError("ATTEMPT_FENCE_INVALID")
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise AttemptFenceError("ATTEMPT_FENCE_READ_FAILED") from exc
    if value not in {"cancel", "commit"}:
        raise AttemptFenceError("ATTEMPT_FENCE_INVALID")
    return value  # type: ignore[return-value]


def _read_existing_fence(path: Path) -> AttemptOutcome:
    # The creator uses O_EXCL, then writes/fsyncs a handful of bytes. A racing
    # loser can observe the directory entry during that tiny write window. Retry
    # only the explicit incomplete state; corrupt/oversized/symlinked markers
    # remain fail-closed immediately.
    deadline = time.monotonic() + 0.25
    while True:
        try:
            decision = _read_fence(path)
            try:
                with path.open("r+b") as handle:
                    os.fsync(handle.fileno())
                sync_namespace(path.parent)
            except OSError as exc:
                raise AttemptFenceError("ATTEMPT_FENCE_WRITE_UNCONFIRMED") from exc
            return decision
        except AttemptFenceError as exc:
            if str(exc) != "ATTEMPT_FENCE_INCOMPLETE" or time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def read_attempt_outcome(
    package_root: Path,
    job_id: str,
    attempt: int,
) -> AttemptOutcome | None:
    path = _fence_path(package_root, job_id, attempt)
    try:
        return _read_fence(path)
    except AttemptFenceError as exc:
        if str(exc) == "ATTEMPT_FENCE_NOT_FOUND":
            return None
        raise


def claim_attempt_outcome(
    package_root: Path,
    job_id: str,
    attempt: int,
    decision: AttemptOutcome,
) -> AttemptOutcome:
    if decision not in {"cancel", "commit"}:
        raise AttemptFenceError("ATTEMPT_FENCE_DECISION_INVALID")

    path = _fence_path(
        package_root,
        job_id,
        attempt,
        create_parent=True,
    )
    # Re-evaluate after mkdir so a pre-existing reparse point cannot redirect
    # the cross-process winner marker outside the staged Craig package.
    path = _fence_path(package_root, job_id, attempt)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return _read_existing_fence(path)
    except OSError as exc:
        raise AttemptFenceError("ATTEMPT_FENCE_WRITE_FAILED") from exc

    payload = f"{decision}\n".encode("ascii")
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError("short fence write")
        os.fsync(descriptor)
    except OSError as exc:
        try:
            os.close(descriptor)
        finally:
            path.unlink(missing_ok=True)
        raise AttemptFenceError("ATTEMPT_FENCE_WRITE_FAILED") from exc
    else:
        os.close(descriptor)
    try:
        _fence_path(package_root, job_id, attempt)
        sync_namespace(path.parent)
    except OSError as exc:
        # The winner marker is already visible; never unlink it to compensate.
        raise AttemptFenceError("ATTEMPT_FENCE_WRITE_UNCONFIRMED") from exc
    return decision
