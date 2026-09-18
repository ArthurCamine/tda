from __future__ import annotations

import json
import sys
from importlib import metadata


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unavailable"


def _driver_version(pynvml) -> str | None:
    try:
        pynvml.nvmlInit()
        try:
            value = pynvml.nvmlSystemGetDriverVersion()
        finally:
            pynvml.nvmlShutdown()
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="replace")
        text = str(value or "").strip()
        return text or None
    except Exception:
        return None


def _cuda_execution_probe(torch) -> tuple[bool | None, str | None]:
    if not bool(torch.cuda.is_available()) or int(torch.cuda.device_count()) < 1:
        return None, None
    try:
        probe = torch.ones((32,), device="cuda:0", dtype=torch.float32)
        observed = float((probe * 2.0).sum().item())
        torch.cuda.synchronize()
        if observed != 64.0:
            raise RuntimeError("CUDA_EXECUTION_RESULT_INVALID")
        return True, None
    except Exception as exc:
        value = f"{type(exc).__name__}: {exc}".casefold()
        if any(
            marker in value
            for marker in (
                "driver version is insufficient",
                "cuda driver version is insufficient",
                "forward compatibility was attempted",
                "unsupported display driver",
            )
        ):
            return False, "QWEN_CUDA_DRIVER_INCOMPATIBLE"
        return False, "QWEN_CUDA_EXECUTION_FAILED"


def main() -> int:
    try:
        import accelerate
        import av
        import huggingface_hub
        import numpy
        import pynvml
        import safetensors
        import torch
        import transformers
        from transformers import (
            AutoModelForMultimodalLM,
            AutoModelForTokenClassification,
            AutoProcessor,
            Qwen3ASRConfig,
            Qwen3ASRForConditionalGeneration,
        )

        del accelerate, av, huggingface_hub, numpy, safetensors
        del AutoModelForMultimodalLM, AutoModelForTokenClassification, AutoProcessor
        del Qwen3ASRConfig, Qwen3ASRForConditionalGeneration
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "tda_qwen_runtime_probe_v1",
                    "ready": False,
                    "error": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 1

    cuda_available = bool(torch.cuda.is_available())
    device_count = int(torch.cuda.device_count()) if cuda_available else 0
    driver_version = _driver_version(pynvml)
    cuda_execution_ready, cuda_execution_error = _cuda_execution_probe(torch)
    devices: list[dict[str, object]] = []
    for index in range(device_count):
        props = torch.cuda.get_device_properties(index)
        major, minor = torch.cuda.get_device_capability(index)
        devices.append(
            {
                "index": index,
                "name": str(props.name),
                "compute_capability": f"{major}.{minor}",
                "total_memory_bytes": int(props.total_memory),
            }
        )

    payload = {
        "schema": "tda_qwen_runtime_probe_v1",
        "ready": True,
        "python": sys.version.split()[0],
        "torch": _version("torch"),
        "torch_cuda": str(torch.version.cuda or "none"),
        "driver_version": driver_version,
        "cuda_execution_ready": cuda_execution_ready,
        "cuda_execution_error": cuda_execution_error,
        "transformers": transformers.__version__,
        "accelerate": _version("accelerate"),
        "huggingface_hub": _version("huggingface-hub"),
        "safetensors": _version("safetensors"),
        "av": _version("av"),
        "numpy": _version("numpy"),
        "nvidia_ml_py": _version("nvidia-ml-py"),
        "qwen3_asr_native": True,
        "forced_aligner_native": True,
        "cuda_available": cuda_available,
        "cuda_device_count": device_count,
        "bf16_supported": bool(torch.cuda.is_bf16_supported()) if cuda_available else False,
        "devices": devices,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
