// Shared numeric-parsing guard for values coming off external APIs (Alpaca
// trading + market data). Number(null) === 0 and Number("") === 0, so a missing
// price/qty would silently become 0 and corrupt the SMA200 signal, the
// kill-switch drawdown, or sizing/P&L. Non-finite values (Infinity from a bad
// payload) are just as corrupting, so require a finite number. Fail loud instead.

export class DataError extends Error {
  override name = "DataError";
}

export function requireNumber(val: unknown, field: string): number {
  if (val === null || val === undefined || val === "") {
    throw new DataError(`expected numeric ${field}, got ${JSON.stringify(val)}`);
  }
  const n = Number(val);
  if (!Number.isFinite(n)) {
    throw new DataError(`expected finite numeric ${field}, got ${JSON.stringify(val)}`);
  }
  return n;
}
