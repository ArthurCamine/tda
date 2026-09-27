from __future__ import annotations

import math
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .asr_checkpoints import (
    QwenTextCheckpointWindow,
    build_checkpoint_signature,
    load_qwen_text_checkpoint,
    load_track_checkpoint,
    save_qwen_text_checkpoint,
    save_track_checkpoint,
    verify_checkpoint_source_bytes,
)
from .asr_models import QWEN_FORCED_ALIGNER_MODEL_ID, get_profile
from .asr_qwen import (
    QWEN_MAX_NEW_TOKENS,
    QWEN_SAMPLE_RATE,
    QWEN_SEGMENT_GAP_SECONDS,
    QWEN_SEGMENT_MAX_SECONDS,
    QWEN_WINDOW_SECONDS,
    AlignerSession,
    AsrSession,
    AudioWindow,
    CancelCallback,
    EnergyReader,
    ProgressCallback,
    QwenRuntimeError,
    QwenWindowTranscript,
    _bounded_prompt,
    _default_aligner_session,
    _default_asr_session,
    _prepare_aligner,
    _prepare_model,
    _resolve_plan,
    _runtime_fingerprint,
    _safe_track_path,
    _segments_from_words,
    _validated_words,
    _window_energy_db,
)
from .asr_timeline import build_turns, deduplicate_cross_track_segments, flatten_tracks
from .craig import CraigPackage, CraigPackageError, CraigTrack
from .qwen_acceptance import QwenPlan
from .qwen_checkpoint_compat import load_compatible_qwen_text_checkpoint
from .transcript import TranscriptDocument, TranscriptEngine, TranscriptSegment, TranscriptTrack, TranscriptWord, stats_for_tracks

QWEN_WINDOW_OVERLAP_SECONDS = 6.0
QWEN_WINDOW_STRIDE_SECONDS = QWEN_WINDOW_SECONDS - QWEN_WINDOW_OVERLAP_SECONDS
QWEN_ALIGNMENT_POLICY = "strict-overlap-v4"
QWEN_PREVIOUS_TEXT_ALIGNMENT_POLICY = "strict-overlap-v3"
QWEN_LEGACY_TEXT_ALIGNMENT_POLICY = "strict-overlap-v2"
_ALIGNMENT_FAILURE_CLASS = re.compile(r"^[A-Z0-9_]{1,96}$")
_RUNTIME_VERSION_FIELD = re.compile(r"(?:^|;)runtime=([0-9]+\.[0-9]+\.[0-9]+)(?:;|$)")
_RUNTIME_WORKER_SHA256_FIELD = re.compile(r"(?:^|;)worker_sha256=([0-9a-f]{64})(?:;|$)")
_ALIGNMENT_RUNTIME_PASSTHROUGH = frozenset(
    {
        "QWEN_CUDA_DRIVER_INCOMPATIBLE",
        "QWEN_ASR_GPU_MEMORY_EXHAUSTED",
        "QWEN_ASR_CUDA_FAILED",
        "QWEN_ASR_RUNTIME_API_FAILED",
    }
)
_ALIGNMENT_DIAGNOSTIC_KEYS = frozenset(
    {
        "aligned_item",
        "relative_start_seconds",
        "relative_end_seconds",
        "overflow_seconds",
        "previous_end_seconds",
        "aligned_word_count",
        "owned_word_count",
    }
)
def _runtime_identity_metadata(fingerprint: str) -> dict[str, str]:
    version = _RUNTIME_VERSION_FIELD.search(fingerprint)
    worker = _RUNTIME_WORKER_SHA256_FIELD.search(fingerprint)
    if version is None or worker is None:
        return {}
    return {
        "runtime_version": version.group(1),
        "worker_sha256": worker.group(1),
    }


