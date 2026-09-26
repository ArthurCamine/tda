"""Bounded preparation history; never an authority for artifact readiness."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .atomic_storage import atomic_write
from .local_state_paths import confined_directory, confined_regular_file

SCHEMA = "tda_profile_preparation_receipt_v1"
LIMIT = 4096
FIELDS = ("operation_id", "resumes_operation_id", "source_id", "profile_id", "engine",
          "state", "stage", "sequence", "started_at", "updated_at", "finished_at", "error_code")


def validate(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("PREPARATION_RECEIPT_INVALID")
    patterns = {
        "operation_id": r"[0-9a-f]{32}", "resumes_operation_id": r"[0-9a-f]{32}",
        "source_id": r"craig-[0-9a-f]{64}",
        "profile_id": r"(?:qwen-(?:fast|quality)|whisper-(?:turbo|detailed))",
        "engine": r"(?:qwen3|whisper)",
        "state": r"(?:running|completed|failed|interrupted)",
        "stage": r"[a-z_]{1,64}", "error_code": r"[A-Z0-9_]{1,96}",
        "started_at": r"[0-9T:.+Z-]{20,40}", "updated_at": r"[0-9T:.+Z-]{20,40}",
        "finished_at": r"[0-9T:.+Z-]{20,40}",
    }
    optional = {"resumes_operation_id", "error_code", "finished_at"}
    result = {"schema": SCHEMA}
    for key, pattern in patterns.items():
        raw = value.get(key)
        if raw is None and key in optional:
            result[key] = None
        elif isinstance(raw, str) and re.fullmatch(pattern, raw):
            result[key] = raw
        else:
            raise ValueError("PREPARATION_RECEIPT_INVALID")
    sequence = value.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= 1_000_000:
        raise ValueError("PREPARATION_RECEIPT_INVALID")
    result["sequence"] = sequence
    return result


class PreparationReceipt:
    def __init__(self, state_root: Path):
        self.root = state_root

    def _path(self, *, create: bool) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        directory = confined_directory(self.root, ("preparation",), create=create)
        return confined_regular_file(directory, directory / "latest.json", allow_missing=True)

    def read(self) -> dict | None:
        path = self._path(create=False)
        if not path.exists():
            return None
        with path.open("rb") as handle:
            payload = handle.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise ValueError("PREPARATION_RECEIPT_INVALID")
        return validate(json.loads(payload))

    def write(self, state: dict) -> None:
        value = validate({"schema": SCHEMA, **{key: state.get(key) for key in FIELDS}})
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        if len(payload) > LIMIT:
            raise ValueError("PREPARATION_RECEIPT_INVALID")
        atomic_write(self._path(create=True), payload, storage_class="checkpoint")
