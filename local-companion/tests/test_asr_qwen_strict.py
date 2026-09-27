from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import tda_companion.asr_qwen as asr_qwen
import tda_companion.asr_qwen_strict as asr_qwen_strict
from tda_companion.asr_models import get_profile
from tda_companion.asr_qwen import (
    AudioWindow,
    QWEN_WINDOW_SECONDS,
    QwenRuntimeError,
    QwenWindowTranscript,
    _runtime_fingerprint,
)
from tda_companion.asr_qwen_strict import (
    QWEN_WINDOW_OVERLAP_SECONDS,
    _owned_words,
    _strict_alignment_segments,
    transcribe_craig_package_qwen_strict,
)
from tda_companion.craig import CraigPackage, CraigPackageError, CraigTrack
from tda_companion.qwen_acceptance import QwenPlan
from tda_companion.transcript import TranscriptWord


def _package(tmp_path: Path) -> tuple[CraigPackage, Path]:
    root = tmp_path / "Data" / "staging" / "strict"
    tracks = root / "tracks"
    tracks.mkdir(parents=True)
    source = tracks / "1-Alice.flac"
    payload = b"audio"
    source.write_bytes(payload)
    track = CraigTrack(
        number=1,
        speaker="Alice",
        filename="1-Alice.flac",
        path="tracks/1-Alice.flac",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
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


def _two_track_package(tmp_path: Path) -> tuple[CraigPackage, Path]:
    root = tmp_path / "Data" / "staging" / "strict-two"
    tracks_root = root / "tracks"
    tracks_root.mkdir(parents=True)
    tracks = []
    for number, speaker in ((1, "Alice"), (2, "Bob")):
        filename = f"{number}-{speaker}.flac"
        payload = f"audio-{speaker}".encode("utf-8")
        (tracks_root / filename).write_bytes(payload)
        tracks.append(
            CraigTrack(
                number=number,
                speaker=speaker,
                filename=filename,
                path=f"tracks/{filename}",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                identity=None,
            )
        )
    return (
        CraigPackage(
            schema_version="tda_craig_package_v1",
            source_zip="fixture-two.zip",
            source_sha256="b" * 64,
            recording_id="strict-two",
            guild=None,
            channel=None,
            requester=None,
            start_time=None,
            tracks=tuple(tracks),
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


def test_qwen_checkpoint_pipeline_revision_is_explicit():
    assert "checkpoint=qwen-track-v3" in _runtime_fingerprint()


def test_packaged_qwen_fingerprint_uses_sealed_marker_without_distribution_scan(
    monkeypatch,
    tmp_path: Path,
):
    runtime = tmp_path / "Runtime" / "qwen" / "1.0.11"
    runtime.mkdir(parents=True)
    executable = runtime / "TDAQwenWorker.exe"
    executable.write_bytes(b"worker")
    (runtime / ".tda-runtime.json").write_text(
        '{"schema":"tda_asr_runtime_v1","runtime_id":"qwen3-transformers","version":"1.0.11","worker_sha256":"'
        + ("f" * 64)
        + '"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.0.11")
    monkeypatch.setattr(asr_qwen.sys, "executable", str(executable))
    monkeypatch.setattr(asr_qwen.sys, "frozen", True, raising=False)

    def forbidden(_name: str) -> str:
        raise AssertionError("packaged fingerprint must not scan package metadata")

    monkeypatch.setattr(asr_qwen, "_distribution_version", forbidden)

    assert _runtime_fingerprint() == (
        "checkpoint=qwen-track-v3;"
        "runtime=1.0.11;"
        f"worker_sha256={'f' * 64}"
    )


def test_packaged_qwen_fingerprint_rejects_invalid_marker(
    monkeypatch,
    tmp_path: Path,
):
    runtime = tmp_path / "Runtime" / "qwen" / "1.0.11"
    runtime.mkdir(parents=True)
    executable = runtime / "TDAQwenWorker.exe"
    executable.write_bytes(b"worker")
    (runtime / ".tda-runtime.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.0.11")
    monkeypatch.setattr(asr_qwen.sys, "executable", str(executable))
    monkeypatch.setattr(asr_qwen.sys, "frozen", True, raising=False)

    with pytest.raises(QwenRuntimeError, match="QWEN_RUNTIME_FINGERPRINT_INVALID"):
        _runtime_fingerprint()


def test_strict_qwen_reports_runtime_validation_before_cuda_plan_resolution(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []

    def plan(profile_id: str) -> QwenPlan:
        assert reports[-1] == {
            "type": "stage",
            "stage": "runtime_validation",
            "profile": profile_id,
        }
        raise QwenRuntimeError("TEST_STOP_AFTER_RUNTIME_VALIDATION")

    with pytest.raises(QwenRuntimeError, match="TEST_STOP_AFTER_RUNTIME_VALIDATION"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            checkpoints=False,
            report=reports.append,
            plan_resolver=plan,
        )

    assert reports == [
        {
            "type": "stage",
            "stage": "runtime_validation",
            "profile": "qwen-fast",
        }
    ]


def test_runtime_identity_metadata_accepts_only_sealed_runtime_fingerprint():
    sealed = (
        "checkpoint=qwen-track-v3;"
        "runtime=1.0.11;"
        "worker_sha256=" + ("a" * 64)
    )
    assert asr_qwen_strict._runtime_identity_metadata(sealed) == {
        "runtime_version": "1.0.11",
        "worker_sha256": "a" * 64,
    }
    assert asr_qwen_strict._runtime_identity_metadata(
        "checkpoint=qwen-track-v3;runtime=development;torch=2.13.0"
    ) == {}
    assert asr_qwen_strict._runtime_identity_metadata(
        "checkpoint=qwen-track-v3;runtime=1.0.11;worker_sha256=C:\\private\\secret"
    ) == {}


def test_strict_qwen_exposes_fingerprint_and_checkpoint_scan_before_model_load(
    monkeypatch,
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []
    monkeypatch.setattr(
        asr_qwen_strict,
        "_runtime_fingerprint",
        lambda: "checkpoint=qwen-track-v3;runtime=test;worker_sha256=" + ("a" * 64),
    )

    def stop_model_prepare(_models_root: Path, _profile):
        raise QwenRuntimeError("TEST_STOP_AFTER_CHECKPOINT_SCAN")

    with pytest.raises(QwenRuntimeError, match="TEST_STOP_AFTER_CHECKPOINT_SCAN"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            checkpoints=False,
            report=reports.append,
            plan_resolver=_plan,
            model_prepare=stop_model_prepare,
        )

    stages = [
        item["stage"]
        for item in reports
        if item.get("type") == "stage"
    ]
    assert stages[:4] == [
        "runtime_validation",
        "runtime_fingerprint",
        "checkpoint_scan",
        "model_prepare",
    ]
    fingerprint = next(
        item for item in reports if item.get("code") == "QWEN_RUNTIME_FINGERPRINT_READY"
    )
    checkpoint = next(
        item for item in reports if item.get("code") == "ASR_CHECKPOINT_SCAN_COMPLETED"
    )
    assert fingerprint["stage"] == "runtime_fingerprint"
    assert fingerprint["duration_ms"] >= 0
    assert checkpoint == {
        "type": "event",
        "code": "ASR_CHECKPOINT_SCAN_COMPLETED",
        "stage": "checkpoint_scan",
        "track_count": 1,
        "aligned_reused": 0,
        "text_reused": 0,
        "pending_asr": 1,
        "duration_ms": checkpoint["duration_ms"],
    }
    assert checkpoint["duration_ms"] >= 0


def test_strict_qwen_accepts_silent_window_without_alignment(tmp_path: Path):
    package, root = _package(tmp_path)
    align_calls = 0
    reports: list[dict] = []

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "   ", "Portuguese"
        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            nonlocal align_calls
            align_calls += 1
            raise AssertionError("silent windows must not reach forced alignment")
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
        window_reader=lambda _path: iter(
            [AudioWindow(index=1, start=0.0, end=2.0, audio="silence")]
        ),
        energy_reader=lambda *_args: -120.0,
        report=reports.append,
    )

    assert align_calls == 0
    assert len(document.tracks) == 1
    assert document.tracks[0].segments == ()
    assert document.stats.segment_count == 0
    assert document.stats.word_count == 0
    windows = [
        item
        for item in reports
        if item.get("code") == "QWEN_WINDOW_TRANSCRIBED"
    ]
    assert windows == [
        {
            "type": "event",
            "code": "QWEN_WINDOW_TRANSCRIBED",
            "stage": "transcription",
            "track": 1,
            "total_tracks": 1,
            "speaker": "Alice",
            "window": 1,
            "completed_window_count": 1,
            "start_seconds": 0.0,
            "end_seconds": 2.0,
        }
    ]
    completed = next(
        item for item in reports if item.get("code") == "TRACK_COMPLETED"
    )
    assert completed["track"] == 1
    assert completed["completed_window_count"] == 1


def test_alignment_failure_event_allowlists_diagnostic_metadata(
    monkeypatch,
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []
    sealed_worker = "a" * 64
    monkeypatch.setattr(
        asr_qwen_strict,
        "_runtime_fingerprint",
        lambda: (
            "checkpoint=qwen-track-v3;"
            "runtime=1.0.11;"
            f"worker_sha256={sealed_worker}"
        ),
    )

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "texto", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "texto", "start_time": 0.1, "end_time": 0.5}]

        def close(self):
            pass

    def fail_with_extra_metadata(*_args, **_kwargs):
        raise asr_qwen_strict._alignment_required(
            "QWEN_ALIGNMENT_FAILED",
            aligned_item=2,
            private_counter=999,
        )

    monkeypatch.setattr(
        asr_qwen_strict,
        "_strict_alignment_segments",
        fail_with_extra_metadata,
    )

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
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=lambda _path: iter(
                (AudioWindow(index=1, start=0.0, end=2.0, audio="window"),)
            ),
            energy_reader=lambda *_args: -12.0,
            report=reports.append,
        )

    failure = next(
        item for item in reports if item.get("code") == "QWEN_ALIGNMENT_WINDOW_FAILED"
    )
    assert failure["aligned_item"] == 2
    assert failure["runtime_version"] == "1.0.11"
    assert failure["worker_sha256"] == sealed_worker
    assert "private_counter" not in failure


def test_strict_qwen_reports_alignment_window_context_for_vram_failure(tmp_path: Path):
    package, root = _package(tmp_path)
    reports: list[dict] = []

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "texto", "Portuguese"

        def close(self):
            pass

    class OomAligner:
        def align(self, _audio, _text: str, _language: str):
            raise QwenRuntimeError("QWEN_ASR_GPU_MEMORY_EXHAUSTED")

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ASR_GPU_MEMORY_EXHAUSTED"):
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
            aligner_session_factory=lambda _root, _plan: OomAligner(),
            window_reader=lambda _path: iter(
                (AudioWindow(index=1, start=0.0, end=2.0, audio="window"),)
            ),
            energy_reader=lambda *_args: -12.0,
            report=reports.append,
        )

    failure = next(
        item for item in reports if item.get("code") == "QWEN_ALIGNMENT_WINDOW_FAILED"
    )
    assert failure["track"] == 1
    assert failure["window"] == 1
    assert failure["failure_class"] == "QWEN_ASR_GPU_MEMORY_EXHAUSTED"


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


def test_strict_qwen_reports_safe_overflow_then_later_owned_failure_and_reuses_text(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    asr_calls = 0
    first_reports: list[dict] = []
    second_reports: list[dict] = []

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return f"texto {audio}", "Portuguese"

        def close(self):
            pass

    class SequenceAligner:
        def align(self, audio, _text: str, _language: str):
            if audio == "w1":
                return [
                    {"text": "owned", "start_time": 10.0, "end_time": 11.0},
                    {"text": "neighbor", "start_time": 56.8, "end_time": 61.4},
                ]
            return [
                # Window 2 spans 54s..100s. This word remains owned by the final
                # window but extrapolates beyond its decoded audio, so it must
                # stay terminal and observable instead of being silently dropped.
                {"text": "owned-failure", "start_time": 45.0, "end_time": 47.0},
            ]

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: SequenceAligner(),
            window_reader=_two_windows,
            energy_reader=lambda *_args: -12.0,
            report=first_reports.append,
        )

    assert asr_calls == 2
    codes = [item.get("code") for item in first_reports]
    safe_index = codes.index("QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED")
    failure_index = codes.index("QWEN_ALIGNMENT_WINDOW_FAILED")
    assert safe_index < failure_index
    assert first_reports[safe_index]["track"] == 1
    assert first_reports[safe_index]["window"] == 1
    assert first_reports[failure_index]["track"] == 1
    assert first_reports[failure_index]["window"] == 2
    assert (
        first_reports[failure_index]["failure_class"]
        == "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW"
    )
    assert len(list(root.glob(".checkpoints/*/qwen-text-v1/track-*.json"))) == 1
    assert list(root.glob(".checkpoints/*/track-*.json")) == []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retry must reuse persisted Qwen text")

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=forbidden,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=forbidden,
            aligner_session_factory=lambda _root, _plan: SequenceAligner(),
            window_reader=_two_windows,
            energy_reader=lambda *_args: -12.0,
            report=second_reports.append,
        )

    assert asr_calls == 2
    assert sum(
        item.get("code") == "ASR_TEXT_CHECKPOINT_REUSED"
        for item in second_reports
    ) == 1
    retry_codes = [item.get("code") for item in second_reports]
    assert retry_codes.index("QWEN_ALIGNMENT_TRAILING_OVERFLOW_IGNORED") < retry_codes.index(
        "QWEN_ALIGNMENT_WINDOW_FAILED"
    )


def test_strict_qwen_reuses_prealignment_text_after_aligner_failure(tmp_path: Path):
    package, root = _two_track_package(tmp_path)
    asr_calls = 0
    first_reports: list[dict] = []
    second_reports: list[dict] = []

    def reader(path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio=path.name)

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return f"texto {audio}", "Portuguese"

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
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=reader,
            report=first_reports.append,
        )

    assert asr_calls == 2
    text_checkpoints = list(
        root.glob(".checkpoints/*/qwen-text-v1/track-*.json")
    )
    assert len(text_checkpoints) == 2
    assert list(root.glob(".checkpoints/*/track-*.json")) == []
    assert sum(
        item.get("code") == "ASR_TEXT_CHECKPOINT_SAVED"
        for item in first_reports
    ) == 2
    first_failure = next(
        item
        for item in first_reports
        if item.get("code") == "QWEN_ALIGNMENT_WINDOW_FAILED"
    )
    assert first_failure["track"] == 1
    assert first_failure["window"] == 1
    assert first_failure["failure_class"] == "QWEN_ALIGNMENT_FAILED"
    assert "text" not in first_failure

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retry must reuse durable Qwen text instead of loading ASR")

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=forbidden,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=forbidden,
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=reader,
            report=second_reports.append,
        )

    assert asr_calls == 2
    assert sum(
        item.get("code") == "ASR_TEXT_CHECKPOINT_REUSED"
        for item in second_reports
    ) == 2
    second_failure = next(
        item
        for item in second_reports
        if item.get("code") == "QWEN_ALIGNMENT_WINDOW_FAILED"
    )
    assert second_failure["track"] == 1
    assert second_failure["window"] == 1
    assert second_failure["failure_class"] == "QWEN_ALIGNMENT_FAILED"
    stages = [
        item.get("stage")
        for item in second_reports
        if item.get("type") == "stage"
    ]
    assert "model_prepare" not in stages
    assert "model_load" not in stages
    assert "transcription" not in stages
    assert "alignment" in stages


