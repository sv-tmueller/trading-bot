// Strategy/runtime config for the migrated bot. Ports the numeric range checks
// from config/settings.py. Alpaca/notify/panic secrets are read in their own
// modules (Plans 2-3) so this stays testable without broker credentials.
import { CONTEXT_MODES, type ContextMode } from "./candlestick.ts";

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
  return raw.trim();
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
  if (botTicker === "") {
    throw new Error("BOT_TICKER must be a non-empty ticker symbol");
  }

  const botBenchmark = strEnv("BOT_BENCHMARK", "SPY");
  if (botBenchmark === "") {
    throw new Error("BOT_BENCHMARK must be a non-empty ticker symbol");
  }

  return { regimeSmaDays, killSwitchDrawdownPct, killSwitchLookbackDays, botTicker, botBenchmark };
}

// #475 T1: hourly-check's §10 settings. Kept separate from getStrategyConfig()
// so daily-check/kill-switch (which read StrategyConfig) are byte-for-byte
// untouched.
export interface HourlyConfig {
  hourlyBotTicker: string;
  sizingRiskPct: number;
  sizingNotionalCapPct: number;
  hourlyBracketRMultiple: number;
  hourlyStopBufferPct: number;
  hourlyMinStopDistance: number;
  hourlyMaxEntriesPerDay: number;
  hourlyStalenessToleranceMin: number;
  hourlyContextMode: ContextMode;
  hourlyShortsEnabled: boolean;
  // Always `true` when this function returns at all -- getHourlyConfig()
  // throws rather than returning `false` (see the strict-reading note below).
  hourlyBotPaperOnly: true;
}

