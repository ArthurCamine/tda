from __future__ import annotations

import math
import os
import wave
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from .qwen_acceptance import QwenAcceptanceError

QWEN_GATE_WINDOW_SECONDS = 60.0
QWEN_GATE_STEP_SECONDS = 15.0
QWEN_GATE_SAMPLE_RATE = 16_000
QWEN_GATE_MAX_SOURCE_BYTES = 16 * 1024**3


def _pcm_blocks(source: Path, block_samples: int) -> Iterable[Any]:
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise QwenAcceptanceError("QWEN_RUNTIME_NOT_INSTALLED") from exc

    pieces: list[Any] = []
    buffered = 0

    def drain() -> list[Any]:
        nonlocal pieces, buffered
        output: list[Any] = []
        while buffered >= block_samples:
            joined = np.concatenate(pieces).astype(np.int16, copy=False)
            block = joined[:block_samples].copy()
            remainder = joined[block_samples:]
            pieces = [remainder.copy()] if remainder.size else []
            buffered = int(remainder.size)
            output.append(block)
        return output

    try:
        with av.open(str(source)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is None:
                raise QwenAcceptanceError("QWEN_ACCEPTANCE_AUDIO_STREAM_MISSING")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=QWEN_GATE_SAMPLE_RATE)
            for frame in container.decode(stream):
                for converted in resampler.resample(frame):
                    array = converted.to_ndarray().reshape(-1).astype(np.int16, copy=False)
                    if array.size:
                        pieces.append(array.copy())
                        buffered += int(array.size)
                    yield from drain()
            for converted in resampler.resample(None):
                array = converted.to_ndarray().reshape(-1).astype(np.int16, copy=False)
                if array.size:
                    pieces.append(array.copy())
                    buffered += int(array.size)
                yield from drain()
    except QwenAcceptanceError:
        raise
    except Exception as exc:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_WINDOW_DECODE_FAILED") from exc


def materialize_qwen_acceptance_window(
    source_path: Path,
    target_path: Path,
    *,
    window_seconds: float = QWEN_GATE_WINDOW_SECONDS,
    step_seconds: float = QWEN_GATE_STEP_SECONDS,
) -> dict[str, float]:
    """Write the highest-energy bounded window from a long local track to a temporary WAV.

    The caller owns the temporary destination and must remove it after acceptance. No
    transcript text or source path is returned from this helper.
    """
    source = source_path.resolve()
    target = target_path.resolve()
    if window_seconds != QWEN_GATE_WINDOW_SECONDS or step_seconds != QWEN_GATE_STEP_SECONDS:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_WINDOW_CONFIG_INVALID")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_AUDIO_NOT_FOUND") from exc
    if not source.is_file() or size <= 0:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_AUDIO_INVALID")
    if size > QWEN_GATE_MAX_SOURCE_BYTES:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_AUDIO_TOO_LARGE")
    if target.exists():
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_WINDOW_TARGET_EXISTS")

    try:
        import numpy as np
    except ImportError as exc:
        raise QwenAcceptanceError("QWEN_RUNTIME_NOT_INSTALLED") from exc

    block_samples = int(round(step_seconds * QWEN_GATE_SAMPLE_RATE))
    blocks_per_window = int(round(window_seconds / step_seconds))
    if block_samples <= 0 or blocks_per_window <= 0:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_WINDOW_CONFIG_INVALID")

    blocks: deque[Any] = deque(maxlen=blocks_per_window)
    energies: deque[float] = deque(maxlen=blocks_per_window)
    best_samples: Any | None = None
    best_score = -1.0
    best_start = 0.0
    block_count = 0

    for block in _pcm_blocks(source, block_samples):
        block_count += 1
        blocks.append(block)
        normalized = block.astype(np.float64, copy=False) / 32768.0
        energies.append(float(np.mean(np.square(normalized, dtype=np.float64))))
        if len(blocks) != blocks_per_window:
            continue
        score = float(sum(energies) / len(energies))
        if score > best_score:
            best_score = score
            best_samples = np.concatenate(tuple(blocks)).astype(np.int16, copy=True)
            best_start = float((block_count - blocks_per_window) * step_seconds)

    expected_samples = int(round(window_seconds * QWEN_GATE_SAMPLE_RATE))
    if best_samples is None or int(best_samples.size) != expected_samples:
        raise QwenAcceptanceError("QWEN_ACCEPTANCE_AUDIO_TOO_SHORT")

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as raw:
            with wave.open(raw, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(QWEN_GATE_SAMPLE_RATE)
                pcm = best_samples.astype("<i2", copy=False).tobytes()
                output.writeframes(pcm)
            raw.flush()
            os.fsync(raw.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    dbfs = 10.0 * math.log10(max(best_score, 1e-12))
    return {
        "start_seconds": round(best_start, 3),
        "duration_seconds": QWEN_GATE_WINDOW_SECONDS,
        "sample_rate": float(QWEN_GATE_SAMPLE_RATE),
        "energy_dbfs": round(dbfs, 3),
    }