def test_strict_qwen_reuses_1_0_10_text_checkpoint_after_1_0_11_alignment_upgrade(
    monkeypatch,
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    asr_calls = 0
    first_reports: list[dict] = []
    second_reports: list[dict] = []

    def reader(_path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio="window")

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return "texto preservado", "Portuguese"

        def close(self):
            pass

    class BrokenAligner:
        def align(self, _audio, _text: str, _language: str):
            raise QwenRuntimeError("QWEN_ALIGNMENT_FAILED")

        def close(self):
            pass

    monkeypatch.setattr(asr_qwen_strict, "QWEN_ALIGNMENT_POLICY", "strict-overlap-v2")
    monkeypatch.setattr(
        asr_qwen_strict,
        "_runtime_fingerprint",
        lambda: "checkpoint=qwen-track-v3;runtime=1.0.10;worker_sha256=8c07e1c3bd34ecc53d49025a510c7547e7748b030ac6a90fdd70a2abc431e62e",
    )
    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=reader,
            report=first_reports.append,
        )

    assert asr_calls == 1
    assert any(item.get("code") == "ASR_TEXT_CHECKPOINT_SAVED" for item in first_reports)

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "texto", "start_time": 0.1, "end_time": 0.5}]

        def close(self):
            pass

    def forbidden(*_args, **_kwargs):
        raise AssertionError("1.0.11 retry must reuse compatible 1.0.10 ASR text")

    monkeypatch.setattr(asr_qwen_strict, "QWEN_ALIGNMENT_POLICY", "strict-overlap-v3")
    monkeypatch.setattr(
        asr_qwen_strict,
        "_runtime_fingerprint",
        lambda: "checkpoint=qwen-track-v3;runtime=1.0.11;worker_sha256=" + ("b" * 64),
    )
    document = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=forbidden,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=forbidden,
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -10.0,
        report=second_reports.append,
    )

    assert asr_calls == 1
    assert document.tracks[0].segments[0].text == "texto"
    assert "strict-overlap-v3" in document.engine.alignment
    compat_event = next(
        item
        for item in second_reports
        if item.get("code") == "ASR_TEXT_CHECKPOINT_COMPAT_REUSED"
    )
    assert compat_event["source_runtime_version"] == "1.0.10"
    assert len(compat_event["source_signature_sha256"]) == 64
    assert set(compat_event["source_signature_sha256"]) <= set("0123456789abcdef")
    assert document.warnings == (
        "qwen_text_checkpoint_compat_reused:runtime=1.0.10",
    )
    stages = [
        item.get("stage")
        for item in second_reports
        if item.get("type") == "stage"
    ]
    assert "model_prepare" not in stages
    assert "model_load" not in stages
    assert "transcription" not in stages
    assert "alignment" in stages


