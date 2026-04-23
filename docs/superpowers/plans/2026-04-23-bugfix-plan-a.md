# Bug Fix Plan A — Critical Correctness Issues

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five bugs that corrupt live data, crash silently, or produce wrong database records.

**Architecture:** Each task is self-contained — one file, one concern, one commit. Order matters: fix atomic helpers first (#3, #5), then wiring (#4, #14), then the top-level error handler (#2) last so it wraps already-fixed code.

**Tech Stack:** Python 3.9, SQLite, Alpaca SDK, Anthropic SDK, pytest + pytest-mock

**Closes:** GitHub issues #2, #3, #4, #5, #14

---

## File map

| File | Change |
|---|---|
| `tools/broker.py` | Raise `ValueError` when quote returns 0/0 (#3) |
| `tools/market_data.py` | Increase `fetch_bars` calendar buffer (#5) |
| `main.py` | Replace `str()` with `json.dumps()` for inter-agent handoff (#4); wrap pipeline in `try/except` (#2) |
| `agents/team_leader.py` | Accept `reason` param in `close_position` tool (#14) |
| `tests/test_tools_broker.py` | New test for #3 |
| `tests/test_tools_market_data.py` | New test for #5 |
| `tests/test_main.py` | New file — tests for #4 and #2 |
| `tests/test_agents/test_team_leader.py` | New test for #14 |

---

## Task 1: Raise on zero quote — `get_current_price` (#3)

**Files:**
- Modify: `tools/broker.py:47-52`
- Test: `tests/test_tools_broker.py`

The current fallback `return ask if ask > 0 else bid` silently returns `0.0` when the market is closed or the ticker has no quote. Any PnL or position-size calculation that receives `0.0` produces garbage without any error. Fix: raise `ValueError` so the caller (and the try/except added in Task 5) can catch and report it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools_broker.py`:

```python
def test_get_current_price_raises_on_zero_quote():
    mock_data_client = MagicMock()
    mock_quote = MagicMock()
    mock_quote.bid_price = "0.0"
    mock_quote.ask_price = "0.0"
    mock_data_client.get_stock_latest_quote.return_value = {"AMD": mock_quote}

    with patch("tools.broker.StockHistoricalDataClient", return_value=mock_data_client):
        with pytest.raises(ValueError, match="No valid quote for AMD"):
            get_current_price("AMD")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_tools_broker.py::test_get_current_price_raises_on_zero_quote -v
```

Expected: `FAILED` — currently `get_current_price` returns `0.0` instead of raising.

- [ ] **Step 3: Fix `get_current_price` in `tools/broker.py`**

Replace the final three lines of `get_current_price`:

```python
# old — silently returns 0.0
    return ask if ask > 0 else bid
```

With:

```python
# new — raises so callers can react
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    raise ValueError(f"No valid quote for {ticker}: bid={bid}, ask={ask}")
```

Full function after edit:

```python
def get_current_price(ticker: str) -> float:
    data_client = StockHistoricalDataClient(
        settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY
    )
    feed = DataFeed.SIP if settings.DATA_FEED == "sip" else DataFeed.IEX
    request = StockLatestQuoteRequest(symbol_or_symbols=ticker, feed=feed)
    quote = data_client.get_stock_latest_quote(request)
    q = quote[ticker]
    bid = float(q.bid_price)
    ask = float(q.ask_price)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    raise ValueError(f"No valid quote for {ticker}: bid={bid}, ask={ask}")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python3 -m pytest tests/test_tools_broker.py -v
```

Expected: all pass including the new test.

- [ ] **Step 5: Commit**

```bash
git add tools/broker.py tests/test_tools_broker.py
git commit -m "fix: raise ValueError on zero quote in get_current_price — closes #3"
```

---

## Task 2: Widen `fetch_bars` calendar buffer (#5)

**Files:**
- Modify: `tools/market_data.py:17`
- Test: `tests/test_tools_market_data.py`

`fetch_bars(ticker, days=60)` currently requests `days + 15` calendar days then calls `.tail(days)`. With `days=60` that is 75 calendar days ≈ 53 trading bars. EMA50 needs 50 bars of **warmup** before the first usable bar — with only 53 bars total, the first 50 bars of EMA50 are NaN, leaving just 3 bars with valid values. The fix is to request `days * 2 + 20` calendar days, which for `days=60` yields 140 calendar days ≈ 100 trading bars — enough for EMA50 warmup with room to spare. `.tail(days)` still trims the result to exactly `days` bars.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools_market_data.py`:

```python
def test_fetch_bars_requests_enough_buffer_for_ema50():
    """fetch_bars must request at least days + 70 calendar days so EMA50 has warmup data."""
    from datetime import timedelta
    import tools.market_data as md

    captured = {}

    def fake_request(**kwargs):
        captured["start"] = kwargs.get("start") or None
        return None  # we only care the request is constructed with the right window

    mock_client = MagicMock()

    # Intercept StockBarsRequest construction
    with patch("tools.market_data.get_data_client", return_value=mock_client), \
         patch("tools.market_data.StockBarsRequest", side_effect=lambda **kw: captured.update(kw) or MagicMock()):
        try:
            md.fetch_bars("AMD", days=60)
        except Exception:
            pass  # we just want to inspect the request args

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if "start" in captured and captured["start"] is not None:
        diff = (now - captured["start"]).days
        assert diff >= 130, f"Buffer too thin: only {diff} calendar days requested (need ≥130 for EMA50 warmup)"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_tools_market_data.py::test_fetch_bars_requests_enough_buffer_for_ema50 -v
```

Expected: `FAILED` — current buffer is only 75 days, below the 130 threshold.

- [ ] **Step 3: Fix the buffer in `tools/market_data.py`**

Line 17 — change:

```python
    start = end - timedelta(days=days + 15)  # buffer for weekends/holidays
```

To:

```python
    start = end - timedelta(days=days * 2 + 20)  # warmup buffer for EMA50
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python3 -m pytest tests/test_tools_market_data.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/market_data.py tests/test_tools_market_data.py
git commit -m "fix: widen fetch_bars buffer to days*2+20 for EMA50 warmup — closes #5"
```

---

## Task 3: Inter-agent JSON serialization (#4)

**Files:**
- Modify: `main.py:64,82,98`
- Test: `tests/test_main.py` (new file)

`str()` on a Python dict produces Python repr, not JSON — e.g. `True` becomes `True` (valid Python) but an LLM receiving it may be confused by single-quoted strings and Python-specific syntax. `json.dumps()` produces valid JSON the LLM can reliably parse.

- [ ] **Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, call


def _make_agent_mock(return_value: dict):
    mock = MagicMock()
    mock.run.return_value = return_value
    return mock


def test_inter_agent_handoff_is_valid_json(db_conn):
    """Strategy agent must receive valid JSON from market briefing, not Python repr."""
    market_briefing = {
        "market_context": "bullish",
        "watchlist_summary": "AMD up 2%",
        "flagged_positions": [],
        "top_movers": ["AMD"],
    }
    candidates = {
        "candidates": [{"ticker": "AMD", "score": 0.8}],
        "tldr": "AMD crossover",
        "tickers_to_watch": [],
    }
    reviewed = {
        "approved": [{"ticker": "AMD", "shares": 100, "stop_loss": 140.0, "take_profit": 160.0}],
        "rejected": [],
    }
    decisions = {"decisions": [], "summary": "done"}

    mi_mock = _make_agent_mock(market_briefing)
    strategy_mock = _make_agent_mock(candidates)
    risk_mock = _make_agent_mock(reviewed)
    leader_mock = _make_agent_mock(decisions)

    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent", return_value=mi_mock), \
         patch("main.StrategyAgent", return_value=strategy_mock), \
         patch("main.RiskReviewAgent", return_value=risk_mock), \
         patch("main.TeamLeaderAgent", return_value=leader_mock), \
         patch("main.get_daily_token_costs", return_value={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}), \
         patch("main.notify_scan_complete"), \
         patch("main.notify_error"):
        from main import run_morning_scan
        run_morning_scan()

    # strategy_agent.run was called with the market briefing — must be valid JSON
    strategy_call_arg = strategy_mock.run.call_args[0][0]
    parsed = json.loads(strategy_call_arg)  # raises if not valid JSON
    assert parsed["market_context"] == "bullish"

    # risk_agent.run was called with candidates — must be valid JSON
    risk_call_arg = risk_mock.run.call_args[0][0]
    parsed = json.loads(risk_call_arg)
    assert "candidates" in parsed

    # leader_agent.run was called with reviewed — must be valid JSON
    leader_call_arg = leader_mock.run.call_args[0][0]
    parsed = json.loads(leader_call_arg)
    assert "approved" in parsed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_main.py::test_inter_agent_handoff_is_valid_json -v
```

Expected: `FAILED` — `json.loads(str(dict_with_bool))` raises because Python repr uses `True`/`False`/`None` instead of `true`/`false`/`null`.

- [ ] **Step 3: Fix `main.py`**

Add `import json` at the top of `main.py` (after the existing stdlib imports):

```python
import json
```

Then replace the three `str()` calls:

Line 64 — change:
```python
    candidates = strategy_agent.run(str(market_briefing), conn=conn)
```
To:
```python
    candidates = strategy_agent.run(json.dumps(market_briefing), conn=conn)
```

Line 82 — change:
```python
    reviewed = risk_agent.run(str(candidates), conn=conn)
```
To:
```python
    reviewed = risk_agent.run(json.dumps(candidates), conn=conn)
```

Line 98 — change:
```python
    decisions = leader_agent.run(
        str(reviewed),
```
To:
```python
    decisions = leader_agent.run(
        json.dumps(reviewed),
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python3 -m pytest tests/test_main.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "fix: use json.dumps for inter-agent handoff instead of str() — closes #4"
```

---

## Task 4: Fix `close_position` exit reason (#14)

**Files:**
- Modify: `agents/team_leader.py:58,90-95`
- Test: `tests/test_agents/test_team_leader.py`

The `close_position` tool in `TeamLeaderAgent` always writes `"exit_reason": "manual"` regardless of why the LLM closed the position. The schema allows `('stop_loss', 'take_profit', 'trend_reversal', 'max_hold', 'manual')`. Fix: add an optional `reason` parameter to the tool definition and pass it through to `close_trade`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents/test_team_leader.py`:

```python
def test_team_leader_close_position_records_reason(db_conn):
    """close_position tool must write the LLM-supplied reason, not always 'manual'."""
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

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_001"
    tool_use_block.name = "close_position"
    tool_use_block.input = {"ticker": "AMD", "reason": "trend_reversal"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "reversal"}], "summary": "closed AMD"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=155.0), \
         patch("tools.broker.TradingClient") as mock_tc:
        mock_tc.return_value.close_position.return_value = MagicMock(id="order-999")
        agent = TeamLeaderAgent()
        agent.run("Close AMD — trend reversal", conn=db_conn)

    row = db_conn.execute(
        "SELECT exit_reason FROM trades WHERE ticker = 'AMD'"
    ).fetchone()
    assert row is not None
    assert row["exit_reason"] == "trend_reversal"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_agents/test_team_leader.py::test_team_leader_close_position_records_reason -v
```

Expected: `FAILED` — `exit_reason` is `'manual'`, not `'trend_reversal'`.

- [ ] **Step 3: Update tool schema in `agents/team_leader.py`**

In `get_tools()`, update the `close_position` tool definition:

```python
{
    "name": "close_position",
    "description": "Close an open position entirely",
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "reason": {
                "type": "string",
                "enum": ["stop_loss", "take_profit", "trend_reversal", "max_hold", "manual"],
                "description": "Why this position is being closed",
            },
        },
        "required": ["ticker"],
    },
},
```

- [ ] **Step 4: Update the `close_position` closure in `_get_tool_functions()`**

Change the function signature and the `close_trade` call:

```python
        def close_position(ticker: str, reason: str = "manual") -> dict:
            order_id = broker_close_position(ticker)
            today = date.today().isoformat()
            price = get_current_price(ticker)
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

- [ ] **Step 5: Run tests to verify pass**

```bash
python3 -m pytest tests/test_agents/test_team_leader.py -v
```

Expected: all pass including the new test.

- [ ] **Step 6: Commit**

```bash
git add agents/team_leader.py tests/test_agents/test_team_leader.py
git commit -m "fix: pass exit reason through close_position tool — closes #14"
```

---

## Task 5: Wrap agent pipeline in try/except (#2)

**Files:**
- Modify: `main.py` — `run_morning_scan()` and `run_position_monitor()`
- Test: `tests/test_main.py`

If any agent raises (e.g. API timeout, zero-quote ValueError from Task 1, JSON parse error), the pipeline crashes and exits with no Discord alert. `notify_error` is already imported but never called. Fix: wrap each function body in `try/except Exception` and call `notify_error` in the handler.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_run_morning_scan_calls_notify_error_on_exception(db_conn):
    """If any agent raises, notify_error must be called and the exception must not propagate."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.MarketIntelligenceAgent") as MockMI, \
         patch("main.notify_error") as mock_notify_error:
        MockMI.return_value.run.side_effect = RuntimeError("API timeout")
        from main import run_morning_scan
        run_morning_scan()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "morning_scan"
    assert "API timeout" in error_text


def test_run_position_monitor_calls_notify_error_on_exception(db_conn):
    """If run_monitor raises, notify_error must be called."""
    with patch("main.is_trading_day", return_value=True), \
         patch("main.get_db", return_value=db_conn), \
         patch("main.run_monitor", side_effect=RuntimeError("connection refused")), \
         patch("main.notify_error") as mock_notify_error:
        from main import run_position_monitor
        run_position_monitor()  # must NOT raise

    mock_notify_error.assert_called_once()
    context, error_text = mock_notify_error.call_args[0]
    assert context == "position_monitor"
    assert "connection refused" in error_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_main.py::test_run_morning_scan_calls_notify_error_on_exception tests/test_main.py::test_run_position_monitor_calls_notify_error_on_exception -v
```

Expected: both `FAILED` — exceptions propagate and `notify_error` is never called.

- [ ] **Step 3: Wrap `run_morning_scan` in `main.py`**

Add `import traceback` to the imports at the top of `main.py`.

Then wrap the body of `run_morning_scan` (everything after the `is_trading_day` guard):

```python
def run_morning_scan():
    if not is_trading_day():
        print("Not a trading day. Exiting.")
        return

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
            conn.close()
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
            conn.close()
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
        conn.close()

    except Exception as e:
        print(f"SCAN ERROR: {e}")
        notify_error("morning_scan", traceback.format_exc())
```

- [ ] **Step 4: Wrap `run_position_monitor` in `main.py`**

```python
def run_position_monitor():
    if not is_trading_day():
        return
    try:
        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        print(f"=== Position monitor — {date.today()} {now} ===")
        conn = get_db()
        actions = run_monitor(conn)
        closed = [a for a in actions if a.action == "close"]
        print(f"Checked {len(actions)} positions. Closed: {len(closed)}")
        notify_monitor(date.today().isoformat(), now, len(actions), closed)
        conn.close()
    except Exception as e:
        print(f"MONITOR ERROR: {e}")
        notify_error("position_monitor", traceback.format_exc())
```

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest -v
```

Expected: all 74+ tests pass.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "fix: wrap agent pipeline in try/except and call notify_error on failure — closes #2"
```

---

## Final check

```bash
python3 -m pytest -v
```

All tests green → push:

```bash
git push origin main
```

Then create release `v1.4.0` and close issues #2, #3, #4, #5, #14.
