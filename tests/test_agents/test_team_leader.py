from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from agents.team_leader import TeamLeaderAgent


def make_mock_claude_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(type="text", text=text)]
    mock.usage.input_tokens = 1200
    mock.usage.output_tokens = 500
    mock.stop_reason = "end_turn"
    return mock


def test_team_leader_executes_trades(db_conn):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 222, "reasoning": "all signals aligned"}], "summary": "1 trade placed"}'
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        with patch("tools.broker.place_market_order", return_value={"order_id": "order-123", "fill_price": 150.0}), \
             patch("tools.broker.get_current_price", return_value=150.0):
            agent = TeamLeaderAgent()
            result = agent.run("Approved: AMD 222 shares", conn=db_conn)

    assert "decisions" in result
    assert "summary" in result
    assert result["decisions"][0]["ticker"] == "AMD"
    assert result["summary"] == "1 trade placed"


def test_team_leader_name():
    with patch("agents.base.anthropic.Anthropic"):
        agent = TeamLeaderAgent()
    assert agent.name == "team_leader"


def test_team_leader_parse_fallback():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = make_mock_claude_response(
        "No trades today, conditions unfavorable"
    )
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = TeamLeaderAgent()
        result = agent.run("Approved: AMD 222 shares")

    assert result["decisions"] == []
    assert "No trades today" in result["summary"]


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

    # Patching tools.broker.close_position works because _get_tool_functions uses a
    # deferred import (`from tools.broker import close_position as broker_close_position`)
    # that resolves at run() time, so the patch is already active when the import executes.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", side_effect=mock_price), \
         patch("tools.broker.close_position", side_effect=mock_broker_close):
        agent = TeamLeaderAgent()
        agent.run("Close AMD", conn=db_conn)

    assert call_order.index("price") < call_order.index("broker"), \
        "get_current_price must be called before broker_close_position"


def test_dry_run_skips_place_order(db_conn):
    """With dry_run=True, place_order must not call place_market_order or insert_trade."""
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_001"
    tool_use_block.name = "place_order"
    tool_use_block.input = {"ticker": "AMD", "shares": 100, "side": "buy"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "dry run"}], "summary": "dry run"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.database.insert_trade") as mock_insert:
        agent = TeamLeaderAgent()
        result = agent.run("Approved: AMD 100 shares", conn=db_conn, dry_run=True)

    mock_place.assert_not_called()
    mock_insert.assert_not_called()
    assert result.get("summary") == "dry run"


def test_dry_run_skips_place_order_sell_side(db_conn):
    """With dry_run=True and side=sell, place_order must not call place_market_order or insert_trade."""
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_003"
    tool_use_block.name = "place_order"
    tool_use_block.input = {"ticker": "AMD", "shares": 100, "side": "sell"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "dry-run sell"}], "summary": "dry-run"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.database.insert_trade") as mock_insert:
        agent = TeamLeaderAgent()
        result = agent.run("Approved: AMD 100 shares sell", conn=db_conn, dry_run=True)

    mock_place.assert_not_called()
    mock_insert.assert_not_called()
    assert "dry-run" in str(result)


def _make_place_order_tool_use(tool_id: str, ticker: str, shares: int, side: str = "buy") -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = "place_order"
    block.input = {"ticker": ticker, "shares": shares, "side": side}
    return block


def _make_tool_response(*blocks) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = list(blocks)
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    return resp


def test_place_order_passes_when_under_exposure_cap(db_conn):
    """Single buy, no open positions, candidate notional well under cap → order placed."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_g1", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "fits"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-1", "fill_price": 150.0}) as mock_place:
        agent = TeamLeaderAgent()
        agent.run("Approved: AMD 100", conn=db_conn,
                  pending_stops={"AMD": 145.0}, pending_targets={"AMD": 160.0})

    # 100 * $150 = $15k = 15% of $100k → well under 20% cap
    assert mock_place.call_count == 1
    args, kwargs = mock_place.call_args
    assert args[:3] == ("AMD", 100, "buy")
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert len(rows) == 1


def test_place_order_rejected_when_candidate_alone_exceeds_cap(db_conn):
    """Candidate notional alone > MAX_PORTFOLIO_EXPOSURE → rejected, no broker call."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_g2", "SHEL", 200, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "oversized"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run("Approved: SHEL 200", conn=db_conn)

    # 200 * $150 = $30k = 30% of $100k → over 20% cap
    mock_place.assert_not_called()
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []
    mock_notify.assert_called_once()


