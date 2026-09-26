from __future__ import annotations

import re
from pathlib import Path

import tda_companion.worker_event_schema as schema_module
from tda_companion.worker_event_schema import (
    registered_worker_event_codes,
    sanitize_worker_event,
)


def test_known_activity_event_drops_private_extra_fields_without_losing_safe_metadata():
    event = sanitize_worker_event(
        {
            "code": "QWEN_WINDOW_TRANSCRIBED",
            "stage": "transcription",
            "track": 2,
            "total_tracks": 4,
            "speaker": "Álice",
            "window": 89,
            "text": "segredo reconhecido",
            "path": "C:/private/audio.flac",
        }
    )

    assert event.code == "QWEN_WINDOW_TRANSCRIBED"
    assert event.level == "info"
    assert event.data == {
        "stage": "transcription",
        "track": 2,
        "total_tracks": 4,
        "speaker": "Álice",
        "window": 89,
    }
    assert event.drift_reason == "unexpected_or_invalid_field"
    assert event.rejected_field_count == 2
    assert "segredo" not in repr(event)


def test_activity_counts_are_bounded_and_terminal_zero_is_valid():
    qwen = sanitize_worker_event(
        {
            "code": "QWEN_WINDOW_TRANSCRIBED",
            "stage": "transcription",
            "track": 1,
            "total_tracks": 1,
            "speaker": "Alice",
            "window": 2,
            "completed_window_count": 2,
        }
    )
    assert qwen.data["completed_window_count"] == 2

    whisper_terminal = sanitize_worker_event(
        {
            "code": "TRACK_COMPLETED",
            "stage": "transcription",
            "track": 2,
            "total_tracks": 2,
            "speaker": "Bob",
            "completed_segment_count": 0,
        }
    )
    assert whisper_terminal.code == "TRACK_COMPLETED"
    assert whisper_terminal.data["completed_segment_count"] == 0

    invalid = sanitize_worker_event(
        {
            "code": "TRACK_COMPLETED",
            "stage": "transcription",
            "track": 2,
            "total_tracks": 2,
            "speaker": "Bob",
            "completed_segment_count": -1,
        }
    )
    assert "completed_segment_count" not in invalid.data
    assert invalid.drift_reason == "unexpected_or_invalid_field"


def test_unknown_or_malformed_event_code_never_persists_raw_code_or_payload():
    for payload in (
        {"code": "PRIVATE_WORDS_FROM_TRANSCRIPT", "detail": "segredo"},
        {"code": "new-event", "text": "segredo"},
        {"code": 123, "path": "C:/private"},
    ):
        event = sanitize_worker_event(payload)
        assert event.code == "WORKER_EVENT_UNRECOGNIZED"
        assert event.data == {}
        assert event.level == "warning"
        assert event.drift_reason == "unknown_code"
        assert "segredo" not in repr(event)
        assert "PRIVATE_WORDS_FROM_TRANSCRIPT" not in repr(event)


def test_invalid_required_metadata_degrades_to_safe_schema_event():
    event = sanitize_worker_event(
        {
            "code": "QWEN_WINDOW_TRANSCRIBED",
            "stage": "transcription",
            "track": -1,
            "total_tracks": 4,
            "speaker": "Alice",
            "window": 2,
            "text": "secret",
        }
    )

    assert event.code == "WORKER_EVENT_SCHEMA_INVALID"
    assert event.level == "warning"
    assert event.data["reason"] == "invalid_required_field"
    assert event.data["rejected_field_count"] >= 2
    assert "text" not in event.data
    assert "secret" not in repr(event)


