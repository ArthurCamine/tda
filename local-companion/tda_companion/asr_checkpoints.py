from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .asr_models import AsrProfile
from .craig import CraigPackage, CraigTrack
from .transcript import TranscriptSegment, TranscriptTrack, TranscriptValidationError

CHECKPOINT_SCHEMA = "tda_asr_track_checkpoint_v2"
QWEN_TEXT_CHECKPOINT_SCHEMA = "tda_qwen_text_checkpoint_v1"
QWEN_TEXT_CHECKPOINT_NAMESPACE = "qwen-text-v1"
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
_TRACK_CHECKPOINT_KEYS = frozenset(
    {
        "schema",
        "signature",
        "signature_sha256",
        "content_sha256",
        "track_source_sha256",
        "track",
    }
)
_TRACK_CHECKPOINT_TRACK_KEYS = frozenset(
    {
        "number",
        "speaker",
        "source_filename",
        "source_sha256",
        "duration_seconds",
        "segments",
        "timeline_offset_seconds",
        "identity",
    }
)
_TRACK_CHECKPOINT_SEGMENT_KEYS = frozenset(
    {"id", "start", "end", "text", "words", "confidence"}
)
_TRACK_CHECKPOINT_WORD_KEYS = frozenset(
    {"text", "start", "end", "confidence"}
)
_TRACK_CHECKPOINT_IDENTITY_KEYS = frozenset(
    {"username", "discriminator", "discord_id"}
)


@dataclass(frozen=True)
class QwenTextCheckpointWindow:
    index: int
    start: float
    end: float
    text: str
    language: str


@dataclass(frozen=True)
class CheckpointSignature:
    package_sha256: str
    profile_id: str
    engine: str
    model_id: str
    model_revision: str | None
    alignment: str
    alignment_revision: str | None
    runtime_fingerprint: str
    recipe_sha256: str
    context_sha256: str
    glossary_sha256: str

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)

    def digest(self) -> str:
        payload = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_checkpoint_signature(
    package: CraigPackage,
    profile: AsrProfile,
    *,
    recipe: object,
    context: str,
    glossary: str,
    runtime_fingerprint: str,
) -> CheckpointSignature:
    return CheckpointSignature(
        package_sha256=package.source_sha256.lower(),
        profile_id=profile.id,
        engine=profile.engine,
        model_id=profile.model_id,
        model_revision=profile.revision,
        alignment=profile.alignment,
        alignment_revision=profile.alignment_revision,
        runtime_fingerprint=runtime_fingerprint,
        recipe_sha256=_canonical_json_hash(recipe),
        context_sha256=_sha_text(context),
        glossary_sha256=_sha_text(glossary),
    )


def _checkpoint_path(package_root: Path, signature: CheckpointSignature, track_number: int) -> Path:
    if track_number < 1:
        raise ValueError("CHECKPOINT_TRACK_NUMBER_INVALID")
    root = package_root.resolve() / ".checkpoints" / signature.digest()
    return root / f"track-{track_number:04d}.json"


def _qwen_text_checkpoint_path(
    package_root: Path,
    signature: CheckpointSignature,
    track_number: int,
) -> Path:
    if track_number < 1:
        raise ValueError("CHECKPOINT_TRACK_NUMBER_INVALID")
    package = package_root.resolve()
    base = package / ".checkpoints"
    signature_root = base / signature.digest()
    namespace = signature_root / QWEN_TEXT_CHECKPOINT_NAMESPACE
    for candidate in (base, signature_root, namespace):
        if candidate.is_symlink():
            raise ValueError("CHECKPOINT_PATH_SYMLINK")
        if candidate.exists() and not candidate.is_dir():
            raise ValueError("CHECKPOINT_PATH_INVALID")
    return namespace / f"track-{track_number:04d}.json"


def _track_descriptor(track: CraigTrack) -> dict[str, object]:
    return {
        "number": track.number,
        "speaker": track.speaker,
        "source_filename": track.filename,
        "source_sha256": track.sha256.lower(),
        "timeline_offset_seconds": float(track.timeline_offset_seconds),
        "identity": asdict(track.identity) if track.identity is not None else None,
    }