def test_place_order_rejected_when_already_at_cap(db_conn):
    """Existing positions already at cap → new buy rejected."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_g3", "AMD", 50, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "at cap"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # Already deployed: 1 position worth $20k = 20% of $100k → at cap.
    existing = [{"ticker": "NVDA", "qty": 100, "avg_entry_price": 200.0}]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=existing), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        agent.run("Approved: AMD 50", conn=db_conn)

    # any AMD buy would push past 20% → reject
    mock_place.assert_not_called()


def test_place_order_multi_trade_first_passes_second_rejects(db_conn):
    """3 candidates: 1st passes, 2nd passes, 3rd would push over cap → 3rd rejects.

    The order of `tool_use` blocks reflects risk_review priority. Earlier (higher-priority)
    candidates take the available exposure budget; later ones reject if they'd exceed it.
    """
    tool_response = _make_tool_response(
        _make_place_order_tool_use("tu_m1", "AMD", 50, "buy"),    # 50*$150=$7.5k → 7.5%
        _make_place_order_tool_use("tu_m2", "MSFT", 50, "buy"),   # +$7.5k → 15%
        _make_place_order_tool_use("tu_m3", "GOOG", 50, "buy"),   # +$7.5k → 22.5% (reject)
    )
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "1"},'
        '{"ticker": "MSFT", "action": "buy", "shares": 50, "reasoning": "2"}], "summary": "2/3"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # Live broker positions grow as we open trades — simulate with a list that
    # the patched function reads from a closure.
    live_positions = []

    def fake_get_positions():
        return list(live_positions)

    def fake_place_order(ticker, shares, side, stop_price=None, take_profit_price=None):
        live_positions.append({"ticker": ticker, "qty": shares, "avg_entry_price": 150.0})
        return {"order_id": f"ord-{ticker}", "fill_price": 150.0}

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", side_effect=fake_get_positions), \
         patch("tools.broker.place_market_order", side_effect=fake_place_order) as mock_place, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run("3 candidates", conn=db_conn,
                  pending_stops={"AMD": 145, "MSFT": 145, "GOOG": 145},
                  pending_targets={"AMD": 160, "MSFT": 160, "GOOG": 160})

    # First two should be placed; third should be rejected.
    assert mock_place.call_count == 2
    placed_tickers = [c.args[0] for c in mock_place.call_args_list]
    assert placed_tickers == ["AMD", "MSFT"]
    mock_notify.assert_called_once()
    notify_args, _ = mock_notify.call_args
    assert "GOOG" in notify_args[0]

    rows = db_conn.execute("SELECT ticker FROM trades ORDER BY id").fetchall()
    assert [r["ticker"] for r in rows] == ["AMD", "MSFT"]


def test_place_order_fails_closed_when_broker_call_raises(db_conn):
    """If get_alpaca_positions raises, the gate must reject (not fall through to place_order)."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_g4", "AMD", 100, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "fail-closed"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", side_effect=ConnectionError("alpaca down")), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run("Approved: AMD 100", conn=db_conn)

    mock_place.assert_not_called()
    mock_notify.assert_called_once()
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []


