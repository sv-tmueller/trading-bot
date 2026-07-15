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
  RESPONSE="$(curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL")"

  # #384: short one-line "why" summary (same construction as
  # scripts/render_soak_digest.sh's headline) above the raw dump below.
  # Guarded on regime/regime_margin_pct being present — skipped otherwise.
  if printf '%s' "$RESPONSE" | jq -e '.regime != null and .regime_margin_pct != null' >/dev/null 2>&1; then
    current_state="$(printf '%s' "$RESPONSE" | jq -r '.regime.current_state')"
    position_symbol="$(printf '%s' "$RESPONSE" | jq -r '.alpaca.position.symbol')"
    margin_direction="$(printf '%s' "$RESPONSE" | jq -r 'if .regime_margin_pct >= 0 then "above" else "below" end')"
    margin_abs_raw="$(printf '%s' "$RESPONSE" | jq -r '(.regime_margin_pct | if . < 0 then -. else . end)')"
    margin_abs="$(printf '%.1f' "$margin_abs_raw")"
    if [ "$current_state" = "CASH" ]; then
      echo "${current_state} because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
    else
      echo "${current_state} \`${position_symbol}\` because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
    fi
    echo
  fi

  printf '%s' "$RESPONSE" | jq .
else
  echo "warning: jq not found; printing raw response" >&2
  curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL"
fi
