# Bug Fix Plan B — Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden operational reliability: fix data-integrity risks, connection leaks, duplicate orders, and reduce unnecessary API calls.

**Architecture:** Seven independent tasks touching different files. Tasks 1 and 4 both modify `agents/team_leader.py` — do them sequentially in order. All others are fully independent.

**Tech Stack:** Python 3.9, SQLite, Alpaca SDK, pytest + pytest-mock

**Closes:** GitHub issues #6, #7, #8, #13, #15, #16, #21, #22

---

## File map

| File | Tasks |
|---|---|
| `tools/broker.py` | Task 1 — return fill price from `place_market_order` |
| `agents/team_leader.py` | Task 1 — price before broker; Task 4 — idempotency guard |
| `main.py` | Task 2 — `finally` connection close |
| `config/settings.py` | Task 3 — env-configurable settings |
| `.env.example` | Task 3 — document new vars |
| `tools/database.py` | Task 4 — `has_open_trade()` |
| `tests/test_agents/test_base_agent.py` | Task 5 — tool-use loop coverage |
| `agents/market_intelligence.py` | Task 6 — fetch prices for open positions only |
| `scripts/cron_setup.sh` | Task 7 — move on-the-bell monitor check |
| `README.md` | Task 7 — update cron table |
| `tests/test_tools_broker.py` | Task 1 — update for new return type |
| `tests/test_main.py` | Task 2 — connection close on exception |
| `tests/test_config.py` | Task 3 — validation tests |
| `tests/test_tools_database.py` | Task 4 — `has_open_trade` tests |
| `tests/test_agents/test_market_intelligence.py` | Task 6 — price fetch scope test |

---

## Task 1: Price before broker + fill price (#21, #8)

**Files:**
- Modify: `tools/broker.py:22-33`
- Modify: `agents/team_leader.py:82-119`
- Test: `tests/test_tools_broker.py`
- Test: `tests/test_agents/test_team_leader.py`

**Why combined:** Both #21 and #8 touch `place_order` in `TeamLeaderAgent`. #21 requires fetching the price _before_ calling the broker in both `place_order` and `close_position`. #8 requires using the Alpaca fill price from the order object instead of a post-order quote. Doing them together avoids two conflicting edits to the same closure.

**Context:** `place_market_order` currently returns `str(order.id)`. Change it to return a dict `{"order_id": ..., "fill_price": ...}` where `fill_price` is `float(order.filled_avg_price)` if set, else `None`. In `place_order`, use the fill price if available; fall back to the pre-fetched quote if the order isn't filled yet (paper trading is fast but not instant). In `close_position`, just reorder so `get_current_price` is called before `broker_close_position`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools_broker.py`:

```python
def test_place_market_order_returns_fill_price():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-123"
    mock_order.filled_avg_price = "152.50"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    assert result["order_id"] == "order-123"
    assert result["fill_price"] == pytest.approx(152.50)


def test_place_market_order_fill_price_none_when_not_filled():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_order.filled_avg_price = None
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    assert result["order_id"] == "order-456"
    assert result["fill_price"] is None
```

Run: `python3 -m pytest tests/test_tools_broker.py::test_place_market_order_returns_fill_price tests/test_tools_broker.py::test_place_market_order_fill_price_none_when_not_filled -v`
Expected: FAIL — currently returns a string, not a dict.

- [ ] **Step 2: Update `place_market_order` in `tools/broker.py`**

Replace the current function (lines 22–33):

```python
def place_market_order(ticker: str, shares: int, side: str) -> dict:
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid order side: {side!r}. Must be 'buy' or 'sell'.")
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=order_side,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(request)
    fill_price = float(order.filled_avg_price) if order.filled_avg_price is not None else None
    return {"order_id": str(order.id), "fill_price": fill_price}
```

- [ ] **Step 3: Update existing broker tests that assumed a string return**

In `tests/test_tools_broker.py`, update `test_place_market_order_buy` and `test_place_market_order_sell`. They currently do `assert result == "order-123"`. Update them to set `filled_avg_price` on the mock and assert the dict:

