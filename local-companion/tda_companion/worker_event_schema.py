from __future__ import annotations

from .execution_device import gpu_uuid, pci_bus_id

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

Scalar = str | int | float | bool | None

_GENERIC_UNKNOWN_CODE = "WORKER_EVENT_UNRECOGNIZED"
_GENERIC_INVALID_CODE = "WORKER_EVENT_SCHEMA_INVALID"
_TOKEN = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")
_STAGE = re.compile(r"^[a-z0-9_]{1,64}$")
_UPPER_CODE = re.compile(r"^[A-Z0-9_]{1,96}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REASON = frozenset({"hash_mismatch", "write_failed", "legacy_preserved"})
_MAX_COUNTER = 1_000_000_000
_MAX_BYTES = (1 << 53) - 1
_MAX_SECONDS = 7 * 24 * 60 * 60
_MAX_DURATION_MS = _MAX_SECONDS * 1000


@dataclass(frozen=True)
class EventSchema:
    allowed: frozenset[str]
    required: frozenset[str] = frozenset()
    level: str = "info"


@dataclass(frozen=True)
class SanitizedWorkerEvent:
    code: str
    data: dict[str, Scalar]
    level: str
    drift_reason: str | None = None
    rejected_field_count: int = 0


def _schema(
    *allowed: str,
    required: tuple[str, ...] = (),
    level: str = "info",
) -> EventSchema:
    return EventSchema(
        allowed=frozenset(allowed),
        required=frozenset(required),
        level=level,
    )


_TRACK = ("stage", "track", "total_tracks", "speaker")
_CHECKPOINT = ("stage", "track", "total_tracks", "speaker")
_ALIGNMENT_DIAGNOSTICS = (
    "aligned_item",
    "relative_start_seconds",
    "relative_end_seconds",
    "overflow_seconds",
    "previous_end_seconds",
    "aligned_word_count",
    "owned_word_count",
)

EVENT_SCHEMAS: dict[str, EventSchema] = {
    "ASR_EXECUTION_DEVICE": _schema("stage", "device", "kind", "logical_index", "physical_uuid", "pci_bus_id", required=("stage", "device", "kind")),
    "WHISPER_RUNTIME_IMPORT_STARTED": _schema(
        "stage", "preloaded", required=("stage", "preloaded")
    ),
    "WHISPER_RUNTIME_IMPORT_READY": _schema(
        "stage", "preloaded", "duration_ms",
        required=("stage", "preloaded", "duration_ms"),
    ),
    "WHISPER_MODEL_CONSTRUCT_STARTED": _schema(
        "stage", "device", "compute_type",
        required=("stage", "device", "compute_type"),
    ),
    "WHISPER_MODEL_CONSTRUCT_READY": _schema(
        "stage", "device", "compute_type", "duration_ms",
        required=("stage", "device", "compute_type", "duration_ms"),
    ),
    "WHISPER_MODEL_CONSTRUCT_FAILED": _schema(
        "stage", "device", "compute_type", "memory_error", "duration_ms",
        required=("stage", "device", "compute_type", "memory_error", "duration_ms"),
    ),
    "WHISPER_MODEL_FALLBACK_STARTED": _schema(
        "stage", "device", "compute_type",
        required=("stage", "device", "compute_type"),
    ),
    "WHISPER_MODEL_FALLBACK_READY": _schema(
        "stage", "device", "compute_type", "duration_ms",
        required=("stage", "device", "compute_type", "duration_ms"),
    ),
    "WHISPER_MODEL_FALLBACK_FAILED": _schema(
        "stage", "device", "compute_type", "duration_ms",
        required=("stage", "device", "compute_type", "duration_ms"),
    ),
    "MODEL_DOWNLOAD_PROGRESS": _schema(
        "stage", "profile", "downloaded_bytes", "total_bytes",
        required=("stage", "profile", "downloaded_bytes"),
    ),
    "ASR_CHECKPOINT_FAST_PATH": _schema(
        "stage", "total_tracks", "compute_type",
        required=("stage", "total_tracks", "compute_type"),
    ),
    "ASR_CHECKPOINT_REUSED": _schema(
        *_CHECKPOINT, required=("stage", "track")
    ),
    "ASR_CHECKPOINT_SAVED": _schema(
        *_CHECKPOINT, required=("track",)
    ),
    "ASR_CHECKPOINT_WRITE_SKIPPED": _schema(
        *_CHECKPOINT, required=("track",), level="warning"
    ),
    "TRACK_STARTED": _schema(
        *_TRACK, required=("stage", "track", "total_tracks", "speaker")
    ),
    "TRACK_COMPLETED": _schema(
        *_TRACK, "completed_window_count", "completed_segment_count",
        required=("stage", "track", "total_tracks", "speaker"),
    ),
    "WHISPER_SEGMENT_TRANSCRIBED": _schema(
        *_TRACK, "segment", "completed_segment_count",
        required=("stage", "track", "total_tracks", "speaker", "segment"),
    ),
    "QWEN_RUNTIME_FINGERPRINT_READY": _schema(
        "stage", "runtime_version", "worker_sha256", "duration_ms",
        required=("stage", "duration_ms"),
    ),
    "ASR_TEXT_CHECKPOINT_REUSED": _schema(
        *_TRACK, required=("stage", "track", "total_tracks", "speaker")
    ),
    "ASR_TEXT_CHECKPOINT_COMPAT_REUSED": _schema(
        *_TRACK, "source_runtime_version", "source_signature_sha256",
        required=("stage", "track", "total_tracks", "speaker"),
    ),
    "ASR_CHECKPOINT_SCAN_COMPLETED": _schema(
        "stage", "track_count", "aligned_reused", "text_reused",
        "text_compat_reused", "pending_asr", "duration_ms",
        required=(
            "stage", "track_count", "aligned_reused", "text_reused",
            "pending_asr", "duration_ms",
        ),
    ),
    "QWEN_WINDOW_TRANSCRIBED": _schema(
        *_TRACK, "window", "completed_window_count", "start_seconds", "end_seconds",
        required=("stage", "track", "total_tracks", "speaker", "window"),
    ),
    "ASR_TEXT_CHECKPOINT_SAVED": _schema(
        *_TRACK, required=("stage", "track")
    ),
    "ASR_TEXT_CHECKPOINT_WRITE_SKIPPED": _schema(
        *_TRACK, required=("stage", "track"), level="warning"
    ),
    "TRACK_ALIGNMENT_STARTED": _schema(
        *_TRACK, required=("stage", "track", "total_tracks", "speaker")
    ),
    "TRACK_ENERGY_STARTED": _schema(
        *_TRACK, required=("stage", "track", "total_tracks", "speaker")
    ),
    "QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED": _schema(
        "stage", "track", "window", "failure_class", "context_seconds",
        required=("stage", "track", "window", "failure_class", "context_seconds"),
    ),
    "QWEN_ALIGNMENT_WINDOW_RECOVERY_FAILED": _schema(
        "stage", "track", "window", "failure_class", "context_seconds",
        required=("stage", "track", "window", "failure_class", "context_seconds"),
        level="warning",
    ),
    "QWEN_ALIGNMENT_WINDOW_RECOVERED": _schema(
        "stage", "track", "window", "context_seconds",
        required=("stage", "track", "window", "context_seconds"),
    ),
    "QWEN_ALIGNMENT_WINDOW_FAILED": _schema(
        "stage", "track", "window", "failure_class",
        "window_start_seconds", "window_end_seconds",
        "ownership_left_seconds", "ownership_right_seconds",
        "first_window", "last_window", "runtime_version", "worker_sha256",
        *_ALIGNMENT_DIAGNOSTICS,
        required=("stage", "track", "window", "failure_class"),
        level="error",
    ),
    "QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED": _schema(
        "stage", "track", "window", "count",
        required=("stage", "track", "window", "count"),
    ),
    "SOURCE_VALIDATED": _schema(
        "stage", "track_count", required=("stage", "track_count")
    ),
    "INCOMPLETE_RUNS_CLEANED": _schema(
        "stage", "count", required=("stage", "count")
    ),
    "RUN_COMMIT_FENCE_WON": _schema(
        "stage", "attempt", required=("stage", "attempt")
    ),
    "COMPATIBILITY_MIRROR_WRITE_FAILED": _schema(
        "stage", "reason", required=("stage", "reason"), level="warning"
    ),
    "COMPATIBILITY_MIRROR_LEGACY_PRESERVED": _schema(
        "stage", "reason", required=("stage", "reason"), level="warning"
    ),
}


_POSITIVE_INT_FIELDS = frozenset(
    {
        "track", "total_tracks", "segment", "attempt",
        "track_count", "count",
    }
)
_NONNEGATIVE_INT_FIELDS = frozenset(
    {
        "window", "aligned_reused", "text_reused", "text_compat_reused",
        "pending_asr", "aligned_item", "aligned_word_count", "owned_word_count",
        "completed_window_count", "completed_segment_count",
    }
)
_BYTE_FIELDS = frozenset({"downloaded_bytes", "total_bytes"})
_BOOL_FIELDS = frozenset({"preloaded", "memory_error", "first_window", "last_window"})
_SECONDS_FIELDS = frozenset(
    {
        "context_seconds", "window_start_seconds", "window_end_seconds",
        "ownership_left_seconds", "ownership_right_seconds",
        "overflow_seconds", "previous_end_seconds",
        "start_seconds", "end_seconds",
    }
)
_SIGNED_SECONDS_FIELDS = frozenset({"relative_start_seconds", "relative_end_seconds"})
_TOKEN_FIELDS = frozenset({"profile", "device", "compute_type"})
_RUNTIME_FIELDS = frozenset({"runtime_version", "source_runtime_version"})
_HASH_FIELDS = frozenset({"worker_sha256", "source_signature_sha256"})


def _safe_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _sanitize_field(key: str, value: object) -> Scalar | None:
    if key == "physical_uuid":
        return gpu_uuid(value)
    if key == "pci_bus_id":
        return pci_bus_id(value)
    if key == "kind":
        return value if value in ("cpu", "cuda") else None
    if key == "logical_index":
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 100 else None
    if key == "stage":
        return value if isinstance(value, str) and _STAGE.fullmatch(value) else None
    if key == "speaker":
        return _safe_text(value, 160)
    if key == "failure_class":
        return value if isinstance(value, str) and _UPPER_CODE.fullmatch(value) else None
    if key == "reason":
        return value if isinstance(value, str) and value in _SAFE_REASON else None
    if key in _TOKEN_FIELDS:
        return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None
    if key in _RUNTIME_FIELDS:
        return value if isinstance(value, str) and _SEMVER.fullmatch(value) else None
    if key in _HASH_FIELDS:
        return value if isinstance(value, str) and _SHA256.fullmatch(value) else None
    if key in _BOOL_FIELDS:
        return value if isinstance(value, bool) else None
    if key in _POSITIVE_INT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 1 <= value <= _MAX_COUNTER else None
    if key in _NONNEGATIVE_INT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= _MAX_COUNTER else None
    if key in _BYTE_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= _MAX_BYTES else None
    if key == "duration_ms":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return value if math.isfinite(number) and 0 <= number <= _MAX_DURATION_MS else None
    if key in _SECONDS_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return value if math.isfinite(number) and 0 <= number <= _MAX_SECONDS else None
    if key in _SIGNED_SECONDS_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return value if math.isfinite(number) and -_MAX_SECONDS <= number <= _MAX_SECONDS else None
    return None


def sanitize_worker_event(payload: Mapping[str, Any]) -> SanitizedWorkerEvent:
    raw_code = payload.get("code")
    if not isinstance(raw_code, str) or raw_code not in EVENT_SCHEMAS:
        return SanitizedWorkerEvent(
            code=_GENERIC_UNKNOWN_CODE,
            data={},
            level="warning",
            drift_reason="unknown_code",
            rejected_field_count=max(len(payload) - 1, 0),
        )

    schema = EVENT_SCHEMAS[raw_code]
    clean: dict[str, Scalar] = {}
    rejected = 0
    invalid_required = False

    for key, value in payload.items():
        if key == "code":
            continue
        if key not in schema.allowed:
            rejected += 1
            continue
        sanitized = _sanitize_field(key, value)
        if sanitized is None:
            rejected += 1
            if key in schema.required:
                invalid_required = True
            continue
        clean[key] = sanitized

    missing = schema.required.difference(clean)
    if missing:
        invalid_required = True
        rejected += len(missing)

    if invalid_required:
        return SanitizedWorkerEvent(
            code=_GENERIC_INVALID_CODE,
            data={
                "reason": "invalid_required_field",
                "rejected_field_count": min(rejected, 1_000_000),
            },
            level="warning",
            drift_reason="invalid_required_field",
            rejected_field_count=min(rejected, 1_000_000),
        )

    return SanitizedWorkerEvent(
        code=raw_code,
        data=clean,
        level=schema.level,
        drift_reason="unexpected_or_invalid_field" if rejected else None,
        rejected_field_count=min(rejected, 1_000_000),
    )


def registered_worker_event_codes() -> frozenset[str]:
    return frozenset(EVENT_SCHEMAS)
