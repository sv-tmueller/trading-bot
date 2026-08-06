#!/usr/bin/env node
// Documented fallback for the "Vercel outside-root-directory" risk (#548
// design spec §8). web/lib/dailyJournal.ts prefers web/content/** and falls
// through to ../docs/trading-journal/** on ENOENT, so activating this
// fallback is a one-line package.json change, not a redesign: add
//
//   "prebuild": "node scripts/copy-daily-artifacts.mjs"
//
// This script is intentionally NOT wired into package.json today. A full CI
// checkout and a correctly configured Vercel project (with "Include source
// files outside of the Root Directory" enabled) both already have
// ../docs/trading-journal readable from web/, so the module's own fallback
// path handles them without this script running at all. If that Vercel
// setting turns out to be off, the operator adds the prebuild line above.
//
// Plain Node fs/path only (no new dependency) — no-ops (exit 0, one notice)
// when the source directory is unreachable, so it is safe to wire in before
// #547 has produced any artifacts yet.

import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.join(here, "..");
const repoRoot = path.join(webRoot, "..");

const sourceDailyDir = path.join(repoRoot, "docs", "trading-journal", "daily");
const sourceLedger = path.join(repoRoot, "docs", "trading-journal", "daily-verification.jsonl");
const destContentDir = path.join(webRoot, "content");
const destDailyDir = path.join(destContentDir, "daily");
const destLedger = path.join(destContentDir, "daily-verification.jsonl");

function main() {
  if (!existsSync(sourceDailyDir) && !existsSync(sourceLedger)) {
    console.log(
      "copy-daily-artifacts: no docs/trading-journal daily artifacts found yet — nothing to copy.",
    );
    return;
  }

  rmSync(destContentDir, { recursive: true, force: true });
  mkdirSync(destContentDir, { recursive: true });

  if (existsSync(sourceDailyDir)) {
    cpSync(sourceDailyDir, destDailyDir, { recursive: true });
  }
  if (existsSync(sourceLedger)) {
    cpSync(sourceLedger, destLedger);
  }

  console.log(`copy-daily-artifacts: copied artifacts into ${destContentDir}`);
}

main();