def test_strict_qwen_cancel_after_text_save_preserves_reusable_checkpoint(tmp_path: Path):
    package, root = _package(tmp_path)
    cancelled = False
    asr_calls = 0

    def reader(_path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio="window")

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return "texto", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "texto", "start_time": 0.1, "end_time": 0.6}]

        def close(self):
            pass

    def report(value: dict):
        nonlocal cancelled
        if value.get("code") == "ASR_TEXT_CHECKPOINT_SAVED":
            cancelled = True

    with pytest.raises(QwenRuntimeError, match="ASR_CANCELLED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=reader,
            report=report,
            is_cancelled=lambda: cancelled,
        )

    assert asr_calls == 1
    assert len(list(root.glob(".checkpoints/*/qwen-text-v1/track-*.json"))) == 1
    assert list(root.glob(".checkpoints/*/track-*.json")) == []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retry after cancel must reuse Qwen text")

    document = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=forbidden,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=forbidden,
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -12.0,
    )
    assert asr_calls == 1
    assert document.tracks[0].segments[0].text == "texto"
    assert len(list(root.glob(".checkpoints/*/track-*.json"))) == 1


def test_strict_qwen_crash_before_alignment_preserves_reusable_checkpoint(tmp_path: Path):
    package, root = _package(tmp_path)
    asr_calls = 0

    def reader(_path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio="window")

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return "texto", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "texto", "start_time": 0.1, "end_time": 0.6}]

        def close(self):
            pass

    with pytest.raises(RuntimeError, match="synthetic crash"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=lambda _root: (_ for _ in ()).throw(
                RuntimeError("synthetic crash")
            ),
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=reader,
        )

    assert asr_calls == 1
    assert len(list(root.glob(".checkpoints/*/qwen-text-v1/track-*.json"))) == 1
    assert not list(root.glob(".checkpoints/**/*.partial"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retry after crash must reuse Qwen text")

    document = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=forbidden,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=forbidden,
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -12.0,
    )
    assert asr_calls == 1
    assert document.tracks[0].segments[0].text == "texto"


def test_strict_qwen_refuses_text_reuse_if_staged_track_bytes_changed(tmp_path: Path):
    package, root = _two_track_package(tmp_path)

    def reader(path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio=path.name)

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            return f"texto {audio}", "Portuguese"

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
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=reader,
        )

    changed = root / package.tracks[0].path
    original = changed.read_bytes()
    changed.write_bytes(b"X" + original[1:])
    assert changed.stat().st_size == package.tracks[0].size_bytes

    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_TRACK_HASH_MISMATCH"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=lambda *_args: (_ for _ in ()).throw(
                AssertionError("changed source must fail before model load")
            ),
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda *_args: (_ for _ in ()).throw(
                AssertionError("changed source must not reach ASR")
            ),
            aligner_session_factory=lambda _root, _plan: BrokenAligner(),
            window_reader=reader,
        )


