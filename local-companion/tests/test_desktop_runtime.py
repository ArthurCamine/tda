from __future__ import annotations

from tda_companion.desktop_runtime import DesktopExitCoordinator


def test_user_close_can_hide_when_tray_is_available():
    coordinator = DesktopExitCoordinator()

    assert coordinator.should_hide("hide", tray_available=True) is True
    assert coordinator.should_hide("close_ui", tray_available=True) is False
    assert coordinator.should_hide("hide", tray_available=False) is False


def test_programmatic_exit_bypasses_hide_preference():
    coordinator = DesktopExitCoordinator()
    closed: list[bool] = []

    coordinator.request_exit(lambda: closed.append(True))

    assert closed == [True]
    assert coordinator.programmatic_exit is True
    assert coordinator.should_hide("hide", tray_available=True) is False
