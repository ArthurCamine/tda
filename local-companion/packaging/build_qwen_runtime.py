from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "local-companion" / "runtime" / "qwen-windows-x64.json"
ENTRY = ROOT / "local-companion" / "packaging" / "qwen_runtime_entry.py"
OUTPUT = ROOT / "local-companion" / "out" / "qwen-runtime-package"
PART_BYTES = 1900 * 1024**2
_COPY_CHUNK = 1024 * 1024


def run(*args: str, cwd: Path | None = None) -> str:
    try:
        value = subprocess.run(
            args,
            cwd=cwd or ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout.rstrip(), file=sys.stdout)
        if exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        raise
    return value.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _install_environment(python: Path, config: dict) -> None:
    torch_config = config["torch"]
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--index-url",
        str(torch_config["index_url"]),
        f"torch=={torch_config['version']}",
    )
    pins = [f"{name}=={version}" for name, version in config["packages"].items()]
    run("uv", "pip", "install", "--python", str(python), *pins)


def _probe(worker: Path) -> dict:
    value = json.loads(run(str(worker), "--probe"))
    if value.get("schema") != "tda_qwen_runtime_probe_v1" or value.get("ready") is not True:
        raise RuntimeError("QWEN_RUNTIME_PACKAGED_PROBE_NOT_READY")
    if value.get("qwen3_asr_native") is not True or value.get("forced_aligner_native") is not True:
        raise RuntimeError("QWEN_RUNTIME_PACKAGED_NATIVE_SUPPORT_MISSING")
    if value.get("audio_decode_ready") is not True:
        raise RuntimeError("QWEN_RUNTIME_PACKAGED_AUDIO_DECODE_FAILED")
    return value


def _write_zip(package_root: Path, archive: Path) -> None:
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as bundle:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(package_root).as_posix())


def _split_archive(archive: Path, version: str) -> tuple[list[dict], Path]:
    parts: list[dict] = []
    index = 1
    with archive.open("rb") as source:
        while True:
            name = f"TDAQwenRuntime-{version}-windows-x64.zip.part{index:03d}"
            target = OUTPUT / name
            written = 0
            digest = hashlib.sha256()
            with target.open("wb") as output:
                while written < PART_BYTES:
                    chunk = source.read(min(_COPY_CHUNK, PART_BYTES - written))
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if written == 0:
                target.unlink(missing_ok=True)
                break
            parts.append(
                {
                    "index": index,
                    "name": name,
                    "size": written,
                    "sha256": digest.hexdigest(),
                }
            )
            index += 1
    if not parts:
        raise RuntimeError("QWEN_RUNTIME_PACKAGE_EMPTY")

    manifest = {
        "schema": "tda_qwen_runtime_bundle_v1",
        "runtime_id": "qwen3-transformers",
        "platform": "windows-x64",
        "version": version,
        "archive": {
            "name": archive.name,
            "size": archive.stat().st_size,
            "sha256": sha256(archive),
        },
        "parts": parts,
    }
    target = OUTPUT / f"TDAQwenRuntimeBundle-{version}-windows-x64.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return parts, target


def _smoke_installer(archive: Path, version: str, digest: str) -> dict:
    sys.path.insert(0, str(ROOT / "local-companion"))
    from tda_companion.qwen_runtime import (  # noqa: PLC0415
        inspect_qwen_runtime,
        install_qwen_runtime_archive,
    )

    with tempfile.TemporaryDirectory(prefix="tda-qwen-install-") as value:
        runtime_root = Path(value) / "Runtime"
        install_qwen_runtime_archive(
            archive,
            runtime_root,
            version=version,
            expected_sha256=digest,
        )
        state = inspect_qwen_runtime(runtime_root, verify_worker=True)
        if state.get("status") != "ready" or state.get("version") != version:
            raise RuntimeError("QWEN_RUNTIME_INSTALL_SMOKE_FAILED")
        worker = Path(str(state["worker"]))
        return _probe(worker)


