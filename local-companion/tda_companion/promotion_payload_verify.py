from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .payload_evidence import PayloadEvidenceError, load_payload_manifest


class PromotionPayloadError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionPayloadError(code) from exc
    if not isinstance(value, dict):
        raise PromotionPayloadError(code)
    return value


def verify_promotion_payload(
    candidate_manifest: Path,
    acceptance_receipt: Path,
    assets_root: Path,
) -> None:
    candidate = _load_json(candidate_manifest, "PROMOTION_CANDIDATE_INVALID")
    receipt = _load_json(acceptance_receipt, "PROMOTION_RECEIPT_INVALID")
    assets = candidate.get("assets")
    artifact = receipt.get("artifact")
    if not isinstance(assets, dict) or not isinstance(artifact, dict):
        raise PromotionPayloadError("PROMOTION_PAYLOAD_BINDING_INVALID")
    payload_asset = assets.get("payload_manifest")
    if not isinstance(payload_asset, dict):
        raise PromotionPayloadError("PROMOTION_PAYLOAD_BINDING_INVALID")
    name = payload_asset.get("name")
    expected_sha = payload_asset.get("sha256")
    expected_size = payload_asset.get("size")
    if not isinstance(name, str) or not isinstance(expected_sha, str) or not isinstance(expected_size, int):
        raise PromotionPayloadError("PROMOTION_PAYLOAD_BINDING_INVALID")
    payload_path = (assets_root / name).resolve()
    if payload_path.parent != assets_root.resolve() or not payload_path.is_file():
        raise PromotionPayloadError("PROMOTION_PAYLOAD_ASSET_MISSING")
    if payload_path.stat().st_size != expected_size or _sha256(payload_path) != expected_sha:
        raise PromotionPayloadError("PROMOTION_PAYLOAD_ASSET_MISMATCH")
    try:
        payload = load_payload_manifest(payload_path)
    except PayloadEvidenceError as exc:
        raise PromotionPayloadError("PROMOTION_PAYLOAD_MANIFEST_INVALID") from exc
    for key in ("version", "source_sha", "source_tree_sha"):
        if payload.get(key) != candidate.get(key) or artifact.get(key) != candidate.get(key):
            raise PromotionPayloadError("PROMOTION_PAYLOAD_IDENTITY_MISMATCH")
    if artifact.get("payload_manifest_sha256") != expected_sha:
        raise PromotionPayloadError("PROMOTION_PAYLOAD_RECEIPT_MISMATCH")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise PromotionPayloadError("PROMOTION_PAYLOAD_MANIFEST_INVALID")
    expected = {
        "executable_sha256": "TDACompanion.exe",
        "maintenance_helper_sha256": "TDACompanionMaintenance.exe",
    }
    for receipt_key, filename in expected.items():
        row = files.get(filename)
        if not isinstance(row, dict) or artifact.get(receipt_key) != row.get("sha256"):
            raise PromotionPayloadError("PROMOTION_INSTALLED_BINARY_MISMATCH")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tda_companion.promotion_payload_verify")
    parser.add_argument("--candidate-manifest", required=True, type=Path)
    parser.add_argument("--acceptance-receipt", required=True, type=Path)
    parser.add_argument("--assets-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        verify_promotion_payload(args.candidate_manifest, args.acceptance_receipt, args.assets_root)
        return 0
    except PromotionPayloadError as exc:
        print(exc.code)
        return 66


if __name__ == "__main__":
    raise SystemExit(main())
