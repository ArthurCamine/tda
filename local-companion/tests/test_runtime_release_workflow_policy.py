from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _push_paths(name: str) -> set[str]:
    value = _workflow(name)
    start = value.index("  push:")
    end = value.index("\nconcurrency:", start)
    block = value[start:end]
    return {
        line.strip()[2:].strip("'\"")
        for line in block.splitlines()
        if line.strip().startswith("- '") or line.strip().startswith('- "')
    }


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


def test_whisper_runtime_workflow_tracks_worker_dependency_closure():
    value = _workflow("whisper-runtime.yml")
    required = {
        "local-companion/tda_companion/asr_checkpoints.py",
        "local-companion/tda_companion/asr_timeline.py",
        "local-companion/tda_companion/execution_device.py",
        "local-companion/tda_companion/craig_runtime.py",
        "local-companion/tda_companion/flac_metadata.py",
        "local-companion/tda_companion/transcript.py",
        "local-companion/tda_companion/transcription_runs.py",
        "local-companion/tda_companion/atomic_storage.py",
        "local-companion/tda_companion/attempt_fence.py",
    }
    for path in required:
        assert value.count(path) == 2, f"whisper-runtime.yml must watch {path} on PR and push"


def test_qwen_runtime_workflows_track_the_strict_worker_dependency_closure():
    required = {
        "local-companion/tda_companion/asr_checkpoints.py",
        "local-companion/tda_companion/asr_qwen_strict.py",
        "local-companion/tda_companion/asr_timeline.py",
        "local-companion/tda_companion/execution_device.py",
        "local-companion/tda_companion/craig_runtime.py",
        "local-companion/tda_companion/flac_metadata.py",
        "local-companion/tda_companion/transcript.py",
        "local-companion/tda_companion/transcription_runs.py",
        "local-companion/tda_companion/atomic_storage.py",
        "local-companion/tda_companion/attempt_fence.py",
    }
    for name in ("qwen-runtime.yml", "qwen-runtime-package.yml"):
        value = _workflow(name)
        for path in required:
            assert value.count(path) == 2, f"{name} must watch {path} on PR and push"



def test_runtime_rc_source_drift_fence_is_family_scoped_to_real_runtime_inputs():
    value = _workflow("runtime-rc.yml")

    assert value.count("RUNTIME_PATHS=(") == 2
    assert 'git diff --quiet "$SOURCE_SHA" origin/main -- "${RUNTIME_PATHS[@]}"' in value
    assert 'git diff --name-only "$SOURCE_SHA" origin/main -- "${RUNTIME_PATHS[@]}"' in value

    # The RC fence must keep up with every file that can trigger an actual runtime
    # build on main, rather than conservatively invalidating the whole Companion tree.
    required = (
        _push_paths("whisper-runtime.yml")
        | _push_paths("qwen-runtime.yml")
        | _push_paths("qwen-runtime-package.yml")
    )
    missing = sorted(path for path in required if f'"{path}"' not in value)
    assert missing == []

    # Test/acceptance-only changes do not alter packaged runtime bytes.
    assert '"local-companion/tests/test_qwen_physical_gate_harness.py"' not in value
    assert '"tools/acceptance/run-qwen-recovery-physical-gate.ps1"' not in value
    assert "              local-companion \\" not in value


def test_runtime_stable_promotion_drift_fence_matches_runtime_family_inputs():
    promote = _workflow("runtime-promote.yml")

    assert promote.count("RUNTIME_PATHS=(") == 2
    assert 'git diff --quiet "$SOURCE_SHA" HEAD -- "${RUNTIME_PATHS[@]}"' in promote
    assert 'git diff --name-only "$SOURCE_SHA" HEAD -- "${RUNTIME_PATHS[@]}"' in promote
    assert "RUNTIME_PROMOTION_RUNTIME_INPUT_DRIFT" in promote
    assert "RUNTIME_PROMOTION_FAMILY_INVALID" in promote

    required = (
        _push_paths("whisper-runtime.yml")
        | _push_paths("qwen-runtime.yml")
        | _push_paths("qwen-runtime-package.yml")
    )
    missing = sorted(path for path in required if f'"{path}"' not in promote)
    assert missing == []

    # Physical acceptance and test-only evolution must not force rebuilding
    # immutable runtime bytes that have not changed.
    assert '"local-companion/tests/test_qwen_physical_gate_harness.py"' not in promote
    assert '"tools/acceptance/run-qwen-recovery-physical-gate.ps1"' not in promote
    assert "            local-companion \\" not in promote


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
