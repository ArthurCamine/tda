from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from tda_companion.asr_runtime import install_whisper_runtime_archive
from tda_companion.craig import ingest_craig_zip
from tda_companion.worker_protocol import WorkerProtocolError
from tda_companion.worker_supervisor import WorkerProcessError, WorkerSupervisor


def _stage_craig(data_root: Path, source_id: str = "source-123") -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    source = data_root.parent / "fixture.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("1-Alice.flac", b"fLaC-worker-boundary")
    ingest_craig_zip(source, data_root / "staging" / source_id)


def _install_old_whisper(runtime_root: Path) -> None:
    archive = runtime_root.parent / "old-whisper.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("TDAWhisperWorker.exe", b"old-worker")
        bundle.writestr("_internal/runtime.dll", b"runtime")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    install_whisper_runtime_archive(
        archive,
        runtime_root,
        version="1.1.1",
        expected_sha256=digest,
    )


def test_supervisor_requires_fixed_asr_roots_before_spawn():
    supervisor = WorkerSupervisor()
    with pytest.raises(WorkerProcessError, match="WORKER_ASR_ROOTS_UNCONFIGURED"):
        supervisor.run_craig(
            job_id="asr-job",
            attempt=1,
            source_id="source-123",
            profile_id="qwen-fast",
            glossary="",
            context="",
            cpu=False,
            on_progress=lambda _message: None,
        )


def test_supervisor_validates_opaque_source_before_spawn(tmp_path: Path):
    sentinel = tmp_path / "spawned.txt"
    script = tmp_path / "worker.py"
    script.write_text(
        "from pathlib import Path; Path(r'" + str(sentinel).replace("\\", "\\\\") + "').write_text('spawned')",
        encoding="utf-8",
    )
    supervisor = WorkerSupervisor(
        command_factory=lambda: [sys.executable, str(script)],
        data_root=tmp_path / "Data",
        models_root=tmp_path / "Models",
    )
    with pytest.raises(WorkerProtocolError, match="WORKER_SOURCE_ID_INVALID"):
        supervisor.run_craig(
            job_id="asr-job",
            attempt=1,
            source_id="../private",
            profile_id="qwen-fast",
            glossary="",
            context="",
            cpu=False,
            on_progress=lambda _message: None,
        )
    assert not sentinel.exists()


def test_supervisor_rejects_incompatible_whisper_before_spawn(tmp_path: Path):
    data_root = tmp_path / "Data"
    models_root = tmp_path / "Models"
    runtime_root = tmp_path / "Runtime"
    _stage_craig(data_root)
    _install_old_whisper(runtime_root)

    sentinel = tmp_path / "spawned.txt"
    script = tmp_path / "worker.py"
    script.write_text(
        "from pathlib import Path; Path(r'" + str(sentinel).replace("\\", "\\\\") + "').write_text('spawned')",
        encoding="utf-8",
    )
    supervisor = WorkerSupervisor(
        command_factory=lambda: [sys.executable, str(script)],
        data_root=data_root,
        models_root=models_root,
        runtime_root=runtime_root,
    )
    with pytest.raises(WorkerProcessError, match="WHISPER_RUNTIME_UNAVAILABLE"):
        supervisor.run_craig(
            job_id="asr-whisper-old",
            attempt=1,
            source_id="source-123",
            profile_id="whisper-turbo",
            glossary="",
            context="",
            cpu=False,
            on_progress=lambda _message: None,
        )
    assert not sentinel.exists()


def test_supervisor_does_not_run_qwen_inside_companion_python_without_physical_gate(tmp_path: Path):
    data_root = tmp_path / "Data"
    models_root = tmp_path / "Models"
    _stage_craig(data_root)
    supervisor = WorkerSupervisor(
        data_root=data_root,
        models_root=models_root,
        startup_timeout=5,
        heartbeat_timeout=5,
    )
    with pytest.raises(WorkerProcessError, match="QWEN_PHYSICAL_ACCEPTANCE_REQUIRED"):
        supervisor.run_craig(
            job_id="asr-qwen-boundary",
            attempt=1,
            source_id="source-123",
            profile_id="qwen-fast",
            glossary="",
            context="",
            cpu=False,
            on_progress=lambda _message: None,
        )
