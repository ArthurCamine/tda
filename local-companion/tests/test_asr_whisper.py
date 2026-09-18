from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tda_companion.asr_models import get_profile, model_path, write_install_marker
from tda_companion.asr_whisper import (
    WhisperRuntimeError,
    prepare_whisper_model,
    resolve_whisper_plan,
    transcribe_craig_package,
    whisper_transcribe_options,
)
from tda_companion.craig import CraigPackage, CraigTrack


def _install_whisper_fixture(models_root: Path, profile_id: str = "whisper-turbo") -> Path:
    profile = get_profile(profile_id)
    directory = model_path(models_root, profile)
    directory.mkdir(parents=True)
    for name in profile.required_files:
        (directory / name).write_bytes(f"fixture:{name}".encode("utf-8"))
    write_install_marker(directory, profile)
    return directory


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


def test_craig_whisper_reuses_exact_track_checkpoint(tmp_path: Path):
    models_root = tmp_path / "Models"
    _install_whisper_fixture(models_root)
    package_root = tmp_path / "Data" / "staging" / "fixture-source"
    track_root = package_root / "tracks"
    track_root.mkdir(parents=True)
    track_file = track_root / "1-Alice.flac"
    track_file.write_bytes(b"fake-flac-for-checkpoint")

    track = CraigTrack(
        number=1,
        speaker="Alice",
        filename="1-Alice.flac",
        path="tracks/1-Alice.flac",
        size_bytes=track_file.stat().st_size,
        sha256="b" * 64,
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
    calls = {"transcribe": 0}

    class FakeModel:
        def transcribe(self, _path: str, **_options):
            calls["transcribe"] += 1
            words = [SimpleNamespace(word=" Olá", start=0.1, end=0.4, probability=0.9)]
            segments = [
                SimpleNamespace(id=0, start=0.1, end=0.4, text="Olá", words=words)
            ]
            return iter(segments), SimpleNamespace(duration=2.0)

    def loader(_path, plan):
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
    assert second.as_dict()["tracks"] == first.as_dict()["tracks"]
    assert second.as_dict()["turns"] == first.as_dict()["turns"]
    assert any(item.get("code") == "ASR_CHECKPOINT_SAVED" for item in first_reports)
    assert any(item.get("code") == "ASR_CHECKPOINT_REUSED" for item in second_reports)

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
    assert calls["transcribe"] == 2
