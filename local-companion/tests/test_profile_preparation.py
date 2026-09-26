from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import tda_companion.profile_preparation as preparation
from tda_companion.profile_preparation import (
    ProfilePreparationError,
    ProfilePreparationManager,
)
from tda_companion.runtime_compat import (
    MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
    MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
)


def _manager(tmp_path: Path) -> ProfilePreparationManager:
    root = tmp_path / "TDA"
    return ProfilePreparationManager(
        data_root=root / "Data",
        models_root=root / "Models",
        runtime_root=root / "Runtime",
        state_root=root / "State",
        cache_root=root / "Cache",
    )


def test_preparation_global_deadline_is_distinct_from_manual_cancel(
    monkeypatch,
    tmp_path: Path,
):
    manager = _manager(tmp_path)
    manager._started_at = 100.0
    monkeypatch.setattr(
        preparation.time,
        "monotonic",
        lambda: 100.0 + preparation._PREPARATION_MAX_SECONDS + 0.1,
    )

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_TIMEOUT",
    ):
        manager._ensure_not_cancelled()

    manager._started_at = 100.0
    monkeypatch.setattr(preparation.time, "monotonic", lambda: 101.0)
    manager._cancel.set()
    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_CANCELLED",
    ):
        manager._ensure_not_cancelled()


def test_terminal_preparation_elapsed_time_is_frozen(monkeypatch, tmp_path: Path):
    manager = _manager(tmp_path)
    manager._started_at = 100.0
    manager._state.update({"active": True, "state": "running"})

    monkeypatch.setattr(preparation.time, "monotonic", lambda: 112.34)
    manager._set("complete", "Pronto.", "Concluído.", state="completed")
    first = manager.snapshot()

    monkeypatch.setattr(preparation.time, "monotonic", lambda: 999.0)
    second = manager.snapshot()

    assert first["elapsed_seconds"] == 12.3
    assert second["elapsed_seconds"] == 12.3


def test_qwen_preparation_runs_in_background_and_reports_truthful_stages(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_id = "craig-" + "a" * 64
    catalog_calls = 0

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )

    def catalog(*_args):
        nonlocal catalog_calls
        catalog_calls += 1
        return [
            {
                "id": "qwen-quality",
                "engine": "qwen3",
                "ready": catalog_calls >= 2,
                "preparation_required": catalog_calls < 2,
                "reason": None if catalog_calls >= 2 else "QWEN_RUNTIME_REQUIRED",
            }
        ]

    monkeypatch.setattr(preparation, "profile_catalog", catalog)
    monkeypatch.setattr(
        preparation,
        "_install_qwen_runtime",
        lambda _runtime, _cache, **_kwargs: {
            "status": "ready",
            "version": MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
        },
    )

    def prepare_qwen(**kwargs):
        kwargs["progress"]("runtime_probe", {"profile_id": "qwen-quality"})
        kwargs["progress"]("physical_gate", {"track_number": 2})
        kwargs["progress"]("physical_gate_ready", {"track_number": 2})
        return {"ready": True}

    monkeypatch.setattr(preparation, "prepare_qwen_profile_from_craig", prepare_qwen)

    started = manager.start(source_id, "qwen-quality")
    assert started["state"] == "running"
    assert started["source_id"] == source_id

    deadline = time.monotonic() + 2
    while manager.snapshot()["active"] is True and time.monotonic() < deadline:
        time.sleep(0.01)

    final = manager.snapshot()
    assert final["state"] == "completed"
    assert final["stage"] == "complete"
    assert final["error_code"] is None
    assert final["elapsed_seconds"] >= 0


def test_profile_preparation_cancel_becomes_terminal_and_joinable(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_id = "craig-" + "c" * 64

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )
    monkeypatch.setattr(
        preparation,
        "profile_catalog",
        lambda *_args: [
            {
                "id": "whisper-turbo",
                "engine": "whisper",
                "ready": False,
                "preparation_required": True,
                "reason": "WHISPER_RUNTIME_REQUIRED",
            }
        ],
    )

    entered = threading.Event()

    def install(_runtime, _cache, *, is_cancelled=None):
        entered.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            preparation._check_cancelled(is_cancelled)
            time.sleep(0.01)
        raise AssertionError("cancellation was not observed")

    monkeypatch.setattr(preparation, "_install_whisper_runtime", install)

    manager.start(source_id, "whisper-turbo")
    assert entered.wait(timeout=1)
    assert manager.request_cancel() is True
    assert manager.wait(timeout=2) is True

    final = manager.snapshot()
    assert final["active"] is False
    assert final["state"] == "failed"
    assert final["error_code"] == "TRANSCRIPTION_PREPARATION_CANCELLED"


