from __future__ import annotations

import concurrent.futures
import os
import subprocess
from pathlib import Path

import pytest

from tda_companion.attempt_fence import (
    AttemptFenceError,
    claim_attempt_outcome,
    read_attempt_outcome,
)


def test_first_attempt_outcome_claim_wins_across_concurrent_callers(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()

    def claim(decision: str):
        return claim_attempt_outcome(
            package_root,
            "job-race",
            1,
            decision,  # type: ignore[arg-type]
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["cancel", "commit"]))

    assert results[0] == results[1]
    assert read_attempt_outcome(package_root, "job-race", 1) == results[0]


def test_attempt_outcome_is_idempotent_and_scoped_per_attempt(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()

    assert claim_attempt_outcome(package_root, "job-a", 1, "cancel") == "cancel"
    assert claim_attempt_outcome(package_root, "job-a", 1, "commit") == "cancel"
    assert claim_attempt_outcome(package_root, "job-a", 2, "commit") == "commit"
    assert read_attempt_outcome(package_root, "job-a", 1) == "cancel"
    assert read_attempt_outcome(package_root, "job-a", 2) == "commit"


def test_missing_fence_reads_as_unclaimed(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()
    assert read_attempt_outcome(package_root, "job-a", 1) is None


def test_corrupt_fence_fails_closed(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()
    assert claim_attempt_outcome(package_root, "job-a", 1, "commit") == "commit"
    path = next((package_root / ".attempt-fences").iterdir())
    path.write_text("unknown\n", encoding="ascii")

    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_INVALID"):
        read_attempt_outcome(package_root, "job-a", 1)
    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_INVALID"):
        claim_attempt_outcome(package_root, "job-a", 1, "cancel")


def test_symlinked_fence_root_is_rejected(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (package_root / ".attempt-fences").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this runner")

    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_PATH_SYMLINK"):
        claim_attempt_outcome(package_root, "job-a", 1, "commit")
    assert list(outside.iterdir()) == []


def test_attempt_fence_guard_treats_junction_semantics_as_reparse(monkeypatch, tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()
    fence_root = package_root / ".attempt-fences"
    fence_root.mkdir()
    original = getattr(Path, "is_junction", lambda self: False)

    def fake_junction(self: Path) -> bool:
        return self == fence_root or bool(original(self))

    monkeypatch.setattr(Path, "is_junction", fake_junction, raising=False)

    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_PATH_SYMLINK"):
        claim_attempt_outcome(package_root, "job-a", 1, "commit")
    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_PATH_SYMLINK"):
        read_attempt_outcome(package_root, "job-a", 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_attempt_fence_rejects_windows_junction_root(tmp_path: Path):
    package_root = tmp_path / "source"
    package_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    fence_root = package_root / ".attempt-fences"
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(fence_root), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("junction creation unavailable on this Windows runner")

    with pytest.raises(AttemptFenceError, match="ATTEMPT_FENCE_PATH_SYMLINK"):
        claim_attempt_outcome(package_root, "job-a", 1, "commit")
    assert list(outside.iterdir()) == []