def test_alignment_failure_keeps_only_allowlisted_bounded_diagnostics():
    payload = {
        "code": "QWEN_ALIGNMENT_WINDOW_FAILED",
        "stage": "alignment",
        "track": 2,
        "window": 89,
        "failure_class": "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW",
        "window_start_seconds": 4752.0,
        "window_end_seconds": 4812.0,
        "ownership_left_seconds": 4755.0,
        "ownership_right_seconds": 4809.0,
        "first_window": False,
        "last_window": False,
        "runtime_version": "1.0.12",
        "worker_sha256": "a" * 64,
        "aligned_item": 1,
        "relative_start_seconds": -0.01,
        "relative_end_seconds": 130.16,
        "overflow_seconds": 70.16,
        "previous_end_seconds": 4752.0,
        "aligned_word_count": 411,
        "owned_word_count": 0,
        "text": "must never survive",
    }

    event = sanitize_worker_event(payload)

    assert event.code == "QWEN_ALIGNMENT_WINDOW_FAILED"
    assert event.level == "error"
    assert event.data["failure_class"] == payload["failure_class"]
    assert event.data["worker_sha256"] == "a" * 64
    assert event.data["relative_start_seconds"] == -0.01
    assert event.data["overflow_seconds"] == 70.16
    assert "text" not in event.data
    assert event.drift_reason == "unexpected_or_invalid_field"


def test_invalid_optional_numeric_metadata_is_dropped_without_invalidating_event():
    event = sanitize_worker_event(
        {
            "code": "QWEN_RUNTIME_FINGERPRINT_READY",
            "stage": "runtime_fingerprint",
            "runtime_version": "1.0.12",
            "worker_sha256": "b" * 64,
            "duration_ms": 12.5,
            "bogus": float("inf"),
        }
    )

    assert event.code == "QWEN_RUNTIME_FINGERPRINT_READY"
    assert event.data["duration_ms"] == 12.5
    assert "bogus" not in event.data
    assert event.drift_reason == "unexpected_or_invalid_field"


def test_mirror_reason_is_an_enum_not_an_arbitrary_short_string():
    valid = sanitize_worker_event(
        {
            "code": "COMPATIBILITY_MIRROR_WRITE_FAILED",
            "stage": "result_prepare",
            "reason": "hash_mismatch",
        }
    )
    assert valid.code == "COMPATIBILITY_MIRROR_WRITE_FAILED"
    assert valid.level == "warning"

    invalid = sanitize_worker_event(
        {
            "code": "COMPATIBILITY_MIRROR_WRITE_FAILED",
            "stage": "result_prepare",
            "reason": "recognized_words_here",
        }
    )
    assert invalid.code == "WORKER_EVENT_SCHEMA_INVALID"
    assert invalid.data["reason"] == "invalid_required_field"


def test_all_current_literal_worker_event_codes_are_registered():
    package_root = Path(schema_module.__file__).resolve().parent
    files = (
        package_root / "asr_whisper.py",
        package_root / "asr_qwen_strict.py",
        package_root / "asr_worker.py",
    )
    literal_codes: set[str] = set()
    for path in files:
        literal_codes.update(
            re.findall(r'["\']code["\']\s*:\s*["\']([A-Z0-9_]+)["\']', path.read_text(encoding="utf-8"))
        )

    # These literals belong to strict terminal/error messages, not type="event".
    literal_codes.difference_update(
        {
            "TRANSCRIPT_VALIDATION_FAILED",
            "WORKER_RUNTIME_BOOTSTRAP_FAILED",
            "WORKER_KIND_UNSUPPORTED",
            "WORKER_EXECUTION_FAILED",
        }
    )
    # Current producers also select these event codes dynamically.
    literal_codes.update(
        {
            "ASR_TEXT_CHECKPOINT_REUSED",
            "ASR_TEXT_CHECKPOINT_COMPAT_REUSED",
            "COMPATIBILITY_MIRROR_LEGACY_PRESERVED",
        }
    )

    assert literal_codes <= registered_worker_event_codes()


def test_registered_recovery_events_cover_the_current_qwen_v4_path():
    registered = registered_worker_event_codes()
    assert {
        "QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED",
        "QWEN_ALIGNMENT_WINDOW_RECOVERY_FAILED",
        "QWEN_ALIGNMENT_WINDOW_RECOVERED",
    } <= registered
