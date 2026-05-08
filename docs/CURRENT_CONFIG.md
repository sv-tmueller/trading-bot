# Current Configuration

(Last reviewed: 2026-05-08 for the rules-engine pivot.)

## Schedule (UTC)

- `30 22 * * 1-5` — `daily_check.py` (5h after NYSE close, 1.5h after yfinance daily bar publishes)
- `5 14-21 * * 1-5` — `monitor/kill_switch.py` (hourly during US market hours)

## Active env vars

| Var | Default | What it does |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | TWS / IB Gateway host |
| `IBKR_PORT` | `4002` | Paper-trading port. Set to `4001` for live. |
| `IBKR_CLIENT_ID` | `1` | Connection client ID |
| `BOT_TICKER` | `WSPL.DE` | The instrument the bot trades (3x leveraged ETF) |
| `BOT_BENCHMARK` | `SPY` | The instrument used for the regime decision |
| `REGIME_SMA_DAYS` | `200` | SMA window for the regime decision |
| `KILL_SWITCH_DRAWDOWN_PCT` | `0.25` | Drawdown from 30-day high that triggers the kill switch |
| `KILL_SWITCH_LOOKBACK_DAYS` | `30` | Trading-day window for the rolling high |
| `N8N_WEBHOOK_URL` | `http://localhost:5678/webhook/trading-bot-notify` | Discord notification webhook |
| `TRADING_PAUSED` | `false` | Operational kill switch — halts new entries |
| `DAILY_CHECK_DRY_RUN` | `false` | Soak mode — skips all broker writes |

## Operational state

- Cron status: <unknown — operator-controlled>
- Bot status: <unknown — operator-controlled>
