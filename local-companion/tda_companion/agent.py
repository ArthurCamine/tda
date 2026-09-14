from __future__ import annotations

import threading
import time
from pathlib import Path

import uvicorn

from . import VERSION
from .__main__ import RootLock
from .agent_connection import probe_agent
from .api import create_app
from .craig_ingest_http import CraigIngestBoundary
from .system_log import SystemLog


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/v1/health"


def wait_until_ready(
    port: int,
    timeout: float = 8.0,
    *,
    expected_version: str | None = None,
) -> bool:
    """Wait for a verified TDA Agent, never for an arbitrary HTTP 200 listener."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.05, min(0.5, deadline - time.monotonic()))
        probe = probe_agent(
            port,
            expected_version=expected_version,
            timeout=remaining,
        )
        if probe.state == "exact":
            return True
        if probe.state in {"foreign", "incompatible"}:
            return False
        time.sleep(0.1)
    return False


class AgentController:
    """Own the loopback API independently from any desktop window."""

    def __init__(
        self,
        data_root: Path,
        token: str,
        origins: frozenset[str],
        port: int,
        system_log: SystemLog | None = None,
        models_root: Path | None = None,
    ):
        self.data_root = data_root
        self.models_root = models_root
        self.token = token
        self.origins = origins
        self.port = port
        self.system_log = system_log
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.lock: RootLock | None = None
        self.server_error: BaseException | None = None

    def _serve(self) -> None:
        try:
            assert self.server is not None
            self.server.run()
        except BaseException as exc:
            self.server_error = exc

    def request_shutdown(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.lock = RootLock(self.data_root)
        self.lock.__enter__()
        try:
            api = create_app(
                self.data_root,
                self.token,
                self.origins,
                self.port,
                system_log=self.system_log,
                shutdown_callback=self.request_shutdown,
                models_root=self.models_root,
            )
            app = CraigIngestBoundary(
                api,
                data_root=self.data_root,
                token=self.token,
                origins=self.origins,
                port=self.port,
                system_log=self.system_log,
            )
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                access_log=False,
                proxy_headers=False,
                server_header=False,
                log_level="critical",
                log_config=None,
            )
            self.server = uvicorn.Server(config)
            self.server_error = None
            self.thread = threading.Thread(target=self._serve, name="tda-companion-http", daemon=True)
            self.thread.start()
            if not wait_until_ready(self.port, expected_version=VERSION):
                error = self.server_error
                self.stop()
                if isinstance(error, ModuleNotFoundError):
                    raise RuntimeError(f"LOCAL_SERVICE_MISSING_MODULE:{error.name or 'unknown'}")
                if error is not None:
                    raise RuntimeError(f"LOCAL_SERVICE_RUNTIME_FAILED:{type(error).__name__}")
                raise RuntimeError("LOCAL_SERVICE_START_FAILED")
        except Exception:
            if self.lock is not None:
                self.lock.__exit__(None, None, None)
                self.lock = None
            raise

    def stop(self) -> None:
        self.request_shutdown()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=8)
        self.server = None
        self.thread = None
        if self.lock is not None:
            self.lock.__exit__(None, None, None)
            self.lock = None

    def run_forever(self, on_ready=None) -> None:
        self.start()
        if on_ready is not None:
            on_ready()
        try:
            while self.thread is not None and self.thread.is_alive():
                time.sleep(0.25)
            if self.server_error is not None:
                raise RuntimeError(f"LOCAL_SERVICE_RUNTIME_FAILED:{type(self.server_error).__name__}")
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