def test_strict_qwen_corrupt_text_checkpoint_retranscribes_only_that_track(
    tmp_path: Path,
):
    package, root = _two_track_package(tmp_path)
    asr_calls = 0

    def reader(path: Path):
        yield AudioWindow(index=1, start=0.0, end=2.0, audio=path.name)

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return f"texto {audio}", "Portuguese"

        def close(self):
            pass

    class BrokenAligner:
        def align(self, _audio, _text: str, _language: str):
            raise QwenRuntimeError("QWEN_ALIGNMENT_FAILED")

        def close(self):
            pass

    def attempt():
        with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
            transcribe_craig_package_qwen_strict(
                package,
                root,
                tmp_path / "Models",
                profile_id="qwen-fast",
                plan_resolver=_plan,
                model_prepare=_model_prepare,
                aligner_prepare=_aligner_prepare,
                asr_session_factory=lambda _root, _plan: Asr(),
                aligner_session_factory=lambda _root, _plan: BrokenAligner(),
                window_reader=reader,
            )

    attempt()
    assert asr_calls == 2
    checkpoints = sorted(root.glob(".checkpoints/*/qwen-text-v1/track-*.json"))
    assert len(checkpoints) == 2
    checkpoints[0].write_text("{broken", encoding="utf-8")

    attempt()
    assert asr_calls == 3


