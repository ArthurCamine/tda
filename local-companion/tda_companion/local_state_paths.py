from __future__ import annotations

import os
from pathlib import Path


class LocalStatePathError(ValueError):
    pass


def is_reparse_path(path: Path) -> bool:
    """Return true for symlinks and Windows directory junctions/reparse aliases."""
    try:
        if path.is_symlink():
            return True
        return bool(getattr(path, "is_junction", lambda: False)())
    except OSError as exc:
        raise LocalStatePathError("LOCAL_STATE_PATH_INSPECTION_FAILED") from exc


def confined_directory(
    package_root: Path,
    relative_parts: tuple[str, ...],
    *,
    create: bool,
) -> Path:
    """Resolve a local state directory without accepting reparse-point ancestors."""
    package = package_root.resolve()
    current = package
    for part in relative_parts:
        if not isinstance(part, str) or not part or part in {".", ".."}:
            raise LocalStatePathError("LOCAL_STATE_PATH_COMPONENT_INVALID")
        current = current / part
        if is_reparse_path(current):
            raise LocalStatePathError("LOCAL_STATE_PATH_REPARSE")
        try:
            exists = current.exists()
        except OSError as exc:
            raise LocalStatePathError("LOCAL_STATE_PATH_INSPECTION_FAILED") from exc
        if not exists:
            if not create:
                continue
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise LocalStatePathError("LOCAL_STATE_PATH_CREATE_FAILED") from exc
        if is_reparse_path(current):
            raise LocalStatePathError("LOCAL_STATE_PATH_REPARSE")
        try:
            if not current.is_dir():
                raise LocalStatePathError("LOCAL_STATE_PATH_NOT_DIRECTORY")
            resolved = current.resolve(strict=True)
            if os.path.commonpath((str(package), str(resolved))) != str(package):
                raise LocalStatePathError("LOCAL_STATE_PATH_ESCAPE")
        except (OSError, ValueError) as exc:
            if isinstance(exc, LocalStatePathError):
                raise
            raise LocalStatePathError("LOCAL_STATE_PATH_INSPECTION_FAILED") from exc
    return current


def confined_regular_file(
    package_root: Path,
    path: Path,
    *,
    allow_missing: bool,
) -> Path:
    """Reject linked/reparse file targets and prove existing files stay under root."""
    package = package_root.resolve()
    if is_reparse_path(path):
        raise LocalStatePathError("LOCAL_STATE_PATH_REPARSE")
    try:
        exists = path.exists()
    except OSError as exc:
        raise LocalStatePathError("LOCAL_STATE_PATH_INSPECTION_FAILED") from exc
    if not exists:
        if allow_missing:
            return path
        raise LocalStatePathError("LOCAL_STATE_PATH_MISSING")
    try:
        if not path.is_file():
            raise LocalStatePathError("LOCAL_STATE_PATH_NOT_FILE")
        resolved = path.resolve(strict=True)
        if os.path.commonpath((str(package), str(resolved))) != str(package):
            raise LocalStatePathError("LOCAL_STATE_PATH_ESCAPE")
    except (OSError, ValueError) as exc:
        if isinstance(exc, LocalStatePathError):
            raise
        raise LocalStatePathError("LOCAL_STATE_PATH_INSPECTION_FAILED") from exc
    return path
