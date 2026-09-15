from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .large_download import download_verified_release_asset, github_release_asset_url
from .network import NetworkClient, NetworkError, classify_network_error
from .qwen_runtime_bundle import (
    QwenRuntimeBundleManifest,
    QwenRuntimePart,
    assemble_qwen_runtime_bundle,
    parse_qwen_runtime_bundle_manifest,
)
from .release_download import ReleaseRedirectError, open_verified_release
from .runtime_compat import qwen_runtime_version_compatible

PRODUCTION_ORIGIN = "https://dnd.faysk.dev"
MANIFEST_URL = f"{PRODUCTION_ORIGIN}/api/downloads/companion/windows/qwen-runtime/manifest"
RUNTIME_ID = "qwen3-transformers"
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TAG = re.compile(r"^companion-qwen-runtime-v(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class QwenRuntimeDownloadManifest:
    version: str
    tag: str
    bundle: QwenRuntimeBundleManifest


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError("INVALID_QWEN_RUNTIME_VERSION")
    return tuple(int(match[index]) for index in range(1, 4))  # type: ignore[return-value]


def parse_qwen_runtime_download_manifest(value: object) -> QwenRuntimeDownloadManifest:
    if not isinstance(value, dict):
        raise ValueError("INVALID_QWEN_RUNTIME_MANIFEST")
    if value.get("channel") != "stable" or value.get("runtime_id") != RUNTIME_ID:
        raise ValueError("INVALID_QWEN_RUNTIME_CHANNEL")
    version = value.get("version")
    tag = value.get("tag")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("INVALID_QWEN_RUNTIME_VERSION")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError("INVALID_QWEN_RUNTIME_TAG")
    if tag != f"companion-qwen-runtime-v{version}":
        raise ValueError("INVALID_QWEN_RUNTIME_TAG")
    try:
        bundle = parse_qwen_runtime_bundle_manifest(value.get("bundle"))
    except Exception as exc:
        raise ValueError("INVALID_QWEN_RUNTIME_BUNDLE") from exc
    if bundle.version != version or bundle.runtime_id != RUNTIME_ID:
        raise ValueError("INVALID_QWEN_RUNTIME_BUNDLE")
    return QwenRuntimeDownloadManifest(version=version, tag=tag, bundle=bundle)


def fetch_qwen_runtime_manifest(
    timeout: float = 8.0,
    *,
    client: NetworkClient | None = None,
) -> QwenRuntimeDownloadManifest:
    request = urllib.request.Request(
        MANIFEST_URL,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": "TDACompanion",
        },
    )
    network = client or NetworkClient.internet()
    with network.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise NetworkError("HTTP_ERROR", status=response.status)
        body = response.read(256 * 1024 + 1)
        if len(body) > 256 * 1024:
            raise NetworkError("MANIFEST_INVALID")
    try:
        value = json.loads(body.decode("utf-8"))
        return parse_qwen_runtime_download_manifest(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise NetworkError("MANIFEST_INVALID") from exc


def qwen_runtime_update_available(
    current_version: str | None,
    manifest: QwenRuntimeDownloadManifest,
) -> bool:
    # Companion 0.3.5 cannot install an obsolete Stable when the compatible
    # 1.0.2+ worker is still only available through the dedicated RC gate.
    if not qwen_runtime_version_compatible(manifest.version):
        return False
    if current_version is None:
        return True
    return _version_tuple(manifest.version) > _version_tuple(current_version)


def _part_endpoint(part: QwenRuntimePart) -> str:
    return f"{PRODUCTION_ORIGIN}/api/downloads/companion/windows/qwen-runtime/{part.name}"


def _release_asset_url(manifest: QwenRuntimeDownloadManifest, part: QwenRuntimePart) -> str:
    return github_release_asset_url(manifest.tag, part.name)


def _download_part(
    manifest: QwenRuntimeDownloadManifest,
    part: QwenRuntimePart,
    target: Path,
    *,
    timeout: float,
    prefer_bits: bool,
) -> Path:
    request = urllib.request.Request(
        _part_endpoint(part),
        headers={
            "Accept": "application/octet-stream",
            "Cache-Control": "no-cache",
            "User-Agent": "TDACompanion",
        },
    )
    expected_github = _release_asset_url(manifest, part)

    def fallback_open():
        try:
            return open_verified_release(
                request,
                expected_github_url=expected_github,
                timeout=timeout,
            )
        except ReleaseRedirectError as exc:
            raise RuntimeError("QWEN_RUNTIME_REDIRECT_REJECTED") from exc

    try:
        return download_verified_release_asset(
            target=target,
            github_url=expected_github,
            expected_size=part.size,
            expected_sha256=part.sha256,
            timeout=timeout,
            fallback_open=fallback_open,
            prefer_bits=prefer_bits,
            size_exceeded_code="QWEN_RUNTIME_PART_SIZE_EXCEEDED",
            size_mismatch_code="QWEN_RUNTIME_PART_SIZE_MISMATCH",
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ssl.SSLError) as exc:
        failure = classify_network_error(exc)
        raise NetworkError(failure.code, status=failure.status) from exc


def download_qwen_runtime(
    manifest: QwenRuntimeDownloadManifest,
    cache_root: Path,
    timeout: float = 300.0,
    *,
    prefer_bits: bool = True,
) -> Path:
    root = cache_root.resolve() / "runtime" / "qwen" / manifest.version
    parts_root = root / "parts"
    assembled_root = root / "assembled"
    parts_root.mkdir(parents=True, exist_ok=True)
    for part in manifest.bundle.parts:
        _download_part(
            manifest,
            part,
            parts_root / part.name,
            timeout=timeout,
            prefer_bits=prefer_bits,
        )
    return assemble_qwen_runtime_bundle(manifest.bundle, parts_root, assembled_root)