```python
def test_place_market_order_buy():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-123"
    mock_order.filled_avg_price = "150.00"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "buy")

    mock_client.submit_order.assert_called_once()
    assert result["order_id"] == "order-123"
    assert result["fill_price"] == pytest.approx(150.00)


def test_place_market_order_sell():
    mock_client = MagicMock()
    mock_order = MagicMock()
    mock_order.id = "order-456"
    mock_order.filled_avg_price = "148.50"
    mock_client.submit_order.return_value = mock_order

    with patch("tools.broker.get_trading_client", return_value=mock_client):
        result = place_market_order("AMD", 100, "sell")

    assert result["order_id"] == "order-456"
```

- [ ] **Step 4: Run broker tests**

```bash
python3 -m pytest tests/test_tools_broker.py -v
```

Expected: all pass.

- [ ] **Step 5: Update `place_order` and `close_position` in `agents/team_leader.py`**

Replace both closures in `_get_tool_functions()`:

```python
        def place_order(ticker: str, shares: int, side: str) -> dict:
            if side == "buy":
                price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk
            order_result = place_market_order(ticker, shares, side)
            order_id = order_result["order_id"]
            if side == "buy":
                entry_price = order_result["fill_price"] or price  # use fill; fall back to quote
                insert_trade(conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": entry_price,
                    "shares": shares,
                    "stop_loss": pending_stops.get(ticker, price * 0.97),
                    "take_profit": pending_targets.get(ticker, price * 1.06),
                })
            return {"order_id": order_id, "status": "submitted"}

        def close_position(ticker: str, reason: str = "manual") -> dict:
            price = get_current_price(ticker)   # fetch BEFORE broker — no ghost risk
            order_id = broker_close_position(ticker)
            today = date.today().isoformat()
            open_trades = get_open_trades(conn)
            trade = next((t for t in open_trades if t["ticker"] == ticker), None)
            if trade is not None:
                entry_price = trade["entry_price"]
                stop_distance = entry_price - trade["stop_loss"]
                pnl_dollars = (price - entry_price) * trade["shares"]
                r_multiple = (price - entry_price) / stop_distance if stop_distance != 0 else 0.0
                entry_date = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
                today_date = datetime.strptime(today, "%Y-%m-%d").date()
                hold_days = (today_date - entry_date).days
                close_trade(conn, trade["id"], {
                    "exit_date": today,
                    "exit_price": price,
                    "exit_reason": reason,
                    "pnl_dollars": round(pnl_dollars, 2),
                    "pnl_pct": round(pnl_dollars / (entry_price * trade["shares"]), 4),
                    "hold_days": hold_days,
                    "r_multiple": round(r_multiple, 3),
                })
            return {"order_id": order_id, "status": "closed"}
```

- [ ] **Step 6: Write a test verifying price is fetched before the broker close**

Add to `tests/test_agents/test_team_leader.py`:

```python
def test_close_position_fetches_price_before_broker(db_conn):
    """get_current_price must be called before broker_close_position to prevent ghost positions."""
    from tools.database import insert_trade
    from datetime import date

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": date.today().isoformat(),
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 140.0,
        "take_profit": 170.0,
    })

    call_order = []

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_001"
    tool_use_block.name = "close_position"
    tool_use_block.input = {"ticker": "AMD", "reason": "manual"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response('{"decisions": [], "summary": "done"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    def mock_price(ticker):
        call_order.append("price")
        return 155.0

    def mock_broker_close(ticker):
        call_order.append("broker")
        mock_order = MagicMock()
        mock_order.id = "order-999"
        return str(mock_order.id)

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", side_effect=mock_price), \
         patch("tools.broker.close_position", side_effect=mock_broker_close):
        agent = TeamLeaderAgent()
        agent.run("Close AMD", conn=db_conn)

    assert call_order.index("price") < call_order.index("broker"), \
        "get_current_price must be called before broker_close_position"
```

- [ ] **Step 7: Run team leader tests**

```bash
python3 -m pytest tests/test_agents/test_team_leader.py -v
```

Expected: all pass.

