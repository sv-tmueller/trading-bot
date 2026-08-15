// Nightly reflection glue (#583, wiring the frozen nightly-reflection engine
// (backtest/reflection.py, #578) into .github/workflows/daily-verification.yml).
// Shaped exactly like scripts/daily_verify.ts: a pure exported core plus a
// thin two-mode CLI. This script never spawns a subprocess and never touches
// the network -- its whole job is text transforms over three artifacts the
// engine or the evaluator already produced/consumed on disk:
//
//   1. `prior-ledger` mode: filters docs/trading-journal/daily-verification.jsonl
//      down to the rows strictly before the target date (the engine's own
//      trailing-20 fold has no date cutoff, so the CALLER must not hand it
//      today's just-rewritten row or any later date's rows -- see
//      selectPriorLedgerRows below), and writes that subset to a runner-local
//      file the engine CLI reads as its own `--ledger` argument.
//
//        deno run --allow-read=docs/trading-journal --allow-write=$RUNNER_TEMP \
//          scripts/apply_reflection.ts prior-ledger --date=YYYY-MM-DD \
//          --ledger=docs/trading-journal/daily-verification.jsonl \
//          --out=$RUNNER_TEMP/reflection/prior-ledger.jsonl
//
//   2. `apply` mode: reads the engine's stdout envelope ({date, markdown,
//      reflection}, captured to a file by the workflow) and merges it onto
//      the SAME two artifacts scripts/daily_verify.ts just wrote for this
//      date -- the `## Reflection` section appended to the daily digest doc,
//      and the `reflection` object merged onto the ledger row. Never raises
//      into a nonzero exit for an ordinary degrade case (a missing/malformed
//      envelope writes a glue-authored fallback section instead); the
//      workflow additionally wraps this whole step in capture-then-warn, so
//      even an unexpected throw here (e.g. an envelope/--date mismatch) can
//      never red the run -- see the workflow's own header comment.
//
//        deno run --allow-read=docs/trading-journal,$RUNNER_TEMP \
//          --allow-write=docs/trading-journal \
//          scripts/apply_reflection.ts apply --date=YYYY-MM-DD \
//          --envelope=$RUNNER_TEMP/reflection/envelope.json
//
// Load-bearing observation (not a bug): scripts/daily_verify.ts's own
// upsertLedgerJsonl replaces the whole ledger row for a date, and its
// renderMarkdownDigest rewrites the whole doc -- so every daily-verify run
// first strips any prior reflection from both artifacts before this script
// ever runs. Re-rendering a date always re-runs reflection (or visibly
// degrades); a stale section is structurally impossible on the workflow
// path. This script's own replace-not-duplicate logic exists for glue-only
// re-runs (re-applying the same envelope without re-running daily_verify.ts)
// and for the fixture test below.
import { type Environment, parseLedgerJsonl } from "./daily_verify.ts";

// ---------------------------------------------------------------------------
// applyReflectionSection -- append or replace the ## Reflection section at
// the end of a daily digest doc (§ decision 3, "section replace mechanics").
// ---------------------------------------------------------------------------

// Reflection is always the FINAL section of the doc (appended after
// "Changed since the previous verified day", per the engine module
// docstring's own framing) -- so finding this exact marker and truncating
// from it is enough to strip a prior run's section, whatever else the doc
// contains (every other section in scripts/daily_verify.ts's own layout also
// uses bare "---" separators, so a plain "---" search would risk matching
// the wrong one; this marker is specific to the boundary this script itself
// writes).
const REFLECTION_SECTION_MARKER = "\n---\n\n## Reflection";

/**
 * Appends `markdown` (the engine envelope's own `markdown` field) as the
 * doc's `## Reflection` section, replacing any prior run's section rather
 * than duplicating it. `markdown` that doesn't already start with the
 * heading (the engine's bare error-day line, `"Reflection: error -- ..."`)
 * is wrapped under one, so the section delimiter this function's own strip
 * logic depends on stays stable across every envelope shape. Idempotent:
 * applying the same `markdown` twice in a row is byte-identical.
 */
export function applyReflectionSection(docText: string, markdown: string): string {
  const section = markdown.startsWith("## Reflection") ? markdown : `## Reflection\n\n${markdown}`;
  const markerIndex = docText.indexOf(REFLECTION_SECTION_MARKER);
  const base = (markerIndex === -1 ? docText : docText.slice(0, markerIndex)).replace(/\n+$/, "");
  return `${base}\n\n---\n\n${section}\n`;
}

// ---------------------------------------------------------------------------
// selectPriorLedgerRows -- the caller-side input-preparation step the
// engine's own frozen contract requires (backtest/reflection.py's
// build_trailing_window folds EVERY row's reflection.trades with no date
// cutoff): feeds it exactly the ledger rows strictly before the target date.
// ---------------------------------------------------------------------------

