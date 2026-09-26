from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.asr_whisper as asr_whisper
from tda_companion.asr_models import get_profile, model_path, write_install_marker
from tda_companion.asr_whisper import (
    WhisperRuntimeError,
    _whisper_runtime_fingerprint,
    prepare_whisper_model,
    resolve_whisper_plan,
    transcribe_craig_package,
    whisper_transcribe_options,
)
from tda_companion.craig import CraigPackage, CraigPackageError, CraigTrack


def _install_whisper_fixture(models_root: Path, profile_id: str = "whisper-turbo") -> Path:
    profile = get_profile(profile_id)
    directory = model_path(models_root, profile)
    directory.mkdir(parents=True)
    for name in profile.required_files:
        (directory / name).write_bytes(f"fixture:{name}".encode("utf-8"))
    write_install_marker(directory, profile)
    return directory


def test_whisper_resumable_staging_ignores_redirected_partial(tmp_path: Path):
    downloads = tmp_path / ".downloads"
    downloads.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = downloads / "whisper-small-redirect.partial"
    try:
        redirected.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this runner")

    chosen = asr_whisper._resumable_model_staging(downloads, "whisper-small")

    assert chosen != redirected
    assert chosen.parent == downloads
    assert chosen.name.startswith("whisper-small-")
    assert chosen.name.endswith(".partial")


def test_whisper_checkpoint_pipeline_revision_is_explicit():
    assert "checkpoint=whisper-track-v2" in _whisper_runtime_fingerprint()


def test_whisper_plan_prefers_float16_and_only_uses_cpu_when_requested():
    status = {"available": True, "supported_compute_types": ["float16", "int8_float16"]}
    plan = resolve_whisper_plan("whisper-turbo", cuda_status=status)
    assert plan.device == "cuda"
    assert plan.compute_type == "float16"
    assert plan.fallback_compute_type == "int8_float16"
    assert plan.cpu_requested is False

    cpu_plan = resolve_whisper_plan("whisper-turbo", cpu=True, cuda_status={"available": False})
    assert cpu_plan.device == "cpu"
    assert cpu_plan.compute_type == "int8"
    assert cpu_plan.fallback_compute_type is None

    with pytest.raises(WhisperRuntimeError, match="WHISPER_CUDA_UNAVAILABLE"):
        resolve_whisper_plan("whisper-turbo", cuda_status={"available": False})


def test_whisper_recipe_preserves_v03_contract():
    options = whisper_transcribe_options(glossary="Yuhara   Pipipi", context="mesa   principal")
    assert options == {
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
        "hotwords": "Yuhara Pipipi",
        "initial_prompt": (
            "Sessão de RPG Dungeons & Dragons em português. "
            "Contexto da campanha: mesa principal "
            "Nomes e termos importantes: Yuhara Pipipi"
        ),
    }


def test_model_prepare_uses_tda_marker_and_no_fake_percent(tmp_path: Path):
    profile = get_profile("whisper-turbo")
    reports: list[dict] = []

    def downloader(model_id: str, *, output_dir: str, revision: str):
        assert model_id == profile.model_id
        assert revision == profile.revision
        directory = Path(output_dir)
        directory.mkdir(parents=True)
        for name in profile.required_files:
            (directory / name).write_bytes(name.encode("utf-8"))

    result = prepare_whisper_model(tmp_path, profile, downloader=downloader, report=reports.append)
    assert result == model_path(tmp_path, profile)
    assert (result / ".tda-model.json").is_file()
    assert reports[0] == {"type": "stage", "stage": "model_prepare", "profile": profile.id}
    download = next(item for item in reports if item.get("code") == "MODEL_DOWNLOAD_PROGRESS")
    assert download["stage"] == "model_prepare"
    assert download["profile"] == profile.id
    assert int(download["downloaded_bytes"]) > 0
    assert all("percent" not in item for item in reports)


