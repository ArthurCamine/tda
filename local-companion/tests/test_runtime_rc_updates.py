from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import tda_companion.runtime_rc_updates as runtime_rc
from tda_companion.network import NetworkError
from tda_companion.rc_runtime_artifacts import RC_QWEN_VERSION, RC_WHISPER_VERSION


class _Response:
    status = 200

    def __init__(self, value):  # noqa: ANN001
        self.body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.body


class _Client:
    def __init__(self, pages):  # noqa: ANN001
        self.pages = pages
        self.urls: list[str] = []

    def open(self, request, *, timeout):  # noqa: ANN001
        del timeout
        self.urls.append(request.full_url)
        page = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
        return _Response(self.pages.get(page, []))


def _asset(tag: str, name: str = "TDARuntime-candidate.json", size: int = 10):
    return {
        "name": name,
        "size": size,
        "browser_download_url": f"https://github.com/Faysk/tda/releases/download/{tag}/{name}",
        "digest": "sha256:" + "a" * 64,
    }


def _release(family: str, version: str, source: str, *, release_id: int, draft=False, prerelease=True):
    tag = f"companion-{family}-runtime-rc-v{version}-{source[:12]}"
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": f"2026-09-17T20:{release_id % 60:02d}:00Z",
        "assets": [_asset(tag)],
    }


def test_discovery_ignores_draft_and_selects_newest_exact_published_runtime():
    source_a = "1" * 40
    source_b = "2" * 40
    client = _Client(
        {
            1: [
                _release("qwen", RC_QWEN_VERSION, source_a, release_id=10, draft=True),
                _release("qwen", "9.9.9", source_b, release_id=11),
                _release("qwen", RC_QWEN_VERSION, source_a, release_id=12),
                _release("qwen", RC_QWEN_VERSION, source_b, release_id=13),
            ]
        }
    )

    value = runtime_rc.discover_published_runtime_rc("qwen", client=client)

    assert value["id"] == 13
    assert value["tag_name"].endswith(source_b[:12])
    assert len(client.urls) == 1


def test_discovery_fails_closed_when_only_incomplete_draft_exists():
    source = "3" * 40
    client = _Client({1: [_release("whisper", RC_WHISPER_VERSION, source, release_id=20, draft=True)]})

    with pytest.raises(NetworkError) as exc:
        runtime_rc.discover_published_runtime_rc("whisper", client=client)

    assert exc.value.code == "RUNTIME_RC_RELEASE_NOT_PUBLISHED"


def test_candidate_identity_requires_exact_family_version_tag_source_and_asset_set():
    source = "4" * 40
    release = _release("whisper", RC_WHISPER_VERSION, source, release_id=30)
    tag = release["tag_name"]
    runtime_name = f"TDAWhisperRuntime-{RC_WHISPER_VERSION}-windows-x64.zip"
    release["assets"].append(_asset(tag, runtime_name, 123))
    candidate = {
        "family": "whisper",
        "version": RC_WHISPER_VERSION,
        "candidate_tag": tag,
        "source_sha": source,
        "assets": [{"name": runtime_name, "size": 123, "sha256": "a" * 64}],
    }

    runtime_rc._validate_candidate_release_identity("whisper", release, candidate)

    bad = dict(candidate, source_sha="5" * 40)
    with pytest.raises(NetworkError) as exc:
        runtime_rc._validate_candidate_release_identity("whisper", release, bad)
    assert exc.value.code == "RUNTIME_RC_CANDIDATE_IDENTITY_MISMATCH"

    release_with_extra = dict(release, assets=[*release["assets"], _asset(tag, "unexpected.bin", 1)])
    with pytest.raises(NetworkError) as exc:
        runtime_rc._validate_candidate_release_identity("whisper", release_with_extra, candidate)
    assert exc.value.code == "RUNTIME_RC_RELEASE_INCOMPLETE"


def test_runtime_asset_release_digest_must_be_sha256_and_match_candidate(monkeypatch, tmp_path: Path):
    source = "6" * 40
    release = _release("qwen", RC_QWEN_VERSION, source, release_id=40)
    tag = release["tag_name"]
    name = f"TDAQwenRuntimeBundle-{RC_QWEN_VERSION}-windows-x64.json"
    digest = "b" * 64
    release["assets"].append(
        {
            "name": name,
            "size": 7,
            "browser_download_url": f"https://github.com/Faysk/tda/releases/download/{tag}/{name}",
            "digest": "sha256:" + digest,
        }
    )
    candidate = {
        "assets": [{"name": name, "size": 7, "sha256": digest}],
    }
    seen = []

    def fake_download(**kwargs):
        seen.append(kwargs)
        return kwargs["target"]

    monkeypatch.setattr(runtime_rc, "download_verified_release_asset", fake_download)
    runtime_rc._download_candidate_assets(
        release,
        candidate,
        tmp_path,
        timeout=30.0,
        prefer_bits=False,
    )
    assert len(seen) == 1
    assert seen[0]["expected_sha256"] == digest

    release["assets"][1]["digest"] = "sha256:" + "c" * 64
    with pytest.raises(NetworkError) as exc:
        runtime_rc._download_candidate_assets(
            release,
            candidate,
            tmp_path,
            timeout=30.0,
            prefer_bits=False,
        )
    assert exc.value.code == "RUNTIME_RC_RELEASE_ASSET_MISMATCH"


def test_install_runtime_candidate_path_is_automatic_and_uses_verified_release(monkeypatch, tmp_path: Path):
    source = "7" * 40
    release = _release("qwen", RC_QWEN_VERSION, source, release_id=50)
    candidate = {
        "family": "qwen",
        "version": RC_QWEN_VERSION,
        "candidate_tag": release["tag_name"],
        "source_sha": source,
        "assets": [],
    }
    manifest = json.dumps(candidate, sort_keys=True).encode("utf-8")
    release["assets"][0]["size"] = len(manifest)
    release["assets"][0]["digest"] = "sha256:" + __import__("hashlib").sha256(manifest).hexdigest()
    observed = {}

    monkeypatch.setattr(runtime_rc, "discover_published_runtime_rc", lambda family, client=None: release)
    monkeypatch.setattr(runtime_rc, "_read_candidate_manifest", lambda release, timeout: (candidate, manifest))
    monkeypatch.setattr(runtime_rc, "_download_candidate_assets", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_rc, "verify_candidate_assets", lambda candidate, root: None)

    def fake_install(path, assets_root, *, runtime_root, cache_root):
        observed.update(
            path=path,
            assets_root=assets_root,
            runtime_root=runtime_root,
            cache_root=cache_root,
        )
        return {"runtime": "qwen", "version": RC_QWEN_VERSION, "status": "ready"}

    monkeypatch.setattr(runtime_rc, "install_runtime_candidate", fake_install)
    result = runtime_rc.install_published_runtime_rc(
        "qwen",
        runtime_root=tmp_path / "Runtime",
        cache_root=tmp_path / "Cache",
        prefer_bits=False,
    )

    assert result["status"] == "ready"
    assert result["channel"] == "rc"
    assert observed["path"].name == "TDARuntime-candidate.json"
    assert observed["path"].is_file()
