from __future__ import annotations

import threading
from typing import Any


class TrayController:
    """Windows tray integration kept separate from Agent lifecycle."""

    def __init__(self, bridge: Any, window: Any):
        self.bridge = bridge
        self.window = window
        self.icon = None
        self.thread: threading.Thread | None = None

    @staticmethod
    def _image():
        from PIL import Image, ImageDraw

        size = 64
        image = Image.new("RGBA", (size, size), (10, 12, 15, 255))
        draw = ImageDraw.Draw(image)
        gold = (215, 170, 97, 255)
        soft = (238, 232, 220, 255)
        draw.rounded_rectangle((3, 3, 60, 60), radius=14, outline=gold, width=3)
        draw.polygon(((32, 11), (52, 32), (32, 53), (12, 32)), outline=soft)
        draw.line((32, 17, 32, 47), fill=gold, width=4)
        draw.line((22, 25, 42, 25), fill=gold, width=4)
        return image

    def _notify(self, message: str) -> None:
        if self.icon is None:
            return
        try:
            if getattr(self.icon, "HAS_NOTIFICATION", False):
                self.icon.notify(message, "TDA Companion")
        except Exception:
            pass

    def _show(self, _icon=None, _item=None) -> None:
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def _open_tda(self, _icon=None, _item=None) -> None:
        try:
            self.bridge.open_tda()
        except Exception as exc:
            self._notify(f"Não foi possível abrir o TDA: {exc}")

    def _toggle_queue(self, _icon=None, _item=None) -> None:
        try:
            snapshot = self.bridge.snapshot()
            paused = snapshot.get("agent", {}).get("lifecycle") == "paused"
            self.bridge.set_queue_paused(not paused)
            self._notify("Fila retomada." if paused else "Novas execuções pausadas.")
        except Exception as exc:
            self._notify(f"Não foi possível alterar a fila: {exc}")

    def _restart(self, _icon=None, _item=None) -> None:
        try:
            self.bridge.restart_agent()
            self._notify("Agent reiniciado.")
        except Exception as exc:
            self._notify(f"Agent não foi reiniciado: {exc}")

    def _exit_ui(self, _icon=None, _item=None) -> None:
        try:
            self.bridge.close_desktop()
        except Exception as exc:
            self._notify(f"A interface não foi encerrada: {exc}")

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Abrir Companion", self._show, default=True),
            pystray.MenuItem("Abrir TDA", self._open_tda),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Pausar/retomar fila", self._toggle_queue),
            pystray.MenuItem("Reiniciar Agent", self._restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair da interface", self._exit_ui),
        )
        self.icon = pystray.Icon("tda-companion", self._image(), "TDA Companion", menu)
        # The Companion targets Windows; pystray's Win32 backend supports a tray
        # loop in a background thread while WebView2 owns the main GUI thread.
        self.thread = threading.Thread(target=self.icon.run, name="tda-companion-tray", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.icon = None
        self.thread = None
