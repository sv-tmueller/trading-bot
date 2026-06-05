// Pure regime-filter logic. The entire trading decision lives in one function.
// 1:1 port of strategy/regime.py (Mebane Faber, 2007):
//   if SPY > SMA(200): LONG  (kill-switch flag cleared)
//   else:              CASH  (kill-switch flag preserved)
// I/O-free: all I/O happens in callers (Edge Functions, Plans 2-3).

export type State = "LONG" | "CASH";

export interface RegimeInput {
  spyClose: number;
  spySma200: number; // NaN acceptable (insufficient history) -> defensive CASH
  currentState: State;
  killSwitchActive: boolean;
}

export interface RegimeResult {
  targetState: State;
  killSwitchActive: boolean;
}

export function computeTargetState(input: RegimeInput): RegimeResult {
  const { spyClose, spySma200, currentState, killSwitchActive } = input;

  if (spyClose <= 0) {
    throw new Error(`spyClose must be > 0, got ${spyClose}`);
  }
  if (!Number.isNaN(spySma200) && spySma200 < 0) {
    throw new Error(`spySma200 must be >= 0 or NaN, got ${spySma200}`);
  }
  if (currentState !== "LONG" && currentState !== "CASH") {
    throw new Error(`currentState must be LONG or CASH, got ${currentState}`);
  }

  // Defensive: SMA200 unavailable -> CASH, preserve any kill-switch flag.
  if (Number.isNaN(spySma200)) {
    return { targetState: "CASH", killSwitchActive };
  }

  // Strictly greater than — exact equality is treated as bearish.
  const isBullish = spyClose > spySma200;

  if (isBullish) {
    return { targetState: "LONG", killSwitchActive: false }; // bullish clears the flag
  }

  // Bearish: stay in / move to CASH; preserve any existing flag.
  return { targetState: "CASH", killSwitchActive };
}
