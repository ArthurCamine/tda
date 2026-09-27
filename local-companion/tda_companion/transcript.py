from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .engine_metrics import validate_engine_metrics

SCHEMA_VERSION = "tda_transcript_v1"
TIME_EPSILON = 0.05


class TranscriptValidationError(ValueError):
    pass


def _number(value: Any, field_name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TranscriptValidationError(f"{field_name}:NUMBER_REQUIRED")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise TranscriptValidationError(f"{field_name}:NUMBER_INVALID")
    return result


def _text(value: Any, field_name: str, *, maximum: int = 4096, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TranscriptValidationError(f"{field_name}:TEXT_REQUIRED")
    if "\0" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise TranscriptValidationError(f"{field_name}:TEXT_INVALID")
    result = value.strip()
    if not allow_empty and not result:
        raise TranscriptValidationError(f"{field_name}:TEXT_EMPTY")
    if len(result) > maximum:
        raise TranscriptValidationError(f"{field_name}:TEXT_TOO_LONG")
    return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start: float
    end: float
    confidence: float | None = None

    def validate(self, *, segment_start: float | None = None, segment_end: float | None = None) -> None:
        _text(self.text, "word.text", maximum=512)
        start = _number(self.start, "word.start")
        end = _number(self.end, "word.end")
        if end < start:
            raise TranscriptValidationError("word:END_BEFORE_START")
        if segment_start is not None and start + TIME_EPSILON < segment_start:
            raise TranscriptValidationError("word:BEFORE_SEGMENT")
        if segment_end is not None and end - TIME_EPSILON > segment_end:
            raise TranscriptValidationError("word:AFTER_SEGMENT")
        if self.confidence is not None:
            confidence = _number(self.confidence, "word.confidence")
            if confidence > 1.0:
                raise TranscriptValidationError("word:CONFIDENCE_RANGE")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TranscriptWord":
        if not isinstance(value, dict):
            raise TranscriptValidationError("word:OBJECT_REQUIRED")
        confidence = value.get("confidence")
        if confidence is None and value.get("probability") is not None:
            confidence = value.get("probability")
        text = value.get("text") if value.get("text") is not None else value.get("word")
        result = cls(
            text=_text(text, "word.text", maximum=512),
            start=_number(value.get("start"), "word.start"),
            end=_number(value.get("end"), "word.end"),
            confidence=None if confidence is None else _number(confidence, "word.confidence"),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class TranscriptSegment:
    id: str
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...] = ()
    confidence: float | None = None

    def validate(self) -> None:
        _text(self.id, "segment.id", maximum=256)
        _text(self.text, "segment.text", maximum=100_000)
        start = _number(self.start, "segment.start")
        end = _number(self.end, "segment.end")
        if end < start:
            raise TranscriptValidationError("segment:END_BEFORE_START")
        previous_end = start
        for word in self.words:
            word.validate(segment_start=start, segment_end=end)
            if word.start + TIME_EPSILON < previous_end:
                raise TranscriptValidationError("segment:WORDS_OUT_OF_ORDER")
            previous_end = max(previous_end, word.end)
        if self.confidence is not None:
            confidence = _number(self.confidence, "segment.confidence")
            if confidence > 1.0:
                raise TranscriptValidationError("segment:CONFIDENCE_RANGE")

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, fallback_id: str | None = None) -> "TranscriptSegment":
        if not isinstance(value, dict):
            raise TranscriptValidationError("segment:OBJECT_REQUIRED")
        words_value = value.get("words") or []
        if not isinstance(words_value, list):
            raise TranscriptValidationError("segment.words:ARRAY_REQUIRED")
        segment_id = value.get("id")
        if segment_id is None:
            segment_id = fallback_id
        confidence = value.get("confidence")
        if confidence is None and value.get("avg_logprob") is not None:
            confidence = None
        result = cls(
            id=_text(str(segment_id) if segment_id is not None else "", "segment.id", maximum=256),
            start=_number(value.get("start"), "segment.start"),
            end=_number(value.get("end"), "segment.end"),
            text=_text(value.get("text"), "segment.text", maximum=100_000),
            words=tuple(TranscriptWord.from_dict(item) for item in words_value),
            confidence=None if confidence is None else _number(confidence, "segment.confidence"),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class TranscriptTrack:
    number: int
    speaker: str
    source_filename: str
    source_sha256: str | None
    duration_seconds: float | None
    segments: tuple[TranscriptSegment, ...]
    timeline_offset_seconds: float = 0.0
    identity: dict[str, str | None] | None = None

    def validate(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number < 1:
            raise TranscriptValidationError("track.number:INTEGER_INVALID")
        _text(self.speaker, "track.speaker", maximum=160)
        _text(self.source_filename, "track.source_filename", maximum=512)
        if self.source_sha256 is not None:
            digest = _text(self.source_sha256, "track.source_sha256", maximum=64)
            if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
                raise TranscriptValidationError("track.source_sha256:INVALID")
        duration_seconds = (
            None
            if self.duration_seconds is None
            else _number(self.duration_seconds, "track.duration_seconds")
        )
        _number(self.timeline_offset_seconds, "track.timeline_offset_seconds")
        previous_start = -1.0
        seen_ids: set[str] = set()
        for segment in self.segments:
            segment.validate()
            if (
                duration_seconds is not None
                and segment.end - TIME_EPSILON > duration_seconds
            ):
                raise TranscriptValidationError("track.segment:AFTER_DURATION")
            if segment.id in seen_ids:
                raise TranscriptValidationError("track.segment:DUPLICATE_ID")
            seen_ids.add(segment.id)
            if segment.start + TIME_EPSILON < previous_start:
                raise TranscriptValidationError("track.segments:OUT_OF_ORDER")
            previous_start = segment.start
        if self.identity is not None:
            if not isinstance(self.identity, dict):
                raise TranscriptValidationError("track.identity:OBJECT_REQUIRED")
            for key in ("username", "discriminator", "discord_id"):
                value = self.identity.get(key)
                if value is not None and not isinstance(value, str):
                    raise TranscriptValidationError(f"track.identity.{key}:TEXT_REQUIRED")


@dataclass(frozen=True)
class TranscriptSegmentRef:
    track_number: int
    segment_id: str

    def validate(self) -> None:
        if isinstance(self.track_number, bool) or not isinstance(self.track_number, int) or self.track_number < 1:
            raise TranscriptValidationError("turn.segment.track_number:INTEGER_INVALID")
        _text(self.segment_id, "turn.segment.segment_id", maximum=256)


@dataclass(frozen=True)
class TranscriptTurn:
    id: str
    speaker: str
    start: float
    end: float
    text: str
    segments: tuple[TranscriptSegmentRef, ...]
    overlaps_other_speaker: bool = False

    def validate(self) -> None:
        _text(self.id, "turn.id", maximum=256)
        _text(self.speaker, "turn.speaker", maximum=160)
        _text(self.text, "turn.text", maximum=200_000)
        start = _number(self.start, "turn.start")
        end = _number(self.end, "turn.end")
        if end < start:
            raise TranscriptValidationError("turn:END_BEFORE_START")
        if not self.segments:
            raise TranscriptValidationError("turn.segments:EMPTY")
        for segment in self.segments:
            segment.validate()
        if not isinstance(self.overlaps_other_speaker, bool):
            raise TranscriptValidationError("turn.overlaps_other_speaker:BOOLEAN_REQUIRED")


@dataclass(frozen=True)
class TranscriptEngine:
    engine: str
    model: str
    profile: str
    device: str
    compute_type: str | None = None
    alignment: str = "native"
    model_revision: str | None = None

    def validate(self) -> None:
        _text(self.engine, "engine.engine", maximum=64)
        _text(self.model, "engine.model", maximum=256)
        _text(self.profile, "engine.profile", maximum=64)
        _text(self.device, "engine.device", maximum=32)
        if self.compute_type is not None:
            _text(self.compute_type, "engine.compute_type", maximum=64)
        _text(self.alignment, "engine.alignment", maximum=128)
        if self.model_revision is not None:
            _text(self.model_revision, "engine.model_revision", maximum=256)


@dataclass(frozen=True)
class TranscriptStats:
    audio_work_seconds: float
    session_duration_seconds: float
    processing_seconds: float
    word_count: int
    segment_count: int
    track_count: int
    rtf: float | None = None
    turn_count: int = 0
    deduplicated_segment_count: int = 0
    duration_semantics: str | None = "session_extent_v1"
    processing_metrics: dict[str, Any] | None = None

    def validate(self) -> None:
        try:
            validate_engine_metrics(self.processing_metrics)
        except ValueError as exc:
            raise TranscriptValidationError("stats.processing_metrics:INVALID") from exc
        if self.duration_semantics not in (None, "session_extent_v1"):
            raise TranscriptValidationError("stats.duration_semantics:UNSUPPORTED")
        _number(self.audio_work_seconds, "stats.audio_work_seconds")
        _number(self.session_duration_seconds, "stats.session_duration_seconds")
        _number(self.processing_seconds, "stats.processing_seconds")
        for name, value in (
            ("word_count", self.word_count),
            ("segment_count", self.segment_count),
            ("track_count", self.track_count),
            ("turn_count", self.turn_count),
            ("deduplicated_segment_count", self.deduplicated_segment_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TranscriptValidationError(f"stats.{name}:INTEGER_INVALID")
        if self.deduplicated_segment_count > self.segment_count:
            raise TranscriptValidationError("stats.deduplicated_segment_count:RANGE_INVALID")
        if self.rtf is not None:
            _number(self.rtf, "stats.rtf")
        if self.processing_metrics is not None:
            metrics = self.processing_metrics
            if metrics["total_tracks"] != self.track_count or not math.isclose(
                metrics["fresh_audio_work_seconds"] + metrics["reused_audio_work_seconds"],
                self.audio_work_seconds, abs_tol=0.001,
            ):
                raise TranscriptValidationError("stats.processing_metrics:WORK_MISMATCH")


@dataclass(frozen=True)
class TranscriptDocument:
    recording_id: str | None
    source_sha256: str
    language: str
    engine: TranscriptEngine
    tracks: tuple[TranscriptTrack, ...]
    stats: TranscriptStats
    turns: tuple[TranscriptTurn, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Any) -> "TranscriptDocument":
        """Parse the persisted schema without coercing or repairing source values.

        Worker adapters intentionally accept engine-specific aliases. Persisted
        transcripts do not: preserve their exact strings and validate all nested
        dataclasses and cross-field invariants before trusting any metadata.
        Missing optional fields use the v1 dataclass defaults.
        """
        def object_value(raw: Any, kind: str) -> dict[str, Any]:
            if not isinstance(raw, dict):
                raise TranscriptValidationError(f"{kind}:OBJECT_REQUIRED")
            return dict(raw)

        def array(raw: Any, kind: str) -> list[Any]:
            if not isinstance(raw, list):
                raise TranscriptValidationError(f"{kind}:ARRAY_REQUIRED")
            return raw

        try:
            data = object_value(value, "transcript")
            tracks = []
            for raw_track in array(data.get("tracks"), "transcript.tracks"):
                track = object_value(raw_track, "track")
                segments = []
                for raw_segment in array(track.get("segments"), "track.segments"):
                    segment = object_value(raw_segment, "segment")
                    segment["words"] = tuple(
                        TranscriptWord(**object_value(word, "word"))
                        for word in array(segment.get("words", []), "segment.words")
                    )
                    segments.append(TranscriptSegment(**segment))
                track["segments"] = tuple(segments)
                tracks.append(TranscriptTrack(**track))
            turns = []
            for raw_turn in array(data.get("turns", []), "transcript.turns"):
                turn = object_value(raw_turn, "turn")
                turn["segments"] = tuple(
                    TranscriptSegmentRef(**object_value(ref, "turn.segment"))
                    for ref in array(turn.get("segments"), "turn.segments")
                )
                turns.append(TranscriptTurn(**turn))
            # Required identity fields must not be manufactured by defaults.
            if "created_at" not in data or "schema_version" not in data:
                raise TranscriptValidationError("transcript:IDENTITY_REQUIRED")
            stats = object_value(data.get("stats"), "stats")
            # Historical bytes retain their recorded metrics; absence is not a
            # claim that the corrected timeline semantics were used.
            stats.setdefault("duration_semantics", None)
            data.update(
                engine=TranscriptEngine(**object_value(data.get("engine"), "engine")),
                stats=TranscriptStats(**stats),
                tracks=tuple(tracks),
                turns=tuple(turns),
                warnings=tuple(array(data.get("warnings", []), "transcript.warnings")),
            )
            document = cls(**data)
            document.validate()
            return document
        except (TypeError, KeyError, OverflowError) as exc:
            raise TranscriptValidationError("transcript:SCHEMA_INVALID") from exc

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise TranscriptValidationError("transcript:SCHEMA_UNSUPPORTED")
        if self.recording_id is not None:
            _text(self.recording_id, "transcript.recording_id", maximum=256)
        digest = _text(self.source_sha256, "transcript.source_sha256", maximum=64)
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise TranscriptValidationError("transcript.source_sha256:INVALID")
        _text(self.language, "transcript.language", maximum=32)
        _text(self.created_at, "transcript.created_at", maximum=128)
        try:
            if datetime.fromisoformat(self.created_at.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("timezone required")
        except ValueError as exc:
            raise TranscriptValidationError("transcript.created_at:INVALID") from exc
        self.engine.validate()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.engine.profile):
            raise TranscriptValidationError("engine.profile:INVALID")
        self.stats.validate()

        seen_tracks: set[int] = set()
        segment_index: dict[tuple[int, str], tuple[str, float, float]] = {}
        for track in self.tracks:
            track.validate()
            if track.number in seen_tracks:
                raise TranscriptValidationError("transcript.track:DUPLICATE_NUMBER")
            seen_tracks.add(track.number)
            for segment in track.segments:
                key = (track.number, segment.id)
                segment_index[key] = (
                    track.speaker,
                    float(segment.start) + float(track.timeline_offset_seconds),
                    float(segment.end) + float(track.timeline_offset_seconds),
                )

        if self.stats.track_count != len(self.tracks):
            raise TranscriptValidationError("transcript.stats:TRACK_COUNT_MISMATCH")
        segment_count = sum(len(track.segments) for track in self.tracks)
        word_count = sum(len(segment.words) for track in self.tracks for segment in track.segments)
        if self.stats.segment_count != segment_count:
            raise TranscriptValidationError("transcript.stats:SEGMENT_COUNT_MISMATCH")
        if self.stats.word_count != word_count:
            raise TranscriptValidationError("transcript.stats:WORD_COUNT_MISMATCH")
        if self.stats.turn_count != len(self.turns):
            raise TranscriptValidationError("transcript.stats:TURN_COUNT_MISMATCH")
        metrics = duration_metrics((track.timeline_offset_seconds, track.duration_seconds)
                                   for track in self.tracks)
        if self.stats.duration_semantics == "session_extent_v1" and metrics is not None:
            audio_work, session_extent = metrics
            for name, actual, expected in (
                ("AUDIO_WORK", self.stats.audio_work_seconds, audio_work),
                ("SESSION_DURATION", self.stats.session_duration_seconds, session_extent),
            ):
                if abs(actual - expected) > 0.001:
                    raise TranscriptValidationError(f"transcript.stats:{name}_MISMATCH")

        seen_turn_ids: set[str] = set()
        seen_turn_refs: set[tuple[int, str]] = set()
        previous_turn_start = -1.0
        for turn in self.turns:
            turn.validate()
            if turn.id in seen_turn_ids:
                raise TranscriptValidationError("transcript.turn:DUPLICATE_ID")
            seen_turn_ids.add(turn.id)
            if turn.start + TIME_EPSILON < previous_turn_start:
                raise TranscriptValidationError("transcript.turns:OUT_OF_ORDER")
            previous_turn_start = turn.start

            starts: list[float] = []
            ends: list[float] = []
            for reference in turn.segments:
                key = (reference.track_number, reference.segment_id)
                if key in seen_turn_refs:
                    raise TranscriptValidationError("transcript.turn.segment:DUPLICATE_REFERENCE")
                seen_turn_refs.add(key)
                indexed = segment_index.get(key)
                if indexed is None:
                    raise TranscriptValidationError("transcript.turn.segment:REFERENCE_MISSING")
                speaker, start, end = indexed
                if speaker != turn.speaker:
                    raise TranscriptValidationError("transcript.turn.segment:SPEAKER_MISMATCH")
                starts.append(start)
                ends.append(end)
            expected_start = min(starts)
            expected_end = max(ends)
            if abs(float(turn.start) - expected_start) > TIME_EPSILON:
                raise TranscriptValidationError("transcript.turn:START_MISMATCH")
            if abs(float(turn.end) - expected_end) > TIME_EPSILON:
                raise TranscriptValidationError("transcript.turn:END_MISMATCH")

        for warning in self.warnings:
            _text(warning, "transcript.warning", maximum=1024)

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def write_atomic(self, path: Path) -> None:
        from .atomic_storage import atomic_write
        payload = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        atomic_write(path, payload.encode("utf-8"))


def duration_metrics(tracks: Iterable[tuple[float, float | None]]) -> tuple[float, float] | None:
    """Physical workload and extent from session origin; no text-coverage proxy."""
    values = tuple(tracks)
    if not values or any(duration is None for _, duration in values):
        return None
    for offset, duration in values:
        _number(offset, "track.timeline_offset_seconds")
        _number(duration, "track.duration_seconds")
    return (round(sum(duration for _, duration in values), 3),
            round(max(offset + duration for offset, duration in values), 3))


def stats_for_tracks(
    tracks: Iterable[TranscriptTrack],
    *,
    processing_seconds: float,
    turn_count: int = 0,
    deduplicated_segment_count: int = 0,
    processing_metrics: dict[str, Any] | None = None,
) -> TranscriptStats:
    values = tuple(tracks)
    durations = [float(track.duration_seconds or 0.0) for track in values]
    audio_work = sum(durations)
    metrics = duration_metrics((track.timeline_offset_seconds, track.duration_seconds) for track in values)
    segment_count = sum(len(track.segments) for track in values)
    word_count = sum(len(segment.words) for track in values for segment in track.segments)
    elapsed = _number(processing_seconds, "stats.processing_seconds")
    return TranscriptStats(
        audio_work_seconds=round(audio_work, 3),
        session_duration_seconds=metrics[1] if metrics else round(max(durations, default=0.0), 3),
        processing_seconds=round(elapsed, 3),
        word_count=word_count,
        segment_count=segment_count,
        track_count=len(values),
        rtf=round(elapsed / audio_work, 6) if audio_work > 0 else None,
        turn_count=turn_count,
        deduplicated_segment_count=deduplicated_segment_count,
        duration_semantics="session_extent_v1" if metrics else None,
        processing_metrics=processing_metrics,
    )
