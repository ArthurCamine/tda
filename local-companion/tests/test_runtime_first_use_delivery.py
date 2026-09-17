from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.desktop_session_bridge as session_module
from tda_companion.desktop import DesktopBridge
from tda_companion.desktop_session_bridge import SessionDesktopBridge
from tda_companion.network import NetworkError


def _bridge(tmp_path: Path) -> SessionDesktopBridge:
    paths = SimpleNamespace(
        root=tmp_path,
        companion_root=tmp_path / "Companion",
        state_root=tmp_path / "State",
        data_root=tmp_path / "Data",
        logs_root=tmp_path / "Logs",
        cache_root=tmp_path / "Cache",
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
    )
    for value in (
        paths.state_root,
        paths.data_root,
        paths.logs_root,
        paths.cache_root,
        paths.models_root,
        paths.runtime_root,
    ):
        value.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(snapshot=lambda: {}, update=lambda value: value)
    return SessionDesktopBridge(
        token="t" * 43,
        port=8765,
        paths=paths,
        settings=settings,
        executable=tmp_path / "TDACompanion.exe",
        start_agent=lambda: None,
    )


@pytest.mark.parametrize(
    ("family", "method", "base_method"),
    [
        ("whisper", "install_whisper_runtime", "install_whisper_runtime"),
        ("qwen", "install_qwen_runtime", "install_qwen_runtime"),
    ],
)
def test_candidate_first_use_falls_back_to_exact_published_runtime_rc(
    monkeypatch,
    tmp_path: Path,
    family: str,
    method: str,
    base_method: str,
):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        DesktopBridge,
        base_method,
        lambda self: {"accepted": False, "available": False, "status": "missing", "version": "old"},
    )
    monkeypatch.setattr(
        session_module,
        "fetch_companion_manifest",
        lambda: SimpleNamespace(version="0.3.2"),
    )
    observed = []

    def install_rc(selected, *, runtime_root, cache_root):
        observed.append((selected, runtime_root, cache_root))
        return {"runtime": selected, "version": "candidate", "status": "ready", "channel": "rc"}

    monkeypatch.setattr(session_module, "install_published_runtime_rc", install_rc)

    result = getattr(bridge, method)()

    assert result["accepted"] is True
    assert result["available"] is True
    assert result["status"] == "ready"
    assert result["channel"] == "rc"
    assert observed == [(family, bridge.paths.runtime_root, bridge.paths.cache_root)]


@pytest.mark.parametrize("method", ["install_whisper_runtime", "install_qwen_runtime"])
def test_stable_companion_never_consumes_runtime_rc(monkeypatch, tmp_path: Path, method: str):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        DesktopBridge,
        method,
        lambda self: {"accepted": False, "available": False, "status": "missing", "version": "old"},
    )
    monkeypatch.setattr(
        session_module,
        "fetch_companion_manifest",
        lambda: SimpleNamespace(version="0.3.8"),
    )
    monkeypatch.setattr(
        session_module,
        "install_published_runtime_rc",
        lambda *_args, **_kwargs: pytest.fail("stable Companion must never consume runtime RC"),
    )

    with pytest.raises(RuntimeError) as exc:
        getattr(bridge, method)()

    assert "RUNTIME_COMPATIBLE_RELEASE_UNAVAILABLE" in str(exc.value)


def test_rc_publication_failure_is_translated_to_actionable_user_message(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        DesktopBridge,
        "install_qwen_runtime",
        lambda self: {"accepted": False, "available": False, "status": "missing", "version": "1.0.1"},
    )
    monkeypatch.setattr(
        session_module,
        "fetch_companion_manifest",
        lambda: SimpleNamespace(version="0.3.2"),
    )

    def unavailable(*_args, **_kwargs):
        raise NetworkError("RUNTIME_RC_RELEASE_NOT_PUBLISHED")

    monkeypatch.setattr(session_module, "install_published_runtime_rc", unavailable)

    with pytest.raises(RuntimeError) as exc:
        bridge.install_qwen_runtime()

    text = str(exc.value)
    assert "ainda não terminou de ser publicado" in text
    assert text.endswith("[RUNTIME_RC_RELEASE_NOT_PUBLISHED]")
