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
  # #384 fix: capture curl's exit status explicitly instead of letting a bare
  # `RESPONSE="$(curl ...)"` assignment trip `set -e` — under errexit, a
  # failing command substitution exits the script immediately, before the
  # captured body (which --fail-with-body promises above) is ever printed.
  set +e
  RESPONSE="$(curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL")"
  curl_status=$?
  set -e
  if [ "$curl_status" -ne 0 ]; then
    printf '%s\n' "$RESPONSE" >&2
    exit "$curl_status"
  fi

  # #384: short one-line "why" summary (same construction as
  # scripts/render_soak_digest.sh's headline) above the raw dump below.
  # Guarded on regime/regime_margin_pct being present — skipped otherwise.
  #
  # D5 (#384 fix round): the margin is only the TRUE cause of the current
  # position when target_state == current_state AND the kill-switch hasn't
  # fired — otherwise (kill-switch active, or a pending flip where
  # target_state != current_state) state the margin without the causal
  # "because" clause; the raw JSON dump below still carries target_state and
  # kill_switch_active for the real reason.
  if printf '%s' "$RESPONSE" | jq -e '.regime != null and .regime_margin_pct != null' >/dev/null 2>&1; then
    current_state="$(printf '%s' "$RESPONSE" | jq -r '.regime.current_state')"
    target_state="$(printf '%s' "$RESPONSE" | jq -r '.regime.target_state')"
    kill_switch_active="$(printf '%s' "$RESPONSE" | jq -r '.regime.kill_switch_active')"
    position_symbol="$(printf '%s' "$RESPONSE" | jq -r '.alpaca.position.symbol')"
    margin_direction="$(printf '%s' "$RESPONSE" | jq -r 'if .regime_margin_pct >= 0 then "above" else "below" end')"
    margin_abs_raw="$(printf '%s' "$RESPONSE" | jq -r '(.regime_margin_pct | if . < 0 then -. else . end)')"
    margin_abs="$(LC_ALL=C printf '%.1f' "$margin_abs_raw")"
    if [ "$target_state" = "$current_state" ] && [ "$kill_switch_active" != "true" ]; then
      if [ "$current_state" = "CASH" ]; then
        echo "${current_state} because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
      else
        echo "${current_state} \`${position_symbol}\` because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
      fi
    else
      margin_signed="+${margin_abs}"
      if [ "$margin_direction" = "below" ]; then
        margin_signed="-${margin_abs}"
      fi
      if [ "$current_state" = "CASH" ]; then
        echo "${current_state} — SPY vs 200-DMA: ${margin_signed}% (${margin_direction})."
      else
        echo "${current_state} \`${position_symbol}\` — SPY vs 200-DMA: ${margin_signed}% (${margin_direction})."
      fi
    fi
    echo
  fi

  printf '%s' "$RESPONSE" | jq .
else
  echo "warning: jq not found; printing raw response" >&2
  curl --fail-with-body -sS -H "x-status-token: $STATUS_TOKEN" "$REQUEST_URL"
fi
