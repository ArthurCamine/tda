from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

TRACK_NAME = re.compile(r"^(?P<track>[1-9][0-9]*)-(?P<speaker>.+)\.flac$", re.IGNORECASE)
MAX_ENTRIES = 256
MAX_INFO_BYTES = 1024 * 1024
MAX_TRACK_BYTES = 16 * 1024**3
MAX_TOTAL_BYTES = 64 * 1024**3
MAX_COMPRESSION_RATIO = 150.0
COPY_CHUNK = 1024 * 1024


class CraigPackageError(ValueError):
    pass


@dataclass(frozen=True)
class CraigIdentity:
    username: str
    discriminator: str | None
    discord_id: str | None


@dataclass(frozen=True)
class CraigTrack:
    number: int
    speaker: str
    filename: str
    path: str
    size_bytes: int
    sha256: str
    identity: CraigIdentity | None
    timeline_offset_seconds: float = 0.0


@dataclass(frozen=True)
class CraigPackage:
    schema_version: str
    source_zip: str
    source_sha256: str
    recording_id: str | None
    guild: str | None
    channel: str | None
    requester: str | None
    start_time: str | None
    tracks: tuple[CraigTrack, ...]
    info_present: bool
    raw_dat_present: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def physical_track_filename(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise CraigPackageError("CRAIG_TRACK_NUMBER_INVALID")
    return f"track-{number:06d}.flac"


def _member_name(info: zipfile.ZipInfo) -> str:
    # ZIP paths are POSIX regardless of host platform.
    value = info.filename.replace("\\", "/")
    path = PurePosixPath(value)
    if not value or value.startswith("/") or path.is_absolute():
        raise CraigPackageError("CRAIG_ARCHIVE_ABSOLUTE_PATH")
    if any(part in ("", ".", "..") for part in path.parts):
        raise CraigPackageError("CRAIG_ARCHIVE_UNSAFE_PATH")
    if len(path.parts) != 1:
        raise CraigPackageError("CRAIG_ARCHIVE_NESTED_PATH")
    return path.name


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode and stat.S_ISLNK(mode))


