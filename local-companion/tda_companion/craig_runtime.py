from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .craig import (
    CraigIdentity,
    CraigPackage,
    CraigPackageError,
    CraigTrack,
    TRACK_NAME,
    physical_track_filename,
)

_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_COPY_CHUNK = 1024 * 1024
_WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')


def _text(value: Any, code: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise CraigPackageError(code)
    result = value.strip()
    if not result or len(result) > maximum:
        raise CraigPackageError(code)
    return result


def _optional_text(value: Any, code: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, code, maximum=maximum)


def _sha(value: Any, code: str) -> str:
    result = _text(value, code, maximum=64)
    if not _SHA256.fullmatch(result):
        raise CraigPackageError(code)
    return result.lower()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(value: Any) -> CraigIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CraigPackageError("CRAIG_MANIFEST_IDENTITY_INVALID")
    username = _text(value.get("username"), "CRAIG_MANIFEST_IDENTITY_INVALID", maximum=160)
    discriminator = _optional_text(
        value.get("discriminator"), "CRAIG_MANIFEST_IDENTITY_INVALID", maximum=32
    )
    discord_id = _optional_text(value.get("discord_id"), "CRAIG_MANIFEST_IDENTITY_INVALID", maximum=64)
    return CraigIdentity(username=username, discriminator=discriminator, discord_id=discord_id)


def _portable_legacy_filename(value: str) -> bool:
    # Older staged packages used Craig's source filename physically. Keep ordinary
    # historical packages readable, but never trust NTFS-special characters or
    # control characters from an old manifest.
    return (
        bool(value)
        and value == Path(value).name
        and not value.endswith((" ", "."))
        and not any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN for char in value)
    )


def load_craig_package(package_root: Path, *, verify_tracks: bool = True) -> CraigPackage:
    """Load a TDA-staged Craig package without trusting paths stored in its manifest."""
    root = package_root.resolve()
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.stat().st_size > _MANIFEST_MAX_BYTES:
            raise CraigPackageError("CRAIG_MANIFEST_SIZE_LIMIT")
        raw = manifest_path.read_bytes()
    except FileNotFoundError as exc:
        raise CraigPackageError("CRAIG_MANIFEST_NOT_FOUND") from exc
    except OSError as exc:
        raise CraigPackageError("CRAIG_MANIFEST_READ_FAILED") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CraigPackageError("CRAIG_MANIFEST_INVALID") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "tda_craig_package_v1":
        raise CraigPackageError("CRAIG_MANIFEST_SCHEMA_UNSUPPORTED")

    source_zip = _text(value.get("source_zip"), "CRAIG_MANIFEST_SOURCE_INVALID", maximum=512)
    if Path(source_zip).name != source_zip or "/" in source_zip or "\\" in source_zip:
        raise CraigPackageError("CRAIG_MANIFEST_SOURCE_INVALID")
    source_sha256 = _sha(value.get("source_sha256"), "CRAIG_MANIFEST_SOURCE_HASH_INVALID")

    tracks_value = value.get("tracks")
    if not isinstance(tracks_value, list) or not tracks_value or len(tracks_value) > 256:
        raise CraigPackageError("CRAIG_MANIFEST_TRACKS_INVALID")

    tracks: list[CraigTrack] = []
    seen_numbers: set[int] = set()
    for item in tracks_value:
        if not isinstance(item, dict):
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_INVALID")
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in seen_numbers:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_NUMBER_INVALID")
        seen_numbers.add(number)
        speaker = _text(item.get("speaker"), "CRAIG_MANIFEST_SPEAKER_INVALID", maximum=160)
        filename = _text(item.get("filename"), "CRAIG_MANIFEST_FILENAME_INVALID", maximum=512)
        match = TRACK_NAME.fullmatch(filename)
        if not match or int(match.group("track")) != number or match.group("speaker").strip() != speaker:
            raise CraigPackageError("CRAIG_MANIFEST_FILENAME_INVALID")

        canonical_relative = f"tracks/{physical_track_filename(number)}"
        legacy_relative = f"tracks/{filename}"
        stored_path = item.get("path")
        if stored_path == canonical_relative:
            expected_relative = canonical_relative
        elif stored_path == legacy_relative and _portable_legacy_filename(filename):
            expected_relative = legacy_relative
        else:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_PATH_INVALID")

        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_SIZE_INVALID")
        digest = _sha(item.get("sha256"), "CRAIG_MANIFEST_TRACK_HASH_INVALID")
        offset = item.get("timeline_offset_seconds", 0.0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or float(offset) < 0:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_OFFSET_INVALID")

        candidate = (root / expected_relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_MISSING")
        stat = candidate.stat()
        if stat.st_size != size_bytes:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_SIZE_MISMATCH")
        if verify_tracks and _sha256_file(candidate) != digest:
            raise CraigPackageError("CRAIG_MANIFEST_TRACK_HASH_MISMATCH")

        tracks.append(
            CraigTrack(
                number=number,
                speaker=speaker,
                filename=filename,
                path=expected_relative,
                size_bytes=size_bytes,
                sha256=digest,
                identity=_identity(item.get("identity")),
                timeline_offset_seconds=float(offset),
            )
        )

    tracks.sort(key=lambda item: item.number)
    return CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip=source_zip,
        source_sha256=source_sha256,
        recording_id=_optional_text(value.get("recording_id"), "CRAIG_MANIFEST_RECORDING_INVALID", maximum=256),
        guild=_optional_text(value.get("guild"), "CRAIG_MANIFEST_GUILD_INVALID", maximum=512),
        channel=_optional_text(value.get("channel"), "CRAIG_MANIFEST_CHANNEL_INVALID", maximum=512),
        requester=_optional_text(value.get("requester"), "CRAIG_MANIFEST_REQUESTER_INVALID", maximum=512),
        start_time=_optional_text(value.get("start_time"), "CRAIG_MANIFEST_START_TIME_INVALID", maximum=128),
        tracks=tuple(tracks),
        info_present=bool(value.get("info_present")),
        raw_dat_present=bool(value.get("raw_dat_present")),
    )
