from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BITS_RESUME_SCHEMA = "tda_bits_resume_evidence_v1"
MAX_EVIDENCE_BYTES = 64 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_BEFORE_STATES = frozenset({"Queued", "Connecting", "Transferring", "Suspended", "TransientError"})
_ALLOWED_AFTER_STATES = frozenset({"Connecting", "Transferring", "Transferred"})
_ALLOWED_KEYS = frozenset(
    {
        "schema",
        "pass",
        "job_id_sha256",
        "bytes_before",
        "bytes_after",
        "bytes_total",
        "state_before",
        "state_after",
        "same_job",
        "reused_job",
        "contains_paths",
        "contains_url",
    }
)


class BitsResumeEvidenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _integer(value: object, code: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BitsResumeEvidenceError(code)
    return value


def validate_bits_resume_evidence(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ALLOWED_KEYS:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_SHAPE_INVALID")
    if value.get("schema") != BITS_RESUME_SCHEMA or value.get("pass") is not True:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_NOT_PASSED")
    if value.get("same_job") is not True or value.get("reused_job") is not True:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_JOB_NOT_REUSED")
    if value.get("contains_paths") is not False or value.get("contains_url") is not False:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_PRIVACY_INVALID")
    job_hash = value.get("job_id_sha256")
    if not isinstance(job_hash, str) or _SHA256.fullmatch(job_hash) is None:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_JOB_HASH_INVALID")
    before = _integer(value.get("bytes_before"), "BITS_EVIDENCE_BYTES_INVALID")
    after = _integer(value.get("bytes_after"), "BITS_EVIDENCE_BYTES_INVALID")
    total = _integer(value.get("bytes_total"), "BITS_EVIDENCE_BYTES_INVALID", minimum=1)
    if not (before < after <= total):
        raise BitsResumeEvidenceError("BITS_EVIDENCE_PROGRESS_INVALID")
    state_before = value.get("state_before")
    state_after = value.get("state_after")
    if state_before not in _ALLOWED_BEFORE_STATES or state_after not in _ALLOWED_AFTER_STATES:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_STATE_INVALID")
    return {
        "schema": BITS_RESUME_SCHEMA,
        "pass": True,
        "job_id_sha256": job_hash,
        "bytes_before": before,
        "bytes_after": after,
        "bytes_total": total,
        "state_before": state_before,
        "state_after": state_after,
        "same_job": True,
        "reused_job": True,
        "contains_paths": False,
        "contains_url": False,
    }


def verify_bits_resume_evidence(path: Path) -> dict[str, Any]:
    source = path.resolve()
    try:
        stat = source.stat()
        if stat.st_size <= 0 or stat.st_size > MAX_EVIDENCE_BYTES:
            raise BitsResumeEvidenceError("BITS_EVIDENCE_SIZE_INVALID")
        value = json.loads(source.read_text(encoding="utf-8"))
    except BitsResumeEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BitsResumeEvidenceError("BITS_EVIDENCE_INVALID") from exc
    return validate_bits_resume_evidence(value)
