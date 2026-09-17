from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .large_download import download_verified_release_asset, github_release_asset_url
from .network import NetworkClient, NetworkError
from .rc_runtime_artifacts import (
    RC_QWEN_VERSION,
    RC_WHISPER_VERSION,
    RcRuntimeArtifactError,
    install_runtime_candidate,
)
from .release_download import ReleaseRedirectError, open_verified_release
from .runtime_release_evidence import RuntimeReleaseEvidenceError, _parse_candidate, verify_candidate_assets

_GITHUB_RELEASES_API = "https://api.github.com/repos/Faysk/tda/releases"
_CANDIDATE_ASSET = "TDARuntime-candidate.json"
_RELEASE_PAGE_SIZE = 100
_MAX_RELEASE_PAGES = 5
_MAX_RELEASE_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 512 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TAGS = {
    "whisper": re.compile(r"^companion-whisper-runtime-rc-v(\d+\.\d+\.\d+)-([a-f0-9]{12})$"),
    "qwen": re.compile(r"^companion-qwen-runtime-rc-v(\d+\.\d+\.\d+)-([a-f0-9]{12})$"),
}
_VERSIONS = {
    "whisper": RC_WHISPER_VERSION,
    "qwen": RC_QWEN_VERSION,
}


class RuntimeRcUpdateError(NetworkError):
    pass


