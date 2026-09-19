from __future__ import annotations

from pathlib import Path

import pytest

import tda_companion.worker_supervisor as worker_supervisor
from tda_companion.worker_supervisor import WorkerOutcome, WorkerProcessError, WorkerSupervisor


def _supervisor(tmp_path: Path) -> WorkerSupervisor:
    roots = {
        "data_root": tmp_path / "Data",
        "models_root": tmp_path / "Models",
        "runtime_root": tmp_path / "Runtime",
        "state_root": tmp_path / "State",
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return WorkerSupervisor(**roots)


def test_qwen_job_dispatch_uses_lightweight_gate_and_worker_lookup(monkeypatch, tmp_path: Path):
    supervisor = _supervisor(tmp_path)
    worker = tmp_path / "Runtime" / "qwen" / "1.0.6" / "TDAQwenWorker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    observed: dict[str, object] = {}

    def inspect_gate(state, runtime, models, *, profile_id, verify_model_content=False):  # noqa: ANN001
        observed["profile_id"] = profile_id
        observed["verify_model_content"] = verify_model_content
        return {"ready": True, "status": "ready", "profile_id": profile_id}

    def current_worker(_root, *, verify_worker=True):  # noqa: ANN001
        observed["verify_worker"] = verify_worker
        return worker

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        observed["process_command"] = kwargs["process_command"]
        observed["kind"] = command.kind
        return WorkerOutcome(terminal="cancelled", payload={}, returncode=0)

    monkeypatch.setattr(worker_supervisor, "inspect_qwen_physical_gate", inspect_gate)
    monkeypatch.setattr(worker_supervisor, "current_qwen_worker", current_worker)
    monkeypatch.setattr(supervisor, "_run_command", fake_run)

    outcome = supervisor.run_craig(
        job_id="job",
        attempt=1,
        source_id="craig-source",
        profile_id="qwen-quality",
        glossary="",
        context="",
        cpu=False,
        on_progress=lambda _message: None,
        on_event=lambda _message: None,
        is_cancelled=lambda: False,
    )

    assert outcome.terminal == "cancelled"
    assert observed["kind"] == "transcription.craig"
    assert observed["profile_id"] == "qwen-quality"
    assert observed["verify_model_content"] is False
    assert observed["verify_worker"] is False
    assert observed["process_command"] == [str(worker)]


def test_qwen_job_dispatch_rejects_stale_sealed_gate_before_worker_lookup(monkeypatch, tmp_path: Path):
    supervisor = _supervisor(tmp_path)
    monkeypatch.setattr(
        worker_supervisor,
        "inspect_qwen_physical_gate",
        lambda *_args, **_kwargs: {
            "ready": False,
            "status": "stale",
            "profile_id": "qwen-quality",
            "reason": "QWEN_GATE_BINDING_CHANGED",
        },
    )
    monkeypatch.setattr(
        worker_supervisor,
        "current_qwen_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("worker lookup must not run for a stale gate")
        ),
    )

    with pytest.raises(WorkerProcessError, match="QWEN_PHYSICAL_ACCEPTANCE_REQUIRED"):
        supervisor.run_craig(
            job_id="job",
            attempt=1,
            source_id="craig-source",
            profile_id="qwen-quality",
            glossary="",
            context="",
            cpu=False,
            on_progress=lambda _message: None,
        )