@pytest.mark.parametrize(
    "runtime_code",
    (
        "QWEN_CUDA_DRIVER_INCOMPATIBLE",
        "QWEN_ASR_GPU_MEMORY_EXHAUSTED",
        "QWEN_ASR_CUDA_FAILED",
        "QWEN_ASR_RUNTIME_API_FAILED",
    ),
)
def test_strict_alignment_preserves_actionable_runtime_failures(runtime_code: str):
    window = AudioWindow(index=7, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=7,
        start=0.0,
        end=60.0,
        text="texto",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            raise QwenRuntimeError(runtime_code)

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match=runtime_code) as caught:
        _strict_alignment_segments(
            1,
            window,
            pending,
            Aligner(),
            first=True,
            last=True,
        )

    assert caught.value.code == runtime_code
    assert not hasattr(caught.value, "alignment_failure_class")


def test_alignment_failure_class_rejects_arbitrary_private_text():
    error = asr_qwen_strict._alignment_required(
        "C:\\private\\session\\secret.flac",
        aligned_item=3,
    )
    assert error.alignment_failure_class == "QWEN_ALIGNMENT_REQUIRED"
    assert error.alignment_diagnostics == {"aligned_item": 3}


@pytest.mark.parametrize(
    ("aligned", "failure_class"),
    (
        ([{"text": "word", "start_time": "bad", "end_time": 1.0}], "QWEN_ALIGNMENT_TIMESTAMP_PARSE_INVALID"),
        ([{"text": "word", "start_time": float("nan"), "end_time": 1.0}], "QWEN_ALIGNMENT_TIMESTAMP_NONFINITE"),
        ([{"text": "word", "start_time": -0.1, "end_time": 0.1}], "QWEN_ALIGNMENT_TIMESTAMP_NEGATIVE_START"),
        ([{"text": "word", "start_time": 1.0, "end_time": 0.5}], "QWEN_ALIGNMENT_TIMESTAMP_REVERSED"),
        ([{"text": "word", "start_time": 60.4, "end_time": 60.5}], "QWEN_ALIGNMENT_TIMESTAMP_OUTSIDE_WINDOW"),
        ([{"text": "word", "start_time": 10.0, "end_time": 61.0}], "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW"),
        (
            [
                {"text": "first", "start_time": 10.0, "end_time": 11.0},
                {"text": "second", "start_time": 9.0, "end_time": 9.5},
            ],
            "QWEN_ALIGNMENT_TIMESTAMP_NON_MONOTONIC",
        ),
        ([], "QWEN_ALIGNMENT_EMPTY"),
    ),
)
def test_strict_alignment_classifies_failures_without_transcript_payload(
    aligned,
    failure_class: str,
):
    window = AudioWindow(index=42, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=42,
        start=0.0,
        end=60.0,
        text="private transcript must never enter diagnostics",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return aligned

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED") as caught:
        _strict_alignment_segments(
            1,
            window,
            pending,
            Aligner(),
            first=False,
            last=False,
        )

    assert caught.value.alignment_failure_class == failure_class
    assert "private transcript" not in repr(caught.value.alignment_diagnostics)


def test_strict_alignment_ignores_only_non_owned_trailing_overflow():
    window = AudioWindow(index=1, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=1,
        start=0.0,
        end=60.0,
        text="owned neighbor",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "owned", "start_time": 10.0, "end_time": 11.0},
                {"text": "neighbor", "start_time": 59.92, "end_time": 61.68},
            ]

        def close(self):
            pass

    segments, ignored = _strict_alignment_segments(
        1,
        window,
        pending,
        Aligner(),
        first=True,
        last=False,
    )

    assert ignored == 1
    assert len(segments) == 1
    assert segments[0].text == "owned"


