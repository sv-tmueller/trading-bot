// Shared numeric boundary for values crossing between this bot and external
// APIs (Alpaca trading + market data). It covers both directions:
//
// Inbound (requireNumber): Number(null) === 0 and Number("") === 0, so a
// missing price/qty would silently become 0 and corrupt the SMA200 signal, the
// kill-switch drawdown, or sizing/P&L. Non-finite values (Infinity from a bad
// payload) are just as corrupting, so require a finite number. Fail loud
// instead.
//
// Outbound (roundToCents): quantize a computed price before it reaches the
// wire. Rationale in that function's own doc comment.

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
 * Quantizes an outbound price to whole cents. Canonical rationale for #494;
 * every other site that quantizes or validates a price points here.
 *
 * Alpaca rejects any equity price above $1 that is not a $0.01 multiple (HTTP
 * 422, code 42210000), which blocked every entry the hourly bot attempted on
 * 2026-07-30. The contract is a SERIALIZATION contract, because the defect is
 * a serialization defect: `String(roundToCents(v))` renders at most two
 * decimals with no float artifact, for any finite `v` below 1e21 (every price
 * magnitude this bot can produce). Above that, `String` switches to exponent
 * notation and the claim does not hold; callers sending to the wire validate
 * the serialized form separately. Precision loss at large magnitude yields
 * FEWER decimals, never more, so it is not a failure mode here.
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
