#!/usr/bin/env bash
set -euo pipefail

: "${SUPABASE_PROJECT_REF:?SUPABASE_PROJECT_REF is required}"
: "${SUPABASE_ACCESS_TOKEN:?SUPABASE_ACCESS_TOKEN is required}"
: "${SUPABASE_DB_PASSWORD:?SUPABASE_DB_PASSWORD is required}"
: "${TDA_MIGRATION_BOUNDARY:?TDA_MIGRATION_BOUNDARY is required}"

SUPABASE_RETRY_ATTEMPTS="${TDA_SUPABASE_RETRY_ATTEMPTS:-4}"
SUPABASE_RETRY_BASE_DELAY_SECONDS="${TDA_SUPABASE_RETRY_BASE_DELAY_SECONDS:-2}"

if ! [[ "$SUPABASE_RETRY_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::TDA_SUPABASE_RETRY_ATTEMPTS must be a positive integer."
  exit 1
fi
if ! [[ "$SUPABASE_RETRY_BASE_DELAY_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "::error::TDA_SUPABASE_RETRY_BASE_DELAY_SECONDS must be a non-negative integer."
  exit 1
fi

is_transient_supabase_error() {
  grep -Eiq '(scheduled maintenance|under maintenance|temporar(il)?y unavailable|too many requests|rate.?limit|http[^0-9]*(429|502|503|504)|status[^0-9]*(429|502|503|504)|gateway timeout|service unavailable|connection reset by peer|connection refused|i/o timeout|tls handshake timeout|context deadline exceeded|network is unreachable|server closed the connection unexpectedly|unexpected eof)'
}

run_supabase_network() {
  local label="$1"
  shift
  local attempt=1
  local delay="$SUPABASE_RETRY_BASE_DELAY_SECONDS"
  local output
  local status

  while true; do
    set +e
    output="$("$@" 2>&1)"
    status=$?
    set -e
    printf '%s\n' "$output"

    if [[ $status -eq 0 ]]; then
      return 0
    fi

    if [[ $attempt -ge $SUPABASE_RETRY_ATTEMPTS ]] || ! printf '%s\n' "$output" | is_transient_supabase_error; then
      echo "::error::Supabase command failed during $label (attempt $attempt/$SUPABASE_RETRY_ATTEMPTS)."
      return "$status"
    fi

    echo "::warning::Transient Supabase failure during $label (attempt $attempt/$SUPABASE_RETRY_ATTEMPTS). Retrying in ${delay}s."
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

OVERLAY="${RUNNER_TEMP:-/tmp}/tda-supabase-overlay"
REMOTE_LIST="${RUNNER_TEMP:-/tmp}/remote-migrations.txt"
REPO_LIST="${RUNNER_TEMP:-/tmp}/repo-migrations.txt"
REMOTE_TDA="${RUNNER_TEMP:-/tmp}/remote-tda-migrations.txt"

rm -rf "$OVERLAY"
mkdir -p "$OVERLAY"

supabase init --workdir "$OVERLAY" --yes
run_supabase_network "project link" supabase link \
  --workdir "$OVERLAY" \
  --project-ref "$SUPABASE_PROJECT_REF" \
  --password "$SUPABASE_DB_PASSWORD" \
  --yes
run_supabase_network "initial migration fetch" supabase migration fetch --workdir "$OVERLAY" --linked --yes

find "$OVERLAY/supabase/migrations" -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | LC_ALL=C sort > "$REMOTE_LIST"
find supabase/migrations -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | LC_ALL=C sort > "$REPO_LIST"

INVALID_REPO="$(grep -Ev '^[0-9]{14}_.+\.sql$' "$REPO_LIST" || true)"
if [[ -n "$INVALID_REPO" ]]; then
  echo "::error::Deployable migration filenames must use the 14-digit Supabase timestamp format."
  printf '%s\n' "$INVALID_REPO"
  exit 1
fi

PRE_BOUNDARY="$(awk -v boundary="$TDA_MIGRATION_BOUNDARY" 'substr($0, 1, 14) < boundary { print }' "$REPO_LIST")"
if [[ -n "$PRE_BOUNDARY" ]]; then
  echo "::error::TDA deployable migrations must not predate boundary $TDA_MIGRATION_BOUNDARY."
  printf '%s\n' "$PRE_BOUNDARY"
  exit 1
fi

awk -v boundary="$TDA_MIGRATION_BOUNDARY" 'substr($0, 1, 14) >= boundary { print }' "$REMOTE_LIST" > "$REMOTE_TDA"
UNEXPECTED_REMOTE="$(comm -23 "$REMOTE_TDA" "$REPO_LIST")"
if [[ -n "$UNEXPECTED_REMOTE" ]]; then
  echo "::error::Remote migration history contains TDA-era entries absent from this repository. Reconcile history before release."
  printf '%s\n' "$UNEXPECTED_REMOTE"
  exit 1
fi

cp -f supabase/migrations/*.sql "$OVERLAY/supabase/migrations/"

echo "Remote migration history files: $(wc -l < "$REMOTE_LIST")"
echo "Authoritative TDA deployable files: $(wc -l < "$REPO_LIST")"
run_supabase_network "migration list" supabase migration list --workdir "$OVERLAY" --linked --password "$SUPABASE_DB_PASSWORD"
run_supabase_network "migration dry-run" supabase db push --workdir "$OVERLAY" --linked --dry-run --skip-vault --password "$SUPABASE_DB_PASSWORD"
run_supabase_network "migration push" supabase db push --workdir "$OVERLAY" --linked --skip-vault --password "$SUPABASE_DB_PASSWORD" --yes

rm -rf "$OVERLAY/supabase/migrations"
mkdir -p "$OVERLAY/supabase/migrations"
run_supabase_network "post-push migration fetch" supabase migration fetch --workdir "$OVERLAY" --linked --yes

AFTER_REMOTE="${RUNNER_TEMP:-/tmp}/remote-migrations-after.txt"
AFTER_REPO="${RUNNER_TEMP:-/tmp}/repo-migrations-after.txt"
AFTER_TDA="${RUNNER_TEMP:-/tmp}/remote-tda-migrations-after.txt"
find "$OVERLAY/supabase/migrations" -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | LC_ALL=C sort > "$AFTER_REMOTE"
find supabase/migrations -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | LC_ALL=C sort > "$AFTER_REPO"
awk -v boundary="$TDA_MIGRATION_BOUNDARY" 'substr($0, 1, 14) >= boundary { print }' "$AFTER_REMOTE" > "$AFTER_TDA"

MISSING_REMOTE="$(comm -23 "$AFTER_REPO" "$AFTER_TDA")"
UNEXPECTED_AFTER="$(comm -13 "$AFTER_REPO" "$AFTER_TDA")"
if [[ -n "$MISSING_REMOTE" || -n "$UNEXPECTED_AFTER" ]]; then
  echo "::error::Production migration history does not exactly match the authoritative TDA migration set."
  if [[ -n "$MISSING_REMOTE" ]]; then
    echo "Missing remotely:"
    printf '%s\n' "$MISSING_REMOTE"
  fi
  if [[ -n "$UNEXPECTED_AFTER" ]]; then
    echo "Unexpected remotely:"
    printf '%s\n' "$UNEXPECTED_AFTER"
  fi
  exit 1
fi

echo "PRODUCTION_MIGRATIONS_OK exact TDA migration history verified"
