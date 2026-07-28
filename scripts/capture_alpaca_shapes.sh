#!/usr/bin/env bash
set -euo pipefail
# Captures the four read-only paper-account API shapes the hourly-bot rollout
# needs to confirm before the Layer-B paper-guard marker (and a few other
# [to verify] fields) can be pinned in code (#479 T2, spec §7/§8.3).
#
# GETs only -- no order, no mutation, nothing that could place a trade. The
# paper host is HARDCODED below and never configurable (not a flag, not an
# env override) so this script cannot accidentally be pointed at a live
# account by a stray env var.
#
# Usage: bash scripts/capture_alpaca_shapes.sh
#   Reads ALPACA_API_KEY / ALPACA_SECRET_KEY from the environment, or from
#   .env.capture (gitignored; copy the pattern from .env.example's Alpaca
#   block and fill in PAPER keys only -- never live keys). Missing/blank
#   either credential prints this usage and exits 1 without any network call.
#
# Sanitization (non-negotiable, so an unsanitized body can never be pasted
# into a GitHub comment): the /v2/account capture masks account_number to a
# 2-character prefix (e.g. "PA****...") and drops the account `id` field
# entirely. The API keys themselves are request headers, never response
# fields, so they never appear in any captured body -- but this script still
# never echoes the header values it sends.
#
# Each capture prints a PASS/FAIL line against the pinned expectation (the
# shape the spec's [to verify] items assert, per docs/superpowers/specs/
# 2026-07-27-hourly-bot-design.md §7/§8.3) followed by the sanitized JSON.
# Paste the FULL output of a run (all four captures) into a comment on #479
# titled "Capture evidence: <endpoint>" per the T1 handoff.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.capture"

# Paper-only, hardcoded (spec §8.3 Layer A precedent: the host is the load-
# bearing check, not a boolean). Never read from an env var -- a compromised
# or mis-set ALPACA_PAPER/ALPACA_BASE_URL elsewhere in the environment cannot
# redirect this script.
readonly PAPER_BASE_URL="https://paper-api.alpaca.markets"

usage() {
  cat >&2 <<'USAGE'
Usage: bash scripts/capture_alpaca_shapes.sh

Requires ALPACA_API_KEY and ALPACA_SECRET_KEY for the Alpaca PAPER account,
either already exported in the shell or set in .env.capture (gitignored,
repo root). Performs four read-only GETs against paper-api.alpaca.markets
(never configurable) and prints a PASS/FAIL + sanitized body per capture.

No credentials found -- nothing was sent over the network.
USAGE
}

if [ -z "${ALPACA_API_KEY:-}" ] || [ -z "${ALPACA_SECRET_KEY:-}" ]; then
  if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
  fi
fi

if [ -z "${ALPACA_API_KEY:-}" ] || [ -z "${ALPACA_SECRET_KEY:-}" ]; then
  usage
  exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0

# $1 = human label, $2 = path (incl. query string), $3 = jq PASS/FAIL predicate
# (must print "PASS" or "FAIL <reason>" on stdout), $4 = jq sanitizer filter
# applied to the raw body before anything is printed.
capture() {
  local label="$1" path="$2" predicate="$3" sanitizer="$4"
  local http_code body
  echo "--- ${label} (GET ${path}) ---"

  body="$(curl -sS -w '\n%{http_code}' \
    -H "APCA-API-KEY-ID: ${ALPACA_API_KEY}" \
    -H "APCA-API-SECRET-KEY: ${ALPACA_SECRET_KEY}" \
    "${PAPER_BASE_URL}${path}")"
  http_code="$(printf '%s' "$body" | tail -n1)"
  body="$(printf '%s' "$body" | sed '$d')"

  if [ "$http_code" != "200" ]; then
    echo "FAIL: HTTP ${http_code} (abort -- do not retry blind; check the paper keys and account state)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    return
  fi

  local sanitized
  sanitized="$(printf '%s' "$body" | jq "$sanitizer")"

  local result
  result="$(printf '%s' "$body" | jq -r "$predicate")"
  if [ "$result" = "PASS" ]; then
    echo "PASS"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL: ${result}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  echo "$sanitized"
  echo
}

# 1. /v2/clock -- pins getClock()'s nextClose field (spec §7 [to verify]).
capture "clock" "/v2/clock" \
  'if (.next_close != null and (.next_close | type) == "string") then "PASS" else "FAIL missing/non-string next_close" end' \
  '{timestamp, is_open, next_open, next_close}'

# 2. /v2/account -- pins the Layer-B paper-account marker (spec §8.3
# [to verify]). account_number is masked to a 2-char prefix; `id` is dropped.
capture "account" "/v2/account" \
  'if ((.account_number | type) == "string" and (.equity != null)) then "PASS" else "FAIL missing account_number/equity" end' \
  '{account_number: (if (.account_number|type)=="string" then (.account_number[0:2] + "****") else .account_number end), status, equity, currency}'

# 3. /v2/calendar -- pins getCalendarSessions()'s open/close HH:MM fields
# (spec §7 session-close flatten mechanic). Window: today through +7 days,
# UTC date, so at least one trading day is covered regardless of when this
# runs.
CAL_START="$(date -u +%Y-%m-%d)"
CAL_END="$(date -u -v+7d +%Y-%m-%d 2>/dev/null || date -u -d '+7 days' +%Y-%m-%d)"
capture "calendar" "/v2/calendar?start=${CAL_START}&end=${CAL_END}" \
  'if (type == "array" and length > 0 and (.[0].open | test("^[0-9]{2}:[0-9]{2}$")) and (.[0].close | test("^[0-9]{2}:[0-9]{2}$"))) then "PASS" else "FAIL non-array or open/close not HH:MM" end' \
  '.'

# 4. /v2/assets/SPY -- pins getAssetShortability()'s shortable/easy_to_borrow
# fields (spec §7 [to verify], must-fix round 1 finding 6).
capture "assets/SPY" "/v2/assets/SPY" \
  'if ((.shortable | type) == "boolean" and (.easy_to_borrow | type) == "boolean") then "PASS" else "FAIL shortable/easy_to_borrow not boolean" end' \
  '{symbol, tradable, shortable, easy_to_borrow, fractionable}'

echo "=== ${PASS_COUNT}/4 captures PASS, ${FAIL_COUNT}/4 FAIL ==="
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
