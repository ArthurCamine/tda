from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion.bits_resume_evidence import BitsResumeEvidenceError, verify_bits_resume_evidence


def _write(path: Path, **changes: object) -> Path:
    value: dict[str, object] = {
        "schema": "tda_bits_resume_evidence_v1",
        "pass": True,
        "job_id_sha256": "a" * 64,
        "bytes_before": 1024,
        "bytes_after": 4096,
        "bytes_total": 8192,
        "state_before": "Transferring",
        "state_after": "Transferring",
        "same_job": True,
        "reused_job": True,
        "contains_paths": False,
        "contains_url": False,
    }
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_accepts_sanitized_same_job_progress(tmp_path: Path) -> None:
    value = verify_bits_resume_evidence(_write(tmp_path / "bits.json"))
    assert value["pass"] is True
    assert value["same_job"] is True
    assert value["reused_job"] is True
    assert value["bytes_after"] > value["bytes_before"]
    assert value["contains_paths"] is False
    assert value["contains_url"] is False


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"same_job": False}, "BITS_EVIDENCE_JOB_NOT_REUSED"),
        ({"reused_job": False}, "BITS_EVIDENCE_JOB_NOT_REUSED"),
        ({"bytes_after": 1024}, "BITS_EVIDENCE_PROGRESS_INVALID"),
        ({"bytes_after": 9000}, "BITS_EVIDENCE_PROGRESS_INVALID"),
        ({"job_id_sha256": "not-a-hash"}, "BITS_EVIDENCE_JOB_HASH_INVALID"),
        ({"contains_paths": True}, "BITS_EVIDENCE_PRIVACY_INVALID"),
        ({"contains_url": True}, "BITS_EVIDENCE_PRIVACY_INVALID"),
        ({"state_after": "Error"}, "BITS_EVIDENCE_STATE_INVALID"),
        ({"pass": False}, "BITS_EVIDENCE_NOT_PASSED"),
    ],
)
def test_rejects_unproven_or_private_evidence(tmp_path: Path, changes: dict[str, object], code: str) -> None:
    path = _write(tmp_path / "bits.json", **changes)
    with pytest.raises(BitsResumeEvidenceError, match=f"^{code}$"):
        verify_bits_resume_evidence(path)


def test_rejects_extra_fields_including_local_identity(tmp_path: Path) -> None:
    path = _write(tmp_path / "bits.json", source_url="https://example.invalid/private")
    with pytest.raises(BitsResumeEvidenceError, match="^BITS_EVIDENCE_SHAPE_INVALID$"):
        verify_bits_resume_evidence(path)
