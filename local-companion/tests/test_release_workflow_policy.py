from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_normal_companion_ci_never_publishes_a_stable_release():
    value = _read("companion.yml")
    assert "publish-companion-release" not in value
    assert "gh release create" not in value
    assert "contents: write" not in value
    assert "TDA_BUILD_SOURCE_SHA" not in value  # one canonical source identity only
    assert "TDA_SOURCE_SHA" in value
    assert "TDACompanion-payload-manifest.json" in value
    assert "retention-days: 90" in value


def test_rc_workflow_auto_publishes_only_validated_main_artifacts_and_never_rebuilds():
    value = _read("companion-rc.yml")
    assert "workflow_dispatch:" in value
    assert "workflow_run:" in value
    assert "workflows: [CI]" in value
    assert "types: [completed]" in value
    assert "branches: [main]" in value
    assert "github.event.workflow_run.conclusion == 'success'" in value
    assert "AUTO_RC_TRIGGER_SOURCE_MISMATCH" in value
    assert "AUTO_RC_TRIGGER_NOT_MAIN_PUSH" in value
    assert "TDACompanion-windows-x64" in value
    assert "No Companion artifact" in value
    assert "gh run download" in value
    assert "candidate-manifest" in value
    assert "--source-tree-sha" in value
    assert "--payload-manifest" in value
    assert "TDACompanion-payload-manifest.json" in value
    assert "RC_RETRY_BYTES_MISMATCH" in value
    assert "--prerelease" in value
    assert "gh release create" in value
    assert "build-windows.ps1" not in value
    assert "actions/checkout@v7" not in value


def test_stable_promotion_is_manual_receipt_gated_content_equivalent_and_never_rebuilds():
    value = _read("companion-promote.yml")
    assert "workflow_dispatch:" in value
    assert "pull_request:" not in value
    assert "branches: [main, Preview]" not in value
    assert "verify-promotion" in value
    assert "docs/companion/acceptance/${RC_TAG}.json" in value
    assert "git merge-base --is-ancestor" not in value
    assert 'git fetch --no-tags origin "$SOURCE_SHA"' in value
    assert 'git diff --quiet "$SOURCE_SHA" HEAD -- local-companion' in value
    assert ".github/workflows/companion-rc.yml" in value
    assert "TDACompanion-payload-manifest.json" in value
    assert "gh release edit \"$RC_TAG\"" in value
    assert "--tag \"$STABLE_TAG\"" in value
    assert "--prerelease=false" in value
    assert "build-windows.ps1" not in value
    assert "gh release create" not in value
    assert "TDACompanion-x64.msi" not in "\n".join(
        line for line in value.splitlines() if "gh release upload" in line
    )
    assert "actions/checkout@v7" not in value


def test_stable_promotion_requires_published_runtimes_meeting_companion_minimums():
    value = _read("companion-promote.yml")
    assert "Require compatible stable runtimes" in value
    assert "MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION" in value
    assert "MIN_COMPATIBLE_QWEN_RUNTIME_VERSION" in value
    assert "companion-whisper-runtime-v" in value
    assert "companion-qwen-runtime-v" in value
    assert "COMPANION_STABLE_{family.upper()}_RUNTIME_INCOMPATIBLE" in value