def test_place_order_sell_skips_exposure_gate(db_conn):
    """Sell side reduces exposure → gate is bypassed and broker call still happens."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_g5", "AMD", 100, "sell"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "trim"}], "summary": "sold"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # Even with broker exposure check broken, sell should go through.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", side_effect=ConnectionError("should not be called")), \
         patch("tools.broker.get_alpaca_positions", side_effect=ConnectionError("should not be called")), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-sell", "fill_price": 150.0}) as mock_place:
        agent = TeamLeaderAgent()
        agent.run("Sell: AMD 100", conn=db_conn)

    assert mock_place.call_count == 1
    args, kwargs = mock_place.call_args
    assert args[:3] == ("AMD", 100, "sell")
    # Sell side does not compute a bracket — both bracket params must be None.
    assert kwargs.get("stop_price") is None
    assert kwargs.get("take_profit_price") is None


def test_dry_run_skips_close_position(db_conn):
    """With dry_run=True, close_position must not call broker or close_trade."""
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_002"
    tool_use_block.name = "close_position"
    tool_use_block.input = {"ticker": "AMD", "reason": "manual"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 0, "reasoning": "dry run close"}], "summary": "dry run close"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price") as mock_price, \
         patch("tools.broker.close_position") as mock_broker_close, \
         patch("tools.database.close_trade") as mock_close_trade:
        agent = TeamLeaderAgent()
        result = agent.run("Close AMD", conn=db_conn, dry_run=True)

    mock_price.assert_not_called()
    mock_broker_close.assert_not_called()
    mock_close_trade.assert_not_called()
    assert result.get("summary") == "dry run close"


# --- Bracket order tests (issue #73) ---


def test_buy_submits_bracket_with_fresh_quote_pricing(db_conn):
    """Buy must submit a bracket with stop/target recomputed from the live quote (not LLM stop/target)."""
    from config import settings
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_b1", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    fresh_quote = 200.0
    atr = 2.0
    expected_stop = round(fresh_quote - atr * settings.ATR_STOP_MULTIPLIER, 4)
    expected_target = round(fresh_quote + atr * settings.ATR_STOP_MULTIPLIER * settings.RR_RATIO_MIN, 4)

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=fresh_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-b1", "fill_price": fresh_quote}) as mock_place:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_stops={"AMD": 999.0},   # stale — must be ignored
            pending_targets={"AMD": 0.01},  # stale — must be ignored
            pending_atrs={"AMD": atr},
        )

    assert mock_place.call_count == 1
    _, kwargs = mock_place.call_args
    assert kwargs.get("stop_price") == pytest.approx(expected_stop)
    assert kwargs.get("take_profit_price") == pytest.approx(expected_target)
    # DB row must reflect the recomputed bracket prices, not the stale LLM values.
    row = db_conn.execute("SELECT stop_loss, take_profit FROM trades").fetchone()
    assert row["stop_loss"] == pytest.approx(expected_stop)
    assert row["take_profit"] == pytest.approx(expected_target)


def test_acceptance_rr_and_risk_within_bounds_under_fill_drift(db_conn):
    """Issue #73 acceptance: when the broker fills slightly above the latest quote (typical microseconds-old quote vs market fill), the stored R:R stays within ±5% of RR_RATIO_MIN and per-trade risk within ±10% of RISK_PER_TRADE × portfolio.

    Pre-fix behaviour: bracket was anchored to LLM's prior-close estimate, which can drift several percent from the actual fill (see issue #73 GOOGL 6.3% drift example). Post-fix: bracket is anchored to the fresh quote at submission, so drift between quote and fill is bounded to typical bid-ask/microbar movement.
    """
    import math
    from config import settings

    portfolio_value = 100_000.0
    # The LLM's stale assumed entry — what the old code anchored against.
    llm_assumed_entry = 327.0
    # The fresh quote at submission — what the new code anchors against.
    fresh_quote = 347.60                # 6.3% above LLM estimate (mirrors GOOGL day-0 evidence)
    # Realistic drift between submission quote and market fill: a few basis points
    # (microseconds-old quote + bid-ask cross on a market order). The whole point
    # of this fix: anchor the bracket to a microseconds-old quote, not an overnight-stale
    # LLM estimate. The smaller the drift, the closer real R:R hugs RR_RATIO_MIN.
    fill_price = fresh_quote + 0.02     # 2 cents over a $347 stock (~0.006%)
    atr = 5.0
    stop_distance = atr * settings.ATR_STOP_MULTIPLIER
    risk_dollars = portfolio_value * settings.RISK_PER_TRADE
    shares = math.floor(risk_dollars / stop_distance)   # same math as tools.risk.calculate_position

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_acc", "GOOGL", shares, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "GOOGL", "action": "buy", "shares": '
        + str(shares) + ', "reasoning": "ok"}], "summary": "ok"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=fresh_quote), \
         patch("tools.broker.get_portfolio_value", return_value=portfolio_value), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("config.settings.MAX_PORTFOLIO_EXPOSURE", 1.0), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-acc", "fill_price": fill_price}):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: GOOGL",
            conn=db_conn,
            # The LLM/risk_review's stale stops/targets — must be ignored by the new code.
            pending_stops={"GOOGL": llm_assumed_entry - stop_distance},
            pending_targets={"GOOGL": llm_assumed_entry + stop_distance * settings.RR_RATIO_MIN},
            pending_atrs={"GOOGL": atr},
        )

    row = db_conn.execute(
        "SELECT entry_price, shares, stop_loss, take_profit FROM trades WHERE ticker = 'GOOGL'"
    ).fetchone()
    entry = row["entry_price"]   # the real fill
    shares = row["shares"]
    stop = row["stop_loss"]
    target = row["take_profit"]

    # R:R relative to the real fill
    real_risk_per_share = entry - stop
    real_reward_per_share = target - entry
    real_rr = real_reward_per_share / real_risk_per_share

    # Acceptance: within ±5% of RR_RATIO_MIN
    rr_min = settings.RR_RATIO_MIN
    assert abs(real_rr - rr_min) / rr_min <= 0.05, (
        f"R:R {real_rr:.3f} not within ±5% of {rr_min:.2f}"
    )

    # Acceptance: per-trade risk within ±10% of RISK_PER_TRADE × portfolio_value
    real_risk_dollars = real_risk_per_share * shares
    target_risk = settings.RISK_PER_TRADE * portfolio_value
    assert abs(real_risk_dollars - target_risk) / target_risk <= 0.10, (
        f"Real risk ${real_risk_dollars:,.2f} not within ±10% of target ${target_risk:,.2f}"
    )


def test_buy_without_atr_falls_back_to_pending_prices(db_conn):
    """If pending_atrs is missing for a ticker, fall back to the LLM-supplied stop/target rather than skipping the order."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_fb", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "fb"}], "summary": "fb"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-fb", "fill_price": 150.0}) as mock_place:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_stops={"AMD": 145.0},
            pending_targets={"AMD": 160.0},
            pending_atrs={},   # no ATR available
        )

    _, kwargs = mock_place.call_args
    assert kwargs.get("stop_price") == 145.0
    assert kwargs.get("take_profit_price") == 160.0


def test_sell_uses_plain_market_order_no_bracket(db_conn):
    """Sells (closes) must remain plain market orders — bracket params must be None."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_s1", "AMD", 100, "sell"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "trim"}], "summary": "sold"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-sell", "fill_price": 150.0}) as mock_place:
        agent = TeamLeaderAgent()
        agent.run(
            "Sell: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},   # even with ATR, sell side ignores it
        )

    _, kwargs = mock_place.call_args
    assert kwargs.get("stop_price") is None
    assert kwargs.get("take_profit_price") is None
