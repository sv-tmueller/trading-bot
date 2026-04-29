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

    mock_place.assert_called_once_with("AMD", 100, "buy")
    # 100 * $150 = $15k = 15% of $100k → well under 20% cap
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

    def fake_place_order(ticker, shares, side):
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
    assert "GOOG" in mock_notify.call_args.args[0]

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

    mock_place.assert_called_once_with("AMD", 100, "sell")


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