def _qwen_text_window_from_dict(value: Any) -> QwenTextCheckpointWindow:
    if not isinstance(value, dict) or set(value) != {"index", "start", "end", "text", "language"}:
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    index = value.get("index")
    start = value.get("start")
    end = value.get("end")
    text = value.get("text")
    language = value.get("language")
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if isinstance(start, bool) or not isinstance(start, (int, float)):
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if isinstance(end, bool) or not isinstance(end, (int, float)):
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if not math.isfinite(float(start)) or not math.isfinite(float(end)):
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if float(start) < 0 or float(end) <= float(start):
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if not isinstance(text, str) or not isinstance(language, str):
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    if not language or len(language) > 64:
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOW_INVALID")
    return QwenTextCheckpointWindow(
        index=index,
        start=float(start),
        end=float(end),
        text=text,
        language=language,
    )


def _validated_qwen_text_windows(value: Any) -> tuple[QwenTextCheckpointWindow, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOWS_INVALID")
    windows = tuple(_qwen_text_window_from_dict(item) for item in value)
    for expected_index, window in enumerate(windows, start=1):
        if window.index != expected_index:
            raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOWS_INVALID")
        if expected_index > 1 and window.start < windows[expected_index - 2].start:
            raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOWS_INVALID")
    return windows


def _track_from_dict(value: Any) -> TranscriptTrack:
    if not isinstance(value, dict):
        raise TranscriptValidationError("track:OBJECT_REQUIRED")
    if set(value) != _TRACK_CHECKPOINT_TRACK_KEYS:
        raise TranscriptValidationError("track:SCHEMA_INVALID")
    segments_value = value.get("segments")
    if not isinstance(segments_value, list):
        raise TranscriptValidationError("track.segments:ARRAY_REQUIRED")
    for segment in segments_value:
        if not isinstance(segment, dict) or set(segment) != _TRACK_CHECKPOINT_SEGMENT_KEYS:
            raise TranscriptValidationError("track.segment:SCHEMA_INVALID")
        words = segment.get("words")
        if not isinstance(words, list):
            raise TranscriptValidationError("track.segment.words:ARRAY_REQUIRED")
        if any(
            not isinstance(word, dict) or set(word) != _TRACK_CHECKPOINT_WORD_KEYS
            for word in words
        ):
            raise TranscriptValidationError("track.segment.word:SCHEMA_INVALID")
    identity = value.get("identity")
    if identity is not None:
        if not isinstance(identity, dict):
            raise TranscriptValidationError("track.identity:OBJECT_REQUIRED")
        if set(identity) != _TRACK_CHECKPOINT_IDENTITY_KEYS:
            raise TranscriptValidationError("track.identity:SCHEMA_INVALID")
    result = TranscriptTrack(
        number=int(value.get("number")),
        speaker=str(value.get("speaker") or ""),
        source_filename=str(value.get("source_filename") or ""),
        source_sha256=None if value.get("source_sha256") is None else str(value.get("source_sha256")),
        duration_seconds=(
            None if value.get("duration_seconds") is None else float(value.get("duration_seconds"))
        ),
        segments=tuple(
            TranscriptSegment.from_dict(segment, fallback_id=f"checkpoint-{index}")
            for index, segment in enumerate(segments_value, start=1)
        ),
        timeline_offset_seconds=float(value.get("timeline_offset_seconds") or 0.0),
        identity=identity,
    )
    result.validate()
    return result


def _matches_source(transcript: TranscriptTrack, track: CraigTrack) -> bool:
    return (
        transcript.number == track.number
        and transcript.speaker == track.speaker
        and transcript.source_filename == track.filename
        and (transcript.source_sha256 or "").lower() == track.sha256.lower()
        and abs(float(transcript.timeline_offset_seconds) - float(track.timeline_offset_seconds)) <= 0.001
    )


def load_track_checkpoint(
    package_root: Path,
    signature: CheckpointSignature,
    track: CraigTrack,
) -> TranscriptTrack | None:
    path = _checkpoint_path(package_root, signature, track.number)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if stat.st_size <= 0 or stat.st_size > MAX_CHECKPOINT_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or set(value) != _TRACK_CHECKPOINT_KEYS
        or value.get("schema") != CHECKPOINT_SCHEMA
    ):
        return None
    if value.get("signature") != signature.as_dict() or value.get("signature_sha256") != signature.digest():
        return None
    content = {
        "track_source_sha256": value.get("track_source_sha256"),
        "track": value.get("track"),
    }
    if value.get("content_sha256") != _canonical_json_hash(content):
        return None
    if value.get("track_source_sha256") != track.sha256.lower():
        return None
    try:
        transcript = _track_from_dict(value.get("track"))
    except (TypeError, ValueError, TranscriptValidationError):
        return None
    return transcript if _matches_source(transcript, track) else None


