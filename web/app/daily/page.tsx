import Link from "next/link";
import { readLedger, type LedgerRow, type Verdict } from "@/lib/dailyJournal";

// No `export const dynamic` here: App Router prerenders statically by
// default unless it sees a dynamic API, and readLedger()'s plain
// fs.readFileSync is not one. This is a build-time-only read (#548 design
// spec §8): no runtime filesystem access, no secrets, and `next build` still
// passes in CI without credentials.

const VERDICT_ACCENT: Record<Verdict, string> = {
  PASS: "text-emerald-400",
  WARN: "text-amber-400",
  FAIL: "text-red-400",
};

export default function DailyIndexPage() {
  const newestFirst = [...readLedger()].reverse();

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Daily verification</h1>
        <Link href="/" className="text-xs text-zinc-500 hover:text-zinc-300">
          ← back to status
        </Link>
      </header>

      {newestFirst.length === 0 ? (
        <div className="rounded-md border border-zinc-700 bg-zinc-900/50 px-4 py-2 text-sm text-zinc-400">
          No verified days yet
        </div>
      ) : (
        <ul className="space-y-2">
          {newestFirst.map((row) => (
            <li key={row.date}>
              <DailyRow row={row} />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function DailyRow({ row }: { row: LedgerRow }) {
  return (
    <Link
      href={`/daily/${row.date}`}
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 hover:border-zinc-700"
    >
      <span className="text-sm text-zinc-200">{row.date}</span>
      <span className={`text-sm font-semibold ${VERDICT_ACCENT[row.verdict]}`}>{row.verdict}</span>
      <span className="text-xs text-zinc-500">
        {row.metrics.hourly_runs} runs · {row.metrics.scan_rows} scans · {row.metrics.entries} entries
        {row.findings.length > 0 ? ` · ${row.findings.length} finding(s)` : ""}
      </span>
    </Link>
  );
}