/**
 * Rows from `ledgerText` (scripts/daily_verify.ts's own JSONL ledger shape)
 * with `date` strictly before `date` AND matching `env`, re-serialized as
 * JSONL text ready to write as the engine's own `--ledger` argument. #555:
 * the prior-ledger filter is scoped to the same environment -- a dev leg's
 * reflection sees only prior dev rows, never prod rows, so the trailing-20
 * window stays within-environment. On the nightly path this is
 * behavior-identical to handing the engine the whole ledger (today's
 * just-rewritten row has no `reflection` key yet), but it makes a backfill
 * re-run byte-reproduce its original reflection instead of contaminating the
 * trailing-20 window with later dates' trades.
 */
export function selectPriorLedgerRows(
  ledgerText: string,
  date: string,
  env: Environment,
): string {
  const rows = parseLedgerJsonl(ledgerText).filter(
    (row) => row.environment === env && row.date < date,
  );
  if (rows.length === 0) return "";
  return rows.map((row) => JSON.stringify(row)).join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// mergeReflectionIntoLedger -- read-modify-write of the matching row only.
// ---------------------------------------------------------------------------

export class MissingLedgerRowError extends Error {
  override name = "MissingLedgerRowError";
}

export class DuplicateLedgerRowError extends Error {
  override name = "DuplicateLedgerRowError";
}

/**
 * Merges `reflection` onto the ledger row for `(date, env)`, adding it as the
 * row's trailing key (a re-merge keeps it in its existing, already-trailing
 * position). Every row is re-serialized in ascending (date, environment) order
 * -- matching scripts/daily_verify.ts's own upsertLedgerJsonl convention --
 * so an unmerged re-run of this function is byte-identical and the workflow's
 * commit step's no-op check keeps working. Every OTHER row's own bytes are
 * unaffected (`JSON.parse` then `JSON.stringify` round-trips a row's own key
 * order and values unchanged since nothing but the target row is touched).
 * Throws `MissingLedgerRowError` if no row for `(date, env)` exists -- merging
 * a reflection onto a date scripts/daily_verify.ts never evaluated would be a
 * caller bug, not a degrade case. Throws `DuplicateLedgerRowError` if more
 * than one row matches `(date, env)` -- scripts/daily_verify.ts's own
 * upsertLedgerJsonl never produces this on the workflow path, so surfacing
 * it here rather than silently merging onto every matching row is safe: the
 * workflow's capture-then-warn around this whole step already contains the
 * throw without redding the run (see this file's own header comment).
 *
 * #555: the match key is now (date, environment), not date alone -- a dev
 * reflection merges onto the dev row, a prod reflection onto the prod row,
 * and neither touches the other environment's row for the same date.
 */
export function mergeReflectionIntoLedger(
  ledgerText: string,
  date: string,
  env: Environment,
  reflection: unknown,
): string {
  const rows = parseLedgerJsonl(ledgerText);
  const matches = rows.filter((row) => row.date === date && row.environment === env).length;
  if (matches === 0) {
    throw new MissingLedgerRowError(
      `apply_reflection: no ledger row for date ${JSON.stringify(date)} environment ${
        JSON.stringify(env)
      } -- scripts/daily_verify.ts must run (and write the ledger) before reflection merges onto it`,
    );
  }
  if (matches > 1) {
    throw new DuplicateLedgerRowError(
      `apply_reflection: ${matches} ledger rows for date ${JSON.stringify(date)} environment ${
        JSON.stringify(env)
      } -- refusing to merge reflection onto more than one row`,
    );
  }
  const merged = rows
    .slice()
    .sort((a, b) => {
      const cmp = a.date.localeCompare(b.date);
      return cmp !== 0 ? cmp : a.environment.localeCompare(b.environment);
    })
    .map((row) => row.date === date && row.environment === env ? { ...row, reflection } : row);
  return merged.map((row) => JSON.stringify(row)).join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// fallbackReflectionMarkdown -- glue-authored vocabulary for the "the
// engine's own envelope never landed" case (a bug, per the workflow's own
// never-red steps -- pip/fetch/engine failures degrade earlier, inside the
// engine's own contract; this is the outer safety net for when even THAT
// degrade never reached disk). Never confuse this with backtest/reflection.py's
// own frozen `"Reflection: error -- <reason>"` line -- that is the engine's
// contract; this is glue vocabulary, disclosed as such in the workflow's own
// header comment.
// ---------------------------------------------------------------------------

export function fallbackReflectionMarkdown(reason: string): string {
  return `## Reflection\n\nReflection unavailable: ${reason}.`;
}

// ---------------------------------------------------------------------------
// planApply -- the apply mode's pure orchestration core. Decides the new doc
// text and ledger text from raw inputs (an envelope file's raw text, or
// `null` when the file never existed) without touching disk itself, so the
// "envelope absent" and "envelope malformed" degrade paths are unit-testable
// without a subprocess. On either degrade path, the ledger is returned
// UNCHANGED ("merges nothing") -- only the doc gains a fallback section, so
// a section is never silently dropped but a degrade also never invents a
// reflection object the engine didn't actually compute.
// ---------------------------------------------------------------------------

export interface ApplyPlan {
  docText: string;
  ledgerText: string;
}

interface ReflectionEnvelope {
  date: string;
  markdown: string;
  reflection: unknown;
}

function isReflectionEnvelope(value: unknown): value is ReflectionEnvelope {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.date === "string" && typeof v.markdown === "string" && "reflection" in v;
}

export function planApply(
  date: string,
  env: Environment,
  envelopeRaw: string | null,
  docText: string,
  ledgerText: string,
): ApplyPlan {
  if (envelopeRaw === null) {
    const markdown = fallbackReflectionMarkdown("engine did not produce an output envelope");
    return { docText: applyReflectionSection(docText, markdown), ledgerText };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(envelopeRaw);
  } catch {
    const markdown = fallbackReflectionMarkdown("engine output envelope was not valid JSON");
    return { docText: applyReflectionSection(docText, markdown), ledgerText };
  }

  if (!isReflectionEnvelope(parsed)) {
    const markdown = fallbackReflectionMarkdown(
      "engine output envelope is missing the expected {date, markdown, reflection} shape",
    );
    return { docText: applyReflectionSection(docText, markdown), ledgerText };
  }

  if (parsed.date !== date) {
    throw new Error(
      `apply_reflection: envelope date ${JSON.stringify(parsed.date)} does not match ` +
        `--date ${JSON.stringify(date)}`,
    );
  }

  return {
    docText: applyReflectionSection(docText, parsed.markdown),
    ledgerText: mergeReflectionIntoLedger(ledgerText, date, env, parsed.reflection),
  };
}

// ---------------------------------------------------------------------------
// CLI entry point (thin, two modes). Not exercised by any test -- matching
// scripts/daily_verify.ts's own documented convention: everything above this
// point is unit-tested with explicit inputs, and only main() touches
// argv/disk.
// ---------------------------------------------------------------------------

const LEDGER_PATH = "docs/trading-journal/daily-verification.jsonl";
const DIGEST_BASE_DIR = "docs/trading-journal/daily";

function digestDir(env: Environment): string {
  return `${DIGEST_BASE_DIR}/${env}`;
}

function digestPath(env: Environment, date: string): string {
  return `${digestDir(env)}/${date}.md`;
}

function parseFlag(argv: string[], flag: string): string | undefined {
  const prefix = `--${flag}=`;
  for (const arg of argv) {
    if (arg.startsWith(prefix)) return arg.slice(prefix.length);
  }
  return undefined;
}

function requireFlag(argv: string[], flag: string): string {
  const value = parseFlag(argv, flag);
  if (value === undefined) {
    throw new Error(`apply_reflection: missing required --${flag}=... argument`);
  }
  return value;
}

function parseEnvironmentFlag(argv: string[]): Environment {
  const val = parseFlag(argv, "environment");
  if (val === undefined) return "dev";
  if (val !== "dev" && val !== "prod") {
    throw new Error(`apply_reflection: invalid --environment=${val} (must be "dev" or "prod")`);
  }
  return val;
}

async function readTextIfExists(path: string): Promise<string | null> {
  try {
    return await Deno.readTextFile(path);
  } catch (e) {
    if (e instanceof Deno.errors.NotFound) return null;
    throw e;
  }
}

async function runPriorLedger(argv: string[]): Promise<void> {
  const date = requireFlag(argv, "date");
  const env = parseEnvironmentFlag(argv);
  const ledgerPath = requireFlag(argv, "ledger");
  const outPath = requireFlag(argv, "out");
  const ledgerText = (await readTextIfExists(ledgerPath)) ?? "";
  const priorText = selectPriorLedgerRows(ledgerText, date, env);
  await Deno.mkdir(outPath.slice(0, outPath.lastIndexOf("/")), { recursive: true }).catch(
    () => {},
  );
  await Deno.writeTextFile(outPath, priorText);
}

async function runApply(argv: string[]): Promise<void> {
  const date = requireFlag(argv, "date");
  const env = parseEnvironmentFlag(argv);
  const envelopePath = requireFlag(argv, "envelope");
  const envelopeRaw = await readTextIfExists(envelopePath);
  const docText = (await readTextIfExists(digestPath(env, date))) ?? "";
  const ledgerText = (await readTextIfExists(LEDGER_PATH)) ?? "";

  const plan = planApply(date, env, envelopeRaw, docText, ledgerText);

  const dir = digestDir(env);
  await Deno.mkdir(dir, { recursive: true });
  await Deno.writeTextFile(digestPath(env, date), plan.docText);
  await Deno.writeTextFile(LEDGER_PATH, plan.ledgerText);
}

async function main(): Promise<void> {
  const [mode, ...rest] = Deno.args;
  try {
    if (mode === "prior-ledger") {
      await runPriorLedger(rest);
    } else if (mode === "apply") {
      await runApply(rest);
    } else {
      throw new Error(
        `apply_reflection: unknown mode ${JSON.stringify(mode)} (want prior-ledger|apply)`,
      );
    }
  } catch (e) {
    console.error(`apply_reflection: ${(e as Error).message}`);
    Deno.exit(1);
    return;
  }
}

if (import.meta.main) {
  main();
}