def _ratio(info: zipfile.ZipInfo) -> float:
    if info.file_size <= 0:
        return 1.0
    return info.file_size / max(info.compress_size, 1)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> str:
    digest = hashlib.sha256()
    temporary = target.with_suffix(target.suffix + ".partial")
    written = 0
    with archive.open(info, "r") as source, temporary.open("wb") as destination:
        while True:
            chunk = source.read(COPY_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > info.file_size:
                raise CraigPackageError("CRAIG_ARCHIVE_SIZE_MISMATCH")
            digest.update(chunk)
            destination.write(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    if written != info.file_size:
        temporary.unlink(missing_ok=True)
        raise CraigPackageError("CRAIG_ARCHIVE_SIZE_MISMATCH")
    os.replace(temporary, target)
    return digest.hexdigest()


def parse_info_text(text: str) -> dict[str, object]:
    """Parse Craig's public info.txt format without depending on Discord APIs."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    value: dict[str, object] = {"tracks": []}
    if lines and lines[0].startswith("Recording "):
        value["recording_id"] = lines[0][len("Recording ") :].strip() or None

    labels = {
        "Guild:": "guild",
        "Channel:": "channel",
        "Requester:": "requester",
        "Start time:": "start_time",
    }
    in_tracks = False
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Tracks:":
            in_tracks = True
            continue
        if stripped == "Notes:":
            in_tracks = False
            continue
        matched_label = False
        for prefix, key in labels.items():
            if stripped.startswith(prefix):
                value[key] = stripped[len(prefix) :].strip() or None
                matched_label = True
                in_tracks = False
                break
        if matched_label or not in_tracks:
            continue
        identity = re.match(r"^(?P<name>.+?)(?:#(?P<disc>[^\s()]+))?\s+\((?P<id>[^()]+)\)$", stripped)
        if identity:
            tracks = value["tracks"]
            assert isinstance(tracks, list)
            tracks.append(
                {
                    "username": identity.group("name").strip(),
                    "discriminator": identity.group("disc"),
                    "discord_id": identity.group("id").strip(),
                }
            )
    return value


def _safe_start_time(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) > 128:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return text


def inspect_craig_zip(source_zip: Path) -> tuple[list[tuple[zipfile.ZipInfo, int, str]], zipfile.ZipInfo | None, bool]:
    source_zip = source_zip.resolve()
    if not source_zip.is_file():
        raise CraigPackageError("CRAIG_ARCHIVE_NOT_FOUND")
    try:
        archive = zipfile.ZipFile(source_zip, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CraigPackageError("CRAIG_ARCHIVE_INVALID") from exc

    with archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if not infos or len(infos) > MAX_ENTRIES:
            raise CraigPackageError("CRAIG_ARCHIVE_ENTRY_LIMIT")
        total = 0
        tracks: list[tuple[zipfile.ZipInfo, int, str]] = []
        seen_numbers: set[int] = set()
        info_member: zipfile.ZipInfo | None = None
        raw_present = False
        names: set[str] = set()
        for item in infos:
            name = _member_name(item)
            folded = name.casefold()
            if folded in names:
                raise CraigPackageError("CRAIG_ARCHIVE_DUPLICATE_NAME")
            names.add(folded)
            if _is_symlink(item):
                raise CraigPackageError("CRAIG_ARCHIVE_SYMLINK")
            if item.file_size < 0 or item.compress_size < 0:
                raise CraigPackageError("CRAIG_ARCHIVE_INVALID_SIZE")
            total += item.file_size
            if total > MAX_TOTAL_BYTES:
                raise CraigPackageError("CRAIG_ARCHIVE_TOTAL_SIZE_LIMIT")
            if _ratio(item) > MAX_COMPRESSION_RATIO:
                raise CraigPackageError("CRAIG_ARCHIVE_COMPRESSION_RATIO")

            match = TRACK_NAME.fullmatch(name)
            if match:
                if item.file_size <= 0 or item.file_size > MAX_TRACK_BYTES:
                    raise CraigPackageError("CRAIG_TRACK_SIZE_LIMIT")
                number = int(match.group("track"))
                if number in seen_numbers:
                    raise CraigPackageError("CRAIG_TRACK_NUMBER_DUPLICATE")
                seen_numbers.add(number)
                speaker = match.group("speaker").strip()
                if not speaker or len(speaker) > 160:
                    raise CraigPackageError("CRAIG_TRACK_SPEAKER_INVALID")
                tracks.append((item, number, speaker))
            elif folded == "info.txt":
                if item.file_size > MAX_INFO_BYTES:
                    raise CraigPackageError("CRAIG_INFO_SIZE_LIMIT")
                info_member = item
            elif folded == "raw.dat":
                raw_present = True
            else:
                raise CraigPackageError("CRAIG_ARCHIVE_UNEXPECTED_FILE")

        if not tracks:
            raise CraigPackageError("CRAIG_ARCHIVE_NO_TRACKS")
        tracks.sort(key=lambda value: value[1])
        return tracks, info_member, raw_present


def ingest_craig_zip(source_zip: Path, destination: Path) -> CraigPackage:
    """Safely materialize only FLAC tracks and bounded metadata from a Craig ZIP."""
    source_zip = source_zip.resolve()
    destination = destination.resolve()
    tracks, info_member, raw_present = inspect_craig_zip(source_zip)
    source_sha = _sha256_file(source_zip)
    staging = destination.parent / f".{destination.name}-{uuid4().hex}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=False)

    try:
        info_value: dict[str, object] = {"tracks": []}
        info_present = info_member is not None
        with zipfile.ZipFile(source_zip, "r") as archive:
            if info_member is not None:
                raw_info = archive.read(info_member)
                if len(raw_info) > MAX_INFO_BYTES:
                    raise CraigPackageError("CRAIG_INFO_SIZE_LIMIT")
                try:
                    info_text = raw_info.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise CraigPackageError("CRAIG_INFO_ENCODING") from exc
                info_value = parse_info_text(info_text)
                (staging / "info.txt").write_text(info_text, encoding="utf-8", newline="\n")

            identities = info_value.get("tracks")
            info_tracks = identities if isinstance(identities, list) else []
            output_tracks: list[CraigTrack] = []
            tracks_root = staging / "tracks"
            tracks_root.mkdir()
            for index, (member, number, speaker) in enumerate(tracks):
                source_filename = _member_name(member)
                physical_filename = physical_track_filename(number)
                target = tracks_root / physical_filename
                digest = _copy_member(archive, member, target)
                identity = None
                if index < len(info_tracks) and isinstance(info_tracks[index], dict):
                    row = info_tracks[index]
                    username = row.get("username")
                    if isinstance(username, str) and username.strip():
                        identity = CraigIdentity(
                            username=username.strip(),
                            discriminator=row.get("discriminator") if isinstance(row.get("discriminator"), str) else None,
                            discord_id=row.get("discord_id") if isinstance(row.get("discord_id"), str) else None,
                        )
                output_tracks.append(
                    CraigTrack(
                        number=number,
                        speaker=speaker,
                        filename=source_filename,
                        path=f"tracks/{physical_filename}",
                        size_bytes=member.file_size,
                        sha256=digest,
                        identity=identity,
                    )
                )

        package = CraigPackage(
            schema_version="tda_craig_package_v1",
            source_zip=source_zip.name,
            source_sha256=source_sha,
            recording_id=info_value.get("recording_id") if isinstance(info_value.get("recording_id"), str) else None,
            guild=info_value.get("guild") if isinstance(info_value.get("guild"), str) else None,
            channel=info_value.get("channel") if isinstance(info_value.get("channel"), str) else None,
            requester=info_value.get("requester") if isinstance(info_value.get("requester"), str) else None,
            start_time=_safe_start_time(info_value.get("start_time")),
            tracks=tuple(output_tracks),
            info_present=info_present,
            raw_dat_present=raw_present,
        )
        manifest = staging / "manifest.json"
        manifest.write_text(
            json.dumps(package.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        if destination.exists():
            raise CraigPackageError("CRAIG_DESTINATION_EXISTS")
        os.replace(staging, destination)
        return package
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
