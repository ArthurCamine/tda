from __future__ import annotations

import gc
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .asr_checkpoints import build_checkpoint_signature, load_track_checkpoint, save_track_checkpoint
from .asr_models import (
    AsrProfile,
    ModelRegistryError,
    get_profile,
    inspect_model_install,
    model_path,
    write_install_marker,
)
from .asr_timeline import build_turns, deduplicate_cross_track_segments, flatten_tracks
from .craig import CraigPackage, CraigTrack
from .transcript import (
    TranscriptDocument,
    TranscriptEngine,
    TranscriptSegment,
    TranscriptTrack,
    TranscriptWord,
    stats_for_tracks,
)

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


class WhisperRuntimeError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _tree_bytes(root: Path, *, max_entries: int = 50_000) -> int:
    if not root.exists():
        return 0
    total = 0
    entries = 0
    try:
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            entries += 1
            if entries > max_entries:
                return total
            total += path.stat().st_size
    except OSError:
        return total
    return total


@dataclass(frozen=True)
class WhisperPlan:
    profile_id: str
    device: str
    compute_type: str
    fallback_compute_type: str | None
    cpu_requested: bool


def probe_whisper_cuda() -> dict[str, Any]:
    """Probe CTranslate2 lazily; never import it in the Agent/API process by default."""
    try:
        import ctranslate2

        count = int(ctranslate2.get_cuda_device_count())
        supported = sorted(ctranslate2.get_supported_compute_types("cuda", 0)) if count > 0 else []
        return {"available": count > 0, "device_count": count, "supported_compute_types": supported}
    except Exception:
        return {"available": False, "device_count": 0, "supported_compute_types": []}


def resolve_whisper_plan(
    profile_id: str,
    *,
    cpu: bool = False,
    cuda_status: dict[str, Any] | None = None,
) -> WhisperPlan:
    profile = get_profile(profile_id)
    if profile.engine != "whisper":
        raise WhisperRuntimeError("WHISPER_PROFILE_REQUIRED")
    if cpu:
        return WhisperPlan(
            profile_id=profile.id,
            device="cpu",
            compute_type="int8",
            fallback_compute_type=None,
            cpu_requested=True,
        )

    status = cuda_status if cuda_status is not None else probe_whisper_cuda()
    if not status.get("available"):
        raise WhisperRuntimeError("WHISPER_CUDA_UNAVAILABLE")
    supported = set(status.get("supported_compute_types") or [])
    if "float16" in supported:
        return WhisperPlan(
            profile_id=profile.id,
            device="cuda",
            compute_type="float16",
            fallback_compute_type="int8_float16" if "int8_float16" in supported else None,
            cpu_requested=False,
        )
    if "int8_float16" in supported:
        return WhisperPlan(
            profile_id=profile.id,
            device="cuda",
            compute_type="int8_float16",
            fallback_compute_type=None,
            cpu_requested=False,
        )
    raise WhisperRuntimeError("WHISPER_CUDA_COMPUTE_UNSUPPORTED")


def _bounded_context(value: str, maximum: int) -> str:
    compact = " ".join(value.split())
    return compact[:maximum].strip()


def whisper_transcribe_options(*, glossary: str = "", context: str = "") -> dict[str, Any]:
    glossary_value = _bounded_context(glossary, 2000)
    context_value = _bounded_context(context, 2000)
    prompt_parts = ["Sessão de RPG Dungeons & Dragons em português."]
    if context_value:
        prompt_parts.append(f"Contexto da campanha: {context_value}")
    if glossary_value:
        prompt_parts.append(f"Nomes e termos importantes: {glossary_value}")
    return {
        "language": "pt",
        "task": "transcribe",
        "beam_size": 5,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 300,
        },
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "hotwords": glossary_value or None,
        "initial_prompt": " ".join(prompt_parts),
    }


def _is_cuda_memory_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return any(
        marker in text
        for marker in (
            "out of memory",
            "not enough memory",
            "cublas_status_alloc_failed",
            "cuda_error_out_of_memory",
            "failed to allocate",
        )
    )


