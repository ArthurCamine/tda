from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LOCAL_COMPANION = Path(__file__).resolve().parents[1]
if str(LOCAL_COMPANION) not in sys.path:
    sys.path.insert(0, str(LOCAL_COMPANION))

from tda_companion.qwen_acceptance import (  # noqa: E402
    QwenAcceptanceError,
    probe_qwen_cuda,
    run_qwen_gpu_acceptance,
)


def _read_optional(path: str | None) -> str:
    if not path:
        return ""
    source = Path(path).resolve()
    return source.read_text(encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="TDA Qwen3 ASR + Forced Aligner physical GPU acceptance")
    value.add_argument("--probe", action="store_true", help="show the PyTorch CUDA probe and exit")
    value.add_argument("--audio", help="local audio sample; acceptance is capped at 240 seconds")
    value.add_argument("--models-root", help="TDA Models root")
    value.add_argument("--profile", choices=("qwen-fast", "qwen-quality"), default="qwen-fast")
    value.add_argument("--require-gpu-name", default="")
    value.add_argument("--context-file")
    value.add_argument("--glossary-file")
    value.add_argument("--transcript-out")
    value.add_argument("--receipt-out")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.probe:
        print(json.dumps(probe_qwen_cuda(), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.audio or not args.models_root:
        parser().error("--audio and --models-root are required unless --probe is used")

    try:
        receipt = run_qwen_gpu_acceptance(
            Path(args.audio),
            Path(args.models_root),
            profile_id=args.profile,
            context=_read_optional(args.context_file),
            glossary=_read_optional(args.glossary_file),
            required_gpu_name=args.require_gpu_name,
            transcript_out=Path(args.transcript_out) if args.transcript_out else None,
        )
    except QwenAcceptanceError as exc:
        print(json.dumps({"schema": "tda_qwen_gpu_acceptance_error_v1", "pass": False, "code": exc.code}))
        return 2

    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    if args.receipt_out:
        target = Path(args.receipt_out).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
