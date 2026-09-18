from __future__ import annotations

import argparse
import json
import sys
import tempfile
import wave
from importlib import metadata
from pathlib import Path


def _version(name: str) -> str:
    try:
        return metadata.version(name)
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


def _probe() -> int:
    try:
        import accelerate  # noqa: F401
        import av  # noqa: F401
        import huggingface_hub  # noqa: F401
        import numpy  # noqa: F401
        import pynvml  # noqa: F401
        import safetensors  # noqa: F401
        import torch
        import transformers
        from tda_companion.qwen_acceptance import _decode_audio_array
        from tda_companion.qwen_physical_gate import MIN_GATE_AUDIO_SECONDS
        from transformers import (
            AutoModelForMultimodalLM,
            AutoModelForTokenClassification,
            AutoProcessor,
            Qwen3ASRConfig,
            Qwen3ASRForConditionalGeneration,
        )

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

    try:
        with tempfile.TemporaryDirectory(prefix="tda-qwen-audio-probe-") as value:
            sample = Path(value) / "probe.wav"
            with wave.open(str(sample), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(b"\x00\x00" * 16_000)
            decoded = _decode_audio_array(sample)
            audio_decode_ready = int(getattr(decoded, "size", 0)) == 16_000
            if not audio_decode_ready:
                raise RuntimeError("QWEN_AUDIO_DECODE_PROBE_INVALID")
    except Exception:
        audio_decode_ready = False

    available = bool(torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if available else 0
    driver_version = _driver_version(pynvml)
    cuda_execution_ready, cuda_execution_error = _cuda_execution_probe(torch)
    devices: list[dict[str, object]] = []
    for index in range(count):
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
    print(
        json.dumps(
            {
                "schema": "tda_qwen_runtime_probe_v1",
                "ready": True,
                "python_packages": {
                    "torch": _version("torch"),
                    "transformers": _version("transformers"),
                    "accelerate": _version("accelerate"),
                    "huggingface_hub": _version("huggingface-hub"),
                    "safetensors": _version("safetensors"),
                    "av": _version("av"),
                    "numpy": _version("numpy"),
                    "nvidia_ml_py": _version("nvidia-ml-py"),
                },
                "transformers": transformers.__version__,
                "torch_cuda": str(torch.version.cuda or "none"),
                "driver_version": driver_version,
                "audio_decode_ready": audio_decode_ready,
                "cuda_available": available,
                "cuda_device_count": count,
                "cuda_execution_ready": cuda_execution_ready,
                "cuda_execution_error": cuda_execution_error,
                "bf16_supported": bool(torch.cuda.is_bf16_supported()) if available else False,
                "qwen3_asr_native": True,
                "forced_aligner_native": True,
                "physical_gate_available": True,
                "long_track_acceptance_window": True,
                "min_gate_audio_seconds": float(MIN_GATE_AUDIO_SECONDS),
                "devices": devices,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


def _read_context(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        value = path.resolve().read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("ACCEPTANCE_CONTEXT_FILE_INVALID") from exc
    if len(value) > 16_384:
        raise RuntimeError("ACCEPTANCE_CONTEXT_FILE_TOO_LARGE")
    return value


def _installed_runtime_root(explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit.resolve()
    elif getattr(sys, "frozen", False):
        # Runtime/qwen/<version>/TDAQwenWorker.exe -> Runtime
        root = Path(sys.executable).resolve().parent.parent.parent
    else:
        raise RuntimeError("QWEN_GATE_RUNTIME_ROOT_REQUIRED")
    if root.name.casefold() != "runtime":
        raise RuntimeError("QWEN_GATE_RUNTIME_ROOT_INVALID")
    return root


def _acceptance(args: argparse.Namespace) -> int:
    from tda_companion.qwen_acceptance import (
        ACCEPTANCE_SCHEMA,
        QwenAcceptanceError,
        run_qwen_gpu_acceptance,
    )

    if args.audio is None or args.models_root is None:
        print(
            json.dumps(
                {"schema": ACCEPTANCE_SCHEMA, "pass": False, "error": "ACCEPTANCE_ARGUMENTS_REQUIRED"},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 64

    try:
        context = _read_context(args.context_file)
        glossary = _read_context(args.glossary_file)
        runtime_root = _installed_runtime_root(args.runtime_root) if args.record_gate else None
        state_root = (
            (args.state_root or runtime_root.parent / "State").resolve()
            if runtime_root is not None
            else None
        )

        def execute(source: Path, window_meta: dict[str, float] | None = None) -> dict[str, object]:
            receipt = run_qwen_gpu_acceptance(
                source,
                args.models_root,
                profile_id=args.profile,
                glossary=glossary,
                context=context,
                required_gpu_name=args.require_gpu_name,
                transcript_out=args.transcript_out,
            )
            if window_meta is not None:
                receipt["source_window"] = window_meta
            if args.record_gate:
                from tda_companion.qwen_physical_gate import record_qwen_physical_gate

                assert runtime_root is not None and state_root is not None
                record_qwen_physical_gate(
                    state_root,
                    runtime_root,
                    args.models_root.resolve(),
                    receipt,
                    profile_id=args.profile,
                    required_gpu_name=args.require_gpu_name,
                )
            return receipt

        if args.acceptance_window:
            if args.scratch_root is None:
                raise RuntimeError("ACCEPTANCE_SCRATCH_ROOT_REQUIRED")
            if args.transcript_out is not None:
                raise RuntimeError("ACCEPTANCE_WINDOW_TRANSCRIPT_FORBIDDEN")
            scratch_root = args.scratch_root.resolve()
            scratch_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="tda-qwen-gate-", dir=str(scratch_root)) as temporary:
                from tda_companion.qwen_acceptance_window import materialize_qwen_acceptance_window

                sample = Path(temporary) / "acceptance-window.wav"
                window_meta = materialize_qwen_acceptance_window(args.audio, sample)
                receipt = execute(sample, window_meta)
        else:
            receipt = execute(args.audio)
    except QwenAcceptanceError as exc:
        print(
            json.dumps(
                {"schema": ACCEPTANCE_SCHEMA, "pass": False, "error": exc.code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 66
    except RuntimeError as exc:
        code = str(exc)
        if not code.startswith(("ACCEPTANCE_", "QWEN_GATE_")):
            code = "ACCEPTANCE_FAILED"
        print(
            json.dumps(
                {"schema": ACCEPTANCE_SCHEMA, "pass": False, "error": code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 67 if code.startswith("QWEN_GATE_") else 66
    except BaseException:
        print(
            json.dumps(
                {"schema": ACCEPTANCE_SCHEMA, "pass": False, "error": "ACCEPTANCE_FAILED"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 70

    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="TDAQwenWorker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--acceptance", action="store_true")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--models-root", type=Path)
    parser.add_argument(
        "--profile",
        choices=("qwen-fast", "qwen-quality"),
        default="qwen-fast",
    )
    parser.add_argument("--require-gpu-name", default="RTX 4070")
    parser.add_argument("--transcript-out", type=Path)
    parser.add_argument("--glossary-file", type=Path)
    parser.add_argument("--context-file", type=Path)
    parser.add_argument("--record-gate", action="store_true")
    parser.add_argument("--acceptance-window", action="store_true")
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    if args.probe:
        return _probe()
    if args.acceptance:
        return _acceptance(args)

    from tda_companion.asr_worker import run_worker_stdio

    return run_worker_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