def test_preparation_rejects_restart_while_terminal_thread_is_still_unwinding(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_id = "craig-" + "d" * 64

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )

    class StillAlive:
        @staticmethod
        def is_alive():
            return True

    manager._thread = StillAlive()  # type: ignore[assignment]
    manager._state.update(
        {
            "active": False,
            "state": "completed",
            "source_id": source_id,
            "profile_id": "whisper-turbo",
        }
    )

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_ALREADY_RUNNING",
    ):
        manager.start(source_id, "whisper-turbo")


def test_preparation_reuses_same_request_and_rejects_competing_work(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_a = "craig-" + "a" * 64
    source_b = "craig-" + "b" * 64
    release = False

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )
    monkeypatch.setattr(
        preparation,
        "profile_catalog",
        lambda *_args: [
            {
                "id": "whisper-turbo",
                "engine": "whisper",
                "ready": False,
                "preparation_required": True,
                "reason": "WHISPER_RUNTIME_REQUIRED",
            }
        ],
    )

    def install(_runtime, _cache, **_kwargs):
        nonlocal release
        deadline = time.monotonic() + 1
        while not release and time.monotonic() < deadline:
            time.sleep(0.01)
        raise preparation.ProfilePreparationError("TEST_STOP")

    monkeypatch.setattr(preparation, "_install_whisper_runtime", install)

    first = manager.start(source_a, "whisper-turbo")
    same = manager.start(source_a, "whisper-turbo")
    assert same["operation_id"] == first["operation_id"]

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_ALREADY_RUNNING",
    ):
        manager.start(source_b, "whisper-turbo")

    release = True


def test_pending_bits_download_reconnects_instead_of_falling_back_to_rc(
    tmp_path: Path,
    monkeypatch,
):
    calls = {"inspect": 0, "download": 0, "rc": 0, "install": 0}

    def inspect(_root, verify_worker=True):
        del verify_worker
        calls["inspect"] += 1
        return (
            {"status": "missing", "version": None}
            if calls["inspect"] == 1
            else {
                "status": "ready",
                "version": MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
            }
        )

    class Manifest:
        version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
        sha256 = "a" * 64

    def download(*_args, **_kwargs):
        calls["download"] += 1
        if calls["download"] == 1:
            raise preparation.NetworkError("DOWNLOAD_CONTINUES_IN_BACKGROUND")
        return tmp_path / "runtime.zip"

    monkeypatch.setattr(preparation, "inspect_whisper_runtime", inspect)
    monkeypatch.setattr(preparation, "fetch_whisper_runtime_manifest", lambda: Manifest())
    monkeypatch.setattr(preparation, "whisper_runtime_update_available", lambda *_args: True)
    monkeypatch.setattr(preparation, "download_whisper_runtime", download)
    monkeypatch.setattr(preparation.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        preparation,
        "install_whisper_runtime_archive",
        lambda *_args, **_kwargs: calls.__setitem__("install", calls["install"] + 1),
    )
    monkeypatch.setattr(
        preparation,
        "install_published_runtime_rc",
        lambda *_args, **_kwargs: calls.__setitem__("rc", calls["rc"] + 1),
    )

    result = preparation._install_whisper_runtime(
        tmp_path / "Runtime",
        tmp_path / "Cache",
    )

    assert result["channel"] == "stable"
    assert calls["download"] == 2
    assert calls["install"] == 1
    assert calls["rc"] == 0


def test_resumable_download_stops_when_preparation_is_cancelled(monkeypatch):
    calls = 0
    cancelled = False

    def operation(_remaining):
        nonlocal calls, cancelled
        calls += 1
        cancelled = True
        raise preparation.NetworkError("DOWNLOAD_CONTINUES_IN_BACKGROUND")

    monkeypatch.setattr(preparation.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_CANCELLED",
    ):
        preparation._finish_resumable_download(
            operation,
            is_cancelled=lambda: cancelled,
        )

    assert calls == 1


