from __future__ import annotations

from .execution_device import gpu_uuid, pci_bus_id

import platform
from datetime import datetime, timezone
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - old local installs remain startable
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - NVIDIA telemetry is optional at runtime
    pynvml = None


class SystemTelemetry:
    """Best-effort local telemetry. Missing sensors never make the companion unhealthy."""

    def __init__(self) -> None:
        self._nvml_initialized = False
        if psutil is not None:
            # Prime the non-blocking sampler so the first API read is useful.
            psutil.cpu_percent(interval=None)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:160] if text else None

    def _gpu_snapshot(self) -> list[dict[str, Any]]:
        if pynvml is None:
            return []
        try:
            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True

            rows: list[dict[str, Any]] = []
            driver_version: str | None = None
            driver_reader = getattr(pynvml, "nvmlSystemGetDriverVersion", None)
            if callable(driver_reader):
                try:
                    driver_value = driver_reader()
                    if isinstance(driver_value, bytes):
                        driver_value = driver_value.decode("utf-8", errors="replace")
                    driver_version = self._text(driver_value)
                except Exception:
                    driver_version = None

            count = min(int(pynvml.nvmlDeviceGetCount()), 16)
            for index in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                row = {
                    "index": index,
                    "name": self._text(name) or f"GPU {index}",
                    "utilization_percent": max(0, min(100, int(utilization.gpu))),
                    "memory_used_bytes": max(0, int(memory.used)),
                    "memory_total_bytes": max(0, int(memory.total)),
                }
                try:
                    row["uuid"] = gpu_uuid(pynvml.nvmlDeviceGetUUID(handle))
                except Exception:
                    row["uuid"] = None
                try:
                    row["pci_bus_id"] = pci_bus_id(pynvml.nvmlDeviceGetPciInfo(handle).busId)
                except Exception:
                    row["pci_bus_id"] = None
                capability_reader = getattr(
                    pynvml,
                    "nvmlDeviceGetCudaComputeCapability",
                    None,
                )
                if callable(capability_reader):
                    try:
                        major, minor = capability_reader(handle)
                        row["compute_capability"] = f"{int(major)}.{int(minor)}"
                    except Exception:
                        pass
                if driver_version:
                    row["driver_version"] = driver_version
                rows.append(row)
            return rows
        except Exception:
            # A driver reset or transient NVML failure must not disable telemetry forever.
            # Fail this sample closed and retry initialization on a later snapshot.
            self._nvml_initialized = False
            return []

    def snapshot(self) -> dict[str, Any]:
        cpu_percent: float | None = None
        memory_used: int | None = None
        memory_total: int | None = None
        memory_percent: float | None = None

        if psutil is not None:
            try:
                cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)
            except Exception:
                cpu_percent = None
            try:
                memory = psutil.virtual_memory()
                memory_used = max(0, int(memory.used))
                memory_total = max(0, int(memory.total))
                memory_percent = round(float(memory.percent), 1)
            except Exception:
                pass

        system_name = platform.system().strip()
        release = platform.release().strip()
        os_label = " ".join(part for part in (system_name, release) if part) or "Sistema local"
        cpu_name = self._text(platform.processor())

        return {
            "sampled_at": self._now(),
            "host": {
                "os": os_label[:160],
                "cpu": cpu_name,
            },
            "cpu": {"utilization_percent": cpu_percent},
            "memory": {
                "used_bytes": memory_used,
                "total_bytes": memory_total,
                "percent": memory_percent,
            },
            "gpus": self._gpu_snapshot(),
        }