- [ ] **Step 8: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add tools/broker.py agents/team_leader.py tests/test_tools_broker.py tests/test_agents/test_team_leader.py
git commit -m "fix: fetch price before broker call; use fill price for entry — closes #21 #8"
```

---

## Task 2: Fix DB connection leak (#22)

**Files:**
- Modify: `main.py` — `run_morning_scan` and `run_position_monitor`
- Test: `tests/test_main.py`

**Context:** `conn = get_db()` is assigned inside the `try` block. If an exception is raised after that point, `conn.close()` is never called. Fix: initialise `conn = None` before the `try`, remove the explicit `conn.close()` calls inside `try` (including the ones before early `return` statements), and add a `finally` block that closes only if `conn is not None`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_main.py`:

```python
def test_run_morning_scan_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when an agent raises."""
    mock_conn = MagicMock()
    mock_conn.row_factory = None

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error"):
        MockMI.return_value.run.side_effect = RuntimeError("boom")
        from main import run_morning_scan
        run_morning_scan()

    mock_conn.close.assert_called_once()


def test_run_position_monitor_closes_conn_on_exception(db_conn):
    """DB connection must be closed even when run_monitor raises."""
    mock_conn = MagicMock()

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=mock_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("boom")), \
         patch("main.notify_error"):
        from main import run_position_monitor
        run_position_monitor()

    mock_conn.close.assert_called_once()
```

Run: `python3 -m pytest tests/test_main.py::test_run_morning_scan_closes_conn_on_exception tests/test_main.py::test_run_position_monitor_closes_conn_on_exception -v`
Expected: FAIL — `close()` is never called on exception.

- [ ] **Step 2: Fix `run_morning_scan` in `main.py`**

Replace the current function with:

```python
def run_morning_scan():
    if not is_trading_day():
        print("Not a trading day. Exiting.")
        return

    conn = None
    try:
        print(f"=== Morning scan — {date.today()} ===")
        conn = get_db()

        print("Running Market Intelligence Agent...")
        mi_agent = MarketIntelligenceAgent()
        market_briefing = mi_agent.run("Scan the watchlist and assess open positions.", conn=conn)
        print(f"Market context: {market_briefing.get('market_context')}")

        print("Running Strategy Agent...")
        strategy_agent = StrategyAgent()
        candidates = strategy_agent.run(json.dumps(market_briefing), conn=conn)
        print(f"Candidates found: {len(candidates.get('candidates', []))}")

        if not candidates.get("candidates"):
            print(f"No trade candidates: {candidates.get('no_trade_reason')}")
            costs = get_daily_token_costs(conn, date.today().isoformat())
            print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
            notify_no_candidates(
                date.today().isoformat(),
                tldr=candidates.get("tldr", "conditions not met"),
                tickers_to_watch=candidates.get("tickers_to_watch", []),
                cost_usd=costs["cost_usd"],
            )
            return

        print("Running Risk Review Agent...")
        risk_agent = RiskReviewAgent()
        reviewed = risk_agent.run(json.dumps(candidates), conn=conn)
        print(f"Approved: {len(reviewed.get('approved', []))} | Rejected: {len(reviewed.get('rejected', []))}")

        if not reviewed.get("approved"):
            print("No trades approved by risk review.")
            costs = get_daily_token_costs(conn, date.today().isoformat())
            print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
            notify_no_approved(date.today().isoformat(), costs["cost_usd"])
            return

        print("Running Team Leader Agent...")
        pending_stops = {t["ticker"]: t["stop_loss"] for t in reviewed["approved"]}
        pending_targets = {t["ticker"]: t["take_profit"] for t in reviewed["approved"]}
        leader_agent = TeamLeaderAgent()
        decisions = leader_agent.run(
            json.dumps(reviewed),
            conn=conn,
            pending_stops=pending_stops,
            pending_targets=pending_targets,
        )
        print(f"Session summary: {decisions.get('summary')}")

        costs = get_daily_token_costs(conn, date.today().isoformat())
        print(f"Token usage — input: {costs['input_tokens']:,} | output: {costs['output_tokens']:,} | cost: ${costs['cost_usd']:.4f}")
        notify_scan_complete(
            date=date.today().isoformat(),
            market_context=market_briefing.get("market_context", "unknown"),
            tldr=candidates.get("tldr", ""),
            approved=len(reviewed.get("approved", [])),
            rejected=len(reviewed.get("rejected", [])),
            decisions=decisions.get("decisions", []),
            cost_usd=costs["cost_usd"],
        )

    except Exception as e:
        print(f"SCAN ERROR: {e}")
        notify_error("morning_scan", traceback.format_exc())
    finally:
        if conn is not None:
            conn.close()
```