def test_whisper_reports_runtime_validation_before_cuda_probe(monkeypatch, tmp_path: Path):
    reports: list[dict] = []
    package_root = tmp_path / "Data" / "staging" / "runtime-stage"
    package_root.mkdir(parents=True)
    package = CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip="fixture.zip",
        source_sha256="a" * 64,
        recording_id="runtime-stage",
        guild=None,
        channel=None,
        requester=None,
        start_time=None,
        tracks=(),
        info_present=False,
        raw_dat_present=False,
    )

    def resolve(*_args, **_kwargs):
        assert reports[-1] == {
            "type": "stage",
            "stage": "runtime_validation",
            "profile": "whisper-turbo",
        }
        raise WhisperRuntimeError("TEST_STOP_AFTER_RUNTIME_VALIDATION")

    monkeypatch.setattr(asr_whisper, "resolve_whisper_plan", resolve)

    with pytest.raises(WhisperRuntimeError, match="TEST_STOP_AFTER_RUNTIME_VALIDATION"):
        transcribe_craig_package(
            package,
            package_root,
            tmp_path / "Models",
            profile_id="whisper-turbo",
            report=reports.append,
        )

    assert reports == [
        {
            "type": "stage",
            "stage": "runtime_validation",
            "profile": "whisper-turbo",
        }
    ]


def test_craig_whisper_adapter_emits_engine_independent_transcript(tmp_path: Path):
    models_root = tmp_path / "Models"
    _install_whisper_fixture(models_root)
    package_root = tmp_path / "Data" / "staging" / "fixture-source"
    track_root = package_root / "tracks"
    track_root.mkdir(parents=True)
    track_file = track_root / "1-Alice.flac"
    track_file.write_bytes(b"fake-flac-for-unit-test")

    package = CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip="fixture.zip",
        source_sha256="a" * 64,
        recording_id="craig-fixture",
        guild="Guild",
        channel="mesa",
        requester="Alice",
        start_time=None,
        tracks=(
            CraigTrack(
                number=1,
                speaker="Alice",
                filename="1-Alice.flac",
                path="tracks/1-Alice.flac",
                size_bytes=track_file.stat().st_size,
                sha256="b" * 64,
                identity=None,
            ),
        ),
        info_present=True,
        raw_dat_present=False,
    )

    captured: dict[str, object] = {}

    class FakeModel:
        def transcribe(self, path: str, **options):
            captured["path"] = path
            captured["options"] = options
            words = [
                SimpleNamespace(word=" Olá", start=0.10, end=0.40, probability=0.91),
                SimpleNamespace(word=" Yuhara", start=0.41, end=0.90, probability=0.94),
            ]
            segments = [
                SimpleNamespace(
                    id=0,
                    start=0.10,
                    end=0.90,
                    text="Olá Yuhara",
                    words=words,
                )
            ]
            info = SimpleNamespace(duration=2.0, language="pt", language_probability=0.99)
            return iter(segments), info

    def loader(path, plan):
        captured["model_path"] = path
        captured["plan"] = plan
        return FakeModel(), plan.compute_type, False

    reports: list[dict] = []
    document = transcribe_craig_package(
        package,
        package_root,
        models_root,
        profile_id="whisper-turbo",
        glossary="Yuhara",
        context="campanha principal",
        cuda_status={"available": True, "supported_compute_types": ["float16", "int8_float16"]},
        model_loader=loader,
        report=reports.append,
    )

    value = document.as_dict()
    assert value["schema_version"] == "tda_transcript_v1"
    assert value["recording_id"] == "craig-fixture"
    assert value["engine"]["engine"] == "whisper"
    assert value["engine"]["profile"] == "whisper-turbo"
    assert value["engine"]["device"] == "cuda"
    assert value["engine"]["compute_type"] == "float16"
    assert value["tracks"][0]["speaker"] == "Alice"
    assert value["tracks"][0]["segments"][0]["text"] == "Olá Yuhara"
    assert value["tracks"][0]["segments"][0]["words"][1]["text"] == "Yuhara"
    assert value["stats"]["track_count"] == 1
    assert value["stats"]["segment_count"] == 1
    assert value["stats"]["word_count"] == 2
    assert value["stats"]["turn_count"] == 1
    assert value["stats"]["deduplicated_segment_count"] == 0
    assert value["turns"] == (
        {
            "id": "turn-000001",
            "speaker": "Alice",
            "start": 0.1,
            "end": 0.9,
            "text": "Olá Yuhara",
            "segments": ({"track_number": 1, "segment_id": "1-0"},),
            "overlaps_other_speaker": False,
        },
    )
    assert captured["path"] == str(track_file.resolve())
    assert captured["options"]["language"] == "pt"
    assert captured["options"]["beam_size"] == 5
    assert any(
        item == {
            "type": "progress",
            "completed": 1,
            "total": 1,
            "unit": "tracks",
            "stage": "transcription",
        }
        for item in reports
    )
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
        and item.get("code") == "WHISPER_SEGMENT_TRANSCRIBED"
        and item.get("track") == 1
        and item.get("total_tracks") == 1
        and item.get("speaker") == "Alice"
        and item.get("segment") == 1
        for item in reports
    )
    assert any(
        item.get("type") == "event"
        and item.get("code") == "TRACK_COMPLETED"
        and item.get("track") == 1
        and item.get("total_tracks") == 1
        and item.get("speaker") == "Alice"
        for item in reports
    )
    stages = [item.get("stage") for item in reports if item.get("type") == "stage"]
    assert stages[-4:] == ["cross_track_dedup", "merge_timeline", "turn_building", "result_prepare"]


