from __future__ import annotations

from pathlib import Path

import pytest

import tda_companion.worker_supervisor as supervisor_module
from tda_companion.worker_protocol import WorkerRunCommand
from tda_companion.worker_supervisor import WorkerOutcome, WorkerProcessError, WorkerSupervisor


class CapturingSupervisor(WorkerSupervisor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.process_command: list[str] | None = None
        self.command: WorkerRunCommand | None = None

    def _run_command(self, command, *, on_progress, on_event=None, is_cancelled=None, process_command=None):
        self.command = command
        self.process_command = process_command
        return WorkerOutcome(terminal="result", payload={"ok": True}, returncode=0)


def _run(supervisor: WorkerSupervisor, *, profile_id: str):
    return supervisor.run_craig(
        job_id="job-qwen",
        attempt=1,
        source_id="source-id",
        profile_id=profile_id,
        glossary="Yuhara",
        context="mesa",
        cpu=False,
        on_progress=lambda _message: None,
    )


def _gate_ready(monkeypatch, calls: dict | None = None):
    def inspect(state_root, runtime_root, models_root, *, profile_id, verify_model_content=False):
        if calls is not None:
            calls.update(
                {
                    "state_root": state_root,
                    "runtime_root": runtime_root,
                    "models_root": models_root,
                    "profile_id": profile_id,
                    "verify_model_content": verify_model_content,
                }
            )
        return {"ready": True, "status": "ready", "profile_id": profile_id}

    monkeypatch.setattr(supervisor_module, "inspect_qwen_physical_gate", inspect)



def test_qwen_profile_uses_sealed_gate_without_full_content_rehash(monkeypatch, tmp_path: Path):
    worker = tmp_path / "Runtime" / "qwen" / "1.0.0" / "TDAQwenWorker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    gate_calls: dict = {}
    worker_calls: dict = {}
    _gate_ready(monkeypatch, gate_calls)

    def current_worker(_root, *, verify_worker=True):
        worker_calls["verify_worker"] = verify_worker
        return worker

    monkeypatch.setattr(supervisor_module, "current_qwen_worker", current_worker)

    supervisor = CapturingSupervisor(
        data_root=tmp_path / "Data",
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
        state_root=tmp_path / "State",
    )
    outcome = _run(supervisor, profile_id="qwen-fast")

    assert outcome.terminal == "result"
    assert supervisor.process_command == [str(worker)]
    assert supervisor.command is not None
    assert supervisor.command.payload["profile_id"] == "qwen-fast"
    assert gate_calls["verify_model_content"] is False
    assert gate_calls["profile_id"] == "qwen-fast"
    assert worker_calls["verify_worker"] is False

def test_qwen_profile_never_falls_back_to_agent_python_when_runtime_missing(monkeypatch, tmp_path: Path):
    _gate_ready(monkeypatch)
    monkeypatch.setattr(supervisor_module, "current_qwen_worker", lambda _root, **_kwargs: None)
    supervisor = CapturingSupervisor(
        data_root=tmp_path / "Data",
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
        state_root=tmp_path / "State",
    )

    with pytest.raises(WorkerProcessError, match="QWEN_RUNTIME_UNAVAILABLE"):
        _run(supervisor, profile_id="qwen-quality")
    assert supervisor.command is None


def test_qwen_profile_is_blocked_before_worker_lookup_when_physical_gate_is_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        supervisor_module,
        "inspect_qwen_physical_gate",
        lambda *_args, **_kwargs: {"ready": False, "status": "missing"},
    )
    monkeypatch.setattr(
        supervisor_module,
        "current_qwen_worker",
        lambda _root, **_kwargs: (_ for _ in ()).throw(AssertionError("worker lookup must not run")),
    )
    supervisor = CapturingSupervisor(
        data_root=tmp_path / "Data",
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
        state_root=tmp_path / "State",
    )

    with pytest.raises(WorkerProcessError, match="QWEN_PHYSICAL_ACCEPTANCE_REQUIRED"):
        _run(supervisor, profile_id="qwen-fast")
    assert supervisor.command is None


def test_qwen_profile_derives_local_state_and_runtime_roots_from_data_root(monkeypatch, tmp_path: Path):
    calls: dict = {}
    _gate_ready(monkeypatch, calls)
    worker = tmp_path / "Runtime" / "qwen" / "1.0.0" / "TDAQwenWorker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    monkeypatch.setattr(supervisor_module, "current_qwen_worker", lambda _root, **_kwargs: worker)
    supervisor = CapturingSupervisor(
        data_root=tmp_path / "Data",
        models_root=tmp_path / "Models",
    )

    _run(supervisor, profile_id="qwen-fast")
    assert calls["state_root"] == tmp_path / "State"
    assert calls["runtime_root"] == tmp_path / "Runtime"
