from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_maintenance_module():
    if "winreg" not in sys.modules:
        stub = types.ModuleType("winreg")
        stub.HKEY_CURRENT_USER = object()
        stub.KEY_SET_VALUE = 0
        stub.KEY_READ = 0
        sys.modules["winreg"] = stub
    path = Path(__file__).parents[1] / "packaging" / "maintenance_entry.py"
    spec = importlib.util.spec_from_file_location("tda_companion_maintenance_entry_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maintenance = _load_maintenance_module()


def _operation(root: Path, operation_id: str) -> dict:
    path = root / "Cache" / "maintenance" / "operations" / f"{operation_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_journal_is_atomic_and_keeps_stage_separate_from_status(tmp_path: Path):
    operation_id = "a" * 32
    journal = maintenance.MaintenanceJournal(
        tmp_path,
        operation_id,
        "update",
        metadata={"target_version": "0.3.3"},
    )
    journal.stage("running_msi", msi_exit_code=None)
    journal.complete(msi_exit_code=0, installed_version="0.3.3")

    value = _operation(tmp_path, operation_id)
    assert value["schema_version"] == 1
    assert value["operation_id"] == operation_id
    assert value["action"] == "update"
    assert value["status"] == "completed"
    assert value["stage"] == "completed"
    assert value["installed_version"] == "0.3.3"
    assert value["msi_exit_code"] == 0
    assert not list((tmp_path / "Cache" / "maintenance").rglob("*.tmp"))


def test_parent_timeout_is_terminal(monkeypatch):
    class Kernel32:
        def OpenProcess(self, *_args):
            return 123

        def WaitForSingleObject(self, *_args):
            return maintenance.WAIT_TIMEOUT

        def CloseHandle(self, *_args):
            return 1

        def GetLastError(self):
            return 0

    monkeypatch.setattr(
        maintenance.ctypes,
        "windll",
        types.SimpleNamespace(kernel32=Kernel32()),
        raising=False,
    )

    with pytest.raises(maintenance.MaintenanceError, match="PARENT_EXIT_TIMEOUT"):
        maintenance._wait_parent(4242, timeout=0.001)


def test_msiexec_writes_verbose_log_and_accepts_restart_required(tmp_path: Path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=3010)

    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)
    log = tmp_path / "logs" / "operation.msi.log"
    code = maintenance._run_msiexec(["/i", "candidate.msi", "/passive"], log)

    assert code == 3010
    command = seen["command"]
    assert command[0] == "msiexec.exe"
    assert "/norestart" in command
    assert "/L*v" in command
    assert str(log) in command
    assert log.parent.is_dir()


def test_parent_failure_records_exact_stage_and_never_runs_msi(tmp_path: Path, monkeypatch):
    operation_id = "b" * 32
    msi = tmp_path / "candidate.msi"
    msi.write_bytes(b"candidate")
    digest = hashlib.sha256(msi.read_bytes()).hexdigest()

    monkeypatch.setattr(
        maintenance,
        "_wait_parent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            maintenance.MaintenanceError("PARENT_EXIT_TIMEOUT")
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "_run_msiexec",
        lambda *_args, **_kwargs: pytest.fail("msiexec must not run while the UI parent is alive"),
    )

    with pytest.raises(maintenance.MaintenanceError, match="PARENT_EXIT_TIMEOUT"):
        maintenance.install_update(
            tmp_path,
            msi,
            digest,
            "0.3.3",
            1234,
            8765,
            operation_id,
        )

    value = _operation(tmp_path, operation_id)
    assert value["status"] == "failed"
    assert value["stage"] == "failed"
    assert value["failure_stage"] == "waiting_for_ui_exit"
    assert value["error_code"] == "PARENT_EXIT_TIMEOUT"
    assert value["msi_exit_code"] is None


def test_update_receipt_records_verified_version_hash_and_msi_exit(tmp_path: Path, monkeypatch):
    operation_id = "c" * 32
    msi = tmp_path / "candidate.msi"
    msi.write_bytes(b"candidate")
    digest = hashlib.sha256(msi.read_bytes()).hexdigest()
    version = "0.3.3"
    executable = tmp_path / "Companion" / "versions" / version / "TDACompanion.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    marker = tmp_path / "Companion" / "current-version.txt"
    marker.write_text(version, encoding="utf-8")

    monkeypatch.setattr(maintenance, "_wait_parent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(maintenance, "prepare_uninstall", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(maintenance, "_run_msiexec", lambda *_args, **_kwargs: 3010)
    launches: list[list[str]] = []
    monkeypatch.setattr(
        maintenance.subprocess,
        "Popen",
        lambda command, **_kwargs: launches.append([str(value) for value in command])
        or types.SimpleNamespace(),
    )

    maintenance.install_update(
        tmp_path,
        msi,
        digest,
        version,
        1234,
        8765,
        operation_id,
    )

    value = _operation(tmp_path, operation_id)
    assert value["status"] == "completed"
    assert value["installed_version"] == version
    assert value["expected_sha256"] == digest
    assert value["msi_exit_code"] == 3010
    receipt = json.loads(
        (tmp_path / "Cache" / "maintenance" / "last-update.json").read_text(encoding="utf-8")
    )
    assert receipt["operation_id"] == operation_id
    assert receipt["sha256"] == digest
    assert receipt["msi_exit_code"] == 3010
    assert launches[0][-2:] == ["--agent", "--startup"]
    assert launches[1][-1] == "--ui"


def test_failed_msi_keeps_exit_code_and_running_msi_as_failure_stage(tmp_path: Path, monkeypatch):
    operation_id = "d" * 32
    msi = tmp_path / "candidate.msi"
    msi.write_bytes(b"candidate")
    digest = hashlib.sha256(msi.read_bytes()).hexdigest()

    monkeypatch.setattr(maintenance, "_wait_parent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(maintenance, "prepare_uninstall", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        maintenance,
        "_run_msiexec",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            maintenance.MaintenanceError("MSI_FAILED", msi_exit_code=1603)
        ),
    )

    with pytest.raises(maintenance.MaintenanceError, match="MSI_FAILED"):
        maintenance.install_update(
            tmp_path,
            msi,
            digest,
            "0.3.3",
            None,
            8765,
            operation_id,
        )

    value = _operation(tmp_path, operation_id)
    assert value["status"] == "failed"
    assert value["failure_stage"] == "running_msi"
    assert value["error_code"] == "MSI_FAILED"
    assert value["msi_exit_code"] == 1603