- [ ] **Step 3: Fix `run_position_monitor` in `main.py`**

```python
def run_position_monitor():
    if not is_trading_day():
        return
    conn = None
    try:
        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        print(f"=== Position monitor — {date.today()} {now} ===")
        conn = get_db()
        actions = run_monitor(conn)
        closed = [a for a in actions if a.action == "close"]
        print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
        notify_monitor(date.today().isoformat(), now, len(actions), closed)
    except Exception as e:
        print(f"MONITOR ERROR: {e}")
        notify_error("position_monitor", traceback.format_exc())
    finally:
        if conn is not None:
            conn.close()
```

- [ ] **Step 4: Run all main tests**

```bash
python3 -m pytest tests/test_main.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "fix: close DB connection in finally block — closes #22"
```

---

## Task 3: Env-configurable settings (#6)

**Files:**
- Modify: `config/settings.py:36-40`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Context:** `MAX_HOLD_DAYS`, `RR_RATIO_MIN`, and `MAX_PORTFOLIO_EXPOSURE` are currently hardcoded constants. They need `os.getenv()` calls with validation, consistent with how `RISK_PER_TRADE` and `MAX_POSITIONS` are handled.

- [ ] **Step 1: Read `tests/test_config.py` to understand the existing test pattern**

```bash
cat tests/test_config.py
```

- [ ] **Step 2: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_max_hold_days_env_override(monkeypatch):
    monkeypatch.setenv("MAX_HOLD_DAYS", "10")
    import importlib, config.settings as s
    importlib.reload(s)
    assert s.MAX_HOLD_DAYS == 10


def test_rr_ratio_min_env_override(monkeypatch):
    monkeypatch.setenv("RR_RATIO_MIN", "2.5")
    import importlib, config.settings as s
    importlib.reload(s)
    assert s.RR_RATIO_MIN == pytest.approx(2.5)


def test_max_portfolio_exposure_env_override(monkeypatch):
    monkeypatch.setenv("MAX_PORTFOLIO_EXPOSURE", "0.30")
    import importlib, config.settings as s
    importlib.reload(s)
    assert s.MAX_PORTFOLIO_EXPOSURE == pytest.approx(0.30)


def test_max_hold_days_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("MAX_HOLD_DAYS", "0")
    import importlib, config.settings as s
    with pytest.raises(ValueError, match="MAX_HOLD_DAYS"):
        importlib.reload(s)


def test_rr_ratio_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("RR_RATIO_MIN", "0.5")
    import importlib, config.settings as s
    with pytest.raises(ValueError, match="RR_RATIO_MIN"):
        importlib.reload(s)


def test_max_portfolio_exposure_out_of_range_raises(monkeypatch):
    monkeypatch.setenv("MAX_PORTFOLIO_EXPOSURE", "0.99")
    import importlib, config.settings as s
    with pytest.raises(ValueError, match="MAX_PORTFOLIO_EXPOSURE"):
        importlib.reload(s)
```

Run: `python3 -m pytest tests/test_config.py -k "override or out_of_range" -v`
Expected: FAIL — settings are hardcoded, `os.getenv` is not called.

- [ ] **Step 3: Update `config/settings.py`**

Replace the four hardcoded lines (around lines 36–39):

```python
MAX_PORTFOLIO_EXPOSURE = 0.20
DAILY_DRAWDOWN_LIMIT = 0.03
MAX_HOLD_DAYS = 5
RR_RATIO_MIN = 2.0
```

With:

```python
MAX_PORTFOLIO_EXPOSURE = float(os.getenv("MAX_PORTFOLIO_EXPOSURE", "0.20"))
if not 0.05 <= MAX_PORTFOLIO_EXPOSURE <= 0.50:
    raise ValueError(f"MAX_PORTFOLIO_EXPOSURE={MAX_PORTFOLIO_EXPOSURE} outside safe bounds [0.05, 0.50]")

DAILY_DRAWDOWN_LIMIT = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.03"))

