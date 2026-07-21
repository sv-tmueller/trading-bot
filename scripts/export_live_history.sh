#!/usr/bin/env bash
set -euo pipefail
# Read-only export of the live trading record for the divergence report (#403).
# Performs GET-only PostgREST requests against the Supabase REST API using the
# service-role key from an env file (default: <repo-root>/.env.backfill, the
# same credential file used by #391's one-time equity backfill). No writes,
# no broker calls — this script only reads regime_state/trades/equity_snapshots/
# audit_log via `Accept: text/csv` and writes them to disk for the offline
# Python analysis (backtest/run_live_divergence.py) to consume.
#
# Usage: bash scripts/export_live_history.sh [--env-file <path>] [--out <dir>]
#   --env-file <path>   env file with SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY
#                        (default: <repo-root>/.env.backfill)
#   --out <dir>         output directory for the four CSVs
#                        (default: <repo-root>/live_export/)
#
# From a worktree (no local .env.backfill), pass the main checkout's file by
# absolute path, e.g.:
#   bash scripts/export_live_history.sh \
#     --env-file /Users/thomas.mueller/Desktop/github/trading-bot/.env.backfill

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.backfill"
OUT_DIR="$REPO_ROOT/live_export"

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file)
      if [ $# -lt 2 ]; then
        echo "error: --env-file requires a value" >&2
        exit 1
      fi
      ENV_FILE="$2"
      shift 2
      ;;
    --out)
      if [ $# -lt 2 ]; then
        echo "error: --out requires a value" >&2
        exit 1
      fi
      OUT_DIR="$2"
      shift 2
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found. Copy .env.backfill.example to .env.backfill and fill it in (or pass --env-file)." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [ -z "${SUPABASE_URL:-}" ]; then
  echo "error: SUPABASE_URL is not set in $ENV_FILE" >&2
  exit 1
fi

if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo "error: SUPABASE_SERVICE_ROLE_KEY is not set in $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

# GET-only: every request below is a plain curl GET against PostgREST's
# `rest/v1/<table>` resource. No write verb (POST/PATCH/PUT/DELETE) appears
# anywhere in this script.
_export_table() {
  local table="$1"
  local query="$2"
  local dest="$OUT_DIR/$table.csv"
  curl --fail-with-body -sS \
    -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
    -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
    -H "Accept: text/csv" \
    "${SUPABASE_URL}/rest/v1/${table}?${query}" \
    -o "$dest"
  echo "wrote $dest"
}

_export_table "equity_snapshots" "select=date,equity_usd&order=date.asc&limit=1000"
_export_table "trades" "select=fill_time,symbol,side,qty,fill_price,reason,broker_order_id&order=fill_time.asc&limit=1000"
_export_table "regime_state" "select=date,spy_close,spy_sma200,target_state,current_state,kill_switch_active&order=date.asc&limit=1000"
_export_table "audit_log" "select=started_at,finished_at,outcome,notes&script_name=eq.daily-check&order=started_at.asc&limit=1000"

echo "Export complete: $OUT_DIR"
