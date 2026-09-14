#!/usr/bin/env bash
set -euo pipefail

RANGE="${1:?git range is required}"
STAGE_DIR=".local/production-media-manifests"
RECEIPT=".local/media-production-publication-receipt.json"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

mapfile -t MANIFESTS < <(
  git diff --name-only --diff-filter=ACMR "$RANGE" -- 'media/manifests/*.json' | LC_ALL=C sort -u
)

if [[ ${#MANIFESTS[@]} -eq 0 ]]; then
  echo "MEDIA_PUBLISH_SKIP no changed canonical manifests in $RANGE"
  exit 0
fi

for manifest in "${MANIFESTS[@]}"; do
  cp "$manifest" "$STAGE_DIR/$(basename "$manifest")"
done

node tools/media/pipeline.mjs publish \
  --manifest-dir "$STAGE_DIR" \
  --receipt "$RECEIPT"

echo "MEDIA_PUBLISH_CHANGED_OK manifests=${#MANIFESTS[@]} range=$RANGE"