def load_whisper_model(path: Path, plan: WhisperPlan):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WhisperRuntimeError("WHISPER_RUNTIME_NOT_INSTALLED") from exc

    try:
        model = WhisperModel(str(path), device=plan.device, compute_type=plan.compute_type)
        return model, plan.compute_type, False
    except Exception as exc:
        if (
            plan.device != "cuda"
            or not plan.fallback_compute_type
            or not _is_cuda_memory_error(exc)
        ):
            raise WhisperRuntimeError("WHISPER_MODEL_LOAD_FAILED") from exc
        gc.collect()
        try:
            model = WhisperModel(
                str(path),
                device="cuda",
                compute_type=plan.fallback_compute_type,
            )
        except Exception as fallback_exc:
            raise WhisperRuntimeError("WHISPER_MODEL_LOAD_FAILED") from fallback_exc
        return model, plan.fallback_compute_type, True


def _resumable_model_staging(downloads: Path, directory: str) -> Path:
    candidates: list[tuple[float, Path]] = []
    for candidate in downloads.glob(f"{directory}-*.partial"):
        if not candidate.is_dir():
            continue
        try:
            modified = candidate.stat().st_mtime
        except OSError:
            continue
        candidates.append((modified, candidate))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        chosen = candidates[0][1]
        for _, stale in candidates[1:]:
            shutil.rmtree(stale, ignore_errors=True)
        return chosen
    return downloads / f"{directory}-{uuid4().hex}.partial"


def prepare_whisper_model(
    models_root: Path,
    profile: AsrProfile,
    *,
    downloader: Callable[..., Any] | None = None,
    report: ProgressCallback | None = None,
) -> Path:
    if profile.engine != "whisper":
        raise WhisperRuntimeError("WHISPER_PROFILE_REQUIRED")
    state = inspect_model_install(models_root, profile)
    target = model_path(models_root, profile)
    if state["status"] == "ready":
        return target
    if target.exists():
        raise WhisperRuntimeError("WHISPER_MODEL_REPAIR_REQUIRED")

    report = report or (lambda _: None)
    report({"type": "stage", "stage": "model_prepare", "profile": profile.id})
    downloads = models_root.resolve() / ".downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    staging = _resumable_model_staging(downloads, profile.directory)

    if downloader is None:
        # huggingface_hub reads these values when its constants module is imported.
        # Keep each network request finite; the overall model preparation may still
        # run for a long time on a slow connection and is supervised separately.
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "15")
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        try:
            from faster_whisper.utils import download_model
        except ImportError as exc:
            raise WhisperRuntimeError("WHISPER_RUNTIME_NOT_INSTALLED") from exc
        downloader = download_model

    stop_monitor = threading.Event()
    last_reported = {"bytes": -1}

    def monitor_download() -> None:
        while not stop_monitor.wait(2.0):
            downloaded = _tree_bytes(staging)
            if downloaded <= 0 or downloaded == last_reported["bytes"]:
                continue
            last_reported["bytes"] = downloaded
            report(
                {
                    "type": "event",
                    "code": "MODEL_DOWNLOAD_PROGRESS",
                    "stage": "model_prepare",
                    "profile": profile.id,
                    "downloaded_bytes": downloaded,
                }
            )

    monitor = threading.Thread(
        target=monitor_download,
        name="tda-whisper-download-progress",
        daemon=True,
    )
    monitor.start()
    try:
        try:
            downloader(profile.model_id, output_dir=str(staging), revision=profile.revision)
        except WhisperRuntimeError:
            raise
        except Exception as exc:
            raise WhisperRuntimeError("WHISPER_MODEL_DOWNLOAD_FAILED") from exc
        # Hugging Face local-dir metadata is useful only while downloading.
        # Do not bind transient resume metadata into the installed model hash.
        shutil.rmtree(staging / ".cache", ignore_errors=True)
        downloaded = _tree_bytes(staging)
        if downloaded > 0:
            report(
                {
                    "type": "event",
                    "code": "MODEL_DOWNLOAD_PROGRESS",
                    "stage": "model_prepare",
                    "profile": profile.id,
                    "downloaded_bytes": downloaded,
                }
            )
        missing = [name for name in profile.required_files if not (staging / name).is_file()]
        if missing:
            raise WhisperRuntimeError("WHISPER_MODEL_DOWNLOAD_INCOMPLETE")
        try:
            write_install_marker(staging, profile)
        except ModelRegistryError as exc:
            raise WhisperRuntimeError("WHISPER_MODEL_INTEGRITY_FAILED") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        return target
    except WhisperRuntimeError as exc:
        # Keep Hugging Face local-dir metadata and partial files after a network
        # failure so the next preparation attempt can resume the same snapshot.
        if exc.code != "WHISPER_MODEL_DOWNLOAD_FAILED":
            shutil.rmtree(staging, ignore_errors=True)
        raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        stop_monitor.set()
        monitor.join(timeout=1.0)