def iter_audio_windows_overlap(
    path: Path,
    *,
    window_seconds: float = QWEN_WINDOW_SECONDS,
    overlap_seconds: float = QWEN_WINDOW_OVERLAP_SECONDS,
    sample_rate: int = QWEN_SAMPLE_RATE,
) -> Iterable[AudioWindow]:
    """Decode bounded overlapping windows without materializing the full track.

    A small overlap protects words crossing each bounded ASR window. Alignment
    later assigns each word to exactly one ownership interval, so overlap does not
    become duplicated transcript content.
    """
    if (
        window_seconds <= 0
        or window_seconds > 240
        or overlap_seconds <= 0
        or overlap_seconds >= window_seconds / 2
        or sample_rate != QWEN_SAMPLE_RATE
    ):
        raise QwenRuntimeError("QWEN_WINDOW_CONFIG_INVALID")
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise QwenRuntimeError("QWEN_RUNTIME_NOT_INSTALLED") from exc

    window_samples = int(round(window_seconds * sample_rate))
    overlap_samples = int(round(overlap_seconds * sample_rate))
    stride_samples = window_samples - overlap_samples
    pieces: list[Any] = []
    buffered = 0
    start_sample = 0
    index = 0

    def compact() -> Any:
        nonlocal pieces, buffered
        if not pieces:
            return np.empty((0,), dtype=np.float32)
        joined = np.concatenate(pieces).astype(np.float32, copy=False)
        pieces = [joined]
        buffered = int(joined.size)
        return joined

    def drain_full() -> list[AudioWindow]:
        nonlocal pieces, buffered, start_sample, index
        output: list[AudioWindow] = []
        while buffered >= window_samples:
            joined = compact()
            chunk = joined[:window_samples].copy()
            index += 1
            start = start_sample / sample_rate
            output.append(
                AudioWindow(index=index, start=start, end=start + chunk.size / sample_rate, audio=chunk)
            )
            remainder = joined[stride_samples:].copy()
            start_sample += stride_samples
            pieces = [remainder] if remainder.size else []
            buffered = int(remainder.size)
        return output

    try:
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is None:
                raise QwenRuntimeError("QWEN_AUDIO_STREAM_MISSING")
            resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
            for frame in container.decode(stream):
                for converted in resampler.resample(frame):
                    array = converted.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                    if array.size:
                        pieces.append(array.copy())
                        buffered += int(array.size)
                    yield from drain_full()
            for converted in resampler.resample(None):
                array = converted.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                if array.size:
                    pieces.append(array.copy())
                    buffered += int(array.size)
                yield from drain_full()
            if buffered:
                joined = compact()
                # A trailing buffer can contain only the overlap already emitted by
                # the previous full window. Do not transcribe that overlap twice.
                if index == 0 or buffered > overlap_samples:
                    index += 1
                    start = start_sample / sample_rate
                    yield AudioWindow(
                        index=index,
                        start=start,
                        end=start + joined.size / sample_rate,
                        audio=joined.copy(),
                    )
    except QwenRuntimeError:
        raise
    except Exception as exc:
        raise QwenRuntimeError("QWEN_AUDIO_DECODE_FAILED") from exc

    if index == 0:
        raise QwenRuntimeError("QWEN_AUDIO_EMPTY")


def _owned_words(
    words: list[TranscriptWord],
    window: AudioWindow,
    *,
    first: bool,
    last: bool,
    overlap_seconds: float = QWEN_WINDOW_OVERLAP_SECONDS,
) -> list[TranscriptWord]:
    half = overlap_seconds / 2.0
    left = window.start if first else window.start + half
    right = window.end if last else window.end - half
    return [
        word
        for word in words
        if left <= (word.start + word.end) / 2.0 < right or (last and math.isclose((word.start + word.end) / 2.0, right))
    ]


def _alignment_required(
    failure_class: str,
    **diagnostics: int | float | bool,
) -> QwenRuntimeError:
    error = QwenRuntimeError("QWEN_ALIGNMENT_REQUIRED")
    safe_failure_class = (
        failure_class
        if isinstance(failure_class, str)
        and _ALIGNMENT_FAILURE_CLASS.fullmatch(failure_class)
        else "QWEN_ALIGNMENT_REQUIRED"
    )
    error.alignment_failure_class = safe_failure_class
    error.alignment_diagnostics = diagnostics
    return error


def _alignment_timestamp_diagnostic(
    items: list[dict[str, Any]],
    window: AudioWindow,
) -> tuple[str, dict[str, int | float | bool]]:
    previous_end = window.start
    for item_index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        details: dict[str, int | float | bool] = {"aligned_item": item_index}
        try:
            relative_start = float(item.get("start_time"))
            relative_end = float(item.get("end_time"))
        except (TypeError, ValueError):
            return "QWEN_ALIGNMENT_TIMESTAMP_PARSE_INVALID", details
        if math.isfinite(relative_start):
            details["relative_start_seconds"] = round(relative_start, 3)
        if math.isfinite(relative_end):
            details["relative_end_seconds"] = round(relative_end, 3)
        if not math.isfinite(relative_start) or not math.isfinite(relative_end):
            return "QWEN_ALIGNMENT_TIMESTAMP_NONFINITE", details
        start = window.start + relative_start
        end = window.start + relative_end
        if relative_start < -0.05:
            return "QWEN_ALIGNMENT_TIMESTAMP_NEGATIVE_START", details
        if end < start:
            return "QWEN_ALIGNMENT_TIMESTAMP_REVERSED", details
        if start > window.end + 0.25:
            return "QWEN_ALIGNMENT_TIMESTAMP_OUTSIDE_WINDOW", details
        if end > window.end + 0.25:
            details["overflow_seconds"] = round(end - window.end, 3)
            return "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW", details
        if start + 0.05 < previous_end:
            details["previous_end_seconds"] = round(previous_end, 3)
            return "QWEN_ALIGNMENT_TIMESTAMP_NON_MONOTONIC", details
        previous_end = max(previous_end, end)
    return "QWEN_ALIGNMENT_TIMESTAMPS_INVALID", {}


