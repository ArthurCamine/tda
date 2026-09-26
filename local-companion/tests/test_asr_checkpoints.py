from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import tda_companion.asr_checkpoints as checkpoints_module
from tda_companion.asr_checkpoints import (
    QwenTextCheckpointWindow,
    build_checkpoint_signature,
    load_qwen_text_checkpoint,
    load_track_checkpoint,
    save_qwen_text_checkpoint,
    save_track_checkpoint,
)
from tda_companion.asr_models import get_profile
from tda_companion.craig import CraigPackage, CraigTrack
from tda_companion.transcript import TranscriptSegment, TranscriptTrack, TranscriptWord


def _source_track() -> CraigTrack:
    return CraigTrack(
        number=1,
        speaker="Alice",
        filename="1-Alice.flac",
        path="tracks/1-Alice.flac",
        size_bytes=123,
        sha256="b" * 64,
        identity=None,
        timeline_offset_seconds=0.0,
    )


def _package(track: CraigTrack) -> CraigPackage:
    return CraigPackage(
        schema_version="tda_craig_package_v1",
        source_zip="fixture.zip",
        source_sha256="a" * 64,
        recording_id="fixture",
        guild=None,
        channel=None,
        requester=None,
        start_time=None,
        tracks=(track,),
        info_present=False,
        raw_dat_present=False,
    )


def _transcript_track(track: CraigTrack) -> TranscriptTrack:
    return TranscriptTrack(
        number=track.number,
        speaker=track.speaker,
        source_filename=track.filename,
        source_sha256=track.sha256,
        duration_seconds=2.0,
        timeline_offset_seconds=track.timeline_offset_seconds,
        identity=None,
        segments=(
            TranscriptSegment(
                id="1-0",
                start=0.1,
                end=0.8,
                text="Olá mesa",
                words=(
                    TranscriptWord(text="Olá", start=0.1, end=0.3, confidence=0.9),
                    TranscriptWord(text="mesa", start=0.4, end=0.8, confidence=0.95),
                ),
            ),
        ),
    )


def _text_windows() -> tuple[QwenTextCheckpointWindow, ...]:
    return (
        QwenTextCheckpointWindow(
            index=1,
            start=0.0,
            end=2.0,
            text="Olá mesa",
            language="Portuguese",
        ),
        QwenTextCheckpointWindow(
            index=2,
            start=1.5,
            end=3.0,
            text="Segunda janela",
            language="Portuguese",
        ),
    )


def _signature(*, context: str = "mesa"):
    track = _source_track()
    return build_checkpoint_signature(
        _package(track),
        get_profile("whisper-turbo"),
        recipe={"vad": {"silence_ms": 500}, "beam": 5},
        context=context,
        glossary="Yuhara",
        runtime_fingerprint="faster-whisper=1.2.1;ctranslate2=4.8.2",
    )


def _qwen_signature(*, context: str = "mesa"):
    track = _source_track()
    return build_checkpoint_signature(
        _package(track),
        get_profile("qwen-fast"),
        recipe={
            "window_seconds": 60.0,
            "window_overlap_seconds": 6.0,
            "alignment_policy": "strict-overlap-v2",
        },
        context=context,
        glossary="Yuhara",
        runtime_fingerprint="qwen-runtime-a",
    )


def test_checkpoint_roundtrip_reuses_only_exact_source_and_signature(tmp_path: Path):
    track = _source_track()
    signature = _signature()
    expected = _transcript_track(track)

    path = save_track_checkpoint(tmp_path, signature, track, expected)
    assert path.is_file()
    restored = load_track_checkpoint(tmp_path, signature, track)
    assert restored == expected

    changed_context = _signature(context="outra mesa")
    assert load_track_checkpoint(tmp_path, changed_context, track) is None

    changed_track = CraigTrack(
        **{**track.__dict__, "sha256": "c" * 64},
    )
    assert load_track_checkpoint(tmp_path, signature, changed_track) is None