def _safe_track_path(package_root: Path, track: CraigTrack) -> Path:
    root = package_root.resolve()
    candidate = (root / track.path).resolve()
    if candidate == root or root not in candidate.parents or not candidate.is_file():
        raise WhisperRuntimeError("CRAIG_TRACK_PATH_INVALID")
    return candidate


def _word_from_engine(word: Any) -> TranscriptWord:
    return TranscriptWord(
        text=str(word.word).strip(),
        start=round(float(word.start), 3),
        end=round(float(word.end), 3),
        confidence=round(float(word.probability), 6) if word.probability is not None else None,
    )


def _segment_from_engine(track_number: int, segment: Any) -> TranscriptSegment:
    words = tuple(
        word_value
        for word in (getattr(segment, "words", None) or [])
        if (word_value := _word_from_engine(word)).text
    )
    return TranscriptSegment(
        id=f"{track_number}-{segment.id}",
        start=round(float(segment.start), 3),
        end=round(float(segment.end), 3),
        text=str(segment.text).strip(),
        words=words,
    )


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unavailable"


def _whisper_runtime_fingerprint() -> str:
    return ";".join(
        (
            "checkpoint=whisper-track-v1",
            f"faster-whisper={_distribution_version('faster-whisper')}",
            f"ctranslate2={_distribution_version('ctranslate2')}",
        )
    )