def test_whisper_cancellation_arriving_during_stable_install_is_not_reported_ready(
    tmp_path: Path,
    monkeypatch,
):
    cancelled = False
    calls = {"inspect": 0, "rc": 0}

    def inspect(_root, verify_worker=True):
        del verify_worker
        calls["inspect"] += 1
        return (
            {"status": "missing", "version": None}
            if calls["inspect"] == 1
            else {
                "status": "ready",
                "version": MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
            }
        )

    class Manifest:
        version = MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION
        sha256 = "a" * 64

    def install(*_args, **_kwargs):
        nonlocal cancelled
        cancelled = True

    monkeypatch.setattr(preparation, "inspect_whisper_runtime", inspect)
    monkeypatch.setattr(preparation, "fetch_whisper_runtime_manifest", lambda: Manifest())
    monkeypatch.setattr(preparation, "whisper_runtime_update_available", lambda *_args: True)
    monkeypatch.setattr(
        preparation,
        "download_whisper_runtime",
        lambda *_args, **_kwargs: tmp_path / "runtime.zip",
    )
    monkeypatch.setattr(preparation, "install_whisper_runtime_archive", install)
    monkeypatch.setattr(
        preparation,
        "install_published_runtime_rc",
        lambda *_args, **_kwargs: calls.__setitem__("rc", calls["rc"] + 1),
    )

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_CANCELLED",
    ):
        preparation._install_whisper_runtime(
            tmp_path / "Runtime",
            tmp_path / "Cache",
            is_cancelled=lambda: cancelled,
        )

    assert calls["rc"] == 0


def test_whisper_cancellation_never_falls_back_to_runtime_rc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        preparation,
        "inspect_whisper_runtime",
        lambda *_args, **_kwargs: {"status": "missing", "version": None},
    )
    monkeypatch.setattr(
        preparation,
        "install_published_runtime_rc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled preparation must not enter RC fallback")
        ),
    )

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_CANCELLED",
    ):
        preparation._install_whisper_runtime(
            tmp_path / "Runtime",
            tmp_path / "Cache",
            is_cancelled=lambda: True,
        )


def test_whisper_skips_incompatible_stable_and_uses_rc(tmp_path: Path, monkeypatch):
    calls = {"inspect": 0, "stable_download": 0, "rc": 0}

    def inspect(_root, verify_worker=True):
        calls["inspect"] += 1
        if calls["inspect"] < 3:
            return {"status": "missing", "version": None}
        return {"status": "ready", "version": MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION}

    class Manifest:
        version = "0.0.0"
        sha256 = "a" * 64

    monkeypatch.setattr(preparation, "inspect_whisper_runtime", inspect)
    monkeypatch.setattr(preparation, "fetch_whisper_runtime_manifest", lambda: Manifest())
    monkeypatch.setattr(preparation, "whisper_runtime_update_available", lambda *_args: True)

    def forbidden_download(*_args, **_kwargs):
        calls["stable_download"] += 1
        raise AssertionError("incompatible Stable runtime must not be downloaded")

    monkeypatch.setattr(preparation, "download_whisper_runtime", forbidden_download)

    def rc(*_args, **_kwargs):
        calls["rc"] += 1
        return {
            "version": MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION,
            "channel": "rc",
        }

    monkeypatch.setattr(preparation, "install_published_runtime_rc", rc)

    result = preparation._install_whisper_runtime(
        tmp_path / "Runtime",
        tmp_path / "Cache",
    )

    assert calls["stable_download"] == 0
    assert calls["rc"] == 1
    assert result["version"] == MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION


def test_qwen_skips_incompatible_stable_and_uses_rc(tmp_path: Path, monkeypatch):
    calls = {"inspect": 0, "stable_download": 0, "rc": 0}

    def inspect(_root, verify_worker=True):
        calls["inspect"] += 1
        if calls["inspect"] < 3:
            return {"status": "missing", "version": None}
        return {"status": "ready", "version": MIN_COMPATIBLE_QWEN_RUNTIME_VERSION}

    class Bundle:
        archive_sha256 = "a" * 64

    class Manifest:
        version = "0.0.0"
        bundle = Bundle()

    monkeypatch.setattr(preparation, "inspect_qwen_runtime", inspect)
    monkeypatch.setattr(preparation, "fetch_qwen_runtime_manifest", lambda: Manifest())
    monkeypatch.setattr(preparation, "qwen_runtime_update_available", lambda *_args: True)

    def forbidden_download(*_args, **_kwargs):
        calls["stable_download"] += 1
        raise AssertionError("incompatible Stable runtime must not be downloaded")

    monkeypatch.setattr(preparation, "download_qwen_runtime", forbidden_download)
    monkeypatch.setattr(preparation, "probe_qwen_long_track_gate", lambda _root: None)

    def rc(*_args, **_kwargs):
        calls["rc"] += 1
        return {
            "version": MIN_COMPATIBLE_QWEN_RUNTIME_VERSION,
            "channel": "rc",
        }

    monkeypatch.setattr(preparation, "install_published_runtime_rc", rc)

    result = preparation._install_qwen_runtime(
        tmp_path / "Runtime",
        tmp_path / "Cache",
    )

    assert calls["stable_download"] == 0
    assert calls["rc"] == 1
    assert result["version"] == MIN_COMPATIBLE_QWEN_RUNTIME_VERSION


