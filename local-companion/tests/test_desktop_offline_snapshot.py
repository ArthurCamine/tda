from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tda_companion import desktop_session_bridge
from tda_companion.desktop_session_bridge import SessionDesktopBridge


def test_offline_snapshot_keeps_local_system_telemetry(monkeypatch, tmp_path: Path):
    bridge = SessionDesktopBridge.__new__(SessionDesktopBridge)
    bridge.client = SimpleNamespace(
        status=lambda: {
            "state": "port_conflict",
            "service_version": None,
            "error": "AGENT_PROCESS_EXECUTABLE_UNVERIFIED",
        }
    )
    bridge.paths = SimpleNamespace(
        data_root=tmp_path / "Data",
        runtime_root=tmp_path / "Runtime",
        cache_root=tmp_path / "Cache",
    )
    bridge.paths.data_root.mkdir(parents=True)
    bridge.settings = SimpleNamespace(snapshot=lambda: {"start_with_windows": True})
    bridge.port = 8765
    bridge._maintenance_snapshot = lambda: None

    monkeypatch.setattr(
        desktop_session_bridge,
        "SystemTelemetry",
        lambda: SimpleNamespace(
            snapshot=lambda: {
                "memory": {"total_bytes": 64 * 1024**3},
                "gpus": [{"name": "NVIDIA GeForce RTX 4070 Laptop GPU"}],
            }
        ),
    )
    monkeypatch.setattr(
        desktop_session_bridge,
        "inspect_whisper_runtime",
        lambda *_args, **_kwargs: {"status": "incompatible", "version": "1.1.1"},
    )
    monkeypatch.setattr(
        desktop_session_bridge,
        "inspect_qwen_runtime",
        lambda *_args, **_kwargs: {"status": "incompatible", "version": "1.0.1"},
    )

    result = bridge._offline_snapshot("AGENT_PROCESS_EXECUTABLE_UNVERIFIED")

    assert result["agent"]["error"] == "AGENT_PROCESS_EXECUTABLE_UNVERIFIED"
    assert result["system"]["memory"]["total_bytes"] == 64 * 1024**3
    assert result["system"]["gpus"][0]["name"] == "NVIDIA GeForce RTX 4070 Laptop GPU"
    assert result["whisper_runtime"] == {"status": "incompatible", "version": "1.1.1"}
    assert result["qwen_runtime"] == {"status": "incompatible", "version": "1.0.1"}
