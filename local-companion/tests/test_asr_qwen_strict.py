from __future__ import annotations

from pathlib import Path

import pytest

from tda_companion.asr_models import get_profile
from tda_companion.asr_qwen import AudioWindow, QWEN_WINDOW_SECONDS, QwenRuntimeError
from tda_companion.asr_qwen_strict import (
    QWEN_WINDOW_OVERLAP_SECONDS,
    _owned_words,
    transcribe_craig_package_qwen_strict,
)
from tda_companion.craig import CraigPackage, CraigTrack
from tda_companion.qwen_acceptance import QwenPlan
from tda_companion.transcript import TranscriptWord


def _package(tmp_path: Path) -> tuple[CraigPackage, Path]:
    root = tmp_path / "Data" / "staging" / "strict"
    tracks = root / "tracks"
    tracks.mkdir(parents=True)
    source = tracks / "1-Alice.flac"
    source.write_bytes(b"audio")
    track = CraigTrack(
        number=1,
        speaker="Alice",
        filename="1-Alice.flac",
        path="tracks/1-Alice.flac",
        size_bytes=5,
        sha256="1" * 64,
        identity=None,
    )
    return (
        CraigPackage(
            schema_version="tda_craig_package_v1",
            source_zip="fixture.zip",
            source_sha256="a" * 64,
            recording_id="strict",
            guild=None,
            channel=None,
            requester=None,
            start_time=None,
            tracks=(track,),
            info_present=False,
            raw_dat_present=False,
        ),
        root,
    )


def _plan(_profile_id: str) -> QwenPlan:
    return QwenPlan(profile_id="qwen-fast", device="cuda", dtype="bfloat16", compute_capability="8.9")


def _model_prepare(_models_root: Path, profile):
    assert profile == get_profile("qwen-fast")
    return Path("model")


def _aligner_prepare(_models_root: Path):
    return Path("aligner")


def _two_windows(_path: Path):
    stride = QWEN_WINDOW_SECONDS - QWEN_WINDOW_OVERLAP_SECONDS
    yield AudioWindow(index=1, start=0.0, end=QWEN_WINDOW_SECONDS, audio="w1")
    yield AudioWindow(index=2, start=stride, end=stride + 46.0, audio="w2")


def test_strict_qwen_fails_instead_of_publishing_window_fallback(tmp_path: Path):
    package, root = _package(tmp_path)

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "texto", "Portuguese"
        def close(self):
            pass

    class BrokenAligner:
        def align(self, _audio, _text: str, _language: str):
            raise QwenRuntimeError("QWEN_ALIGNMENT_FAILED")
        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            checkpoints=False,
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=_two_windows,
        )


def test_overlap_ownership_assigns_boundary_words_once():
    overlap = QWEN_WINDOW_OVERLAP_SECONDS
    stride = QWEN_WINDOW_SECONDS - overlap
    first = AudioWindow(index=1, start=0.0, end=QWEN_WINDOW_SECONDS, audio=None)
    second = AudioWindow(index=2, start=stride, end=stride + 46.0, audio=None)
    boundary = stride + overlap / 2.0
    words = [
        TranscriptWord(text="left", start=boundary - 1.0, end=boundary - 0.2),
        TranscriptWord(text="right", start=boundary + 0.2, end=boundary + 1.0),
    ]

    owned_first = _owned_words(words, first, first=True, last=False, overlap_seconds=overlap)
    owned_second = _owned_words(words, second, first=False, last=True, overlap_seconds=overlap)

    assert [word.text for word in owned_first] == ["left"]
    assert [word.text for word in owned_second] == ["right"]
    assert {word.text for word in owned_first}.isdisjoint({word.text for word in owned_second})


def test_strict_qwen_replays_windows_in_lockstep_not_full_track_dict(tmp_path: Path):
    package, root = _package(tmp_path)
    reads = 0
    align_calls: list[str] = []

    def reader(_path: Path):
        nonlocal reads
        reads += 1
        yield AudioWindow(index=1, start=0.0, end=2.0, audio=f"pass-{reads}-one")
        yield AudioWindow(index=2, start=1.5, end=3.0, audio=f"pass-{reads}-two")

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            return f"texto {audio[-3:]}", "Portuguese"
        def close(self):
            pass

    class Aligner:
        def align(self, audio, text: str, _language: str):
            align_calls.append(audio)
            if audio.endswith("one"):
                return [{"text": "um", "start_time": 0.1, "end_time": 0.4}]
            return [{"text": "dois", "start_time": 0.7, "end_time": 1.0}]
        def close(self):
            pass

    document = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        checkpoints=False,
        plan_resolver=_plan,
        model_prepare=_model_prepare,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=lambda _root, _plan: Asr(),
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -10.0,
    )

    # ASR pass + alignment replay + energy replay. Production alignment consumes
    # each replayed window immediately instead of building {index: AudioWindow}.
    assert reads == 3
    assert align_calls == ["pass-2-one", "pass-2-two"]
    assert "strict-overlap-v2" in document.engine.alignment
    assert document.warnings == ()
