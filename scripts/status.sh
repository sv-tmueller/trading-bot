#!/usr/bin/env bash
set -euo pipefail
# Local check script for the read-only `status` Edge Function (#354).
# Reads STATUS_URL/STATUS_TOKEN from .env.status (gitignored; copy from
# .env.status.example and fill in the values) and renders the JSON digest.
#
# Usage: bash scripts/status.sh   (or: ./scripts/status.sh, if executable)
# See docs/runbooks/status-check.md for the one-time setup (secret, deploy).

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.status"

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

if command -v jq >/dev/null 2>&1; then
  curl -fsS -H "x-status-token: $STATUS_TOKEN" "$STATUS_URL" | jq .
else
  echo "warning: jq not found; printing raw response" >&2
  curl -fsS -H "x-status-token: $STATUS_TOKEN" "$STATUS_URL"
fi
