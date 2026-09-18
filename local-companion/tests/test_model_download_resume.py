from __future__ import annotations

from pathlib import Path

import pytest

from tda_companion.asr_models import get_profile
from tda_companion.asr_whisper import WhisperRuntimeError, prepare_whisper_model
from tda_companion.qwen_acceptance import QwenAcceptanceError, prepare_qwen_model


def _write_required(root: Path, required_files: tuple[str, ...], prefix: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(required_files, start=1):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{prefix}:{index}".encode())


def test_whisper_network_failure_keeps_partial_and_next_attempt_reuses_it(tmp_path: Path):
    profile = get_profile("whisper-turbo")
    seen: list[Path] = []

    def fail(model_id: str, *, output_dir: str, revision: str):
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "partial.bin").write_bytes(b"resume-me")
        seen.append(root)
        raise OSError("temporary network failure")

    with pytest.raises(WhisperRuntimeError, match="WHISPER_MODEL_DOWNLOAD_FAILED"):
        prepare_whisper_model(tmp_path, profile, downloader=fail)

    partials = list((tmp_path / ".downloads").glob(f"{profile.directory}-*.partial"))
    assert len(partials) == 1
    assert (partials[0] / "partial.bin").read_bytes() == b"resume-me"

    def finish(model_id: str, *, output_dir: str, revision: str):
        root = Path(output_dir)
        seen.append(root)
        assert (root / "partial.bin").read_bytes() == b"resume-me"
        _write_required(root, profile.required_files, "whisper")

    target = prepare_whisper_model(tmp_path, profile, downloader=finish)

    assert seen[0] == seen[1]
    assert target.is_dir()
    assert not list((tmp_path / ".downloads").glob(f"{profile.directory}-*.partial"))


def test_qwen_network_failure_keeps_partial_and_next_attempt_reuses_it(tmp_path: Path):
    profile = get_profile("qwen-fast")
    seen: list[Path] = []

    def fail(*, repo_id: str, revision: str, local_dir: str):
        root = Path(local_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "partial.bin").write_bytes(b"resume-me")
        seen.append(root)
        raise OSError("temporary network failure")

    with pytest.raises(QwenAcceptanceError, match="QWEN_MODEL_DOWNLOAD_FAILED"):
        prepare_qwen_model(tmp_path, profile, downloader=fail)

    partials = list((tmp_path / ".downloads").glob(f"{profile.directory}-*.partial"))
    assert len(partials) == 1
    assert (partials[0] / "partial.bin").read_bytes() == b"resume-me"

    def finish(*, repo_id: str, revision: str, local_dir: str):
        root = Path(local_dir)
        seen.append(root)
        assert (root / "partial.bin").read_bytes() == b"resume-me"
        _write_required(root, profile.required_files, "qwen")

    target = prepare_qwen_model(tmp_path, profile, downloader=finish)

    assert seen[0] == seen[1]
    assert target.is_dir()
    assert not list((tmp_path / ".downloads").glob(f"{profile.directory}-*.partial"))


def test_whisper_incomplete_target_is_repaired_automatically(tmp_path: Path):
    profile = get_profile("whisper-turbo")
    stale = tmp_path / profile.directory
    stale.mkdir()
    (stale / "stale.txt").write_text("old", encoding="utf-8")

    def finish(model_id: str, *, output_dir: str, revision: str):
        root = Path(output_dir)
        assert not stale.exists()
        _write_required(root, profile.required_files, "whisper-repaired")

    target = prepare_whisper_model(tmp_path, profile, downloader=finish)

    assert target.is_dir()
    assert not (target / "stale.txt").exists()


def test_qwen_incomplete_target_is_repaired_automatically(tmp_path: Path):
    profile = get_profile("qwen-fast")
    stale = tmp_path / profile.directory
    stale.mkdir()
    (stale / "stale.txt").write_text("old", encoding="utf-8")

    def finish(*, repo_id: str, revision: str, local_dir: str):
        root = Path(local_dir)
        assert not stale.exists()
        _write_required(root, profile.required_files, "qwen-repaired")

    target = prepare_qwen_model(tmp_path, profile, downloader=finish)

    assert target.is_dir()
    assert not (target / "stale.txt").exists()