def test_qwen_hardware_failure_after_stable_install_does_not_fall_back_to_rc(
    tmp_path: Path,
    monkeypatch,
):
    calls = {"inspect": 0, "fallback": 0}

    def inspect(_root, verify_worker=True):
        calls["inspect"] += 1
        if calls["inspect"] == 1:
            return {"status": "missing", "version": None}
        return {"status": "ready", "version": MIN_COMPATIBLE_QWEN_RUNTIME_VERSION}

    class Bundle:
        archive_sha256 = "a" * 64

    class Manifest:
        version = MIN_COMPATIBLE_QWEN_RUNTIME_VERSION
        bundle = Bundle()

    monkeypatch.setattr(preparation, "inspect_qwen_runtime", inspect)
    monkeypatch.setattr(preparation, "fetch_qwen_runtime_manifest", lambda: Manifest())
    monkeypatch.setattr(preparation, "qwen_runtime_update_available", lambda *_args: True)
    monkeypatch.setattr(
        preparation,
        "download_qwen_runtime",
        lambda *_args, **_kwargs: tmp_path / "qwen.zip",
    )
    monkeypatch.setattr(
        preparation,
        "install_qwen_runtime_archive",
        lambda *_args, **_kwargs: {},
    )

    def hardware_failure(_root):
        raise preparation.QwenDesktopPrepareError("QWEN_CUDA_UNAVAILABLE")

    monkeypatch.setattr(preparation, "probe_qwen_long_track_gate", hardware_failure)

    def fallback(*_args, **_kwargs):
        calls["fallback"] += 1
        return {"version": MIN_COMPATIBLE_QWEN_RUNTIME_VERSION}

    monkeypatch.setattr(preparation, "install_published_runtime_rc", fallback)

    with pytest.raises(ProfilePreparationError, match="QWEN_CUDA_UNAVAILABLE"):
        preparation._install_qwen_runtime(tmp_path / "Runtime", tmp_path / "Cache")

    assert calls["fallback"] == 0


def test_preparation_cancel_is_fenced_by_observed_operation_id(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_id = "craig-" + "e" * 64
    entered = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        preparation,
        "load_craig_package",
        lambda _root, verify_tracks=False: object(),
    )
    monkeypatch.setattr(
        preparation,
        "profile_catalog",
        lambda *_args: [
            {
                "id": "whisper-turbo",
                "engine": "whisper",
                "ready": False,
                "preparation_required": True,
                "reason": "WHISPER_RUNTIME_REQUIRED",
            }
        ],
    )

    def install(_runtime, _cache, *, is_cancelled=None):
        entered.set()
        while not release.is_set():
            preparation._check_cancelled(is_cancelled)
            time.sleep(0.005)
        raise preparation.ProfilePreparationError("TEST_STOP")

    monkeypatch.setattr(preparation, "_install_whisper_runtime", install)

    first = manager.start(source_id, "whisper-turbo")
    assert entered.wait(timeout=1)
    operation_id = str(first["operation_id"])

    with pytest.raises(
        ProfilePreparationError,
        match="TRANSCRIPTION_PREPARATION_STALE_OPERATION",
    ):
        manager.request_cancel("f" * 32)

    assert manager.snapshot()["active"] is True
    cancelled = manager.request_cancel(operation_id)
    assert isinstance(cancelled, dict)
    assert cancelled["operation_id"] == operation_id

    repeated = manager.request_cancel(operation_id)
    assert isinstance(repeated, dict)
    assert repeated["operation_id"] == operation_id
    assert manager.wait(timeout=2) is True

    terminal = manager.request_cancel(operation_id)
    assert isinstance(terminal, dict)
    assert terminal["active"] is False
    assert terminal["error_code"] == "TRANSCRIPTION_PREPARATION_CANCELLED"


def test_preparation_operation_is_visible_before_source_validation_finishes(
    tmp_path: Path,
    monkeypatch,
):
    manager = _manager(tmp_path)
    source_id = "craig-" + "f" * 64
    entered = threading.Event()
    release = threading.Event()

    def load(_root, verify_tracks=False):
        del verify_tracks
        entered.set()
        assert release.wait(timeout=2)
        raise preparation.CraigPackageError("CRAIG_MANIFEST_INVALID")

    monkeypatch.setattr(preparation, "load_craig_package", load)

    started = manager.start(source_id, "qwen-quality")
    assert entered.wait(timeout=1)
    snapshot = manager.snapshot()
    assert snapshot["active"] is True
    assert snapshot["operation_id"] == started["operation_id"]
    assert snapshot["stage"] == "validating_source"

    manager.request_cancel(str(started["operation_id"]))
    release.set()
    assert manager.wait(timeout=2) is True
    assert manager.snapshot()["active"] is False
