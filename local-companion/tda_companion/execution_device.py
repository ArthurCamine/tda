"""Resolve CUDA's process-local ordinal through the driver, never through NVML order."""
from __future__ import annotations

import ctypes
import os
import re
import uuid
from collections.abc import Mapping

_CUDA = re.compile(r"cuda(?::([0-9]{1,2}))?", re.IGNORECASE)
_UUID = re.compile(r"(?:GPU|MIG)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_PCI = re.compile(r"([0-9a-f]{4,8}):([0-9a-f]{2}):([0-9a-f]{2})\.([0-7])", re.IGNORECASE)


def gpu_uuid(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        return None
    prefix, identifier = value.split("-", 1)
    return prefix.upper() + "-" + identifier.lower()


def pci_bus_id(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    match = _PCI.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    domain, bus, device, function = match.groups()
    return f"{int(domain, 16):08x}:{bus.lower()}:{device.lower()}.{function}"


def sanitize_execution_device(value: object) -> dict | None:
    if not isinstance(value, Mapping) or value.get("kind") not in ("cuda", "cpu"):
        return None
    if value["kind"] == "cpu":
        return {"kind": "cpu", "logical_index": None, "physical_uuid": None, "pci_bus_id": None}
    index = value.get("logical_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 100:
        return None
    return {"kind": "cuda", "logical_index": index, "physical_uuid": gpu_uuid(value.get("physical_uuid")), "pci_bus_id": pci_bus_id(value.get("pci_bus_id"))}


def resolve_execution_device(device: str, *, driver=None) -> dict | None:
    if device == "cpu":
        return sanitize_execution_device({"kind": "cpu"})
    match = _CUDA.fullmatch(device)
    if match is None:
        return None
    index = int(match.group(1) or "0")
    identity = {"kind": "cuda", "logical_index": index, "physical_uuid": None, "pci_bus_id": None}
    try:
        api = driver if driver is not None else (ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1"))
        if api.cuInit(0) != 0:
            return identity
        selected = ctypes.c_int()
        if api.cuDeviceGet(ctypes.byref(selected), index) != 0:
            return identity
        raw_uuid = (ctypes.c_ubyte * 16)()
        get_uuid = getattr(api, "cuDeviceGetUuid_v2", None) or api.cuDeviceGetUuid
        if get_uuid(ctypes.byref(raw_uuid), selected) == 0 and any(raw_uuid):
            identity["physical_uuid"] = "GPU-" + str(uuid.UUID(bytes=bytes(raw_uuid)))
        raw_pci = ctypes.create_string_buffer(32)
        if api.cuDeviceGetPCIBusId(raw_pci, len(raw_pci), selected) == 0:
            identity["pci_bus_id"] = pci_bus_id(raw_pci.value)
    except Exception:  # Optional driver identity must not fail an ASR result.
        pass
    return identity


def matching_gpu(rows: object, identity: object) -> dict | None:
    device = sanitize_execution_device(identity)
    if not device or device["kind"] != "cuda" or not isinstance(rows, list):
        return None
    # A UUID mismatch must not fall through to a shared PCI address (e.g. MIG).
    if device["physical_uuid"]:
        matches = [row for row in rows if isinstance(row, dict) and gpu_uuid(row.get("uuid")) == device["physical_uuid"]]
    elif device["pci_bus_id"]:
        matches = [row for row in rows if isinstance(row, dict) and pci_bus_id(row.get("pci_bus_id")) == device["pci_bus_id"]]
    else:
        return None
    return matches[0] if len(matches) == 1 else None


_active_device: dict | None = None


def reset_execution_device() -> None:
    global _active_device
    _active_device = None


def committed_execution_device(device: str) -> dict | None:
    if device == "cpu":
        return sanitize_execution_device({"kind": "cpu"})
    match = _CUDA.fullmatch(device)
    if match is None:
        return None
    logical = int(match.group(1) or "0")
    if _active_device and _active_device["kind"] == "cuda" and _active_device["logical_index"] == logical:
        return dict(_active_device)
    # A checkpoint-only attempt may never load a GPU model. Do not invent use.
    return {"kind": "cuda", "logical_index": logical, "physical_uuid": None, "pci_bus_id": None}


def device_event(device: str) -> dict:
    global _active_device
    identity = resolve_execution_device(device)
    _active_device = dict(identity) if identity else None
    data = {"type": "event", "code": "ASR_EXECUTION_DEVICE", "stage": "model_load", "device": device}
    if identity:
        data.update({key: value for key, value in identity.items() if value is not None})
    return data
