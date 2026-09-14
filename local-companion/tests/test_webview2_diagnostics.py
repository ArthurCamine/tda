from __future__ import annotations

from types import SimpleNamespace

import tda_companion.diagnostics as diagnostics


class _Key:
    def __init__(self, hive: object, path: str):
        self.hive = hive
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    HKEY_LOCAL_MACHINE = object()

    def __init__(self, values: dict[tuple[object, str], object]):
        self.values = values
        self.opened: list[tuple[object, str]] = []

    def OpenKey(self, hive: object, path: str):
        self.opened.append((hive, path))
        key = (hive, path)
        if key not in self.values:
            raise FileNotFoundError(path)
        return _Key(hive, path)

    def QueryValueEx(self, key: _Key, name: str):
        assert name == "pv"
        return self.values[(key.hive, key.path)], 1


def test_webview2_registry_uses_official_guid_and_x64_locations():
    guid = diagnostics.WEBVIEW2_CLIENT_GUID
    user_path = rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"
    machine_path = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"
    registry = _FakeWinreg(
        {
            (_FakeWinreg.HKEY_LOCAL_MACHINE, machine_path): "152.0.4191.53",
        }
    )

    version, error = diagnostics._webview2_registry_version(registry, is_64bit=True)

    assert version == "152.0.4191.53"
    assert error is None
    assert registry.opened == [
        (_FakeWinreg.HKEY_CURRENT_USER, user_path),
        (_FakeWinreg.HKEY_LOCAL_MACHINE, machine_path),
    ]


def test_webview2_registry_uses_non_wow_path_on_32bit_windows():
    guid = diagnostics.WEBVIEW2_CLIENT_GUID
    machine_path = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"
    registry = _FakeWinreg(
        {
            (_FakeWinreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"): "0.0.0.0",
            (_FakeWinreg.HKEY_LOCAL_MACHINE, machine_path): "151.0.4129.50",
        }
    )

    version, error = diagnostics._webview2_registry_version(registry, is_64bit=False)

    assert version == "151.0.4129.50"
    assert error is None
    assert registry.opened[-1] == (_FakeWinreg.HKEY_LOCAL_MACHINE, machine_path)


def test_webview2_registry_rejects_missing_empty_and_zero_versions():
    guid = diagnostics.WEBVIEW2_CLIENT_GUID
    user_path = rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"
    machine_path = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"
    registry = _FakeWinreg(
        {
            (_FakeWinreg.HKEY_CURRENT_USER, user_path): "",
            (_FakeWinreg.HKEY_LOCAL_MACHINE, machine_path): "0.0.0.0",
        }
    )

    version, error = diagnostics._webview2_registry_version(registry, is_64bit=True)

    assert version is None
    assert error is None


def test_running_edgechromium_renderer_is_positive_runtime_evidence(monkeypatch):
    monkeypatch.setenv(diagnostics.WEBVIEW2_RENDERER_ENV, "edgechromium")

    result = diagnostics._webview2_check()

    assert result == {
        "code": "webview2",
        "status": "pass",
        "message": "WebView2 Runtime ativo nesta interface",
        "detail": "renderer edgechromium",
    }


def test_webview2_version_validation_matches_documented_nonzero_contract():
    assert diagnostics._valid_webview2_version("152.0.4191.53") is True
    assert diagnostics._valid_webview2_version("0.0.0.1") is True
    assert diagnostics._valid_webview2_version("0.0.0.0") is False
    assert diagnostics._valid_webview2_version("") is False
    assert diagnostics._valid_webview2_version(None) is False
    assert diagnostics._valid_webview2_version("152.preview") is False
