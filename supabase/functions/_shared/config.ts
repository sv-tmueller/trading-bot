// Strategy/runtime config for the migrated bot. Ports the numeric range checks
// from config/settings.py. Alpaca/n8n/panic secrets are read in their own
// modules (Plans 2-3) so this stays testable without broker credentials.

export interface StrategyConfig {
  regimeSmaDays: number;
  killSwitchDrawdownPct: number;
  killSwitchLookbackDays: number;
  botTicker: string;
  botBenchmark: string;
}

function intEnv(name: string, def: number): number {
  const raw = Deno.env.get(name);
  if (raw === undefined || raw.trim() === "") return def;
  const n = Number(raw);
  if (!Number.isInteger(n)) {
    throw new Error(`${name}=${raw} is not an integer`);
  }
  return n;
}

function floatEnv(name: string, def: number): number {
  const raw = Deno.env.get(name);
  if (raw === undefined || raw.trim() === "") return def;
  const n = Number(raw);
  if (Number.isNaN(n)) {
    throw new Error(`${name}=${raw} is not a number`);
  }
  return n;
}

function strEnv(name: string, def: string): string {
  const raw = Deno.env.get(name);
  if (raw === undefined) return def;
  return raw;
}

export function getStrategyConfig(): StrategyConfig {
  const regimeSmaDays = intEnv("REGIME_SMA_DAYS", 200);
  if (regimeSmaDays < 20 || regimeSmaDays > 500) {
    throw new Error(`REGIME_SMA_DAYS=${regimeSmaDays} outside safe bounds [20, 500]`);
  }

  const killSwitchDrawdownPct = floatEnv("KILL_SWITCH_DRAWDOWN_PCT", 0.25);
  if (killSwitchDrawdownPct < 0.05 || killSwitchDrawdownPct > 0.50) {
    throw new Error(
      `KILL_SWITCH_DRAWDOWN_PCT=${killSwitchDrawdownPct} outside safe bounds [0.05, 0.50]`,
    );
  }

  const killSwitchLookbackDays = intEnv("KILL_SWITCH_LOOKBACK_DAYS", 30);
  if (killSwitchLookbackDays < 5 || killSwitchLookbackDays > 252) {
    throw new Error(
      `KILL_SWITCH_LOOKBACK_DAYS=${killSwitchLookbackDays} outside safe bounds [5, 252]`,
    );
  }

  // Default is UPRO, not settings.py's WSPL.DE: Alpaca is US-listed-only (spec §2).
  const botTicker = strEnv("BOT_TICKER", "UPRO");
  if (botTicker.trim() === "") {
    throw new Error("BOT_TICKER must be a non-empty ticker symbol");
  }

  const botBenchmark = strEnv("BOT_BENCHMARK", "SPY");
  if (botBenchmark.trim() === "") {
    throw new Error("BOT_BENCHMARK must be a non-empty ticker symbol");
  }

  return { regimeSmaDays, killSwitchDrawdownPct, killSwitchLookbackDays, botTicker, botBenchmark };
}