def _safe_neighbor_owned_trailing_overflow(
    item: dict[str, Any],
    window: AudioWindow,
    *,
    last: bool,
) -> bool:
    if last or not str(item.get("text") or "").strip():
        return False
    try:
        relative_start = float(item.get("start_time"))
        relative_end = float(item.get("end_time"))
    except (TypeError, ValueError):
        return False
    if (
        not math.isfinite(relative_start)
        or not math.isfinite(relative_end)
        or relative_end <= relative_start
    ):
        return False
    window_duration = window.end - window.start
    if (
        relative_end <= window_duration + 0.25
        or relative_end > window_duration + QWEN_WINDOW_OVERLAP_SECONDS + 0.25
    ):
        return False
    # The canonical ownership rule uses the word midpoint. Permit pre-validation
    # filtering only when the extrapolated word begins inside the decoded trailing
    # overlap and its midpoint belongs to the next window. This is narrower than
    # dropping arbitrary overflow and keeps owned-region anomalies fail-closed.
    overlap_left = window.end - QWEN_WINDOW_OVERLAP_SECONDS
    ownership_right = window.end - QWEN_WINDOW_OVERLAP_SECONDS / 2.0
    absolute_start = window.start + relative_start
    absolute_end = window.start + relative_end
    midpoint = (absolute_start + absolute_end) / 2.0
    return (
        absolute_start >= overlap_left - 0.05
        and absolute_start <= window.end + 0.25
        and midpoint >= ownership_right
    )


def _right_context_alignment_window(
    window: AudioWindow,
    next_window: AudioWindow,
    *,
    overlap_seconds: float = QWEN_WINDOW_OVERLAP_SECONDS,
    sample_rate: int = QWEN_SAMPLE_RATE,
) -> AudioWindow | None:
    """Append bounded new right-side audio for one alignment-only retry.

    The next ASR window already contains the trailing overlap from the current
    window. Recovery skips that duplicated prefix and appends at most one
    overlap-width of genuinely new audio. Ownership is still evaluated against
    the original window; this object only gives the aligner real context.
    """

    if (
        next_window.index != window.index + 1
        or not math.isclose(
            next_window.start,
            window.end - overlap_seconds,
            abs_tol=0.001,
        )
        or sample_rate != QWEN_SAMPLE_RATE
    ):
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    try:
        current = np.asarray(window.audio, dtype=np.float32).reshape(-1)
        following = np.asarray(next_window.audio, dtype=np.float32).reshape(-1)
    except Exception:
        return None
    if current.size <= 0 or following.size <= 0:
        return None

    duplicated_seconds = max(window.end - next_window.start, 0.0)
    duplicated_samples = int(round(duplicated_seconds * sample_rate))
    max_context_samples = int(round(overlap_seconds * sample_rate))
    if duplicated_samples < 0 or duplicated_samples >= int(following.size):
        return None
    suffix = following[
        duplicated_samples : duplicated_samples + max_context_samples
    ]
    if suffix.size <= 0:
        return None

    audio = np.concatenate((current, suffix)).astype(np.float32, copy=False)
    context_seconds = float(suffix.size) / sample_rate
    return AudioWindow(
        index=window.index,
        start=window.start,
        end=window.end + context_seconds,
        audio=audio,
    )