def transcribe_craig_package(
    package: CraigPackage,
    package_root: Path,
    models_root: Path,
    *,
    profile_id: str,
    glossary: str = "",
    context: str = "",
    cpu: bool = False,
    cuda_status: dict[str, Any] | None = None,
    model_loader: Callable[[Path, WhisperPlan], tuple[Any, str, bool]] = load_whisper_model,
    downloader: Callable[..., Any] | None = None,
    report: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    checkpoints: bool = True,
) -> TranscriptDocument:
    profile = get_profile(profile_id)
    if profile.engine != "whisper":
        raise WhisperRuntimeError("WHISPER_PROFILE_REQUIRED")
    plan = resolve_whisper_plan(profile_id, cpu=cpu, cuda_status=cuda_status)
    report = report or (lambda _: None)
    is_cancelled = is_cancelled or (lambda: False)

    prepared = prepare_whisper_model(
        models_root,
        profile,
        downloader=downloader,
        report=report,
    )
    report({"type": "stage", "stage": "model_load", "profile": profile.id})
    model, effective_compute_type, used_fallback = model_loader(prepared, plan)
    options = whisper_transcribe_options(glossary=glossary, context=context)
    checkpoint_recipe = {
        "transcribe_options": options,
        "device": plan.device,
        "compute_type": effective_compute_type,
        "cpu_requested": plan.cpu_requested,
    }
    checkpoint_signature = build_checkpoint_signature(
        package,
        profile,
        recipe=checkpoint_recipe,
        context=_bounded_context(context, 2000),
        glossary=_bounded_context(glossary, 2000),
        runtime_fingerprint=_whisper_runtime_fingerprint(),
    )

    started = time.monotonic()
    tracks: list[TranscriptTrack] = []
    total_tracks = len(package.tracks)
    report({"type": "stage", "stage": "transcription", "profile": profile.id})
    for index, track in enumerate(package.tracks, start=1):
        if is_cancelled():
            raise WhisperRuntimeError("ASR_CANCELLED")
        source = _safe_track_path(package_root, track)
        cached = load_track_checkpoint(package_root, checkpoint_signature, track) if checkpoints else None
        if cached is not None:
            tracks.append(cached)
            report(
                {
                    "type": "event",
                    "code": "ASR_CHECKPOINT_REUSED",
                    "stage": "transcription",
                    "track": track.number,
                }
            )
        else:
            segments_iter, info = model.transcribe(str(source), **options)
            segments: list[TranscriptSegment] = []
            for segment in segments_iter:
                if is_cancelled():
                    raise WhisperRuntimeError("ASR_CANCELLED")
                value = _segment_from_engine(track.number, segment)
                if value.text:
                    segments.append(value)

            identity = asdict(track.identity) if track.identity is not None else None
            duration = round(float(getattr(info, "duration", 0.0) or 0.0), 3)
            transcript_track = TranscriptTrack(
                number=track.number,
                speaker=track.speaker,
                source_filename=track.filename,
                source_sha256=track.sha256,
                duration_seconds=duration,
                segments=tuple(segments),
                timeline_offset_seconds=track.timeline_offset_seconds,
                identity=identity,
            )
            transcript_track.validate()
            tracks.append(transcript_track)
            if checkpoints:
                try:
                    save_track_checkpoint(package_root, checkpoint_signature, track, transcript_track)
                    report(
                        {
                            "type": "event",
                            "code": "ASR_CHECKPOINT_SAVED",
                            "stage": "transcription",
                            "track": track.number,
                        }
                    )
                except (OSError, ValueError):
                    report(
                        {
                            "type": "event",
                            "code": "ASR_CHECKPOINT_WRITE_SKIPPED",
                            "stage": "transcription",
                            "track": track.number,
                        }
                    )

        report(
            {
                "type": "progress",
                "completed": index,
                "total": total_tracks,
                "unit": "tracks",
                "stage": "transcription",
            }
        )

    transcript_tracks = tuple(tracks)
    if is_cancelled():
        raise WhisperRuntimeError("ASR_CANCELLED")

    report({"type": "stage", "stage": "cross_track_dedup", "profile": profile.id})
    flattened = flatten_tracks(transcript_tracks)
    deduplicated_segments, dedup_decisions = deduplicate_cross_track_segments(flattened)

    if is_cancelled():
        raise WhisperRuntimeError("ASR_CANCELLED")
    report({"type": "stage", "stage": "merge_timeline", "profile": profile.id})
    merged_segments = tuple(
        sorted(
            deduplicated_segments,
            key=lambda item: (item.start, item.end, item.track_number, item.segment_id),
        )
    )

    if is_cancelled():
        raise WhisperRuntimeError("ASR_CANCELLED")
    report({"type": "stage", "stage": "turn_building", "profile": profile.id})
    turns = build_turns(merged_segments)

    elapsed = max(time.monotonic() - started, 0.0)
    warnings = ("WHISPER_GPU_MEMORY_FALLBACK",) if used_fallback else ()
    document = TranscriptDocument(
        recording_id=package.recording_id,
        source_sha256=package.source_sha256,
        language="pt",
        engine=TranscriptEngine(
            engine="whisper",
            model=profile.model_id,
            profile=profile.id,
            device=plan.device,
            compute_type=effective_compute_type,
            alignment="native",
            model_revision=profile.revision,
        ),
        tracks=transcript_tracks,
        turns=turns,
        stats=stats_for_tracks(
            transcript_tracks,
            processing_seconds=elapsed,
            turn_count=len(turns),
            deduplicated_segment_count=len(dedup_decisions),
        ),
        warnings=warnings,
    )
    document.validate()
    report({"type": "stage", "stage": "result_prepare", "profile": profile.id})
    return document