def test_strict_alignment_does_not_hide_empty_text_as_safe_neighbor_overflow():
    window = AudioWindow(index=87, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=87,
        start=0.0,
        end=60.0,
        text="texto esperado",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "   ", "start_time": 56.8, "end_time": 61.4},
            ]

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED") as caught:
        _strict_alignment_segments(
            1,
            window,
            pending,
            Aligner(),
            first=False,
            last=False,
        )

    assert caught.value.alignment_failure_class == "QWEN_ALIGNMENT_EMPTY"


def test_strict_alignment_ignores_neighbor_owned_overflow_that_crosses_ownership_boundary():
    window = AudioWindow(index=88, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=88,
        start=0.0,
        end=60.0,
        text="owned crossing",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "owned", "start_time": 10.0, "end_time": 11.0},
                # Starts before the 57s ownership boundary but its midpoint is in
                # the next-window-owned half of the 54-60s overlap. The canonical
                # midpoint ownership rule would drop it after validation, so it is
                # safe to filter before strict overflow validation.
                {"text": "crossing", "start_time": 56.8, "end_time": 61.4},
            ]

        def close(self):
            pass

    segments, ignored = _strict_alignment_segments(
        1,
        window,
        pending,
        Aligner(),
        first=False,
        last=False,
    )

    assert ignored == 1
    assert [segment.text for segment in segments] == ["owned"]


def test_crossing_overlap_word_is_owned_exactly_once_by_adjacent_window():
    first_window = AudioWindow(index=1, start=0.0, end=60.0, audio="w1")
    second_window = AudioWindow(index=2, start=54.0, end=100.0, audio="w2")
    first_pending = QwenWindowTranscript(
        index=1,
        start=0.0,
        end=60.0,
        text="before crossing",
        language="Portuguese",
    )
    second_pending = QwenWindowTranscript(
        index=2,
        start=54.0,
        end=100.0,
        text="crossing after",
        language="Portuguese",
    )

    class FirstAligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "before", "start_time": 10.0, "end_time": 11.0},
                {"text": "crossing", "start_time": 56.8, "end_time": 61.4},
            ]

        def close(self):
            pass

    class SecondAligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "crossing", "start_time": 2.8, "end_time": 7.4},
                {"text": "after", "start_time": 10.0, "end_time": 11.0},
            ]

        def close(self):
            pass

    first_segments, ignored = _strict_alignment_segments(
        1,
        first_window,
        first_pending,
        FirstAligner(),
        first=True,
        last=False,
    )
    second_segments, second_ignored = _strict_alignment_segments(
        1,
        second_window,
        second_pending,
        SecondAligner(),
        first=False,
        last=True,
    )

    combined_words = [
        word.text
        for segment in (*first_segments, *second_segments)
        for word in segment.words
    ]
    assert ignored == 1
    assert second_ignored == 0
    assert combined_words.count("crossing") == 1
    assert combined_words == ["before", "crossing", "after"]


def test_strict_alignment_keeps_owned_overflow_fail_closed():
    window = AudioWindow(index=89, start=0.0, end=60.0, audio="window")
    pending = QwenWindowTranscript(
        index=89,
        start=0.0,
        end=60.0,
        text="degenerate",
        language="Portuguese",
    )

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [
                {"text": "degenerate", "start_time": 0.0, "end_time": 130.16},
            ]

        def close(self):
            pass

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED") as caught:
        _strict_alignment_segments(
            1,
            window,
            pending,
            Aligner(),
            first=False,
            last=False,
        )

    assert caught.value.alignment_failure_class == "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW"
    assert caught.value.alignment_diagnostics["aligned_item"] == 1
    assert caught.value.alignment_diagnostics["overflow_seconds"] > 0


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


