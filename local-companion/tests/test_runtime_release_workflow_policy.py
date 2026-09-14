from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_whisper_runtime_workflow_is_build_only_and_keeps_candidate_long_enough():
    value = _workflow("whisper-runtime.yml")

    assert "publish-whisper-runtime-release" not in value
    assert "gh release create" not in value
    assert "TDA_SOURCE_SHA" in value
    assert "BUILD_SOURCE_SHA_MISMATCH" in value
    assert "retention-days: 30" in value


def test_qwen_runtime_uses_package_builder_without_legacy_direct_stable_publisher():
    package = _workflow("qwen-runtime-package.yml")

    assert not (WORKFLOWS / "qwen-runtime-release.yml").exists()
    assert "TDA_SOURCE_SHA" in package
    assert "BUILD_SOURCE_SHA_MISMATCH" in package
    assert "retention-days: 30" in package
    assert "gh release create" not in package


def test_runtime_stable_promotion_requires_physical_receipt_and_reuses_release_object():
    rc = _workflow("runtime-rc.yml")
    promote = _workflow("runtime-promote.yml")

    assert "--prerelease" in rc
    assert "TDARuntime-candidate.json" in rc
    assert "docs/companion/runtime-acceptance/${RC_TAG}.json" in promote
    assert "runtime_release_evidence verify-promotion" in promote
    assert 'gh release edit "$RC_TAG"' in promote
    assert "STABLE_RELEASE_OBJECT_CHANGED" in promote
    assert "Stable runtime release already exists" in promote
    assert "assets não foram recompilados nem reenviados" in promote
