// Shared numeric boundary for values crossing between this bot and external
// APIs (Alpaca trading + market data). It covers both directions:
//
// Inbound (requireNumber): Number(null) === 0 and Number("") === 0, so a
// missing price/qty would silently become 0 and corrupt the SMA200 signal, the
// kill-switch drawdown, or sizing/P&L. Non-finite values (Infinity from a bad
// payload) are just as corrupting, so require a finite number. Fail loud
// instead.
//
// Outbound (roundToCents): a computed price is a raw float, and Alpaca rejects
// any equity price above $1 that is not a $0.01 multiple (#494). Quantize
// before it reaches the wire.

export class DataError extends Error {
  override name = "DataError";
}

export function requireNumber(val: unknown, field: string): number {
  // Trim before the empty check (finding 14): Number(" ") === 0 too.
  if (val === null || val === undefined || (typeof val === "string" && val.trim() === "")) {
    throw new DataError(`expected numeric ${field}, got ${JSON.stringify(val)}`);
  }
  const n = Number(val);
  if (!Number.isFinite(n)) {
    throw new DataError(`expected finite numeric ${field}, got ${JSON.stringify(val)}`);
  }
  return n;
}

/**
 * Quantizes an outbound price to whole cents (#494).
 *
 * The contract is a SERIALIZATION contract, because the defect it fixes is a
 * serialization defect: `String(roundToCents(v))` renders at most two decimals
 * with no float artifact. A numeric-only contract would still admit
 * 745.05000000000007, which Alpaca rejects with a 422 the same way it rejected
 * the raw 745.0495000000001.
 *
 * Nearest cent, no directional bias: expected shift 0, max half a cent, which
 * is far below the slippage floor of the market entry leg. Tie direction is
 * implementation-defined and pinned by test, not promised here.
 *
 * Takes a number, not a string: this is the outbound direction, so the value
 * has already crossed the boundary via requireNumber. A non-number or
 * non-finite input is a bug upstream, so throw rather than degrade to 0.
 */
export function roundToCents(value: number, field = "value"): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DataError(`expected finite numeric ${field} to quantize, got ${String(value)}`);
  }
  return Math.round(value * 100) / 100;
}