def test_strict_qwen_replays_windows_in_lockstep_not_full_track_dict(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.0.6")
    package, root = _package(tmp_path)
    reads = 0
    align_calls: list[str] = []
    reports: list[dict] = []

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
        report=reports.append,
    )

    assert [
        item
        for item in reports
        if item.get("type") == "progress"
    ] == [
        {
            "type": "progress",
            "completed": 1,
            "total": 1,
            "unit": "tracks",
            "stage": "alignment",
        }
    ]
    assert any(
        item.get("type") == "event"
        and item.get("code") == "TRACK_STARTED"
        and item.get("track") == 1
        and item.get("total_tracks") == 1
        and item.get("speaker") == "Alice"
        for item in reports
    )
    assert any(
        item.get("type") == "event"
        and item.get("code") == "TRACK_COMPLETED"
        and item.get("track") == 1
        for item in reports
    )

    stages = [item.get("stage") for item in reports if item.get("type") == "stage"]
    assert "energy_analysis" not in stages
    assert stages.index("alignment") < stages.index("cross_track_dedup")

    # Fresh tracks reuse the alignment windows for dedup energy, so production
    # decodes each track only for ASR + alignment instead of a third energy pass.
    assert reads == 2
    assert align_calls == ["pass-2-one", "pass-2-two"]
    assert "strict-overlap-v4" in document.engine.alignment
    assert document.warnings == ()


def test_strict_qwen_checkpoint_reuse_skips_model_and_only_replays_energy(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.0.6")
    package, root = _package(tmp_path)
    reads = 0

    def reader(_path: Path):
        nonlocal reads
        reads += 1
        yield AudioWindow(index=1, start=0.0, end=2.0, audio=f"pass-{reads}")

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "texto", "Portuguese"
        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "texto", "start_time": 0.1, "end_time": 0.5}]
        def close(self):
            pass

    first = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=_model_prepare,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=lambda _root, _plan: Asr(),
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -12.0,
    )
    assert reads == 2

    second_reports: list[dict] = []
    before = reads

    def forbidden(*_args, **_kwargs):
        raise AssertionError("checkpoint reuse must not load Qwen model or aligner")

    second = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=forbidden,
        aligner_prepare=forbidden,
        asr_session_factory=forbidden,
        aligner_session_factory=forbidden,
        window_reader=reader,
        energy_reader=lambda *_args: -12.0,
        report=second_reports.append,
    )

    assert reads - before == 1
    assert second.as_dict()["tracks"] == first.as_dict()["tracks"]
    assert any(item.get("code") == "ASR_CHECKPOINT_REUSED" for item in second_reports)
    assert {
        "type": "progress",
        "completed": 1,
        "total": 1,
        "unit": "tracks",
        "stage": "source_validation",
    } in second_reports
    stages = [item.get("stage") for item in second_reports if item.get("type") == "stage"]
    assert "model_prepare" not in stages
    assert "model_load" not in stages
    assert "alignment" not in stages
    assert "energy_analysis" in stages

    source = root / package.tracks[0].path
    payload = source.read_bytes()
    original_stat = source.stat()
    source.write_bytes(bytes(byte ^ 1 for byte in payload))
    os.utime(
        source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_TRACK_HASH_MISMATCH"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=forbidden,
            aligner_prepare=forbidden,
            asr_session_factory=forbidden,
            aligner_session_factory=forbidden,
            window_reader=reader,
            energy_reader=lambda *_args: -12.0,
        )
    source.write_bytes(payload)

    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.0.7")
    before_upgrade = reads
    upgraded = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=_model_prepare,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=lambda _root, _plan: Asr(),
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=reader,
        energy_reader=lambda *_args: -12.0,
    )

    assert reads - before_upgrade == 2
    assert upgraded.as_dict()["tracks"] == first.as_dict()["tracks"]


def test_owned_overflow_retries_once_with_bounded_right_context_without_repeat_asr(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []
    asr_calls = 0
    align_calls: list[str] = []
    builder_calls: list[tuple[int, int]] = []

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return f"text {audio}", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, audio, _text: str, _language: str):
            align_calls.append(audio)
            if audio == "w1":
                return [{"text": "owned", "start_time": 10.0, "end_time": 61.0}]
            if audio == "w1+right":
                return [{"text": "owned", "start_time": 10.0, "end_time": 61.0}]
            if audio == "w2":
                return [{"text": "after", "start_time": 10.0, "end_time": 11.0}]
            raise AssertionError(f"unexpected audio {audio}")

        def close(self):
            pass

    def right_context(window: AudioWindow, next_window: AudioWindow):
        builder_calls.append((window.index, next_window.index))
        assert window.index == 1
        assert next_window.index == 2
        return AudioWindow(
            index=window.index,
            start=window.start,
            end=window.end + QWEN_WINDOW_OVERLAP_SECONDS,
            audio="w1+right",
        )

    document = transcribe_craig_package_qwen_strict(
        package,
        root,
        tmp_path / "Models",
        profile_id="qwen-fast",
        plan_resolver=_plan,
        model_prepare=_model_prepare,
        aligner_prepare=_aligner_prepare,
        asr_session_factory=lambda _root, _plan: Asr(),
        aligner_session_factory=lambda _root, _plan: Aligner(),
        window_reader=_two_windows,
        energy_reader=lambda *_args: -12.0,
        right_context_builder=right_context,
        report=reports.append,
    )

    assert asr_calls == 2
    assert align_calls == ["w1", "w1+right", "w2"]
    assert builder_calls == [(1, 2)]
    codes = [item.get("code") for item in reports]
    assert codes.count("QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED") == 1
    assert codes.count("QWEN_ALIGNMENT_WINDOW_RECOVERED") == 1
    assert "QWEN_ALIGNMENT_WINDOW_RECOVERY_FAILED" not in codes
    assert "QWEN_ALIGNMENT_WINDOW_FAILED" not in codes
    words = [
        word.text
        for track in document.tracks
        for segment in track.segments
        for word in segment.words
    ]
    assert words == ["owned", "after"]