def _strict_alignment_segments(
    track_number: int,
    window: AudioWindow,
    pending: QwenWindowTranscript,
    aligner: AlignerSession,
    *,
    first: bool,
    last: bool,
    alignment_window: AudioWindow | None = None,
) -> tuple[tuple[TranscriptSegment, ...], int]:
    # Silence is a valid ASR outcome. Forced alignment is mandatory for actual
    # transcript text, but an empty/whitespace-only window has nothing to align
    # and must contribute zero segments instead of failing the whole session.
    if not pending.text.strip():
        return (), 0
    aligned: list[dict[str, Any]] = []
    validation_window = alignment_window or window
    try:
        aligned = aligner.align(
            validation_window.audio,
            pending.text,
            pending.language,
        )
        ignored_trailing_overflow = 0
        if alignment_window is None and not last:
            filtered: list[dict[str, Any]] = []
            for item in aligned:
                if isinstance(item, dict) and _safe_neighbor_owned_trailing_overflow(
                    item,
                    window,
                    last=last,
                ):
                    ignored_trailing_overflow += 1
                    continue
                filtered.append(item)
            aligned = filtered
        if not aligned and ignored_trailing_overflow:
            return (), ignored_trailing_overflow
        words = _validated_words(aligned, validation_window)
    except QwenRuntimeError as exc:
        if exc.code in _ALIGNMENT_RUNTIME_PASSTHROUGH:
            # Resource/runtime failures are not transcript-integrity failures.
            # Preserve the actionable terminal code while the caller still adds
            # track/window context through the sanitized diagnostic event.
            raise
        failure_class = exc.code
        diagnostics: dict[str, int | float | bool] = {}
        if exc.code == "QWEN_ALIGNMENT_TIMESTAMPS_INVALID":
            failure_class, diagnostics = _alignment_timestamp_diagnostic(
                aligned,
                validation_window,
            )
        raise _alignment_required(failure_class, **diagnostics) from exc
    owned = _owned_words(words, window, first=first, last=last)
    if not owned:
        # It is valid for an overlap-only window to contribute no owned words only
        # when the aligner returned words entirely in the neighbor-owned overlap.
        if words and (not first or not last):
            return (), ignored_trailing_overflow
        raise _alignment_required(
            "QWEN_ALIGNMENT_NO_OWNED_WORDS",
            aligned_word_count=len(words),
        )
    segments = _segments_from_words(track_number, window, owned)
    if not segments:
        raise _alignment_required(
            "QWEN_ALIGNMENT_NO_SEGMENTS",
            owned_word_count=len(owned),
        )
    return segments, ignored_trailing_overflow


