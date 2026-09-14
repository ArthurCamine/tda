from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .runtime_release_evidence import (
    PROMOTION_SCHEMA,
    QWEN_PROFILES,
    WHISPER_PROFILES,
    RuntimeReleaseEvidenceError,
    verify_candidate_assets,
)

SUITE_SCHEMA = "tda_runtime_release_physical_suite_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_JSON_INVALID")
    return value


def _sha_ok(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _candidate(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "tda_runtime_candidate_v1" or value.get("family") not in {"whisper", "qwen"}:
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_INVALID")
    for key in ("version", "source_sha", "source_tree_sha", "candidate_tag", "stable_tag"):
        if not isinstance(value.get(key), str) or not value.get(key):
            raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_INVALID")
    if not _sha_ok(value.get("runtime_archive_sha256")) or not isinstance(value.get("assets"), list):
        raise RuntimeReleaseEvidenceError("RUNTIME_CANDIDATE_INVALID")
    return value


def _check_whisper(results: dict[str, Any]) -> None:
    for profile in WHISPER_PROFILES:
        value = results.get(profile)
        if not isinstance(value, dict):
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_WHISPER_INCOMPLETE")
        gpu = value.get("gpu") if isinstance(value.get("gpu"), dict) else {}
        inference = value.get("inference") if isinstance(value.get("inference"), dict) else {}
        if value.get("schema") != "tda_whisper_gpu_acceptance_v1" or value.get("pass") is not True:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_WHISPER_INVALID")
        if value.get("profile_id") != profile or value.get("model_integrity") != "sha256-full":
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_WHISPER_INVALID")
        if not _sha_ok(value.get("model_content_sha256")) or gpu.get("required_name_match") is not True:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_WHISPER_INVALID")
        if inference.get("device") != "cuda":
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_WHISPER_INVALID")


def _check_qwen(candidate: dict[str, Any], results: dict[str, Any], gates: object) -> None:
    if not isinstance(gates, dict):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INCOMPLETE")
    for profile in QWEN_PROFILES:
        value = results.get(profile)
        gate = gates.get(profile)
        if not isinstance(value, dict) or not isinstance(gate, dict):
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INCOMPLETE")
        gpu = value.get("gpu") if isinstance(value.get("gpu"), dict) else {}
        align_gpu = value.get("alignment_gpu") if isinstance(value.get("alignment_gpu"), dict) else {}
        inference = value.get("inference") if isinstance(value.get("inference"), dict) else {}
        alignment = value.get("alignment") if isinstance(value.get("alignment"), dict) else {}
        if value.get("schema") != "tda_qwen_gpu_acceptance_v1" or value.get("pass") is not True:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INVALID")
        if value.get("profile_id") != profile or gpu.get("required_name_match") is not True:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INVALID")
        if align_gpu.get("required_name_match") is not True or inference.get("device") != "cuda":
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INVALID")
        if int(alignment.get("word_count") or 0) < 1:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_INVALID")
        if gate.get("schema") != "tda_qwen_physical_gate_v1" or gate.get("profile_id") != profile:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_GATE_INVALID")
        if gate.get("runtime_archive_sha256") != candidate["runtime_archive_sha256"]:
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_GATE_INVALID")
        for key in ("gate_sha256", "binding_sha256", "acceptance_sha256"):
            if not _sha_ok(gate.get(key)):
                raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_QWEN_GATE_INVALID")


def verify_suite_promotion(candidate_path: Path, receipt_path: Path, assets_root: Path) -> dict[str, Any]:
    candidate = _candidate(_read(candidate_path.resolve()))
    receipt = _read(receipt_path.resolve())
    if receipt.get("schema") != SUITE_SCHEMA or receipt.get("pass") is not True:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_INVALID")
    if receipt.get("contains_audio") is not False or receipt.get("contains_transcript") is not False:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_INVALID")
    if receipt.get("contains_local_paths") is not False:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_INVALID")
    if receipt.get("profiles") != [*WHISPER_PROFILES, *QWEN_PROFILES]:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_PROFILE_SET_INVALID")
    bindings = receipt.get("candidates")
    runtimes = receipt.get("runtimes")
    results = receipt.get("results")
    if not isinstance(bindings, dict) or not isinstance(runtimes, dict) or not isinstance(results, dict):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_INVALID")
    binding = bindings.get(candidate["family"])
    runtime = runtimes.get(candidate["family"])
    if not isinstance(binding, dict) or not isinstance(runtime, dict):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_BINDING_MISSING")
    for key in ("candidate_tag", "stable_tag", "version", "source_sha", "source_tree_sha", "runtime_archive_sha256"):
        if binding.get(key) != candidate.get(key):
            raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_CANDIDATE_MISMATCH")
    if binding.get("candidate_manifest_sha256") != _sha(candidate_path.resolve()):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_CANDIDATE_HASH_MISMATCH")
    runtime_id = "whisper-ctranslate2" if candidate["family"] == "whisper" else "qwen3-transformers"
    if runtime.get("runtime_id") != runtime_id or runtime.get("version") != candidate["version"]:
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_RUNTIME_MISMATCH")
    if runtime.get("archive_sha256") != candidate["runtime_archive_sha256"] or not _sha_ok(runtime.get("worker_sha256")):
        raise RuntimeReleaseEvidenceError("RUNTIME_SUITE_RUNTIME_MISMATCH")
    if candidate["family"] == "whisper":
        _check_whisper(results)
    else:
        _check_qwen(candidate, results, receipt.get("qwen_gates"))
    verify_candidate_assets(candidate, assets_root.resolve())
    return {
        "schema": PROMOTION_SCHEMA,
        "candidate_tag": candidate["candidate_tag"],
        "stable_tag": candidate["stable_tag"],
        "family": candidate["family"],
        "version": candidate["version"],
        "source_sha": candidate["source_sha"],
        "source_tree_sha": candidate["source_tree_sha"],
        "runtime_archive_sha256": candidate["runtime_archive_sha256"],
        "candidate_manifest_file_sha256": _sha(candidate_path.resolve()),
        "acceptance_receipt_sha256": _sha(receipt_path.resolve()),
        "assets": candidate["assets"],
    }