MAX_HOLD_DAYS = int(os.getenv("MAX_HOLD_DAYS", "5"))
if not 1 <= MAX_HOLD_DAYS <= 30:
    raise ValueError(f"MAX_HOLD_DAYS={MAX_HOLD_DAYS} outside safe bounds [1, 30]")

RR_RATIO_MIN = float(os.getenv("RR_RATIO_MIN", "2.0"))
if not 1.0 <= RR_RATIO_MIN <= 5.0:
    raise ValueError(f"RR_RATIO_MIN={RR_RATIO_MIN} outside safe bounds [1.0, 5.0]")
```

- [ ] **Step 4: Update `.env.example`**

Add after the `MAX_POSITIONS` line:

```env
MAX_HOLD_DAYS=5
RR_RATIO_MIN=2.0
MAX_PORTFOLIO_EXPOSURE=0.20
```

- [ ] **Step 5: Run config tests**

```bash
python3 -m pytest tests/test_config.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add config/settings.py .env.example tests/test_config.py
git commit -m "feat: make MAX_HOLD_DAYS, RR_RATIO_MIN, MAX_PORTFOLIO_EXPOSURE env-configurable — closes #6"
```

---

## Task 4: Idempotency guard — prevent duplicate orders (#7)

**Files:**
- Modify: `tools/database.py`
- Modify: `agents/team_leader.py:82-94`
- Test: `tests/test_tools_database.py`
- Test: `tests/test_agents/test_team_leader.py`

**Context:** If `run_morning_scan` is triggered twice in the same day (manual re-run, cron glitch), the Team Leader will attempt to place the same order twice. Fix: add `has_open_trade(conn, ticker)` to `tools/database.py` and check it before calling `insert_trade` in `place_order`.

**Important:** `agents/team_leader.py` was modified in Task 1. Read the current file before editing.

- [ ] **Step 1: Write failing test for `has_open_trade`**

Add to `tests/test_tools_database.py`:

```python
def test_has_open_trade_true_when_open(db_conn):
    from tools.database import insert_trade, has_open_trade
    from datetime import date
    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": date.today().isoformat(),
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 140.0,
        "take_profit": 170.0,
    })
    assert has_open_trade(db_conn, "AMD") is True


def test_has_open_trade_false_when_no_trade(db_conn):
    from tools.database import has_open_trade
    assert has_open_trade(db_conn, "AMD") is False


def test_has_open_trade_false_after_close(db_conn):
    from tools.database import insert_trade, close_trade, has_open_trade
    from datetime import date
    trade_id = insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": date.today().isoformat(),
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 140.0,
        "take_profit": 170.0,
    })
    close_trade(db_conn, trade_id, {
        "exit_date": date.today().isoformat(),
        "exit_price": 160.0,
        "exit_reason": "take_profit",
        "pnl_dollars": 1000.0,
        "pnl_pct": 0.0667,
        "hold_days": 3,
        "r_multiple": 1.5,
    })
    assert has_open_trade(db_conn, "AMD") is False
```

Run: `python3 -m pytest tests/test_tools_database.py -k "has_open_trade" -v`
Expected: FAIL — `has_open_trade` does not exist yet.

- [ ] **Step 2: Add `has_open_trade` to `tools/database.py`**

Add after `get_open_trades`:

```python
def has_open_trade(conn: sqlite3.Connection, ticker: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trades WHERE ticker = ? AND exit_date IS NULL",
        (ticker,),
    ).fetchone()
    return row is not None