def load_qwen_text_checkpoint(
    package_root: Path,
    signature: CheckpointSignature,
    track: CraigTrack,
) -> tuple[QwenTextCheckpointWindow, ...] | None:
    if signature.engine != "qwen3":
        return None
    try:
        path = _qwen_text_checkpoint_path(package_root, signature, track.number)
    except ValueError:
        return None
    try:
        if path.is_symlink():
            return None
        stat = path.stat()
    except (FileNotFoundError, OSError):
        return None
    if stat.st_size <= 0 or stat.st_size > MAX_CHECKPOINT_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != QWEN_TEXT_CHECKPOINT_SCHEMA:
        return None
    if value.get("signature") != signature.as_dict() or value.get("signature_sha256") != signature.digest():
        return None
    descriptor = _track_descriptor(track)
    if value.get("track") != descriptor:
        return None
    windows_value = value.get("windows")
    content = {"track": descriptor, "windows": windows_value}
    if value.get("content_sha256") != _canonical_json_hash(content):
        return None
    try:
        return _validated_qwen_text_windows(windows_value)
    except (TypeError, ValueError):
        return None


def save_qwen_text_checkpoint(
    package_root: Path,
    signature: CheckpointSignature,
    source_track: CraigTrack,
    windows: Iterable[QwenTextCheckpointWindow],
) -> Path:
    if signature.engine != "qwen3":
        raise ValueError("QWEN_TEXT_CHECKPOINT_SIGNATURE_INVALID")
    values = tuple(windows)
    if not values:
        raise ValueError("QWEN_TEXT_CHECKPOINT_WINDOWS_INVALID")
    windows_value = [asdict(window) for window in values]
    _validated_qwen_text_windows(windows_value)
    descriptor = _track_descriptor(source_track)
    content = {"track": descriptor, "windows": windows_value}
    payload = {
        "schema": QWEN_TEXT_CHECKPOINT_SCHEMA,
        "signature": signature.as_dict(),
        "signature_sha256": signature.digest(),
        "content_sha256": _canonical_json_hash(content),
        **content,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("CHECKPOINT_SIZE_LIMIT")

    path = _qwen_text_checkpoint_path(package_root, signature, source_track.number)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-evaluate after mkdir so a pre-existing symlinked checkpoint namespace
    # cannot turn the atomic write into an escape from the package root.
    path = _qwen_text_checkpoint_path(package_root, signature, source_track.number)
    temporary = path.with_name(path.name + f".{uuid4().hex}.partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path
    finally:
        temporary.unlink(missing_ok=True)


def save_track_checkpoint(
    package_root: Path,
    signature: CheckpointSignature,
    source_track: CraigTrack,
    transcript_track: TranscriptTrack,
) -> Path:
    transcript_track.validate()
    if not _matches_source(transcript_track, source_track):
        raise ValueError("CHECKPOINT_TRACK_SOURCE_MISMATCH")
    path = _checkpoint_path(package_root, signature, source_track.number)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.partial")
    content = {
        "track_source_sha256": source_track.sha256.lower(),
        "track": asdict(transcript_track),
    }
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "signature": signature.as_dict(),
        "signature_sha256": signature.digest(),
        "content_sha256": _canonical_json_hash(content),
        **content,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("CHECKPOINT_SIZE_LIMIT")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path
    finally:
        temporary.unlink(missing_ok=True)
