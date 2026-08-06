import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { listDigestDates, readDigestMarkdown } from "@/lib/dailyJournal";

// Static params from the digest directory, read once at build time. Combined
// with `dynamicParams = false` below, this is the whole "build time only"
// guarantee for this route (#548 design spec §8): without dynamicParams, an
// unmatched date would silently fall through to on-demand server rendering,
// which is a runtime filesystem read.
export function generateStaticParams() {
  return listDigestDates().map((date) => ({ date }));
}

// Load-bearing: refuses on-demand rendering for any date not returned by
// generateStaticParams(), so a stale link 404s through Next's own
// not-found handling instead of reading the filesystem at request time.
export const dynamicParams = false;

// Deliberately NOT adding rehype-raw or any raw-HTML plugin: react-markdown's
// default behavior of escaping HTML embedded in markdown is an acceptance
// criterion for this route, and a raw-HTML plugin would silently defeat it.
const MARKDOWN_COMPONENTS: Components = {
  table: ({ children }) => (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-zinc-900/60 text-[11px] uppercase tracking-wide text-zinc-500">{children}</thead>
  ),
  tbody: ({ children }) => <tbody className="divide-y divide-zinc-800">{children}</tbody>,
  tr: ({ children }) => <tr className="hover:bg-zinc-900/40">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 font-medium">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-zinc-300">{children}</td>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5 text-zinc-300">{children}</ul>,
  li: ({ children, className }) => <li className={`${className ?? ""} text-zinc-300`}>{children}</li>,
  input: ({ checked, disabled }) => (
    <input type="checkbox" checked={checked ?? false} disabled={disabled ?? true} readOnly className="mr-2 accent-emerald-500" />
  ),
  h1: ({ children }) => <h2 className="text-lg font-semibold text-zinc-100">{children}</h2>,
  h2: ({ children }) => <h3 className="text-base font-semibold text-zinc-100">{children}</h3>,
  code: ({ children }) => <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-200">{children}</code>,
};

// Next 15 made dynamic-segment props async — `params` is a Promise here, not
// a plain object, so the component must await it.
export default async function DailyDigestPage({ params }: { params: Promise<{ date: string }> }) {
  const { date } = await params;
  const markdown = readDigestMarkdown(date);
  if (markdown === null) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Daily verification — {date}</h1>
        <Link href="/daily" className="text-xs text-zinc-500 hover:text-zinc-300">
          ← all days
        </Link>
      </header>
      <article className="space-y-4 text-sm leading-relaxed text-zinc-200">
        <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {markdown}
        </Markdown>
      </article>
    </main>
  );
}