```

- [ ] **Step 3: Run database tests**

```bash
python3 -m pytest tests/test_tools_database.py -v
```

Expected: all pass.

- [ ] **Step 4: Write failing test for idempotency in TeamLeaderAgent**

Add to `tests/test_agents/test_team_leader.py`:

```python
def test_place_order_skips_when_position_already_open(db_conn):
    """If a ticker already has an open trade, place_order must not insert a duplicate."""
    from tools.database import insert_trade
    from datetime import date

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": date.today().isoformat(),
        "entry_price": 148.0,
        "shares": 50,
        "stop_loss": 140.0,
        "take_profit": 168.0,
    })

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_002"
    tool_use_block.name = "place_order"
    tool_use_block.input = {"ticker": "AMD", "shares": 100, "side": "buy"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response('{"decisions": [], "summary": "skipped"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=152.0), \
         patch("tools.broker.place_market_order") as mock_place:
        agent = TeamLeaderAgent()
        agent.run("Buy AMD", conn=db_conn)

    mock_place.assert_not_called()
    rows = db_conn.execute("SELECT COUNT(*) FROM trades WHERE ticker = 'AMD'").fetchone()
    assert rows[0] == 1  # only the original — no duplicate inserted
```

Run: `python3 -m pytest tests/test_agents/test_team_leader.py::test_place_order_skips_when_position_already_open -v`
Expected: FAIL — currently places a second order regardless.

- [ ] **Step 5: Update `place_order` closure in `agents/team_leader.py`**

Add `has_open_trade` to the deferred import in `_get_tool_functions`:

```python
        from tools.database import insert_trade, get_open_trades, close_trade, has_open_trade
```

Then add the guard at the start of `place_order` (after the price fetch, before the broker call):

```python
        def place_order(ticker: str, shares: int, side: str) -> dict:
            if side == "buy":
                price = get_current_price(ticker)
                if has_open_trade(conn, ticker):
                    return {"order_id": None, "status": "skipped — position already open"}
            order_result = place_market_order(ticker, shares, side)
            order_id = order_result["order_id"]
            if side == "buy":
                entry_price = order_result["fill_price"] or price
                insert_trade(conn, {
                    "ticker": ticker,
                    "entry_date": date.today().isoformat(),
                    "entry_price": entry_price,
                    "shares": shares,
                    "stop_loss": pending_stops.get(ticker, price * 0.97),
                    "take_profit": pending_targets.get(ticker, price * 1.06),
                })
            return {"order_id": order_id, "status": "submitted"}
```

- [ ] **Step 6: Run team leader tests**

```bash
python3 -m pytest tests/test_agents/test_team_leader.py -v
```

Expected: all pass.

- [ ] **Step 7: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add tools/database.py agents/team_leader.py tests/test_tools_database.py tests/test_agents/test_team_leader.py
git commit -m "feat: add idempotency guard to prevent duplicate orders — closes #7"
```

---

## Task 5: BaseAgent tool-use loop test coverage (#15)

**Files:**
- Modify: `tests/test_agents/test_base_agent.py`

**Context:** The tool-use loop in `BaseAgent.run()` (the `while response.stop_reason == "tool_use"` block) has zero test coverage. The loop: accumulates tokens across turns, routes tool calls by `fn.__name__`, appends assistant + tool_result messages, and calls `messages.create` again. Need one test that exercises two turns (tool_use → end_turn) and verifies token accumulation and tool dispatch.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agents/test_base_agent.py`:

```python
def test_tool_use_loop_dispatches_tool_and_accumulates_tokens(db_conn):
    """The tool-use loop must call the tool, pass results back, and sum tokens across turns."""
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_001"
    tool_use_block.name = "test_tool"
    tool_use_block.input = {"query": "market data"}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_use_block]
    first_response.usage.input_tokens = 300
    first_response.usage.output_tokens = 100

    second_response = MagicMock()
    second_response.content = [MagicMock(type="text", text="analysis complete")]
    second_response.usage.input_tokens = 500
    second_response.usage.output_tokens = 200
    second_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    tool_was_called_with = {}

    class ToolAgent(ConcreteAgent):
        def get_tools(self) -> list:
            return [{"name": "test_tool", "description": "test", "input_schema": {
                "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
            }}]

        def _get_tool_functions(self) -> list:
            def test_tool(query: str) -> dict:
                tool_was_called_with["query"] = query
                return {"data": f"result for {query}"}
            return [test_tool]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ToolAgent()
        result = agent.run("analyse the market", conn=db_conn)

    assert result["result"] == "analysis complete"
    assert mock_client.messages.create.call_count == 2
    assert tool_was_called_with == {"query": "market data"}

    # tokens accumulated across both turns
    row = db_conn.execute("SELECT input_tokens, output_tokens FROM agent_logs").fetchone()
    assert row["input_tokens"] == 800   # 300 + 500
    assert row["output_tokens"] == 300  # 100 + 200


def test_tool_use_loop_passes_tool_result_in_second_turn():
    """The second messages.create call must include the tool_result content block."""
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_002"
    tool_use_block.name = "test_tool"
    tool_use_block.input = {"query": "prices"}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_use_block]
    first_response.usage.input_tokens = 100
    first_response.usage.output_tokens = 50

    second_response = MagicMock()
    second_response.content = [MagicMock(type="text", text="done")]
    second_response.usage.input_tokens = 200
    second_response.usage.output_tokens = 80
    second_response.stop_reason = "end_turn"

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    class ToolAgent(ConcreteAgent):
        def get_tools(self) -> list:
            return [{"name": "test_tool", "description": "test", "input_schema": {
                "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
            }}]

        def _get_tool_functions(self) -> list:
            def test_tool(query: str) -> dict:
                return {"value": 42}
            return [test_tool]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = ToolAgent()
        agent.run("test")

    second_call_kwargs = mock_client.messages.create.call_args_list[1][1]
    messages = second_call_kwargs["messages"]
    # last message must be user role with tool_result content
    last_msg = messages[-1]
    assert last_msg["role"] == "user"
    tool_result = last_msg["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tu_002"
    assert "42" in tool_result["content"]
```

Run: `python3 -m pytest tests/test_agents/test_base_agent.py::test_tool_use_loop_dispatches_tool_and_accumulates_tokens tests/test_agents/test_base_agent.py::test_tool_use_loop_passes_tool_result_in_second_turn -v`
Expected: FAIL — these tests don't exist yet, so `ConcreteAgent` won't have `test_tool`. (The tests will error, not fail, but that's expected — proceed.)

- [ ] **Step 2: Run the new tests to confirm they error**

```bash
python3 -m pytest tests/test_agents/test_base_agent.py -v
```

Expected: 4 existing pass, 2 new either error or fail.

- [ ] **Step 3: Run the new tests again — they should now pass without any code change**

The tests only exercise existing `BaseAgent` code — no implementation change needed. If they pass, that means the loop already works correctly and the tests are providing coverage. If they fail, read the output carefully.

```bash
python3 -m pytest tests/test_agents/test_base_agent.py -v
```

Expected: all 6 pass.

- [ ] **Step 4: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agents/test_base_agent.py
git commit -m "test: add tool-use loop coverage for BaseAgent — closes #15"
```

---

## Task 6: MI agent fetches prices for open positions only (#16)

**Files:**
- Modify: `agents/market_intelligence.py:44-48`
- Test: `tests/test_agents/test_market_intelligence.py` (check if exists; add if not)

**Context:** `get_portfolio_state()` in `MarketIntelligenceAgent._get_tool_functions()` currently calls `get_current_price(t)` for every ticker in `WATCHLIST` (8 tickers), even when there are no open positions. This is 8 unnecessary Alpaca API calls each morning. Fix: fetch prices only for tickers that have open trades.

- [ ] **Step 1: Write the failing test**

Check if `tests/test_agents/test_market_intelligence.py` exists:

```bash
ls tests/test_agents/
```

If it doesn't exist, create it. Add this test (either to the existing file or the new one):

```python
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from agents.market_intelligence import MarketIntelligenceAgent


def make_mock_claude_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 500
    mock.usage.output_tokens = 200
    mock.stop_reason = "end_turn"
    return mock


def test_get_portfolio_state_fetches_prices_only_for_open_positions(db_conn):
    """get_portfolio_state must call get_current_price only for tickers with open trades."""
    from tools.database import insert_trade
    from datetime import date

    insert_trade(db_conn, {
        "ticker": "AMD",
        "entry_date": date.today().isoformat(),
        "entry_price": 150.0,
        "shares": 100,
        "stop_loss": 140.0,
        "take_profit": 170.0,
    })

    price_calls = []

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_001"
    tool_use_block.name = "get_portfolio_state"
    tool_use_block.input = {}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"watchlist_summary": "ok", "flagged_positions": [], "market_context": "neutral", "top_movers": []}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    def mock_price(ticker):
        price_calls.append(ticker)
        return 152.0

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", side_effect=mock_price):
        agent = MarketIntelligenceAgent()
        agent.run("scan", conn=db_conn)

    assert price_calls == ["AMD"], (
        f"Expected only open position ticker 'AMD', got: {price_calls}"
    )
```

Run: `python3 -m pytest tests/test_agents/test_market_intelligence.py::test_get_portfolio_state_fetches_prices_only_for_open_positions -v`
Expected: FAIL — currently fetches prices for all 8 WATCHLIST tickers.

- [ ] **Step 2: Fix `get_portfolio_state` in `agents/market_intelligence.py`**

In `_get_tool_functions()`, update the `get_portfolio_state` closure. Also add `get_open_trades` to the deferred import:

```python
    def _get_tool_functions(self) -> list:
        from tools.portfolio import get_open_positions_with_prices
        from tools.database import get_open_trades
        from tools.broker import get_current_price
        conn = self._conn

        def get_portfolio_state():
            open_trades = get_open_trades(conn)
            open_tickers = {t["ticker"] for t in open_trades}
            prices = {ticker: get_current_price(ticker) for ticker in open_tickers}
            return get_open_positions_with_prices(conn, prices)

        def get_watchlist():
            return WATCHLIST

        return [get_portfolio_state, get_watchlist]
```

- [ ] **Step 3: Run MI tests**

```bash
python3 -m pytest tests/test_agents/test_market_intelligence.py -v
```

Expected: all pass.

- [ ] **Step 4: Run full suite**

```bash
python3 -m pytest -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agents/market_intelligence.py tests/test_agents/test_market_intelligence.py
git commit -m "fix: fetch prices only for open positions in MarketIntelligenceAgent — closes #16"
```

---

## Task 7: Fix on-the-bell monitor timing (#13)

**Files:**
- Modify: `scripts/cron_setup.sh`
- Modify: `README.md`

**Context:** The monitor cron includes `0 14-20 * * 1-5`, which fires at 20:00 UTC = 4:00 PM EDT = exactly NYSE close. Market orders may not be processable at the exact close bell, and Alpaca's position API may return inconsistent state. Fix: replace `0 14-20` with `0 14-19` (drop the 20:00 run) and add `30 20` (20:30 UTC = 30 min after close) as a dedicated post-close sweep. The `0 21` end-of-day check stays. This is a documentation-only change — the live crontab on the server must be updated manually.

- [ ] **Step 1: Update `scripts/cron_setup.sh`**

Replace:

```bash
# Hourly position monitor 14:00–20:00 UTC (10:00–16:00 ET)
# 0 14-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Final check at 21:00 UTC (17:00 ET)
# 0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

With:

```bash
# Hourly position monitor 14:00–19:00 UTC (10:00–15:00 ET)
# 0 14-19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# Post-close sweep at 20:30 UTC (16:30 ET — 30 min after NYSE close)
# 30 20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh

# End-of-day check at 21:00 UTC (17:00 ET)
# 0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

- [ ] **Step 2: Update the cron table in `README.md`**

Find the cron schedule table and replace:

```markdown
| Monitor | :00 14–20 | 10:00–16:00 | 16:00–22:00 | Hourly position check |
| Final check | 21:00 | 17:00 | 23:00 | End-of-day close |
```

With:

```markdown
| Monitor | :00 14–19 | 10:00–15:00 | 16:00–21:00 | Hourly position check |
| Post-close sweep | 20:30 | 16:30 | 22:30 | 30 min after NYSE close |
| End-of-day check | 21:00 | 17:00 | 23:00 | End-of-day close |
```

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
python3 -m pytest -v
```

Expected: all pass (no code logic was changed).

- [ ] **Step 4: Commit**

```bash
git add scripts/cron_setup.sh README.md
git commit -m "fix: move monitor away from NYSE close bell to 20:30 UTC — closes #13"
```

- [ ] **Step 5: Update live crontab on the server**

SSH into the VPS and run `crontab -e`. Replace:

```
0 14-20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

With:

```
0 14-19 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
30 20 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
0 21 * * 1-5 /opt/trading-bot/scripts/run_monitor.sh
```

---

## Final check

```bash
python3 -m pytest -v
git push origin main
```

Then create release `v1.5.0` and close issues #6, #7, #8, #13, #15, #16, #21, #22.
