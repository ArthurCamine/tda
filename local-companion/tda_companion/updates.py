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

PRODUCTION_ORIGIN = "https://dnd.faysk.dev"
MANIFEST_URL = f"{PRODUCTION_ORIGIN}/api/downloads/companion/windows/manifest"
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_STABLE_TAG = re.compile(r"^companion-v(\d+)\.(\d+)\.(\d+)$")
_RC_TAG = re.compile(r"^companion-rc-v(\d+)\.(\d+)\.(\d+)-([a-f0-9]{12})$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    tag: str
    minimum_api: str
    url: str
    sha256: str
    size: int


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError("INVALID_VERSION")
    return tuple(int(match[index]) for index in range(1, 4))  # type: ignore[return-value]


def _validate_release_tag(channel: str, version: str, tag: str) -> None:
    if channel == "stable":
        if not _STABLE_TAG.fullmatch(tag) or tag != f"companion-v{version}":
            raise ValueError("INVALID_UPDATE_TAG")
        return

    if channel == "rc":
        match = _RC_TAG.fullmatch(tag)
        if not match or ".".join(match.groups()[:3]) != version:
            raise ValueError("INVALID_UPDATE_TAG")
        return

    raise ValueError("INVALID_UPDATE_CHANNEL")


def _release_locked_download_url(
    raw_url: str,
    *,
    channel: str,
    version: str,
    tag: str,
) -> str:
    url = urljoin(PRODUCTION_ORIGIN + "/", raw_url)
    parsed = urlsplit(url)
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("INVALID_UPDATE_URL") from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != "dnd.faysk.dev"
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.path != "/api/downloads/companion/windows"
        or parsed.fragment
    ):
        raise ValueError("INVALID_UPDATE_URL")

    # The current manifest pins every installable release to its exact tag.
    # Keep the previous stable-only version lock as a compatibility input, but
    # never allow a prerelease to be addressed by version alone.
    expected_tag_query = {"tag": [tag]}
    legacy_stable_query = {"version": [version]}
    if query != expected_tag_query and not (
        channel == "stable" and query == legacy_stable_query
    ):
        raise ValueError("INVALID_UPDATE_URL")
    return url


def parse_manifest(value: object) -> UpdateManifest:
    if not isinstance(value, dict):
        raise ValueError("INVALID_UPDATE_MANIFEST")

    channel = value.get("channel")
    version = value.get("version")
    tag = value.get("tag")
    minimum_api = value.get("minimum_api")
    asset = value.get("asset")

    if channel not in {"stable", "rc"}:
        raise ValueError("INVALID_UPDATE_CHANNEL")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("INVALID_UPDATE_VERSION")
    if not isinstance(tag, str):
        raise ValueError("INVALID_UPDATE_TAG")
    _validate_release_tag(channel, version, tag)
    if minimum_api != "1" or not isinstance(asset, dict):
        raise ValueError("INCOMPATIBLE_UPDATE_MANIFEST")

    raw_url = asset.get("url")
    digest = asset.get("sha256")
    size = asset.get("size")
    if not isinstance(raw_url, str):
        raise ValueError("INVALID_UPDATE_URL")
    url = _release_locked_download_url(
        raw_url,
        channel=channel,
        version=version,
        tag=tag,
    )
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("INVALID_UPDATE_DIGEST")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > 512 * 1024 * 1024:
        raise ValueError("INVALID_UPDATE_SIZE")
    return UpdateManifest(version, tag, minimum_api, url, digest, size)


def fetch_manifest(
    timeout: float = 8.0,
    *,
    client: NetworkClient | None = None,
) -> UpdateManifest:
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
        return parse_manifest(json.loads(body.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise NetworkError("MANIFEST_INVALID") from exc


def update_available(current_version: str, manifest: UpdateManifest) -> bool:
    return version_tuple(manifest.version) > version_tuple(current_version)


def download_update(
    manifest: UpdateManifest,
    cache_root: Path,
    timeout: float = 60.0,
    *,
    prefer_bits: bool = True,
) -> Path:
    target_dir = cache_root / "updates" / manifest.version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "TDACompanion-x64.msi"
    request = urllib.request.Request(
        manifest.url,
        headers={
            "Accept": "application/x-msi,application/octet-stream",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": "TDACompanion",
        },
    )
    expected_github_url = github_release_asset_url(
        manifest.tag,
        "TDACompanion-x64.msi",
    )

    def fallback_open():
        try:
            return open_verified_release(
                request,
                expected_github_url=expected_github_url,
                timeout=timeout,
            )
        except ReleaseRedirectError as exc:
            raise RuntimeError("UPDATE_REDIRECT_REJECTED") from exc

    try:
        return download_verified_release_asset(
            target=target,
            github_url=expected_github_url,
            expected_size=manifest.size,
            expected_sha256=manifest.sha256,
            timeout=timeout,
            fallback_open=fallback_open,
            prefer_bits=prefer_bits,
            size_exceeded_code="UPDATE_SIZE_EXCEEDED",
            size_mismatch_code="UPDATE_SIZE_MISMATCH",
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ssl.SSLError) as exc:
        failure = classify_network_error(exc)
        raise NetworkError(failure.code, status=failure.status) from exc