def main() -> int:
    if os.name != "nt" or not sys.maxsize > 2**32:
        raise RuntimeError("QWEN_RUNTIME_WINDOWS_X64_REQUIRED")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config.get("schema") != "tda_qwen_runtime_build_v1":
        raise RuntimeError("QWEN_RUNTIME_MANIFEST_SCHEMA")

    version = str(config["version"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT.glob("TDAQwenRuntime-*-windows-x64.zip.part*"):
        stale.unlink()

    with tempfile.TemporaryDirectory(prefix="tda-qwen-package-") as temp_value:
        temp = Path(temp_value)
        venv = temp / ".venv"
        run("uv", "venv", str(venv), "--python", str(config["python"]))
        python = venv / "Scripts" / "python.exe"
        _install_environment(python, config)

        dist = temp / "dist"
        work = temp / "work"
        run(
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--console",
            "--name",
            "TDAQwenWorker",
            "--paths",
            str(ROOT / "local-companion"),
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            "--collect-all",
            "torch",
            "--collect-all",
            "transformers",
            "--collect-all",
            "tokenizers",
            "--collect-all",
            "safetensors",
            "--collect-all",
            "av",
            "--hidden-import",
            "accelerate",
            "--hidden-import",
            "huggingface_hub",
            "--copy-metadata",
            "nvidia-ml-py",
            "--hidden-import",
            "pynvml",
            "--hidden-import",
            "tda_companion.asr_qwen",
            "--hidden-import",
            "tda_companion.qwen_acceptance",
            "--hidden-import",
            "tda_companion.asr_worker",
            str(ENTRY),
        )
        built = dist / "TDAQwenWorker"
        worker = built / "TDAQwenWorker.exe"
        if not worker.is_file():
            raise RuntimeError("QWEN_RUNTIME_WORKER_NOT_CREATED")

        probe = _probe(worker)
        if not str(probe.get("python_packages", {}).get("torch", "")).startswith(
            str(config["torch"]["version"])
        ):
            raise RuntimeError("QWEN_RUNTIME_PACKAGED_TORCH_VERSION_MISMATCH")
        if str(probe.get("torch_cuda")) != str(config["torch"]["cuda_family"]):
            raise RuntimeError("QWEN_RUNTIME_PACKAGED_CUDA_FAMILY_MISMATCH")
        if probe.get("audio_decode_ready") is not True:
            raise RuntimeError("QWEN_RUNTIME_PACKAGED_AUDIO_DECODE_FAILED")
        expected_nvml = str(config["packages"]["nvidia-ml-py"])
        observed_nvml = str(probe.get("python_packages", {}).get("nvidia_ml_py", ""))
        if observed_nvml != expected_nvml:
            raise RuntimeError("QWEN_RUNTIME_PACKAGED_NVML_VERSION_MISMATCH")

        metadata = {
            "schema": "tda_qwen_runtime_artifact_v1",
            "runtime_id": config["runtime_id"],
            "version": version,
            "python": config["python"],
            "torch": config["torch"],
            "packages": config["packages"],
            "gpu": config["gpu"],
            "probe": probe,
            "physical_gpu_validated": False,
        }
        (built / "runtime-build.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        archive = OUTPUT / f"TDAQwenRuntime-{version}-windows-x64.zip"
        _write_zip(built, archive)
        archive_digest = sha256(archive)
        installed_probe = _smoke_installer(archive, version, archive_digest)
        parts, bundle_manifest = _split_archive(archive, version)

        report = {
            "schema": "tda_qwen_runtime_package_report_v1",
            "version": version,
            "package_uncompressed_bytes": directory_size(built),
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": archive_digest,
            "part_count": len(parts),
            "parts": parts,
            "bundle_manifest": bundle_manifest.name,
            "probe": probe,
            "installed_probe": installed_probe,
            "physical_gpu_validated": False,
        }
        report_path = OUTPUT / f"TDAQwenRuntimePackage-{version}-windows-x64.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
