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


def test_rc_workflow_is_manual_reuses_validated_artifact_and_never_rebuilds():
    value = _read("companion-rc.yml")
    assert "workflow_dispatch:" in value
    assert "pull_request:" not in value
    assert "branches: [main, Preview]" not in value
    assert "gh run download" in value
    assert "candidate-manifest" in value
    assert "--prerelease" in value
    assert "gh release create" in value
    assert "build-windows.ps1" not in value


def test_stable_promotion_is_manual_receipt_gated_and_never_rebuilds_or_reuploads_binaries():
    value = _read("companion-promote.yml")
    assert "workflow_dispatch:" in value
    assert "pull_request:" not in value
    assert "branches: [main, Preview]" not in value
    assert "verify-promotion" in value
    assert "docs/companion/acceptance/${RC_TAG}.json" in value
    assert "git merge-base --is-ancestor" in value
    assert "git diff --quiet \"$SOURCE_SHA\" HEAD -- local-companion" in value
    assert "git diff --quiet \"$SOURCE_SHA\" HEAD -- .github/workflows" in value
    assert "gh release edit \"$RC_TAG\"" in value
    assert "--tag \"$STABLE_TAG\"" in value
    assert "--prerelease=false" in value
    assert "build-windows.ps1" not in value
    assert "gh release create" not in value
    assert "TDACompanion-x64.msi" not in "\n".join(
        line for line in value.splitlines() if "gh release upload" in line
    )