def test_owned_overflow_recovery_stays_fail_closed_when_extended_alignment_is_invalid(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []
    asr_calls = 0
    align_calls: list[str] = []

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            nonlocal asr_calls
            asr_calls += 1
            return f"text {audio}", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, audio, _text: str, _language: str):
            align_calls.append(audio)
            if audio in {"w1", "w1+right"}:
                return [
                    {
                        "text": "degenerate",
                        "start_time": 0.0,
                        "end_time": 130.16,
                    }
                ]
            raise AssertionError("second window must not be reached after failed recovery")

        def close(self):
            pass

    def right_context(window: AudioWindow, next_window: AudioWindow):
        return AudioWindow(
            index=window.index,
            start=window.start,
            end=window.end + QWEN_WINDOW_OVERLAP_SECONDS,
            audio="w1+right",
        )

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED") as caught:
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=_two_windows,
            energy_reader=lambda *_args: -12.0,
            right_context_builder=right_context,
            report=reports.append,
        )

    assert asr_calls == 2
    assert align_calls == ["w1", "w1+right"]
    assert (
        caught.value.alignment_failure_class
        == "QWEN_ALIGNMENT_TIMESTAMP_OWNED_OVERFLOW"
    )
    codes = [item.get("code") for item in reports]
    assert codes.count("QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED") == 1
    assert codes.count("QWEN_ALIGNMENT_WINDOW_RECOVERY_FAILED") == 1
    assert codes.count("QWEN_ALIGNMENT_WINDOW_FAILED") == 1
    assert "QWEN_ALIGNMENT_WINDOW_RECOVERED" not in codes


def test_owned_overflow_recovery_honors_cancel_before_second_alignment(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []
    state = {"cancelled": False}
    builder_called = False

    class Asr:
        def transcribe(self, audio, *, prompt: str):
            return f"text {audio}", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, audio, _text: str, _language: str):
            assert audio == "w1"
            state["cancelled"] = True
            return [{"text": "owned", "start_time": 10.0, "end_time": 61.0}]

        def close(self):
            pass

    def right_context(_window: AudioWindow, _next_window: AudioWindow):
        nonlocal builder_called
        builder_called = True
        raise AssertionError("cancel must fence recovery before context construction")

    with pytest.raises(QwenRuntimeError, match="ASR_CANCELLED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=_two_windows,
            energy_reader=lambda *_args: -12.0,
            right_context_builder=right_context,
            is_cancelled=lambda: state["cancelled"],
            report=reports.append,
        )

    assert builder_called is False
    assert not any(
        item.get("code") == "QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED"
        for item in reports
    )


def test_owned_overflow_on_last_window_never_uses_right_context_recovery(
    tmp_path: Path,
):
    package, root = _package(tmp_path)
    reports: list[dict] = []

    def one_window(_path: Path):
        yield AudioWindow(index=1, start=0.0, end=60.0, audio="last")

    class Asr:
        def transcribe(self, _audio, *, prompt: str):
            return "text", "Portuguese"

        def close(self):
            pass

    class Aligner:
        def align(self, _audio, _text: str, _language: str):
            return [{"text": "owned", "start_time": 10.0, "end_time": 61.0}]

        def close(self):
            pass

    def forbidden_builder(*_args):
        raise AssertionError("last window must never request right context")

    with pytest.raises(QwenRuntimeError, match="QWEN_ALIGNMENT_REQUIRED"):
        transcribe_craig_package_qwen_strict(
            package,
            root,
            tmp_path / "Models",
            profile_id="qwen-fast",
            plan_resolver=_plan,
            model_prepare=_model_prepare,
            aligner_prepare=_aligner_prepare,
            asr_session_factory=lambda _root, _plan: Asr(),
            aligner_session_factory=lambda _root, _plan: Aligner(),
            window_reader=one_window,
            energy_reader=lambda *_args: -12.0,
            right_context_builder=forbidden_builder,
            report=reports.append,
        )

    codes = [item.get("code") for item in reports]
    assert "QWEN_ALIGNMENT_WINDOW_RECOVERY_STARTED" not in codes
    assert codes.count("QWEN_ALIGNMENT_WINDOW_FAILED") == 1