def test_corrupt_or_oversized_checkpoint_is_ignored(tmp_path: Path):
    track = _source_track()
    signature = _signature()
    path = save_track_checkpoint(tmp_path, signature, track, _transcript_track(track))

    path.write_text("{not-json", encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None


def test_completed_track_checkpoint_rejects_semantic_tamper_and_schema_drift(tmp_path: Path):
    track = _source_track()
    signature = _signature()
    path = save_track_checkpoint(tmp_path, signature, track, _transcript_track(track))

    original = json.loads(path.read_text(encoding="utf-8"))
    assert original["schema"] == "tda_asr_track_checkpoint_v2"
    assert len(original["content_sha256"]) == 64

    tampered_text = json.loads(json.dumps(original))
    tampered_text["track"]["segments"][0]["text"] = "conteúdo alterado"
    path.write_text(json.dumps(tampered_text), encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None

    tampered_word = json.loads(json.dumps(original))
    tampered_word["track"]["segments"][0]["words"][0]["end"] = 0.25
    path.write_text(json.dumps(tampered_word), encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None

    tampered_metadata = json.loads(json.dumps(original))
    tampered_metadata["track"]["duration_seconds"] = 2.5
    path.write_text(json.dumps(tampered_metadata), encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None

    bad_digest = json.loads(json.dumps(original))
    bad_digest["content_sha256"] = "0" * 64
    path.write_text(json.dumps(bad_digest), encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None

    unknown_track_field = json.loads(json.dumps(original))
    unknown_track_field["track"]["debug_text_copy"] = "not supported"
    unknown_track_field["content_sha256"] = checkpoints_module._canonical_json_hash(
        {
            "track_source_sha256": unknown_track_field["track_source_sha256"],
            "track": unknown_track_field["track"],
        }
    )
    path.write_text(json.dumps(unknown_track_field), encoding="utf-8")
    assert load_track_checkpoint(tmp_path, signature, track) is None

    for mutate in (
        lambda value: value["track"]["segments"][0].__setitem__("debug", "x"),
        lambda value: value["track"]["segments"][0]["words"][0].__setitem__("debug", "x"),
        lambda value: value["track"].__setitem__(
            "identity",
            {
                "username": "Alice",
                "discriminator": None,
                "discord_id": None,
                "debug": "x",
            },
        ),
    ):
        nested_drift = json.loads(json.dumps(original))
        mutate(nested_drift)
        nested_drift["content_sha256"] = checkpoints_module._canonical_json_hash(
            {
                "track_source_sha256": nested_drift["track_source_sha256"],
                "track": nested_drift["track"],
            }
        )
        path.write_text(json.dumps(nested_drift), encoding="utf-8")
        assert load_track_checkpoint(tmp_path, signature, track) is None


def test_completed_track_checkpoint_v1_is_an_untrusted_cache_miss(tmp_path: Path):
    track = _source_track()
    signature = _signature()
    path = save_track_checkpoint(tmp_path, signature, track, _transcript_track(track))

    value = json.loads(path.read_text(encoding="utf-8"))
    value["schema"] = "tda_asr_track_checkpoint_v1"
    value.pop("content_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    assert load_track_checkpoint(tmp_path, signature, track) is None


def test_qwen_text_checkpoint_roundtrip_requires_exact_signature_and_track(tmp_path: Path):
    track = _source_track()
    signature = _qwen_signature()
    expected = _text_windows()

    path = save_qwen_text_checkpoint(tmp_path, signature, track, expected)
    assert path.is_file()
    assert load_qwen_text_checkpoint(tmp_path, signature, track) == expected

    assert load_qwen_text_checkpoint(
        tmp_path,
        _qwen_signature(context="outra mesa"),
        track,
    ) is None
    changed_track = CraigTrack(**{**track.__dict__, "sha256": "c" * 64})
    assert load_qwen_text_checkpoint(tmp_path, signature, changed_track) is None


def test_qwen_text_checkpoint_rejects_corruption_tampering_and_partial_files(tmp_path: Path):
    track = _source_track()
    signature = _qwen_signature()
    path = save_qwen_text_checkpoint(tmp_path, signature, track, _text_windows())

    value = json.loads(path.read_text(encoding="utf-8"))
    value["windows"][0]["text"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_qwen_text_checkpoint(tmp_path, signature, track) is None

    path.write_text("{not-json", encoding="utf-8")
    assert load_qwen_text_checkpoint(tmp_path, signature, track) is None

    path.unlink()
    partial = path.with_name(path.name + ".interrupted.partial")
    partial.write_text("{}", encoding="utf-8")
    assert load_qwen_text_checkpoint(tmp_path, signature, track) is None


def test_qwen_text_checkpoint_size_limit_fails_closed(
    monkeypatch,
    tmp_path: Path,
):
    track = _source_track()
    signature = _qwen_signature()
    monkeypatch.setattr(checkpoints_module, "MAX_CHECKPOINT_BYTES", 128)

    with pytest.raises(ValueError, match="CHECKPOINT_SIZE_LIMIT"):
        save_qwen_text_checkpoint(tmp_path, signature, track, _text_windows())


def test_qwen_text_checkpoint_rejects_symlinked_checkpoint_root(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    checkpoint_root = tmp_path / ".checkpoints"
    try:
        checkpoint_root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this runner")

    track = _source_track()
    signature = _qwen_signature()
    assert load_qwen_text_checkpoint(tmp_path, signature, track) is None
    with pytest.raises(ValueError, match="CHECKPOINT_PATH_SYMLINK"):
        save_qwen_text_checkpoint(tmp_path, signature, track, _text_windows())
    assert list(outside.iterdir()) == []


def test_qwen_text_signature_invalidates_every_reuse_lineage_input():
    package = _package(_source_track())
    profile = get_profile("qwen-fast")

    def digest(
        *,
        candidate=profile,
        recipe=None,
        context="mesa",
        glossary="Yuhara",
        runtime="runtime-a",
    ):
        return build_checkpoint_signature(
            package,
            candidate,
            recipe=recipe or {"window_seconds": 60, "alignment_policy": "strict-overlap-v2"},
            context=context,
            glossary=glossary,
            runtime_fingerprint=runtime,
        ).digest()

    baseline = digest()
    variants = {
        digest(candidate=replace(profile, id="qwen-fast-v2")),
        digest(candidate=replace(profile, model_id="Qwen/changed-model")),
        digest(candidate=replace(profile, revision="changed-revision")),
        digest(candidate=replace(profile, alignment="Qwen/changed-aligner")),
        digest(candidate=replace(profile, alignment_revision="changed-aligner-revision")),
        digest(recipe={"window_seconds": 61, "alignment_policy": "strict-overlap-v2"}),
        digest(context="outra mesa"),
        digest(glossary="Outro nome"),
        digest(runtime="runtime-b"),
    }

    assert baseline not in variants
    assert len(variants) == 9


def test_signature_changes_for_runtime_recipe_model_inputs():
    package = _package(_source_track())
    profile = get_profile("whisper-turbo")
    first = build_checkpoint_signature(
        package,
        profile,
        recipe={"beam": 5},
        context="mesa",
        glossary="Yuhara",
        runtime_fingerprint="runtime-a",
    )
    second = build_checkpoint_signature(
        package,
        profile,
        recipe={"beam": 6},
        context="mesa",
        glossary="Yuhara",
        runtime_fingerprint="runtime-a",
    )
    third = build_checkpoint_signature(
        package,
        profile,
        recipe={"beam": 5},
        context="mesa",
        glossary="Yuhara",
        runtime_fingerprint="runtime-b",
    )

    assert first.digest() != second.digest()
    assert first.digest() != third.digest()