export function getHourlyConfig(): HourlyConfig {
  const hourlyBotTicker = strEnv("HOURLY_BOT_TICKER", "SPY");
  if (hourlyBotTicker === "") {
    throw new Error("HOURLY_BOT_TICKER must be a non-empty ticker symbol");
  }

  const sizingRiskPct = floatEnv("SIZING_RISK_PCT", 0.01);
  if (sizingRiskPct <= 0 || sizingRiskPct > 0.05) {
    throw new Error(`SIZING_RISK_PCT=${sizingRiskPct} outside safe bounds (0, 0.05]`);
  }

  const sizingNotionalCapPct = floatEnv("SIZING_NOTIONAL_CAP_PCT", 0.10);
  if (sizingNotionalCapPct <= 0 || sizingNotionalCapPct > 1.0) {
    throw new Error(
      `SIZING_NOTIONAL_CAP_PCT=${sizingNotionalCapPct} outside safe bounds (0, 1.0]`,
    );
  }

  // Fixed at 2 for v1 (spec §7); a change requires a spec revision, not a secret flip.
  const hourlyBracketRMultiple = floatEnv("HOURLY_BRACKET_R_MULTIPLE", 2);
  if (hourlyBracketRMultiple !== 2) {
    throw new Error(
      `HOURLY_BRACKET_R_MULTIPLE=${hourlyBracketRMultiple} must be exactly 2 for v1 (spec §7); ` +
        `changing the R multiple requires a spec revision`,
    );
  }

  const hourlyStopBufferPct = floatEnv("HOURLY_STOP_BUFFER_PCT", 0.05);
  if (hourlyStopBufferPct <= 0 || hourlyStopBufferPct > 0.5) {
    throw new Error(`HOURLY_STOP_BUFFER_PCT=${hourlyStopBufferPct} outside safe bounds (0, 0.5]`);
  }

  const hourlyMinStopDistance = floatEnv("HOURLY_MIN_STOP_DISTANCE", 0.05);
  if (hourlyMinStopDistance <= 0) {
    throw new Error(`HOURLY_MIN_STOP_DISTANCE=${hourlyMinStopDistance} must be > 0`);
  }

  const hourlyMaxEntriesPerDay = intEnv("HOURLY_MAX_ENTRIES_PER_DAY", 3);
  if (hourlyMaxEntriesPerDay < 1 || hourlyMaxEntriesPerDay > 10) {
    throw new Error(
      `HOURLY_MAX_ENTRIES_PER_DAY=${hourlyMaxEntriesPerDay} outside safe bounds [1, 10]`,
    );
  }

  const hourlyStalenessToleranceMin = intEnv("HOURLY_STALENESS_TOLERANCE_MIN", 10);
  if (hourlyStalenessToleranceMin < 1 || hourlyStalenessToleranceMin > 60) {
    throw new Error(
      `HOURLY_STALENESS_TOLERANCE_MIN=${hourlyStalenessToleranceMin} outside safe bounds [1, 60]`,
    );
  }

  const hourlyContextModeRaw = strEnv("HOURLY_CONTEXT_MODE", "none");
  if (!CONTEXT_MODES.includes(hourlyContextModeRaw as ContextMode)) {
    throw new Error(
      `HOURLY_CONTEXT_MODE must be one of ${JSON.stringify(CONTEXT_MODES)}, got ${
        JSON.stringify(hourlyContextModeRaw)
      }`,
    );
  }
  const hourlyContextMode = hourlyContextModeRaw as ContextMode;

  // Fail-closed (#493): the spec's §10 table listed a default of `true`, which
  // let a lost or never-set secret arm the short-side path -- the opposite
  // direction from what a safety flag owes. Absent now means shorts off, so
  // enabling them takes an explicit "true" the same way HOURLY_BOT_PAPER_ONLY
  // does. A value that is present but unparseable still throws.
  const hourlyShortsEnabledRaw = (Deno.env.get("HOURLY_SHORTS_ENABLED") ?? "false").trim()
    .toLowerCase();
  if (hourlyShortsEnabledRaw !== "true" && hourlyShortsEnabledRaw !== "false") {
    throw new Error(
      `HOURLY_SHORTS_ENABLED must be "true" or "false", got ${
        JSON.stringify(hourlyShortsEnabledRaw)
      }`,
    );
  }
  const hourlyShortsEnabled = hourlyShortsEnabledRaw === "true";

  // Strict reading (derived decision, #475 T1): §10's table lists a default of
  // `true` alongside "throws if unset or false" -- an internally tense pair.
  // Resolved fail-closed: the mechanical paper-only gate is not a normal
  // tunable, so an operator who has not explicitly set it to "true" has not
  // affirmed the paper-only contract, and this must throw rather than
  // silently defaulting to on.
  const hourlyBotPaperOnlyRaw = Deno.env.get("HOURLY_BOT_PAPER_ONLY");
  if ((hourlyBotPaperOnlyRaw ?? "").trim().toLowerCase() !== "true") {
    throw new Error(
      `HOURLY_BOT_PAPER_ONLY must be explicitly set to "true" (got ${
        JSON.stringify(hourlyBotPaperOnlyRaw ?? null)
      }) -- this bot is paper-only by mechanical guard (CLAUDE.md, §8.3)`,
    );
  }

  return {
    hourlyBotTicker,
    sizingRiskPct,
    sizingNotionalCapPct,
    hourlyBracketRMultiple,
    hourlyStopBufferPct,
    hourlyMinStopDistance,
    hourlyMaxEntriesPerDay,
    hourlyStalenessToleranceMin,
    hourlyContextMode,
    hourlyShortsEnabled,
    hourlyBotPaperOnly: true,
  };
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
    dataFeed,
  };
}

// Discord incoming-webhook URL (#362 — direct-to-Discord, no n8n middleman).
// Optional: unset/blank means notify() silently skips (see notifications.ts).
export function getNotifyWebhookUrl(): string {
  return Deno.env.get("NOTIFY_WEBHOOK_URL")?.trim() ?? "";
}

// x-status-token header value for the read-only status Edge Function (#354).
// Unlike the strategy knobs above, a secret has no sensible default: unset or
// blank MUST throw so the function fails to start rather than silently
// serving with no auth gate.
export function getStatusToken(): string {
  const raw = Deno.env.get("STATUS_TOKEN")?.trim() ?? "";
  if (raw === "") {
    throw new Error("STATUS_TOKEN must be set to a non-empty value");
  }
  return raw;
}

// Ported #168 guard. Read fresh every call so tests can flip it mid-test.
export function isClaudeAgentNoBroker(): boolean {
  const v = Deno.env.get("CLAUDE_AGENT_NO_BROKER")?.toLowerCase() ?? "";
  return v === "1" || v === "true" || v === "yes";
}
