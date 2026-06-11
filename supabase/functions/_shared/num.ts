// Shared numeric-parsing guard for values coming off external APIs (Alpaca
// trading + market data). Number(null) === 0 and Number("") === 0, so a missing
// price/qty would silently become 0 and corrupt the SMA200 signal, the
// kill-switch drawdown, or sizing/P&L. Fail loud instead.

export class DataError extends Error {}

export function requireNumber(val: unknown, field: string): number {
  // Trim before the empty check (finding 14): Number(" ") === 0 too.
  if (val === null || val === undefined || (typeof val === "string" && val.trim() === "")) {
    throw new DataError(`expected numeric ${field}, got ${JSON.stringify(val)}`);
  }
  const n = Number(val);
  if (Number.isNaN(n)) {
    throw new DataError(`expected numeric ${field}, got ${JSON.stringify(val)}`);
  }
  return n;
}
