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
    (.returns | type == "object") and
    (.returns.since_inception_pct | type == "number" or type == "null") and
    (.returns.trailing_7d_pct | type == "number" or type == "null") and
    (.returns.trailing_30d_pct | type == "number" or type == "null")
  ' >/dev/null 2>/dev/null; then
  echo "error: input is not a valid StatusDigest JSON (garbled, partial, truncated, or missing/mistyped required keys)" >&2
  exit 1
fi

DIGEST="$RAW"

generated_at="$(printf '%s' "$DIGEST" | jq -r '.generated_at')"
market_open="$(printf '%s' "$DIGEST" | jq -r '.market_open')"
paused="$(printf '%s' "$DIGEST" | jq -r '.paused')"
audit_since="$(printf '%s' "$DIGEST" | jq -r '.audit_7d.since')"

echo "## Weekly soak digest — ${generated_at}"
echo
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

echo "### Returns"
printf '%s' "$DIGEST" | jq -r '
  .returns |
  "- Since inception: \(if .since_inception_pct == null then "n/a" else (.since_inception_pct | tostring) + "%" end)",
  "- Trailing 7d: \(if .trailing_7d_pct == null then "n/a" else (.trailing_7d_pct | tostring) + "%" end)",
  "- Trailing 30d: \(if .trailing_30d_pct == null then "n/a" else (.trailing_30d_pct | tostring) + "%" end)"
'
echo

echo "<details><summary>Raw digest JSON</summary>"
echo
echo '```json'
printf '%s' "$DIGEST" | jq .
echo '```'
echo
echo "</details>"
