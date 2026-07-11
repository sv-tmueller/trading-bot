#!/usr/bin/env bash
set -euo pipefail
# Local check script for the read-only `status` Edge Function (#354).
# Reads STATUS_URL/STATUS_TOKEN from .env.status (gitignored; copy from
# .env.status.example and fill in the values) and renders the JSON digest.
#
# Usage: bash scripts/status.sh [--days N]   (or: ./scripts/status.sh, if executable)
#   --days N   widen the digest's history window (1-60; server default 7) and
#              add the `trades`/`regime_history` arrays (#358). No client-side
#              range validation — a bad N reaches the server, whose 400 body
#              is now surfaced via --fail-with-body (see below).
# See docs/runbooks/status-check.md for the one-time setup (secret, deploy).

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.status"

DAYS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --days)
      if [ $# -lt 2 ]; then
        echo "error: --days requires a value" >&2
        exit 1
      fi
      DAYS="$2"
      shift 2
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found. Copy .env.status.example to .env.status and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [ -z "${STATUS_URL:-}" ]; then
  echo "error: STATUS_URL is not set in $ENV_FILE" >&2
  exit 1
fi

if [ -z "${STATUS_TOKEN:-}" ]; then
  echo "error: STATUS_TOKEN is not set in $ENV_FILE" >&2
  exit 1
fi

REQUEST_URL="$STATUS_URL"
if [ -n "$DAYS" ]; then
  REQUEST_URL="${STATUS_URL}?days=${DAYS}"
fi

# --fail-with-body (curl >=7.76): unlike -f, this still prints the response
# body (e.g. the 400/401/500 { "error": "..." } JSON) before exiting non-zero,
# so an operator sees *why* the request failed instead of just a curl error.
if command -v jq >/dev/null 2>&1; then
  curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL" | jq .
else
  echo "warning: jq not found; printing raw response" >&2
  curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL"
fi
