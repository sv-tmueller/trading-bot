#!/usr/bin/env bash
# Shared issue-based dedup latch for .github/workflows/deadman-watchdog.yml
# (#396 T3). Invoked once per target (dev/prod) with the target's result
# passed via env vars — see the "Latch dev"/"Latch prod" steps in the
# workflow for the exact env wiring. Not a Deno script (no test coverage
# here by design — the pure evaluation logic lives in scripts/deadman_check.ts
# and IS unit-tested; this is thin gh/curl orchestration glue, same class as
# the untested CLI wiring at the bottom of deadman_check.ts).
#
# Required env:
#   LABEL               - GitHub label for this target's latch issue
#                          (deadman-dev / deadman-prod)
#   TITLE_PREFIX         - issue title prefix (e.g. "[deadman][dev]")
#   MESSAGE_PREFIX        - Discord message prefix (e.g. "[dev]")
#   HEALTHY               - "true" or "false" (from the Evaluate step)
#   FINDINGS               - newline-separated finding messages (ignored
#                            when HEALTHY=true)
#   NOTIFY_WEBHOOK_URL      - Discord incoming webhook URL (may be unset)
# Also relies on GH_TOKEN (job-level env) for `gh`, and the standard
# GITHUB_REPOSITORY / GITHUB_SERVER_URL / GITHUB_RUN_ID Actions env vars.
#
# Exit code: 0 unless findings exist AND no open issue was already latched
# AND the Discord post could not be delivered (webhook unset or curl
# failed) — in that case the issue is still created (the incident is never
# silently unrecorded), but the run itself fails red so a missing/broken
# webhook is loud, not silent.
set -euo pipefail

: "${LABEL:?LABEL is required}"
: "${TITLE_PREFIX:?TITLE_PREFIX is required}"
: "${MESSAGE_PREFIX:?MESSAGE_PREFIX is required}"
: "${HEALTHY:?HEALTHY is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

# Idempotent — never fails if the label already exists.
gh label create "$LABEL" \
  --color B60205 \
  --description "deadman-watchdog latch (#396) — open = active incident, suppresses re-alerts until closed" \
  --force >/dev/null

OPEN_ISSUE=$(gh issue list --repo "$GITHUB_REPOSITORY" --label "$LABEL" --state open \
  --json number --jq '.[0].number // empty')

if [ "$HEALTHY" = "true" ]; then
  if [ -n "$OPEN_ISSUE" ]; then
    gh issue comment "$OPEN_ISSUE" --repo "$GITHUB_REPOSITORY" \
      --body "Recovered — the latest deadman-watchdog run found no findings. Closing this incident; re-opens automatically (a new issue) if the condition recurs."
    gh issue close "$OPEN_ISSUE" --repo "$GITHUB_REPOSITORY"
    echo "deadman-watchdog $LABEL: healthy, closed issue #$OPEN_ISSUE"
  else
    echo "deadman-watchdog $LABEL: healthy, nothing to do"
  fi
  exit 0
fi

# Unhealthy from here on.
if [ -n "$OPEN_ISSUE" ]; then
  echo "deadman-watchdog $LABEL: findings present, but issue #$OPEN_ISSUE is already open — dedup, no new alert"
  exit 0
fi

RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
TITLE="$TITLE_PREFIX $(date -u +%F): scheduled runs stale or status unreachable"
BODY=$(printf '%s\n\nWorkflow run: %s\n' "$FINDINGS" "$RUN_URL")

gh issue create --repo "$GITHUB_REPOSITORY" --title "$TITLE" --label "$LABEL" --body "$BODY"
echo "deadman-watchdog $LABEL: created latch issue"

if [ -z "${NOTIFY_WEBHOOK_URL:-}" ]; then
  echo "::error::deadman-watchdog $LABEL: NOTIFY_WEBHOOK_URL is unset — latch issue created, but no Discord alert could be sent. Failing the run red so this isn't silent."
  exit 1
fi

PAYLOAD=$(jq -n --arg content "$MESSAGE_PREFIX Dead-man watchdog alert:
$FINDINGS

$RUN_URL" '{content: $content}')

if ! curl --fail-with-body -sS --max-time 30 \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$NOTIFY_WEBHOOK_URL" >/dev/null; then
  echo "::error::deadman-watchdog $LABEL: latch issue created, but posting the Discord alert failed. Failing the run red so this isn't silent."
  exit 1
fi

echo "deadman-watchdog $LABEL: alert delivered"