def test_craig_adapter_rejects_track_escape(tmp_path: Path):
    models_root = tmp_path / "Models"
    _install_whisper_fixture(models_root)
    package_root = tmp_path / "package"
    package_root.mkdir()
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"audio")
    package = CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip="fixture.zip",
        source_sha256="a" * 64,
        recording_id=None,
        guild=None,
        channel=None,
        requester=None,
        start_time=None,
        tracks=(
            CraigTrack(
                number=1,
                speaker="Alice",
                filename="outside.flac",
                path="../outside.flac",
                size_bytes=5,
                sha256="b" * 64,
                identity=None,
            ),
        ),
        info_present=False,
        raw_dat_present=False,
    )

    with pytest.raises(WhisperRuntimeError, match="CRAIG_TRACK_PATH_INVALID"):
        transcribe_craig_package(
            package,
            package_root,
            models_root,
            profile_id="whisper-turbo",
            cuda_status={"available": True, "supported_compute_types": ["float16"]},
            model_loader=lambda path, plan: (object(), plan.compute_type, False),
        )


def test_craig_whisper_reuses_exact_track_checkpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.1.3")
    models_root = tmp_path / "Models"
    _install_whisper_fixture(models_root)
    package_root = tmp_path / "Data" / "staging" / "fixture-source"
    track_root = package_root / "tracks"
    track_root.mkdir(parents=True)
    track_file = track_root / "1-Alice.flac"
    payload = b"fake-flac-for-checkpoint"
    track_file.write_bytes(payload)

    track = CraigTrack(
        number=1,
        speaker="Alice",
        filename="1-Alice.flac",
        path="tracks/1-Alice.flac",
        size_bytes=track_file.stat().st_size,
        sha256=hashlib.sha256(payload).hexdigest(),
        identity=None,
    )
    package = CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip="fixture.zip",
        source_sha256="a" * 64,
        recording_id="craig-checkpoint",
        guild=None,
        channel=None,
        requester=None,
        start_time=None,
        tracks=(track,),
        info_present=False,
        raw_dat_present=False,
    )
    calls = {"transcribe": 0, "load": 0}

    class FakeModel:
        def transcribe(self, _path: str, **_options):
            calls["transcribe"] += 1
            words = [SimpleNamespace(word=" Olá", start=0.1, end=0.4, probability=0.9)]
            segments = [
                SimpleNamespace(id=0, start=0.1, end=0.4, text="Olá", words=words)
            ]
            return iter(segments), SimpleNamespace(duration=2.0)

    def loader(_path, plan):
        calls["load"] += 1
        return FakeModel(), plan.compute_type, False

    common = {
        "profile_id": "whisper-turbo",
        "glossary": "Yuhara",
        "context": "campanha principal",
        "cuda_status": {"available": True, "supported_compute_types": ["float16"]},
        "model_loader": loader,
    }
    first_reports: list[dict] = []
    first = transcribe_craig_package(
        package,
        package_root,
        models_root,
        report=first_reports.append,
        **common,
    )
    second_reports: list[dict] = []
    second = transcribe_craig_package(
        package,
        package_root,
        models_root,
        report=second_reports.append,
        **common,
    )

    assert calls["transcribe"] == 1
    assert calls["load"] == 1
    assert second.as_dict()["tracks"] == first.as_dict()["tracks"]
    assert second.as_dict()["turns"] == first.as_dict()["turns"]
    assert any(item.get("code") == "ASR_CHECKPOINT_SAVED" for item in first_reports)
    assert any(item.get("code") == "ASR_CHECKPOINT_REUSED" for item in second_reports)
    assert any(item.get("code") == "ASR_CHECKPOINT_FAST_PATH" for item in second_reports)
    assert "model_load" not in [
        item.get("stage") for item in second_reports if item.get("type") == "stage"
    ]

    original_stat = track_file.stat()
    track_file.write_bytes(bytes(byte ^ 1 for byte in payload))
    os.utime(
        track_file,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    with pytest.raises(CraigPackageError, match="CRAIG_MANIFEST_TRACK_HASH_MISMATCH"):
        transcribe_craig_package(
            package,
            package_root,
            models_root,
            report=lambda _item: None,
            **common,
        )
    track_file.write_bytes(payload)

    monkeypatch.setenv("TDA_ASR_RUNTIME_VERSION", "1.1.4")
    transcribe_craig_package(
        package,
        package_root,
        models_root,
        report=lambda _item: None,
        **common,
    )
    assert calls["transcribe"] == 2
    assert calls["load"] == 2

    transcribe_craig_package(
        package,
        package_root,
        models_root,
        context="contexto alterado",
        glossary="Yuhara",
        profile_id="whisper-turbo",
        cuda_status={"available": True, "supported_compute_types": ["float16"]},
        model_loader=loader,
    )
    assert calls["transcribe"] == 3
    assert calls["load"] == 3


def test_whisper_model_load_emits_sanitized_milestones(monkeypatch, tmp_path: Path):
    import sys
    import types

    module = types.ModuleType("faster_whisper")

    class FakeWhisperModel:
        def __init__(self, path: str, *, device: str, compute_type: str):
            assert path == str(tmp_path)
            assert device == "cuda"
            assert compute_type == "float16"

    module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    reports: list[dict] = []
    plan = asr_whisper.WhisperPlan(
        profile_id="whisper-turbo",
        device="cuda",
        compute_type="float16",
        fallback_compute_type="int8_float16",
        cpu_requested=False,
    )

    _model, compute_type, used_fallback = asr_whisper.load_whisper_model(
        tmp_path,
        plan,
        report=reports.append,
    )

    assert compute_type == "float16"
    assert used_fallback is False
    codes = [item.get("code") for item in reports]
    assert codes == [
        "WHISPER_RUNTIME_IMPORT_STARTED",
        "WHISPER_RUNTIME_IMPORT_READY",
        "WHISPER_MODEL_CONSTRUCT_STARTED",
        "WHISPER_MODEL_CONSTRUCT_READY",
    ]
    assert all(item.get("stage") == "model_load" for item in reports)
    assert all("path" not in item for item in reports)
    assert reports[2]["device"] == "cuda"
    assert reports[2]["compute_type"] == "float16"
    assert int(reports[1]["duration_ms"]) >= 0
    assert int(reports[3]["duration_ms"]) >= 0



def test_whisper_model_load_uses_preloaded_class_without_late_import(
    monkeypatch,
    tmp_path: Path,
):
    import builtins

    calls: list[tuple[str, str]] = []

    class PreloadedWhisperModel:
        def __init__(self, path: str, *, device: str, compute_type: str):
            calls.append((device, compute_type))
            assert path == str(tmp_path)

    monkeypatch.setattr(
        asr_whisper,
        "_PRELOADED_WHISPER_MODEL_CLASS",
        PreloadedWhisperModel,
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "faster_whisper" or name.startswith("faster_whisper."):
            raise AssertionError("preloaded worker must not import faster_whisper inside model_load")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reports: list[dict] = []
    plan = asr_whisper.WhisperPlan(
        profile_id="whisper-turbo",
        device="cuda",
        compute_type="float16",
        fallback_compute_type="int8_float16",
        cpu_requested=False,
    )

    _model, compute_type, used_fallback = asr_whisper.load_whisper_model(
        tmp_path,
        plan,
        report=reports.append,
    )

    assert calls == [("cuda", "float16")]
    assert compute_type == "float16"
    assert used_fallback is False
    imported = next(
        item for item in reports if item.get("code") == "WHISPER_RUNTIME_IMPORT_READY"
    )
    assert imported["preloaded"] is True
    assert any(
        item.get("code") == "WHISPER_MODEL_CONSTRUCT_READY"
        for item in reports
    )


def test_bind_preloaded_whisper_model_class_rejects_non_callable(monkeypatch):
    monkeypatch.setattr(asr_whisper, "_PRELOADED_WHISPER_MODEL_CLASS", None)
    with pytest.raises(
        asr_whisper.WhisperRuntimeError,
        match="WHISPER_RUNTIME_PRELOAD_INVALID",
    ):
        asr_whisper.bind_preloaded_whisper_model_class(object())
