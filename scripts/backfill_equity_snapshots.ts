// One-time operator-run backfill of `equity_snapshots` from Alpaca's
// portfolio-history endpoint (#389, batch #388 Package A). Fetch lives here
// (not in _shared/alpaca.ts) so this stays zero new production surface (D1 —
// see the #389 SUB_PLAN on issue #389 for the full design). Imports only
// getAlpacaConfig()/getServiceClient() from _shared/ for identical env names
// and auth headers. The GET is read-only (parallel to the unguarded
// getAccountValue) — no checkGuard/CLAUDE_AGENT_NO_BROKER involvement, and no
// mutating broker helper is added anywhere.
//
// Insert-if-absent is enforced two ways (D2): a script-local read of existing
// dates in-window, plus (mechanically) `.upsert(rows, { onConflict: "date",
// ignoreDuplicates: true })` — PostgREST's `Prefer: resolution=ignore-
// duplicates`, i.e. `INSERT ... ON CONFLICT DO NOTHING`. This can never
// modify an existing row (daily-check's rows are canonical) and closes the
// TOCTOU window between the read and the write.
// ---------------------------------------------------------------------------
// T1 — arg parsing
// ---------------------------------------------------------------------------

export class ArgError extends Error {
  override name = "ArgError";
}
// Distinguished from a plain ArgError (e.g. a malformed --since) so main()
// can show full usage for a genuinely unknown flag while keeping a bad
// --since value to a one-line message (D5/T1).
export class UnknownArgError extends ArgError {
  override name = "UnknownArgError";
}

export interface ParsedArgs {
  help: boolean;
  since: string | undefined;
  execute: boolean;
}

const YMD_RE = /^\d{4}-\d{2}-\d{2}$/;

// Round-trip validation, not just regex: `new Date("2026-02-30")` silently
// rolls over to March 2 in JS, so a naive regex-only check would accept an
// invalid calendar date.
function isValidYmd(val: string): boolean {
  if (!YMD_RE.test(val)) return false;
  const d = new Date(`${val}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === val;
}

export function parseArgs(argv: string[]): ParsedArgs {
  let since: string | undefined;
  let execute = false;
  let help = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "-h":
      case "--help":
        help = true;
        break;
      case "--execute":
        execute = true;
        break;
      case "--since": {
        const val = argv[++i];
        if (val === undefined || !isValidYmd(val)) {
          throw new ArgError(
            `--since must be a valid YYYY-MM-DD date, got ${JSON.stringify(val ?? "")}`,
          );
        }
        since = val;
        break;
      }
      default:
        throw new UnknownArgError(`unknown argument: ${arg}`);
    }
  }

  return { help, since, execute };
}
