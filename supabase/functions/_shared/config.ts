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

export interface AlpacaConfig {
  apiKeyId: string;
  apiSecretKey: string;
  paper: boolean;
  tradingBaseUrl: string;
  dataBaseUrl: string;
  dataFeed: "iex" | "sip";
}

export function getAlpacaConfig(): AlpacaConfig {
  const apiKeyId = Deno.env.get("ALPACA_API_KEY")?.trim() ?? "";
  const apiSecretKey = Deno.env.get("ALPACA_SECRET_KEY")?.trim() ?? "";
  if (apiKeyId === "" || apiSecretKey === "") {
    throw new Error("ALPACA_API_KEY and ALPACA_SECRET_KEY must both be set");
  }
  // Default to PAPER. Validate explicitly so a typo (e.g. ALPACA_PAPER=0) fails
  // loud instead of silently staying on paper. Only "false" selects live.
  const paperRaw = (Deno.env.get("ALPACA_PAPER") ?? "true").trim().toLowerCase();
  if (paperRaw !== "true" && paperRaw !== "false") {
    throw new Error(`ALPACA_PAPER must be "true" or "false", got ${JSON.stringify(paperRaw)}`);
  }
  const paper = paperRaw !== "false";
  const dataFeed = (Deno.env.get("ALPACA_DATA_FEED") ?? "iex").trim().toLowerCase();
  if (dataFeed !== "iex" && dataFeed !== "sip") {
    throw new Error(`ALPACA_DATA_FEED must be "iex" or "sip", got ${JSON.stringify(dataFeed)}`);
  }
  return {
    apiKeyId,
    apiSecretKey,
    paper,
    tradingBaseUrl: paper ? "https://paper-api.alpaca.markets" : "https://api.alpaca.markets",
    dataBaseUrl: "https://data.alpaca.markets",
    dataFeed: dataFeed as "iex" | "sip",
  };
}

export function getN8nWebhookUrl(): string {
  return Deno.env.get("N8N_WEBHOOK_URL")?.trim() ?? "";
}

// Ported #168 guard. Read fresh every call so tests can flip it mid-test.
export function isClaudeAgentNoBroker(): boolean {
  const v = Deno.env.get("CLAUDE_AGENT_NO_BROKER")?.toLowerCase() ?? "";
  return v === "1" || v === "true" || v === "yes";
}