def _raise(code: str) -> None:
    raise RuntimeRcUpdateError(code)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _asset_digest(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return None
    digest = value[7:].casefold()
    return digest if _SHA256.fullmatch(digest) else None


def _read_json_response(response: Any, *, limit: int, code: str) -> object:
    status = int(getattr(response, "status", 200))
    if status != 200:
        raise RuntimeRcUpdateError("HTTP_ERROR", status=status)
    body = response.read(limit + 1)
    if len(body) > limit:
        _raise(code)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeRcUpdateError(code) from exc


def _release_assets(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = release.get("assets")
    if not isinstance(raw, list):
        _raise("RUNTIME_RC_RELEASE_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            _raise("RUNTIME_RC_RELEASE_INVALID")
        name = item.get("name")
        if not isinstance(name, str) or not name or Path(name).name != name or name in result:
            _raise("RUNTIME_RC_RELEASE_INVALID")
        size = item.get("size")
        url = item.get("browser_download_url")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(url, str)
        ):
            _raise("RUNTIME_RC_RELEASE_INVALID")
        result[name] = item
    return result


def discover_published_runtime_rc(
    family: str,
    *,
    client: NetworkClient | None = None,
) -> dict[str, Any]:
    """Resolve the newest published prerelease for the exact compatible runtime version."""
    if family not in _VERSIONS:
        _raise("RUNTIME_RC_FAMILY_INVALID")
    expected_version = _VERSIONS[family]
    pattern = _TAGS[family]
    network = client or NetworkClient.internet()
    matches: list[dict[str, Any]] = []

    for page in range(1, _MAX_RELEASE_PAGES + 1):
        request = urllib.request.Request(
            f"{_GITHUB_RELEASES_API}?per_page={_RELEASE_PAGE_SIZE}&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "User-Agent": "TDACompanion",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with network.open(request, timeout=10.0) as response:
            value = _read_json_response(
                response,
                limit=_MAX_RELEASE_RESPONSE_BYTES,
                code="RUNTIME_RC_RELEASE_RESPONSE_INVALID",
            )
        if not isinstance(value, list):
            _raise("RUNTIME_RC_RELEASE_RESPONSE_INVALID")
        for release in value:
            if not isinstance(release, dict):
                continue
            tag = release.get("tag_name")
            match = pattern.fullmatch(tag) if isinstance(tag, str) else None
            if (
                match is None
                or match.group(1) != expected_version
                or release.get("draft") is not False
                or release.get("prerelease") is not True
            ):
                continue
            published = release.get("published_at")
            release_id = release.get("id")
            if not isinstance(published, str) or not isinstance(release_id, int) or isinstance(release_id, bool):
                _raise("RUNTIME_RC_RELEASE_INVALID")
            _release_assets(release)
            matches.append(release)
        if len(value) < _RELEASE_PAGE_SIZE:
            break

    if not matches:
        _raise("RUNTIME_RC_RELEASE_NOT_PUBLISHED")
    matches.sort(key=lambda item: (str(item.get("published_at") or ""), int(item.get("id") or 0)))
    return matches[-1]


def _read_candidate_manifest(
    release: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], bytes]:
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        _raise("RUNTIME_RC_RELEASE_INVALID")
    assets = _release_assets(release)
    metadata = assets.get(_CANDIDATE_ASSET)
    if metadata is None:
        _raise("RUNTIME_RC_RELEASE_INCOMPLETE")
    expected_url = github_release_asset_url(tag, _CANDIDATE_ASSET)
    if metadata.get("browser_download_url") != expected_url:
        _raise("RUNTIME_RC_RELEASE_ASSET_URL_INVALID")
    expected_digest = _asset_digest(metadata.get("digest"))
    if expected_digest is None:
        _raise("RUNTIME_RC_RELEASE_ASSET_DIGEST_MISSING")

    request = urllib.request.Request(
        expected_url,
        headers={
            "Accept": "application/json,application/octet-stream",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": "TDACompanion",
        },
    )
    try:
        with open_verified_release(
            request,
            expected_github_url=expected_url,
            timeout=timeout,
        ) as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise RuntimeRcUpdateError("HTTP_ERROR", status=status)
            raw = response.read(_MAX_CANDIDATE_BYTES + 1)
    except ReleaseRedirectError as exc:
        raise RuntimeRcUpdateError("RUNTIME_RC_RELEASE_REDIRECT_REJECTED") from exc
    if len(raw) > _MAX_CANDIDATE_BYTES or len(raw) != metadata.get("size"):
        _raise("RUNTIME_RC_CANDIDATE_SIZE_MISMATCH")
    if _sha256_bytes(raw) != expected_digest:
        _raise("RUNTIME_RC_CANDIDATE_HASH_MISMATCH")
    try:
        parsed = json.loads(raw.decode("utf-8"))
        candidate = _parse_candidate(parsed)
    except (UnicodeError, json.JSONDecodeError, RuntimeReleaseEvidenceError) as exc:
        raise RuntimeRcUpdateError("RUNTIME_RC_CANDIDATE_INVALID") from exc
    return candidate, raw


def _validate_candidate_release_identity(
    family: str,
    release: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        _raise("RUNTIME_RC_RELEASE_INVALID")
    match = _TAGS[family].fullmatch(tag)
    if match is None:
        _raise("RUNTIME_RC_RELEASE_TAG_INVALID")
    expected_version = _VERSIONS[family]
    source = candidate.get("source_sha")
    if (
        candidate.get("family") != family
        or candidate.get("version") != expected_version
        or candidate.get("candidate_tag") != tag
        or not isinstance(source, str)
        or not source.startswith(match.group(2))
    ):
        _raise("RUNTIME_RC_CANDIDATE_IDENTITY_MISMATCH")

    release_assets = _release_assets(release)
    candidate_assets = candidate.get("assets")
    if not isinstance(candidate_assets, list):
        _raise("RUNTIME_RC_CANDIDATE_INVALID")
    expected_names = {_CANDIDATE_ASSET}
    for item in candidate_assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            _raise("RUNTIME_RC_CANDIDATE_INVALID")
        expected_names.add(str(item["name"]))
    if set(release_assets) != expected_names:
        _raise("RUNTIME_RC_RELEASE_INCOMPLETE")


def _download_candidate_assets(
    release: dict[str, Any],
    candidate: dict[str, Any],
    target_root: Path,
    *,
    timeout: float,
    prefer_bits: bool,
) -> None:
    tag = str(release["tag_name"])
    release_assets = _release_assets(release)
    items = candidate.get("assets")
    if not isinstance(items, list):
        _raise("RUNTIME_RC_CANDIDATE_INVALID")

    for item in items:
        if not isinstance(item, dict):
            _raise("RUNTIME_RC_CANDIDATE_INVALID")
        name = item.get("name")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
        ):
            _raise("RUNTIME_RC_CANDIDATE_INVALID")
        metadata = release_assets.get(name)
        if metadata is None or metadata.get("size") != size:
            _raise("RUNTIME_RC_RELEASE_ASSET_MISMATCH")
        release_digest = _asset_digest(metadata.get("digest"))
        if release_digest is None or release_digest != digest:
            _raise("RUNTIME_RC_RELEASE_ASSET_MISMATCH")
        expected_url = github_release_asset_url(tag, name)
        if metadata.get("browser_download_url") != expected_url:
            _raise("RUNTIME_RC_RELEASE_ASSET_URL_INVALID")
        request = urllib.request.Request(
            expected_url,
            headers={
                "Accept": "application/octet-stream,application/zip,application/json",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "User-Agent": "TDACompanion",
            },
        )

        def fallback_open(request=request, expected_url=expected_url):
            try:
                return open_verified_release(
                    request,
                    expected_github_url=expected_url,
                    timeout=timeout,
                )
            except ReleaseRedirectError as exc:
                raise RuntimeRcUpdateError("RUNTIME_RC_RELEASE_REDIRECT_REJECTED") from exc

        download_verified_release_asset(
            target=target_root / name,
            github_url=expected_url,
            expected_size=size,
            expected_sha256=digest,
            timeout=timeout,
            fallback_open=fallback_open,
            prefer_bits=prefer_bits,
            size_exceeded_code="RUNTIME_RC_ASSET_SIZE_EXCEEDED",
            size_mismatch_code="RUNTIME_RC_ASSET_SIZE_MISMATCH",
        )


def install_published_runtime_rc(
    family: str,
    *,
    runtime_root: Path,
    cache_root: Path,
    timeout: float = 300.0,
    prefer_bits: bool = True,
    client: NetworkClient | None = None,
) -> dict[str, object]:
    """Install an exact, published runtime RC without any manual setup step."""
    release = discover_published_runtime_rc(family, client=client)
    candidate, raw_manifest = _read_candidate_manifest(release, timeout=min(timeout, 30.0))
    _validate_candidate_release_identity(family, release, candidate)

    tag = str(release["tag_name"])
    version = _VERSIONS[family]
    target_root = cache_root.resolve() / "runtime-rc" / family / version / tag
    target_root.mkdir(parents=True, exist_ok=True)
    candidate_path = target_root / _CANDIDATE_ASSET
    temporary = candidate_path.with_name(candidate_path.name + ".partial")
    try:
        temporary.write_bytes(raw_manifest)
        temporary.replace(candidate_path)
    finally:
        temporary.unlink(missing_ok=True)

    _download_candidate_assets(
        release,
        candidate,
        target_root,
        timeout=timeout,
        prefer_bits=prefer_bits,
    )
    try:
        verify_candidate_assets(candidate, target_root)
        result = install_runtime_candidate(
            candidate_path,
            target_root,
            runtime_root=runtime_root,
            cache_root=cache_root,
        )
    except (RuntimeReleaseEvidenceError, RcRuntimeArtifactError) as exc:
        raise RuntimeRcUpdateError(str(exc) or "RUNTIME_RC_INSTALL_FAILED") from exc
    return {**result, "channel": "rc"}
