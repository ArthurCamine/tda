import json

import pytest

from tda_companion import atomic_storage
from tda_companion.preparation_receipt import PreparationReceipt
from tda_companion.profile_preparation import ProfilePreparationError
from test_profile_preparation import _manager


def receipt(**updates):
    return {"schema": "tda_profile_preparation_receipt_v1", "operation_id": "a" * 32,
            "source_id": "craig-" + "b" * 64, "profile_id": "whisper-turbo", "engine": "whisper",
            "state": "running", "stage": "runtime", "sequence": 3,
            "started_at": "2026-09-26T00:00:00+00:00", "updated_at": "2026-09-26T00:00:01+00:00",
            "finished_at": None, "error_code": None, **updates}


@pytest.mark.parametrize("stage", ["runtime", "whisper_model", "qwen_gate"])
def test_restart_preserves_stage_and_interrupts_old_operation(tmp_path, stage):
    manager = _manager(tmp_path)
    manager._receipt.write(receipt(stage=stage))
    restarted = _manager(tmp_path)
    snapshot = restarted.snapshot()
    assert snapshot["state"] == "interrupted"
    assert snapshot["active"] is False
    assert snapshot["stage"] == stage
    assert snapshot["sequence"] == 4
    assert snapshot["error_code"] == "TRANSCRIPTION_PREPARATION_INTERRUPTED"
    assert restarted._receipt.read()["state"] == "interrupted"
    assert _manager(tmp_path).snapshot()["sequence"] == 4


def test_resume_creates_new_id_and_stale_cancel_cannot_touch_it(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager._receipt.write(receipt())
    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_run", lambda *_: None)
    started = manager.start("craig-" + "b" * 64, "whisper-turbo")
    manager.wait(1)
    assert started["operation_id"] != "a" * 32
    assert started["resumes_operation_id"] == "a" * 32
    with pytest.raises(ProfilePreparationError, match="STALE_OPERATION"):
        manager.request_cancel("a" * 32)
    assert not manager._cancel.is_set()
    manager.request_cancel(started["operation_id"])
    assert manager._cancel.is_set()


def test_terminal_receipt_and_sanitized_allowlist(tmp_path):
    manager = _manager(tmp_path)
    manager._receipt.write(receipt(state="completed", stage="complete", path="private", token="secret", transcript="private"))
    restored = _manager(tmp_path)
    assert restored.snapshot()["state"] == "completed"
    assert not restored.snapshot()["active"]
    serialized = json.dumps(restored._receipt.read())
    assert "private" not in serialized and "secret" not in serialized


@pytest.mark.parametrize("payload", [b"{", b"x" * 4097, b'{"schema":"wrong"}'])
def test_corrupt_receipt_does_not_block_startup_or_claim_ready(tmp_path, payload):
    manager = _manager(tmp_path)
    path = manager._receipt._path(create=True)
    path.write_bytes(payload)
    restored = _manager(tmp_path).snapshot()
    assert not restored["active"]
    assert restored["error_code"] == "PREPARATION_RECEIPT_INVALID"
    assert "ready" not in restored


def test_interrupted_replace_preserves_last_valid_receipt(tmp_path, monkeypatch):
    store = PreparationReceipt(tmp_path)
    store.write(receipt())
    def fail(*_):
        raise OSError("simulated interruption")
    monkeypatch.setattr(atomic_storage, "_replace", fail)
    with pytest.raises(OSError):
        store.write(receipt(sequence=4, stage="whisper_model"))
    assert store.read()["sequence"] == 3
    assert list((tmp_path / "preparation").glob("*.partial")) == []


def test_linked_receipt_is_not_read_or_overwritten(tmp_path):
    store = PreparationReceipt(tmp_path)
    path = store._path(create=True)
    outside = tmp_path / "outside.json"
    outside.write_text("unchanged")
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError):
        store.read()
    with pytest.raises(ValueError):
        store.write(receipt())
    assert outside.read_text() == "unchanged"


def test_initial_write_failure_never_starts_preparation(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    def fail(*_):
        raise OSError("disk unavailable")
    monkeypatch.setattr(manager._receipt, "write", fail)
    with pytest.raises(ProfilePreparationError, match="PREPARATION_RECEIPT_WRITE_FAILED"):
        manager.start("craig-" + "b" * 64, "whisper-turbo")
    assert manager._thread is None
    assert not manager.snapshot()["active"]


@pytest.mark.parametrize("ready", [True, False])
def test_resume_uses_factual_catalog_and_existing_runtime_recovery(tmp_path, monkeypatch, ready):
    import tda_companion.profile_preparation as preparation
    manager = _manager(tmp_path)
    manager._receipt.write(receipt())
    manager = _manager(tmp_path)
    monkeypatch.setattr(preparation, "load_craig_package", lambda *_args, **_kwargs: object())
    calls = []
    def catalog(*_):
        return [{"id": "whisper-turbo", "ready": ready or bool(calls)}]
    def runtime(*args, **kwargs):
        assert manager._receipt.read()["stage"] == "runtime"
        calls.append("existing-runtime-recovery")
        return {"version": "1.1.5"}
    monkeypatch.setattr(preparation, "profile_catalog", catalog)
    monkeypatch.setattr(preparation, "_install_whisper_runtime", runtime)
    monkeypatch.setattr(preparation, "prepare_whisper_profile", lambda **_: calls.append("existing-model-recovery"))
    manager.start("craig-" + "b" * 64, "whisper-turbo")
    assert manager.wait(2)
    assert manager._receipt.read()["state"] == "completed"
    assert calls == ([] if ready else ["existing-runtime-recovery", "existing-model-recovery"])