def transcribe_craig_package_qwen_strict(
    package: CraigPackage,
    package_root: Path,
    models_root: Path,
    *,
    profile_id: str,
    glossary: str = "",
    context: str = "",
    report: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    checkpoints: bool = True,
    plan_resolver=_resolve_plan,
    model_prepare=_prepare_model,
    aligner_prepare=_prepare_aligner,
    asr_session_factory: Any = _default_asr_session,
    aligner_session_factory: Any = _default_aligner_session,
    window_reader=iter_audio_windows_overlap,
    energy_reader: EnergyReader = _window_energy_db,
    right_context_builder=_right_context_alignment_window,
) -> TranscriptDocument:
    profile = get_profile(profile_id)
    if profile.engine != "qwen3":
        raise QwenRuntimeError("QWEN_PROFILE_REQUIRED")
    report = report or (lambda _: None)
    is_cancelled = is_cancelled or (lambda: False)
    if is_cancelled():
        raise QwenRuntimeError("ASR_CANCELLED")
    report(
        {
            "type": "stage",
            "stage": "runtime_validation",
            "profile": profile.id,
        }
    )
    plan: QwenPlan = plan_resolver(profile.id)
    prompt = _bounded_prompt(context, glossary)
    recipe = {
        "window_seconds": QWEN_WINDOW_SECONDS,
        "window_overlap_seconds": QWEN_WINDOW_OVERLAP_SECONDS,
        "sample_rate": QWEN_SAMPLE_RATE,
        "max_new_tokens": QWEN_MAX_NEW_TOKENS,
        "segment_gap_seconds": QWEN_SEGMENT_GAP_SECONDS,
        "segment_max_seconds": QWEN_SEGMENT_MAX_SECONDS,
        "device": plan.device,
        "dtype": plan.dtype,
        "alignment": QWEN_FORCED_ALIGNER_MODEL_ID,
        "alignment_policy": QWEN_ALIGNMENT_POLICY,
    }
    compatible_text_recipes = (
        {
            **recipe,
            "alignment_policy": QWEN_PREVIOUS_TEXT_ALIGNMENT_POLICY,
        },
        {
            **recipe,
            "alignment_policy": QWEN_LEGACY_TEXT_ALIGNMENT_POLICY,
        },
    )
    report({"type": "stage", "stage": "runtime_fingerprint", "profile": profile.id})
    fingerprint_started = time.monotonic()
    runtime_fingerprint = _runtime_fingerprint()
    report(
        {
            "type": "event",
            "code": "QWEN_RUNTIME_FINGERPRINT_READY",
            "stage": "runtime_fingerprint",
            **_runtime_identity_metadata(runtime_fingerprint),
            "duration_ms": round((time.monotonic() - fingerprint_started) * 1000.0, 2),
        }
    )
    report({"type": "stage", "stage": "checkpoint_scan", "profile": profile.id})
    checkpoint_scan_started = time.monotonic()
    normalized_context = " ".join(context.split())[:2000].strip()
    normalized_glossary = " ".join(glossary.split())[:2000].strip()
    signature = build_checkpoint_signature(
        package,
        profile,
        recipe=recipe,
        context=normalized_context,
        glossary=normalized_glossary,
        runtime_fingerprint=runtime_fingerprint,
    )
    compatible_text_signatures = tuple(
        build_checkpoint_signature(
            package,
            profile,
            recipe=compatible_recipe,
            context=normalized_context,
            glossary=normalized_glossary,
            runtime_fingerprint=runtime_fingerprint,
        )
        for compatible_recipe in compatible_text_recipes
    )

    cached_tracks: dict[int, TranscriptTrack] = {}
    pending_tracks = []
    total_tracks = len(package.tracks)
    completed_tracks = 0
    for track in package.tracks:
        if is_cancelled():
            raise QwenRuntimeError("ASR_CANCELLED")
        _safe_track_path(package_root, track)
        cached = load_track_checkpoint(package_root, signature, track) if checkpoints else None
        if cached is not None and not any(segment.id.endswith("-fallback") for segment in cached.segments):
            verify_checkpoint_source_bytes(_safe_track_path(package_root, track), track)
            cached_tracks[track.number] = cached
            report(
                {
                    "type": "event",
                    "code": "ASR_CHECKPOINT_REUSED",
                    "stage": "source_validation",
                    "track": track.number,
                    "total_tracks": total_tracks,
                    "speaker": track.speaker,
                }
            )
            completed_tracks += 1
            report(
                {
                    "type": "progress",
                    "completed": completed_tracks,
                    "total": total_tracks,
                    "unit": "tracks",
                    "stage": "source_validation",
                }
            )
        else:
            pending_tracks.append(track)

    started = time.monotonic()
    pending_text: dict[int, list[QwenWindowTranscript]] = {}
    fresh_window_counts: dict[int, int] = {}
    asr_tracks = []
    text_checkpoint_reused = 0
    text_checkpoint_compat_reused = 0
    compatibility_warnings: set[str] = set()
    for track in pending_tracks:
        if is_cancelled():
            raise QwenRuntimeError("ASR_CANCELLED")
        cached_text = (
            load_qwen_text_checkpoint(package_root, signature, track)
            if checkpoints
            else None
        )
        compatibility_reuse = False
        compatibility_source_runtime_version: str | None = None
        compatibility_source_signature_sha256: str | None = None
        if cached_text is None and checkpoints:
            compatible = load_compatible_qwen_text_checkpoint(
                package_root,
                signature,
                track,
                templates=compatible_text_signatures,
            )
            if compatible is not None:
                cached_text = compatible.windows
                compatibility_reuse = True
                compatibility_source_runtime_version = compatible.source_runtime_version
                compatibility_source_signature_sha256 = compatible.source_signature_sha256
                compatibility_warnings.add(
                    "qwen_text_checkpoint_compat_reused:"
                    f"runtime={compatible.source_runtime_version}"
                )
        if cached_text is None:
            asr_tracks.append(track)
            continue
        # Reusing ASR text is much cheaper than retranscription, so pay one
        # cryptographic read only on the reuse path. This proves the staged FLAC
        # still matches the manifest even if filesystem metadata was preserved.
        verify_checkpoint_source_bytes(_safe_track_path(package_root, track), track)
        pending_text[track.number] = [
            QwenWindowTranscript(
                index=item.index,
                start=item.start,
                end=item.end,
                text=item.text,
                language=item.language,
            )
            for item in cached_text
        ]
        text_checkpoint_reused += 1
        if compatibility_reuse:
            text_checkpoint_compat_reused += 1
        report(
            {
                "type": "event",
                "code": (
                    "ASR_TEXT_CHECKPOINT_COMPAT_REUSED"
                    if compatibility_reuse
                    else "ASR_TEXT_CHECKPOINT_REUSED"
                ),
                "stage": "source_validation",
                "track": track.number,
                "total_tracks": total_tracks,
                "speaker": track.speaker,
                **(
                    {
                        "source_runtime_version": compatibility_source_runtime_version,
                        "source_signature_sha256": compatibility_source_signature_sha256,
                    }
                    if compatibility_reuse
                    and compatibility_source_runtime_version is not None
                    and compatibility_source_signature_sha256 is not None
                    else {}
                ),
            }
        )

    report(
        {
            "type": "event",
            "code": "ASR_CHECKPOINT_SCAN_COMPLETED",
            "stage": "checkpoint_scan",
            "track_count": total_tracks,
            "aligned_reused": len(cached_tracks),
            "text_reused": text_checkpoint_reused,
            **(
                {"text_compat_reused": text_checkpoint_compat_reused}
                if text_checkpoint_compat_reused
                else {}
            ),
            "pending_asr": len(asr_tracks),
            "duration_ms": round((time.monotonic() - checkpoint_scan_started) * 1000.0, 2),
        }
    )

    if asr_tracks:
        report({"type": "stage", "stage": "model_prepare", "profile": profile.id})
        model_root = model_prepare(models_root.resolve(), profile)
        report({"type": "stage", "stage": "model_load", "profile": profile.id})
        asr_session: AsrSession = asr_session_factory(model_root, plan)
        report({"type": "stage", "stage": "transcription", "profile": profile.id})
        try:
            for track in asr_tracks:
                source = _safe_track_path(package_root, track)
                report(
                    {
                        "type": "event",
                        "code": "TRACK_STARTED",
                        "stage": "transcription",
                        "track": track.number,
                        "total_tracks": total_tracks,
                        "speaker": track.speaker,
                    }
                )
                values: list[QwenWindowTranscript] = []
                for window in window_reader(source):
                    if is_cancelled():
                        raise QwenRuntimeError("ASR_CANCELLED")
                    text, language = asr_session.transcribe(window.audio, prompt=prompt)
                    values.append(
                        QwenWindowTranscript(
                            index=window.index,
                            start=window.start,
                            end=window.end,
                            text=text.strip(),
                            language=language or "Portuguese",
                        )
                    )
                    report(
                        {
                            "type": "event",
                            "code": "QWEN_WINDOW_TRANSCRIBED",
                            "stage": "transcription",
                            "track": track.number,
                            "total_tracks": total_tracks,
                            "speaker": track.speaker,
                            "window": window.index,
                            "completed_window_count": len(values),
                            "start_seconds": window.start,
                            "end_seconds": window.end,
                        }
                    )
                if not values:
                    raise QwenRuntimeError("QWEN_AUDIO_EMPTY")
                fresh_window_counts[track.number] = len(values)
                pending_text[track.number] = values
                if checkpoints:
                    try:
                        save_qwen_text_checkpoint(
                            package_root,
                            signature,
                            track,
                            (
                                QwenTextCheckpointWindow(
                                    index=item.index,
                                    start=item.start,
                                    end=item.end,
                                    text=item.text,
                                    language=item.language,
                                )
                                for item in values
                            ),
                        )
                        report(
                            {
                                "type": "event",
                                "code": "ASR_TEXT_CHECKPOINT_SAVED",
                                "stage": "transcription",
                                "track": track.number,
                                "total_tracks": total_tracks,
                                "speaker": track.speaker,
                            }
                        )
                    except (OSError, ValueError):
                        report(
                            {
                                "type": "event",
                                "code": "ASR_TEXT_CHECKPOINT_WRITE_SKIPPED",
                                "stage": "transcription",
                                "track": track.number,
                                "total_tracks": total_tracks,
                                "speaker": track.speaker,
                            }
                        )
        finally:
            asr_session.close()

    new_tracks: dict[int, TranscriptTrack] = {}
    energy_by_segment: dict[tuple[int, str], float] = {}
    if pending_tracks:
        report({"type": "stage", "stage": "alignment", "profile": profile.id})
        aligner_root = aligner_prepare(models_root.resolve())
        aligner: AlignerSession = aligner_session_factory(aligner_root, plan)
        try:
            for track in pending_tracks:
                source = _safe_track_path(package_root, track)
                report(
                    {
                        "type": "event",
                        "code": "TRACK_ALIGNMENT_STARTED",
                        "stage": "alignment",
                        "track": track.number,
                        "total_tracks": total_tracks,
                        "speaker": track.speaker,
                    }
                )
                expected = pending_text[track.number]
                expected_by_index = {item.index: item for item in expected}
                seen: set[int] = set()
                segments: list[TranscriptSegment] = []
                duration = 0.0
                last_index = expected[-1].index
                # Replay with a one-window lookahead. This keeps memory bounded
                # while allowing one alignment-only retry with real right context.
                windows_iter = iter(window_reader(source))
                window = next(windows_iter, None)
                while window is not None:
                    next_window = next(windows_iter, None)
                    if is_cancelled():
                        raise QwenRuntimeError("ASR_CANCELLED")
                    pending = expected_by_index.get(window.index)
                    if (
                        pending is None
                        or not math.isclose(pending.start, window.start, abs_tol=0.001)
                        or not math.isclose(pending.end, window.end, abs_tol=0.001)
                    ):
                        raise QwenRuntimeError("QWEN_WINDOW_REPLAY_MISMATCH")
                    seen.add(window.index)
                    first_window = window.index == expected[0].index
                    last_window = window.index == last_index
                    energy_window = window
                    try:
                        window_segments, ignored_trailing_overflow = _strict_alignment_segments(
                            track.number,
                            window,
                            pending,
                            aligner,
                            first=first_window,
                            last=last_window,
                        )
                    except QwenRuntimeError as exc:
                        failure_class = getattr(
                            exc,
                            "alignment_failure_class",
                            "QWEN_ALIGNMENT_REQUIRED",
                        )
                        recoverable_owned_overflow = (
                            exc.code == "QWEN_ALIGNMENT_REQUIRED"
                            and failure_class == "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW"
                            and not last_window
                            and next_window is not None
                        )
                        recovered = False
                        if recoverable_owned_overflow:
                            if is_cancelled():
                                raise QwenRuntimeError("ASR_CANCELLED") from exc
                            extended_window = right_context_builder(
                                window,
                                next_window,
                            )
                            if extended_window is not None:
                                context_seconds = max(
                                    extended_window.end - window.end,
                                    0.0,
                                )
                                report(
                                    {
                                        "type": "event",
                                        "code": "QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED",
                                        "stage": "alignment",
                                        "track": track.number,
                                        "window": window.index,
                                        "failure_class": failure_class,
                                        "context_seconds": round(context_seconds, 3),
                                    }
                                )
                                try:
                                    (
                                        window_segments,
                                        ignored_trailing_overflow,
                                    ) = _strict_alignment_segments(
                                        track.number,
                                        window,
                                        pending,
                                        aligner,
                                        first=first_window,
                                        last=last_window,
                                        alignment_window=extended_window,
                                    )
                                except QwenRuntimeError as recovery_exc:
                                    recovery_failure_class = (
                                        recovery_exc.code
                                        if recovery_exc.code in _ALIGNMENT_RUNTIME_PASSTHROUGH
                                        else getattr(
                                            recovery_exc,
                                            "alignment_failure_class",
                                            "QWEN_ALIGNMENT_REQUIRED",
                                        )
                                    )
                                    report(
                                        {
                                            "type": "event",
                                            "code": "QWEN_ALIGNMENT_WINDOW_RECOVERY_FAILED",
                                            "stage": "alignment",
                                            "track": track.number,
                                            "window": window.index,
                                            "failure_class": recovery_failure_class,
                                            "context_seconds": round(context_seconds, 3),
                                        }
                                    )
                                    exc = recovery_exc
                                    failure_class = recovery_failure_class
                                else:
                                    recovered = True
                                    energy_window = extended_window
                                    report(
                                        {
                                            "type": "event",
                                            "code": "QWEN_ALIGNMENT_WINDOW_RECOVERED",
                                            "stage": "alignment",
                                            "track": track.number,
                                            "window": window.index,
                                            "context_seconds": round(context_seconds, 3),
                                        }
                                    )
                        if not recovered:
                            if (
                                exc.code == "QWEN_ALIGNMENT_REQUIRED"
                                or exc.code in _ALIGNMENT_RUNTIME_PASSTHROUGH
                            ):
                                failure_data: dict[str, Any] = {
                                    "type": "event",
                                    "code": "QWEN_ALIGNMENT_WINDOW_FAILED",
                                    "stage": "alignment",
                                    "track": track.number,
                                    "window": window.index,
                                    "failure_class": (
                                        exc.code
                                        if exc.code in _ALIGNMENT_RUNTIME_PASSTHROUGH
                                        else failure_class
                                    ),
                                    "window_start_seconds": round(window.start, 3),
                                    "window_end_seconds": round(window.end, 3),
                                    "ownership_left_seconds": round(
                                        window.start
                                        if first_window
                                        else window.start
                                        + QWEN_WINDOW_OVERLAP_SECONDS / 2.0,
                                        3,
                                    ),
                                    "ownership_right_seconds": round(
                                        window.end
                                        if last_window
                                        else window.end
                                        - QWEN_WINDOW_OVERLAP_SECONDS / 2.0,
                                        3,
                                    ),
                                    "first_window": first_window,
                                    "last_window": last_window,
                                    **_runtime_identity_metadata(runtime_fingerprint),
                                }
                                diagnostics = getattr(exc, "alignment_diagnostics", {})
                                if isinstance(diagnostics, dict):
                                    for key, value in diagnostics.items():
                                        if key not in _ALIGNMENT_DIAGNOSTIC_KEYS:
                                            continue
                                        if isinstance(value, bool) or isinstance(value, int):
                                            failure_data[key] = value
                                        elif isinstance(value, float) and math.isfinite(value):
                                            failure_data[key] = value
                                report(failure_data)
                            raise exc
                    if ignored_trailing_overflow:
                        report(
                            {
                                "type": "event",
                                "code": "QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED",
                                "stage": "alignment",
                                "track": track.number,
                                "window": window.index,
                                "count": ignored_trailing_overflow,
                            }
                        )
                    segments.extend(window_segments)
                    for segment in window_segments:
                        key = (track.number, segment.id)
                        value = energy_reader(
                            energy_window,
                            segment.start,
                            segment.end,
                        )
                        energy_by_segment[key] = max(
                            energy_by_segment.get(key, -120.0),
                            value,
                        )
                    duration = max(duration, window.end)
                    window = next_window
                if seen != set(expected_by_index):
                    raise QwenRuntimeError("QWEN_WINDOW_REPLAY_MISMATCH")
                transcript_track = TranscriptTrack(
                    number=track.number,
                    speaker=track.speaker,
                    source_filename=track.filename,
                    source_sha256=track.sha256,
                    duration_seconds=round(duration, 3),
                    segments=tuple(segments),
                    timeline_offset_seconds=track.timeline_offset_seconds,
                    identity=asdict(track.identity) if track.identity is not None else None,
                )
                transcript_track.validate()
                new_tracks[track.number] = transcript_track
                if checkpoints:
                    try:
                        save_track_checkpoint(package_root, signature, track, transcript_track)
                        report({"type": "event", "code": "ASR_CHECKPOINT_SAVED", "track": track.number})
                    except (OSError, ValueError):
                        report({"type": "event", "code": "ASR_CHECKPOINT_WRITE_SKIPPED", "track": track.number})
                report(
                    {
                        "type": "event",
                        "code": "TRACK_COMPLETED",
                        "stage": "alignment",
                        "track": track.number,
                        "total_tracks": total_tracks,
                        "speaker": track.speaker,
                        **(
                            {"completed_window_count": fresh_window_counts[track.number]}
                            if track.number in fresh_window_counts
                            else {}
                        ),
                    }
                )
                completed_tracks += 1
                report(
                    {
                        "type": "progress",
                        "completed": completed_tracks,
                        "total": total_tracks,
                        "unit": "tracks",
                        "stage": "alignment",
                    }
                )
        finally:
            aligner.close()

    if completed_tracks != total_tracks:
        raise QwenRuntimeError("QWEN_TRACK_PROGRESS_INCOMPLETE")

    transcript_tracks = tuple(cached_tracks.get(track.number) or new_tracks[track.number] for track in package.tracks)

    if cached_tracks:
        report({"type": "stage", "stage": "energy_analysis", "profile": profile.id})
        tracks_by_number = {track.number: track for track in transcript_tracks}
        for source_track in package.tracks:
            if source_track.number not in cached_tracks:
                continue
            report(
                {
                    "type": "event",
                    "code": "TRACK_ENERGY_STARTED",
                    "stage": "energy_analysis",
                    "track": source_track.number,
                    "total_tracks": total_tracks,
                    "speaker": source_track.speaker,
                }
            )
            source = _safe_track_path(package_root, source_track)
            transcript_track = tracks_by_number[source_track.number]
            remaining = list(transcript_track.segments)
            for window in window_reader(source):
                if is_cancelled():
                    raise QwenRuntimeError("ASR_CANCELLED")
                next_remaining: list[TranscriptSegment] = []
                for segment in remaining:
                    if segment.end <= window.start or segment.start >= window.end:
                        next_remaining.append(segment)
                        continue
                    key = (transcript_track.number, segment.id)
                    value = energy_reader(window, segment.start, segment.end)
                    energy_by_segment[key] = max(
                        energy_by_segment.get(key, -120.0),
                        value,
                    )
                remaining = next_remaining

    report({"type": "stage", "stage": "cross_track_dedup", "profile": profile.id})
    flattened = flatten_tracks(transcript_tracks)
    deduplicated, decisions = deduplicate_cross_track_segments(flattened, energy_by_segment=energy_by_segment)
    report({"type": "stage", "stage": "merge_timeline", "profile": profile.id})
    merged = tuple(sorted(deduplicated, key=lambda item: (item.start, item.end, item.track_number, item.segment_id)))
    report({"type": "stage", "stage": "turn_building", "profile": profile.id})
    turns = build_turns(merged)

    elapsed = max(time.monotonic() - started, 0.0)
    document = TranscriptDocument(
        recording_id=package.recording_id,
        source_sha256=package.source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="qwen3",
            model=profile.model_id,
            profile=profile.id,
            device=plan.device,
            compute_type=plan.dtype,
            alignment=f"{QWEN_FORCED_ALIGNER_MODEL_ID}+{QWEN_ALIGNMENT_POLICY}",
            model_revision=profile.revision,
        ),
        tracks=transcript_tracks,
        turns=turns,
        stats=stats_for_tracks(
            transcript_tracks,
            processing_seconds=elapsed,
            turn_count=len(turns),
            deduplicated_segment_count=len(decisions),
        ),
        warnings=tuple(sorted(compatibility_warnings)),
    )
    report({"type": "stage", "stage": "result_prepare", "profile": profile.id})
    document.validate()
    return document
