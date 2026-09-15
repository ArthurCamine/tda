from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .large_download import download_verified_release_asset, github_release_asset_url
from .network import NetworkClient, NetworkError, classify_network_error
from .release_download import ReleaseRedirectError, open_verified_release
from .runtime_compat import whisper_runtime_version_compatible

PRODUCTION_ORIGIN = "https://dnd.faysk.dev"
MANIFEST_URL = f"{PRODUCTION_ORIGIN}/api/downloads/companion/windows/whisper-runtime/manifest"
RUNTIME_ID = "whisper-ctranslate2"
MAX_RUNTIME_DOWNLOAD_BYTES = 3 * 1024**3
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TAG = re.compile(r"^companion-whisper-runtime-v(\d+)\.(\d+)\.(\d+)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class WhisperRuntimeManifest:
    version: str
    tag: str
    url: str
    sha256: str
    size: int


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError("INVALID_RUNTIME_VERSION")
    return tuple(int(match[index]) for index in range(1, 4))  # type: ignore[return-value]


def _version_locked_runtime_url(raw_url: str, version: str) -> str:
    url = urljoin(PRODUCTION_ORIGIN + "/", raw_url)
    parsed = urlsplit(url)
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("INVALID_RUNTIME_URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "dnd.faysk.dev"
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.path != "/api/downloads/companion/windows/whisper-runtime"
        or parsed.fragment
        or query != {"version": [version]}
    ):
        raise ValueError("INVALID_RUNTIME_URL")
    return url


def parse_whisper_runtime_manifest(value: object) -> WhisperRuntimeManifest:
    if not isinstance(value, dict):
        raise ValueError("INVALID_RUNTIME_MANIFEST")
    if value.get("channel") != "stable" or value.get("runtime_id") != RUNTIME_ID:
        raise ValueError("INVALID_RUNTIME_CHANNEL")
    version = value.get("version")
    tag = value.get("tag")
    asset = value.get("asset")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("INVALID_RUNTIME_VERSION")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError("INVALID_RUNTIME_TAG")
    if tag != f"companion-whisper-runtime-v{version}" or not isinstance(asset, dict):
        raise ValueError("INVALID_RUNTIME_TAG")
    raw_url = asset.get("url")
    digest = asset.get("sha256")
    size = asset.get("size")
    if not isinstance(raw_url, str):
        raise ValueError("INVALID_RUNTIME_URL")
    url = _version_locked_runtime_url(raw_url, version)
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("INVALID_RUNTIME_DIGEST")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or size > MAX_RUNTIME_DOWNLOAD_BYTES
    ):
        raise ValueError("INVALID_RUNTIME_SIZE")
    return WhisperRuntimeManifest(version, tag, url, digest, size)


def fetch_whisper_runtime_manifest(
    timeout: float = 8.0,
    *,
    client: NetworkClient | None = None,
) -> WhisperRuntimeManifest:
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
        body = response.read(64 * 1024 + 1)
        if len(body) > 64 * 1024:
            raise NetworkError("MANIFEST_INVALID")
    try:
        return parse_whisper_runtime_manifest(json.loads(body.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise NetworkError("MANIFEST_INVALID") from exc


def whisper_runtime_update_available(
    current_version: str | None,
    manifest: WhisperRuntimeManifest,
) -> bool:
    # Companion 0.3.5 must never install an older stable worker just because no
    # compatible runtime is currently selected. RC runtimes use the dedicated
    # physical-acceptance path until these versions are promoted to Stable.
    if not whisper_runtime_version_compatible(manifest.version):
        return False
    if current_version is None:
        return True
    return _version_tuple(manifest.version) > _version_tuple(current_version)


def download_whisper_runtime(
    manifest: WhisperRuntimeManifest,
    cache_root: Path,
    timeout: float = 300.0,
    *,
    prefer_bits: bool = True,
) -> Path:
    target_dir = cache_root.resolve() / "runtime" / "whisper" / manifest.version
    target_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"TDAWhisperRuntime-{manifest.version}-windows-x64.zip"
    target = target_dir / asset_name
    request = urllib.request.Request(
        manifest.url,
        headers={
            "Accept": "application/zip,application/octet-stream",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": "TDACompanion",
        },
    )
    expected_github = github_release_asset_url(manifest.tag, asset_name)

    def fallback_open():
        try:
            return open_verified_release(
                request,
                expected_github_url=expected_github,
                timeout=timeout,
            )
        except ReleaseRedirectError as exc:
            raise RuntimeError("RUNTIME_REDIRECT_REJECTED") from exc

    try:
        return download_verified_release_asset(
            target=target,
            github_url=expected_github,
            expected_size=manifest.size,
            expected_sha256=manifest.sha256,
            timeout=timeout,
            fallback_open=fallback_open,
            prefer_bits=prefer_bits,
            size_exceeded_code="RUNTIME_SIZE_EXCEEDED",
            size_mismatch_code="RUNTIME_SIZE_MISMATCH",
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ssl.SSLError) as exc:
        failure = classify_network_error(exc)
        raise NetworkError(failure.code, status=failure.status) from exc
