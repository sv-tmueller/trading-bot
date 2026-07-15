#!/usr/bin/env bash
set -euo pipefail
# Renders the `status` Edge Function's no-param JSON digest (#354,
# supabase/functions/status/logic.ts: StatusDigest) into a compact markdown
# soak report for the weekly digest workflow (#357). Reads the digest JSON
# from stdin (or from a file given as $1), writes markdown to stdout.
#
# Usage: bash scripts/render_soak_digest.sh < digest.json > comment.md
#        bash scripts/render_soak_digest.sh digest.json > comment.md
#
# Validates first: garbled/partial/truncated/empty JSON, or JSON missing the
# load-bearing keys with the wrong type, fails this script with a nonzero
# exit before any rendering is attempted — the caller (the soak-digest
# workflow) treats that as a failed step and posts no comment.

INPUT="${1:-/dev/stdin}"

RAW="$(cat "$INPUT")"

if [ -z "$RAW" ]; then
  echo "error: empty input — no digest JSON to render" >&2
  exit 1
fi

if ! printf '%s' "$RAW" | jq -e '
    (.generated_at | type == "string") and
    (.market_open | type == "boolean") and
    (.paused | type == "boolean") and
    (.audit_7d.since | type == "string") and
    (.audit_7d.outcome_counts | type == "object") and
    (.audit_7d.errors | type == "array") and
    (.alpaca.equity_usd | type == "number") and
    (.alpaca.position.symbol | type == "string") and
    (.alpaca.position.qty | type == "number") and
    ((.regime_margin_pct | type == "number") or (.regime_margin_pct | type == "null"))
  ' >/dev/null 2>/dev/null; then
  echo "error: input is not a valid StatusDigest JSON (garbled, partial, truncated, or missing/mistyped required keys)" >&2
  exit 1
fi

DIGEST="$RAW"

generated_at="$(printf '%s' "$DIGEST" | jq -r '.generated_at')"
market_open="$(printf '%s' "$DIGEST" | jq -r '.market_open')"
paused="$(printf '%s' "$DIGEST" | jq -r '.paused')"
audit_since="$(printf '%s' "$DIGEST" | jq -r '.audit_7d.since')"

# #384: signed, 1-decimal SPY-vs-200-DMA margin + above/below, derived from
# the SIGN of regime_margin_pct (not from target_state/current_state, so the
# wording can never contradict the number). Empty when regime is null (no
# regime_state row) or regime_margin_pct is null (e.g. sma <= 0).
margin_raw="$(printf '%s' "$DIGEST" | jq -r '.regime_margin_pct // "null"')"
margin_signed=""
margin_direction=""
if [ "$margin_raw" != "null" ]; then
  margin_direction="$(printf '%s' "$DIGEST" | jq -r 'if .regime_margin_pct >= 0 then "above" else "below" end')"
  margin_abs_raw="$(printf '%s' "$DIGEST" | jq -r '(.regime_margin_pct | if . < 0 then -. else . end)')"
  margin_abs="$(printf '%.1f' "$margin_abs_raw")"
  if [ "$margin_direction" = "above" ]; then
    margin_signed="+${margin_abs}"
  else
    margin_signed="-${margin_abs}"
  fi
fi

echo "## Weekly soak digest — ${generated_at}"
echo

# #384: one headline sentence contextualizing the currently-held position
# (current_state — the reason for the position currently held) against the
# SPY-vs-200-DMA margin. Skipped when regime is null (keep the existing
# fallback below) or regime_margin_pct is null.
if printf '%s' "$DIGEST" | jq -e '.regime != null' >/dev/null && [ -n "$margin_signed" ]; then
  current_state="$(printf '%s' "$DIGEST" | jq -r '.regime.current_state')"
  position_symbol="$(printf '%s' "$DIGEST" | jq -r '.alpaca.position.symbol')"
  if [ "$current_state" = "CASH" ]; then
    echo "${current_state} because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
  else
    echo "${current_state} \`${position_symbol}\` because SPY is ${margin_abs}% ${margin_direction} its 200-DMA."
  fi
  echo
fi

echo "- Market open: \`${market_open}\`"
echo "- Trading paused: \`${paused}\`"
echo

echo "### Regime"
if printf '%s' "$DIGEST" | jq -e '.regime == null' >/dev/null; then
  echo "No \`regime_state\` row."
else
  printf '%s' "$DIGEST" | jq -r '
    .regime |
    "- Date: `\(.date)`",
    "- Target / current state: `\(.target_state)` / `\(.current_state)`",
    "- Position drawdown: \(if .position_drawdown_pct == null then "n/a" else (.position_drawdown_pct | tostring) + "%" end)",
    "- Kill switch active: `\(.kill_switch_active)`" + (if .kill_switch_active then " (fired at \(.kill_switch_fired_at // "unknown"))" else "" end)
  '
  if [ -n "$margin_signed" ]; then
    echo "- SPY vs 200-DMA: \`${margin_signed}%\` (${margin_direction})"
  fi
fi
echo

echo "### 7-day outcomes (since ${audit_since})"
counts="$(printf '%s' "$DIGEST" | jq -r '.audit_7d.outcome_counts | to_entries | if length == 0 then empty else .[] | "- \(.value) x `\(.key)`" end')"
if [ -z "$counts" ]; then
  echo "No \`audit_log\` rows in the last 7 days."
else
  echo "$counts"
fi
echo

echo "### Errors (last 7 days)"
error_count="$(printf '%s' "$DIGEST" | jq -r '.audit_7d.errors | length')"
if [ "$error_count" = "0" ]; then
  echo "None."
else
  printf '%s' "$DIGEST" | jq -r '
    .audit_7d.errors[] |
    "- `\(.script_name)` started `\(.started_at)`, outcome `\(.outcome)`: \(.notes // "(no notes)")"
  '
fi
echo

echo "### Last trade"
if printf '%s' "$DIGEST" | jq -e '.last_trade == null' >/dev/null; then
  echo "None recorded."
else
  printf '%s' "$DIGEST" | jq -r '
    .last_trade |
    "- `\(.side)` \(.qty) `\(.symbol)` @ \(.fill_price), filled `\(.fill_time)`",
    "- Reason: \(.reason)",
    "- Broker order id: `\(.broker_order_id)`"
  '
fi
echo

echo "### Alpaca account"
printf '%s' "$DIGEST" | jq -r '
  .alpaca |
  "- Equity: $\(.equity_usd) USD",
  "- Position: \(.position.qty) `\(.position.symbol)`"
'
echo

echo "<details><summary>Raw digest JSON</summary>"
echo
echo '```json'
printf '%s' "$DIGEST" | jq .
echo '```'
echo
echo "</details>"
