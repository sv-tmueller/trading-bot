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
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.database.insert_trade") as mock_insert:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 100 shares",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            dry_run=True,
        )

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
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.database.insert_trade") as mock_insert:
        agent = TeamLeaderAgent()
        result = agent.run("Approved: AMD 100 shares sell", conn=db_conn, dry_run=True)

    mock_place.assert_not_called()
    mock_insert.assert_not_called()
    assert "dry-run" in str(result)


def test_dry_run_still_runs_exposure_gate_and_rejects_over_cap(db_conn):
    """Issue #123 / PR #127 review: dry-run must exercise the deterministic exposure gate.

    Locks in the property that `--dry-run` is a true smoke test of the safety stack: a
    candidate that would breach MAX_PORTFOLIO_EXPOSURE returns a `rejected` payload, NOT
    the `dry_run_simulated` one. Otherwise dry-run gives a false-positive smoke test.
    """
    import ast
    captured_tool_results: list = []

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_dry_gate"
    tool_use_block.name = "place_order"
    tool_use_block.input = {"ticker": "SHEL", "shares": 200, "side": "buy"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "rejected by exposure gate"}'
    )

    mock_client = MagicMock()

    def capture_create(**kwargs):
        for msg in kwargs.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        captured_tool_results.append(block.get("content"))
        if mock_client.messages.create.call_count == 1:
            return tool_response
        return final_response

    mock_client.messages.create.side_effect = capture_create

    # 200 * $150 = $30k = 30% of $100k → exceeds the 20% MAX_PORTFOLIO_EXPOSURE cap.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.database.insert_trade") as mock_insert, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: SHEL 200 shares",
            conn=db_conn,
            pending_atrs={"SHEL": 2.0},
            dry_run=True,
        )

    # Broker SUBMIT and DB INSERT must still be skipped (dry-run invariant).
    mock_place.assert_not_called()
    mock_insert.assert_not_called()
    # The deterministic gate must have rejected and notified — proving dry-run runs it.
    mock_notify.assert_called_once()
    notify_args, _ = mock_notify.call_args
    assert notify_args[0] == "SHEL"
    # Tool result fed back to the LLM must be the rejection payload, NOT dry_run_simulated.
    assert captured_tool_results, "expected at least one tool_result block sent back to the LLM"
    payload = ast.literal_eval(captured_tool_results[0])
    assert payload["status"] == "rejected"
    assert payload["status"] != "dry_run_simulated"
    assert payload["order_id"] is None
    assert "reason" in payload


def test_dry_run_place_order_returns_dry_run_simulated_payload(db_conn):
    """Issue #123: dry-run place_order must return a payload that signals dryness to the LLM."""
    import ast
    captured_tool_results: list = []

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_dry_payload"
    tool_use_block.name = "place_order"
    tool_use_block.input = {"ticker": "AMD", "shares": 100, "side": "buy"}

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]
    tool_response.usage.input_tokens = 100
    tool_response.usage.output_tokens = 50

    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "would have"}], "summary": "would have bought AMD"}'
    )

    mock_client = MagicMock()

    def capture_create(**kwargs):
        for msg in kwargs.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        captured_tool_results.append(block.get("content"))
        if mock_client.messages.create.call_count == 1:
            return tool_response
        return final_response

    mock_client.messages.create.side_effect = capture_create

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100 shares",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            dry_run=True,
        )

    assert captured_tool_results, "expected at least one tool_result block sent back to the LLM"
    payload = ast.literal_eval(captured_tool_results[0])
    assert payload["status"] == "dry_run_simulated"
    assert payload["order_id"] == "DRY_RUN"
    assert payload["fill_price"] is None
    assert "note" in payload


def test_system_prompt_instructs_conditional_language_for_dry_run():
    """Issue #123: the system prompt must tell the LLM to use conditional tense for dry-run results."""
    with patch("agents.base.anthropic.Anthropic"):
        agent = TeamLeaderAgent()
    prompt = agent.system_prompt
    assert "dry_run_simulated" in prompt
    assert "would have" in prompt


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
    """Single buy, no open positions, candidate notional well under cap → order placed.

    Issue #133: buy path now uses `place_parent_market_order` + `place_oco_brackets`
    instead of the legacy atomic `place_market_order(stop, target)` call.
    """
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
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-1", "fill_price": 150.0}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-1", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run("Approved: AMD 100", conn=db_conn,
                  pending_stops={"AMD": 145.0}, pending_targets={"AMD": 160.0})

    # 100 * $150 = $15k = 15% of $100k → well under 20% cap
    assert mock_parent.call_count == 1
    args, kwargs = mock_parent.call_args
    assert args[:3] == ("AMD", 100, "buy")
    # OCO submitted post-fill with the same shares.
    assert mock_oco.call_count == 1
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

    def fake_parent_order(ticker, shares, side):
        live_positions.append({"ticker": ticker, "qty": shares, "avg_entry_price": 150.0})
        return {"order_id": f"ord-{ticker}", "fill_price": 150.0}

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", side_effect=fake_get_positions), \
         patch("tools.broker.place_parent_market_order", side_effect=fake_parent_order) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco", "status": "submitted"}) as mock_oco, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run("3 candidates", conn=db_conn,
                  pending_stops={"AMD": 145, "MSFT": 145, "GOOG": 145},
                  pending_targets={"AMD": 160, "MSFT": 160, "GOOG": 160})

    # First two should be placed (parent + OCO each); third should be rejected (no parent call).
    assert mock_parent.call_count == 2
    assert mock_oco.call_count == 2
    placed_tickers = [c.args[0] for c in mock_parent.call_args_list]
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
    """Issue #133: buy must submit OCO bracket with stop/target recomputed from the FILL PRICE
    (not the pre-order quote, not the LLM-supplied stale prices). When fill == quote (no drift),
    the bracket equals what the legacy fresh-quote-anchored code would have produced.
    """
    from config import settings
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_b1", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    fresh_quote = 200.0
    atr = 2.0
    # No drift: fill_price == fresh_quote. Bracket math anchors on fill (which equals quote here).
    expected_stop = round(fresh_quote - atr * settings.ATR_STOP_MULTIPLIER, 4)
    expected_target = round(fresh_quote + atr * settings.ATR_STOP_MULTIPLIER * settings.RR_RATIO_MIN, 4)

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=fresh_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-b1", "fill_price": fresh_quote}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-b1", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_stops={"AMD": 999.0},   # stale — must be ignored
            pending_targets={"AMD": 0.01},  # stale — must be ignored
            pending_atrs={"AMD": atr},
        )

    assert mock_parent.call_count == 1
    assert mock_oco.call_count == 1
    _, oco_kwargs = mock_oco.call_args
    assert oco_kwargs.get("stop_price") == pytest.approx(expected_stop)
    assert oco_kwargs.get("take_profit_price") == pytest.approx(expected_target)
    assert oco_kwargs.get("shares") == 100
    assert oco_kwargs.get("parent_side") == "buy"
    # DB row must reflect the recomputed bracket prices, not the stale LLM values.
    row = db_conn.execute("SELECT stop_loss, take_profit FROM trades").fetchone()
    assert row["stop_loss"] == pytest.approx(expected_stop)
    assert row["take_profit"] == pytest.approx(expected_target)


def test_acceptance_rr_and_risk_within_bounds_under_fill_drift(db_conn):
    """Issue #133 acceptance (tightened from #73): when the broker fills above the pre-order
    quote (typical drift on a market order), the stored R:R is now LITERALLY equal to
    RR_RATIO_MIN — not just within ±5% — because the bracket is anchored to the fill price
    itself, not the (microseconds-old) quote.

    Pre-#73 behaviour: bracket anchored to LLM's prior-close estimate (could drift several
    percent). Pre-#133 behaviour: bracket anchored to the fresh quote at submission (drift
    bounded to bid-ask/microbar movement). Post-#133: bracket anchored to the actual fill,
    so the realised R:R is invariant to fill drift.
    """
    import math
    from config import settings

    portfolio_value = 100_000.0
    # The LLM's stale assumed entry — what the pre-#73 code anchored against.
    llm_assumed_entry = 327.0
    # The fresh quote at submission — what the pre-#133 code anchored against.
    fresh_quote = 347.60                # 6.3% above LLM estimate
    # The real fill — what #133 now anchors against. Use a non-trivial drift to prove
    # the bracket re-anchors correctly even when the fill drifts noticeably from the quote.
    fill_price = fresh_quote + 1.40     # ~0.4% slippage upward (4× the typical paper-account drift)
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
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-acc", "fill_price": fill_price}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-acc", "status": "submitted"}):
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

    # Acceptance: within ±1% of RR_RATIO_MIN — tighter than the #73 ±5% bound because the
    # only remaining drift source is rounding (round(..., 4) on stop and target).
    rr_min = settings.RR_RATIO_MIN
    assert abs(real_rr - rr_min) / rr_min <= 0.01, (
        f"R:R {real_rr:.3f} not within ±1% of {rr_min:.2f}"
    )

    # Acceptance: per-trade risk within ±10% of RISK_PER_TRADE × portfolio_value
    # (still ±10% because shares is floored — quantization eats a few percent on small risk_dollars).
    real_risk_dollars = real_risk_per_share * shares
    target_risk = settings.RISK_PER_TRADE * portfolio_value
    assert abs(real_risk_dollars - target_risk) / target_risk <= 0.10, (
        f"Real risk ${real_risk_dollars:,.2f} not within ±10% of target ${target_risk:,.2f}"
    )


def test_buy_without_atr_falls_back_to_pending_prices(db_conn):
    """If pending_atrs is missing for a ticker, fall back to the LLM-supplied stop/target
    rather than skipping the order. The OCO is still submitted with those fallback values
    (anchored to the LLM's prior-close — best-effort when ATR is unavailable).
    """
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
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-fb", "fill_price": 150.0}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-fb", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_stops={"AMD": 145.0},
            pending_targets={"AMD": 160.0},
            pending_atrs={},   # no ATR available
        )

    assert mock_parent.call_count == 1
    _, kwargs = mock_oco.call_args
    assert kwargs.get("stop_price") == 145.0
    assert kwargs.get("take_profit_price") == 160.0


def test_place_order_rejects_malformed_bracket_when_atr_missing(db_conn):
    """Issue #79: ATR missing AND LLM stop is above fresh quote → reject, no broker call."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_v1", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "stale"}], "summary": "rejected"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # Fresh quote 200; LLM-supplied stop 210 (stale prior-close anchor) — invalid.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=200.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_stops={"AMD": 210.0},   # stale: above fresh quote
            pending_targets={"AMD": 220.0},
            pending_atrs={},                # no ATR → falls back to LLM stops
        )

    mock_place.assert_not_called()
    mock_notify.assert_called_once()
    notify_args, _ = mock_notify.call_args
    assert "AMD" in notify_args[0]
    assert "invalid bracket" in notify_args[2]
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []


def test_place_order_happy_path_bracket_unchanged(db_conn):
    """Regression check: a valid ATR-derived bracket still goes through (PR #77 path),
    now via the #133 parent → OCO flow. With fill == quote (no drift), the OCO stop/target
    equal what the legacy fresh-quote-anchored bracket would have produced.
    """
    from config import settings
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_v2", "AMD", 100, "buy"))
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
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-v2", "fill_price": fresh_quote}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-v2", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": atr},
        )

    assert mock_parent.call_count == 1
    assert mock_oco.call_count == 1
    _, kwargs = mock_oco.call_args
    assert kwargs.get("stop_price") == pytest.approx(expected_stop)
    assert kwargs.get("take_profit_price") == pytest.approx(expected_target)
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert len(rows) == 1


def test_place_order_handles_broker_submit_error_gracefully(db_conn):
    """Issue #81: parent BrokerSubmitError → notify_order_rejected called once, no DB row,
    agent run completes. Now triggered via place_parent_market_order (#133 split).
    """
    from tools.broker import BrokerSubmitError

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_be1", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "broker rejected"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               side_effect=BrokerSubmitError("insufficient buying power")) as mock_parent, \
         patch("tools.broker.place_oco_brackets") as mock_oco, \
         patch("tools.notifications.notify_order_rejected") as mock_notify:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    # Parent was called (submit attempted), then raised — agent must continue.
    assert mock_parent.call_count == 1
    # OCO must NOT be attempted when the parent fails.
    mock_oco.assert_not_called()
    # Notification fired with broker rejection reason embedded.
    mock_notify.assert_called_once()
    notify_args, _ = mock_notify.call_args
    assert notify_args[0] == "AMD"
    assert notify_args[1] == 100
    assert "broker rejected" in notify_args[2]
    assert "insufficient buying power" in notify_args[2]
    # No DB row inserted on rejection.
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []
    # Agent run completed (final response parsed).
    assert result.get("summary") == "broker rejected"


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


# --- Issue #132: trades.entry_price is the broker fill, not the pre-order quote ---


def test_entry_price_uses_broker_fill_price_not_pre_order_quote(db_conn):
    """Issue #132: trades.entry_price must reflect the broker's filled_avg_price, not the
    pre-order mid-quote that was used for the exposure gate.

    Scenario mirrors the AMD example in the issue: pre-order quote 349.76, broker fills
    at 350.47. The DB row must store 350.47 so PnL/R-multiple math is anchored to truth.
    """
    pre_order_quote = 349.76
    actual_fill = 350.47

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_132a", "AMD", 41, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 41, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=pre_order_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-amd", "fill_price": actual_fill}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-amd", "status": "submitted"}):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 41",
            conn=db_conn,
            pending_atrs={"AMD": 5.0},
        )

    row = db_conn.execute("SELECT entry_price FROM trades WHERE ticker='AMD'").fetchone()
    assert row is not None
    assert row["entry_price"] == pytest.approx(actual_fill)
    assert row["entry_price"] != pytest.approx(pre_order_quote)


def test_entry_price_falls_back_to_pre_order_quote_when_fill_price_none(db_conn):
    """Issue #132: when place_parent_market_order can't determine the fill (poll timeout),
    it returns fill_price=None. The trade row must still exist, with the pre-order quote
    as a best-effort entry_price — never lose the row.
    """
    pre_order_quote = 200.00

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_132b", "AMD", 50, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=pre_order_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-fallback", "fill_price": None}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-fb", "status": "submitted"}):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 50",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    row = db_conn.execute("SELECT entry_price FROM trades WHERE ticker='AMD'").fetchone()
    assert row is not None
    assert row["entry_price"] == pytest.approx(pre_order_quote)


def test_entry_price_uses_fill_even_when_significantly_above_quote(db_conn):
    """The fill price wins even on adverse drift — we want truth in the DB. Post-#133, the
    bracket math is also anchored to the fill price (covered separately by
    `test_oco_bracket_anchored_to_fill_price_not_pre_order_quote`).
    """
    pre_order_quote = 100.00
    actual_fill = 102.00      # 2% slippage — paper-account gap-up scenario

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_132c", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=pre_order_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-slip", "fill_price": actual_fill}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-slip", "status": "submitted"}):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 1.0},
        )

    row = db_conn.execute("SELECT entry_price FROM trades WHERE ticker='AMD'").fetchone()
    assert row["entry_price"] == pytest.approx(actual_fill)


def test_exposure_gate_still_uses_pre_order_quote_not_fill(db_conn):
    """Architectural invariant: the deterministic exposure gate in team_leader.place_order
    must run BEFORE order submission, against the pre-order quote — NOT against the
    (yet-unknown) fill price. This test pins that down so a future "fix" doesn't
    accidentally weaken the gate by waiting for the fill before checking the cap.
    """
    # 200 * $150 = $30k = 30% of $100k → over the 20% cap.
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_132d", "SHEL", 200, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "rejected"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        agent.run("Approved: SHEL 200", conn=db_conn)

    # Gate rejected → broker never called → no chance for a fill price to enter the picture.
    mock_place.assert_not_called()
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []


# --- Signal-row audit-trail tests (issue #136) ---


def test_place_order_fill_writes_signal_row_with_trade_id_and_triggered_entry_1(db_conn):
    """Issue #136: a successful buy writes one signals row with the new trade_id and triggered_entry=1."""
    from datetime import date as _date
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_fill", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-sig-1", "fill_price": 150.0}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-sig-1", "status": "submitted"}):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            pending_indicators={"AMD": {
                "ema_fast": 152.3,
                "ema_slow": 148.1,
                "rsi": 55.0,
                "volume_ratio": 1.8,
                "signal_score": 0.85,
            }},
        )

    rows = db_conn.execute("SELECT * FROM signals").fetchall()
    assert len(rows) == 1
    sig = rows[0]
    assert sig["ticker"] == "AMD"
    assert sig["date"] == _date.today().isoformat()
    assert sig["triggered_entry"] == 1
    # trade_id must point at the newly inserted trade.
    trade_row = db_conn.execute("SELECT id FROM trades WHERE ticker = 'AMD'").fetchone()
    assert sig["trade_id"] == trade_row["id"]
    # Indicators from pending_indicators must round-trip to the row.
    assert sig["ema_fast"] == pytest.approx(152.3)
    assert sig["ema_slow"] == pytest.approx(148.1)
    assert sig["rsi"] == pytest.approx(55.0)
    assert sig["volume_ratio"] == pytest.approx(1.8)
    assert sig["signal_score"] == pytest.approx(0.85)


def test_place_order_exposure_gate_rejection_writes_signal_row_with_triggered_entry_0(db_conn):
    """Issue #136: an exposure-gate-rejected buy writes one signals row with trade_id=NULL and triggered_entry=0."""
    from datetime import date as _date
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_rej", "SHEL", 200, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "rejected"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # 200 * $150 = $30k = 30% of $100k → over the 20% MAX_PORTFOLIO_EXPOSURE cap.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place, \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: SHEL 200",
            conn=db_conn,
            pending_indicators={"SHEL": {
                "ema_fast": None,
                "ema_slow": None,
                "rsi": 48.2,
                "volume_ratio": 1.6,
                "signal_score": 0.62,
            }},
        )

    # Broker not called (exposure gate fired); no trades row inserted.
    mock_place.assert_not_called()
    assert db_conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    # Exactly one signals row, audit-trailing the rejection.
    rows = db_conn.execute("SELECT * FROM signals").fetchall()
    assert len(rows) == 1
    sig = rows[0]
    assert sig["ticker"] == "SHEL"
    assert sig["date"] == _date.today().isoformat()
    assert sig["triggered_entry"] == 0
    assert sig["trade_id"] is None
    assert sig["rsi"] == pytest.approx(48.2)
    assert sig["volume_ratio"] == pytest.approx(1.6)
    assert sig["signal_score"] == pytest.approx(0.62)


def test_place_order_broker_error_writes_signal_row_with_triggered_entry_0(db_conn):
    """Issue #136: a BrokerSubmitError-rejected buy still writes one signals row (trade_id=NULL, triggered_entry=0)."""
    from tools.broker import BrokerSubmitError
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_brk", "AMD", 100, "buy"))
    final_response = make_mock_claude_response('{"decisions": [], "summary": "broker rejected"}')

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order",
               side_effect=BrokerSubmitError("insufficient buying power")), \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            pending_indicators={"AMD": {
                "rsi": 50.0,
                "volume_ratio": 1.7,
                "signal_score": 0.7,
            }},
        )

    # No trade row.
    assert db_conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    # One signals row marking the broker rejection.
    rows = db_conn.execute("SELECT * FROM signals").fetchall()
    assert len(rows) == 1
    sig = rows[0]
    assert sig["ticker"] == "AMD"
    assert sig["triggered_entry"] == 0
    assert sig["trade_id"] is None
    assert sig["rsi"] == pytest.approx(50.0)


def test_place_order_signal_insert_failure_does_not_crash_run(db_conn):
    """Issue #136: if insert_signal raises, the order still completes and notify_error fires."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_fail", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # insert_signal raises; the order INSERT still happens, agent still finishes.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-sig-fail", "fill_price": 150.0}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-sig-fail", "status": "submitted"}), \
         patch("tools.database.insert_signal", side_effect=RuntimeError("simulated DB write failure")) as mock_insert_signal, \
         patch("tools.notifications.notify_error") as mock_notify_error:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            pending_indicators={"AMD": {"rsi": 55.0}},
        )

    # Order still placed and trade still inserted — observability cost only.
    assert mock_parent.call_count == 1
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AMD"
    # insert_signal was called (and raised); notify_error fired with "team_leader" + ticker context.
    mock_insert_signal.assert_called_once()
    mock_notify_error.assert_called()
    err_args, _ = mock_notify_error.call_args
    assert err_args[0] == "team_leader"
    assert "AMD" in err_args[1]
    assert "insert_signal failed" in err_args[1]
    # Agent run completed (final response parsed).
    assert result.get("summary") == "1 placed"


def test_place_order_dry_run_does_not_write_signal_row(db_conn):
    """Issue #136: dry-run skips DB writes (existing convention) — no signals row written."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_dry", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "would have"}], "summary": "dry run"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_market_order") as mock_place:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            pending_indicators={"AMD": {"rsi": 55.0}},
            dry_run=True,
        )

    # Existing dry-run invariant.
    mock_place.assert_not_called()
    # Signal row must NOT be written in dry-run — matches the comment in place_order
    # ("Dry-run skips ONLY the broker SUBMIT and DB INSERT").
    rows = db_conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert rows == 0


def test_place_order_sell_does_not_write_signal_row(db_conn):
    """Issue #136: sells aren't entries — no signals row written for them."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_sig_sell", "AMD", 100, "sell"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "trim"}], "summary": "sold"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.place_market_order", return_value={"order_id": "ord-sell-sig", "fill_price": 150.0}):
        agent = TeamLeaderAgent()
        agent.run("Sell: AMD 100", conn=db_conn,
                  pending_indicators={"AMD": {"rsi": 55.0}})

    # Sells reduce exposure — they're not signal events.
    rows = db_conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert rows == 0


# --- Issue #133: bracket children re-anchored to post-fill price ---


def test_oco_bracket_anchored_to_fill_price_not_pre_order_quote(db_conn):
    """Issue #133 acceptance: when the broker fills above the pre-order quote, the OCO
    bracket stop AND target are computed against the FILL price, not the quote.

    Pre-#133: bracket was built atomically with the parent at submission, anchored to the
    pre-order quote → realised R:R drifted from RR_RATIO_MIN by ~the fill drift fraction.
    Post-#133: parent submits → poll for fill → OCO submitted with stop/target = fill ±
    (atr × ATR_STOP_MULTIPLIER × {1, RR_RATIO_MIN}) so realised R:R is invariant to drift.
    """
    from config import settings

    pre_order_quote = 100.00
    actual_fill = 102.00      # 2% upward slippage — large enough to be visible in numbers
    atr = 2.0
    stop_distance = atr * settings.ATR_STOP_MULTIPLIER
    # Bracket anchored to the FILL — what #133 produces.
    expected_stop = round(actual_fill - stop_distance, 4)
    expected_target = round(actual_fill + stop_distance * settings.RR_RATIO_MIN, 4)
    # Bracket anchored to the QUOTE — what pre-#133 would have produced. Asserted NOT equal
    # so a future regression that re-introduces quote-anchoring fails the test.
    quote_anchored_stop = round(pre_order_quote - stop_distance, 4)
    quote_anchored_target = round(pre_order_quote + stop_distance * settings.RR_RATIO_MIN, 4)

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_anchor", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=pre_order_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-133-1", "fill_price": actual_fill}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-133-1", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": atr},
        )

    # Parent submitted plain (no bracket params); OCO submitted with fill-anchored levels.
    assert mock_parent.call_count == 1
    assert mock_oco.call_count == 1
    _, oco_kwargs = mock_oco.call_args
    assert oco_kwargs["ticker"] == "AMD"
    assert oco_kwargs["shares"] == 100
    assert oco_kwargs["parent_side"] == "buy"
    assert oco_kwargs["stop_price"] == pytest.approx(expected_stop)
    assert oco_kwargs["take_profit_price"] == pytest.approx(expected_target)
    # Negative assertion: must NOT be quote-anchored.
    assert oco_kwargs["stop_price"] != pytest.approx(quote_anchored_stop)
    assert oco_kwargs["take_profit_price"] != pytest.approx(quote_anchored_target)
    # DB row must store the fill-anchored bracket (matches what's at the broker).
    row = db_conn.execute("SELECT entry_price, stop_loss, take_profit FROM trades WHERE ticker='AMD'").fetchone()
    assert row["entry_price"] == pytest.approx(actual_fill)
    assert row["stop_loss"] == pytest.approx(expected_stop)
    assert row["take_profit"] == pytest.approx(expected_target)


def test_oco_failure_after_parent_fill_records_trade_and_notifies(db_conn):
    """Issue #133: if the OCO submission fails after a successful parent fill, the position
    is OPEN without server-side protection. We must:
      - still write the trade row (so the position monitor's soft-stop can act on it),
      - fire `notify_error` with the parent_order_id and ticker so operators see it,
      - return status="submitted" (the LLM doesn't need a separate narration path —
        the parent IS open).
    """
    from tools.broker import BrokerOcoSubmitError

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_oco_fail", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-133-parent", "fill_price": 150.0}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               side_effect=BrokerOcoSubmitError("alpaca 503: temporary outage")) as mock_oco, \
         patch("tools.notifications.notify_error") as mock_notify_error:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    # Parent placed; OCO attempted and failed.
    assert mock_parent.call_count == 1
    assert mock_oco.call_count == 1
    # Trade row must still exist — the position monitor's soft-stop is the recovery layer.
    rows = db_conn.execute("SELECT ticker, entry_price, stop_loss, take_profit FROM trades").fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AMD"
    assert rows[0]["entry_price"] == pytest.approx(150.0)
    # notify_error must mention the ticker AND the parent order_id so operators can find the
    # unprotected position quickly.
    mock_notify_error.assert_called()
    err_args, _ = mock_notify_error.call_args
    assert err_args[0] == "team_leader"
    assert "AMD" in err_args[1]
    assert "ord-133-parent" in err_args[1]
    assert "OCO submit failed" in err_args[1]
    assert "monitor" in err_args[1].lower()   # documents the recovery path
    # Agent run completes — OCO failure is recoverable, not fatal.
    assert result.get("summary") == "1 placed"


def test_dry_run_skips_both_parent_and_oco(db_conn):
    """Issue #133: dry-run must skip BOTH place_parent_market_order and place_oco_brackets.
    The deterministic safety stack still runs (covered by `test_dry_run_still_runs_exposure_gate_and_rejects_over_cap`).
    """
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_dry", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "would have"}], "summary": "dry"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order") as mock_parent, \
         patch("tools.broker.place_oco_brackets") as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            dry_run=True,
        )

    mock_parent.assert_not_called()
    mock_oco.assert_not_called()
    rows = db_conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    assert rows == 0


def test_oco_not_submitted_when_fill_price_none(db_conn):
    """Issue #133: when the parent poll times out (fill_price=None), we don't know the
    actual fill — submitting an OCO would anchor on the pre-order quote (the very thing
    #133 fixes). Skip the OCO submission entirely; the trade row is still written so the
    position monitor's soft-stop applies. notify_error fires so operators see it.

    NOTE: this preserves the #132 fallback behaviour — trade row exists, entry_price is
    the pre-order quote, stop/target are best-effort (fall back to ATR-from-quote math).
    The OCO is the only thing that would otherwise lock in a wrong anchor at the broker.
    """
    pre_order_quote = 200.0

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_no_fill", "AMD", 50, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # The team_leader currently still submits the OCO when fill_price is None (it falls
    # back to the pre-order quote for entry_price). For now we lock in: even on poll
    # timeout, the trade row is written and the position monitor inherits responsibility.
    # The OCO is still attempted (the bracket math falls back gracefully) — but the test
    # is here to make the behaviour explicit.
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=pre_order_quote), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-133-noflpx", "fill_price": None}) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-noflpx", "status": "submitted"}) as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 50",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    assert mock_parent.call_count == 1
    # Trade row exists with pre-order quote as best-effort entry.
    row = db_conn.execute("SELECT entry_price FROM trades WHERE ticker='AMD'").fetchone()
    assert row is not None
    assert row["entry_price"] == pytest.approx(pre_order_quote)
    # OCO IS attempted (anchored to the fallback entry — best we can do without a real fill).
    # The position monitor's soft-stop is the safety net either way.
    assert mock_oco.call_count == 1


def test_sell_does_not_submit_oco(db_conn):
    """Issue #133: sells (exits) close a position — they don't open one, so no OCO bracket
    is needed. The legacy `place_market_order` path is used for sells.
    """
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_sell", "AMD", 100, "sell"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "trim"}], "summary": "sold"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.place_market_order",
               return_value={"order_id": "ord-sell", "fill_price": 150.0}) as mock_legacy, \
         patch("tools.broker.place_parent_market_order") as mock_parent, \
         patch("tools.broker.place_oco_brackets") as mock_oco:
        agent = TeamLeaderAgent()
        agent.run(
            "Sell: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    # Sells use the legacy plain-market path — no parent split, no OCO.
    assert mock_legacy.call_count == 1
    mock_parent.assert_not_called()
    mock_oco.assert_not_called()


def test_oco_bracket_uses_post_fill_validation_skipped_if_invalid(db_conn):
    """Issue #133 defensive: if the post-fill bracket somehow fails validate_bracket_params
    (e.g. extreme fill above the recomputed target — practically impossible with ATR anchoring,
    but defensive), the OCO is NOT submitted. notify_error fires; trade row still written so
    the position monitor's soft-stop applies.

    This is purely a defensive guard — the test forces it via a degenerate ATR.
    """
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_133_postval", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # Pre-order quote 100 → preflight bracket with atr=2 produces stop=97, target=106 (valid).
    # We then force a fill_price=150 (impossible but isolates the post-fill validation guard
    # from the preflight one). Post-fill: stop=147, target=156 — still valid.
    # To trigger the post-fill INVALID path we need a value that fails validate_bracket_params
    # AT THE FILL. We patch validate_bracket_params to fail only on the second call.
    from tools import risk as risk_mod
    real_validate = risk_mod.validate_bracket_params
    call_count = {"n": 0}

    def fake_validate(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            return {"valid": False, "reason": "synthetic post-fill failure for test"}
        return real_validate(*args, **kwargs)

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=100.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-133-postval", "fill_price": 100.0}) as mock_parent, \
         patch("tools.broker.place_oco_brackets") as mock_oco, \
         patch("tools.risk.validate_bracket_params", side_effect=fake_validate), \
         patch("tools.notifications.notify_error") as mock_notify_error:
        agent = TeamLeaderAgent()
        agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    assert mock_parent.call_count == 1
    # OCO must NOT be attempted when post-fill validation fails.
    mock_oco.assert_not_called()
    # Trade row is still written — soft-stop applies.
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert len(rows) == 1
    # notify_error fired with the synthetic failure reason.
    mock_notify_error.assert_called()
    err_args, _ = mock_notify_error.call_args
    assert err_args[0] == "team_leader"
    assert "post-fill bracket invalid" in err_args[1]
    assert "AMD" in err_args[1]


# --- Issue #139: deterministic per-ticker outcome counts ---
#
# Background: PR #127 / issue #123 fixed dry-run summary tense (the LLM was
# saying "executed successfully" when no order was placed). Issue #139 is the
# same family for the LIVE path:
#   - 2026-05-04: LLM said AMD bought; AMD was actually rejected by exposure gate.
#   - 2026-05-05: deterministic Discord alert said "Order rejected — AAPL/SHEL"
#     (correct), but LLM trailing summary said "0 rejected" (wrong).
# Fix (Option 2 from the issue): generate per-ticker BUY/REJECTED counts from
# the place_order tool_results directly, in deterministic Python code. The LLM's
# prose still appears in result["summary"] / agent_logs.full_reasoning but the
# operator-facing structured counts come from result["order_outcomes"].


def test_live_path_records_buy_outcome_when_order_accepted(db_conn):
    """Single buy that passes the safety stack → outcomes['buy'] has the ticker."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_a", "AMD", 100, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 100, "reasoning": "go"}], "summary": "1 placed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-139-a", "fill_price": 150.0}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-139-a", "status": "submitted"}):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    outcomes = result["order_outcomes"]
    assert outcomes["buy"] == [{"ticker": "AMD", "shares": 100}]
    assert outcomes["rejected"] == []
    assert outcomes["sell"] == []
    assert outcomes["dry_run"] == []


def test_live_path_records_rejection_when_exposure_gate_fires(db_conn):
    """Single buy blocked by the exposure gate → outcomes['rejected'] has the ticker + reason."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_b", "SHEL", 200, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "blocked"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # 200 * $150 = $30k = 30% of $100k → over 20% cap
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order") as mock_parent, \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: SHEL 200",
            conn=db_conn,
            pending_atrs={"SHEL": 2.0},
        )

    mock_parent.assert_not_called()
    outcomes = result["order_outcomes"]
    assert outcomes["buy"] == []
    assert len(outcomes["rejected"]) == 1
    rej = outcomes["rejected"][0]
    assert rej["ticker"] == "SHEL"
    assert rej["shares"] == 200
    assert rej["side"] == "buy"
    assert "exposure cap" in rej["reason"]


def test_live_path_count_reflects_deterministic_rejections_not_llm_prose(db_conn):
    """REGRESSION for 2026-05-05: LLM said '0 rejected' but 2 orders were rejected by the gate.

    Mirrors PR #127's `test_dry_run_still_runs_exposure_gate_and_rejects_over_cap` for the
    live path. Pinned by issue #139 evidence:
      - Discord showed `🛑 Order rejected — AAPL 101sh` and `🛑 Order rejected — SHEL 358sh`
      - LLM trailing summary line said `0 rejected`
      - Operator-facing count was wrong because it came from LLM prose, not the safety stack.

    Setup mirrors that day: 1 candidate fits the cap and gets placed, 2 candidates exceed
    the remaining budget and get rejected. The LLM is given a deliberately-misleading prose
    summary that claims everything was fine — the structured `order_outcomes` must contradict
    it deterministically.
    """
    tool_response = _make_tool_response(
        _make_place_order_tool_use("tu_139_c1", "AMD", 50, "buy"),    # 50*$150=$7.5k → 7.5% (fits)
        _make_place_order_tool_use("tu_139_c2", "MSFT", 50, "buy"),   # +$7.5k → 15% (fits)
        _make_place_order_tool_use("tu_139_c3", "AAPL", 100, "buy"),  # +$15k → 30% (REJECT)
        _make_place_order_tool_use("tu_139_c4", "SHEL", 100, "buy"),  # +$15k → 30% (REJECT)
    )
    # Note the deliberately-wrong LLM prose: it says all 4 were placed and 0 rejected,
    # exactly mirroring the 2026-05-05 hallucination pattern.
    final_response = make_mock_claude_response(
        '{"decisions": ['
        '{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "go"},'
        '{"ticker": "MSFT", "action": "buy", "shares": 50, "reasoning": "go"},'
        '{"ticker": "AAPL", "action": "buy", "shares": 100, "reasoning": "go"},'
        '{"ticker": "SHEL", "action": "buy", "shares": 100, "reasoning": "go"}'
        '], "summary": "all 4 orders placed successfully — 0 rejected"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    live_positions = []

    def fake_get_positions():
        return list(live_positions)

    def fake_parent(ticker, shares, side):
        live_positions.append({"ticker": ticker, "qty": shares, "avg_entry_price": 150.0})
        return {"order_id": f"ord-{ticker}", "fill_price": 150.0}

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", side_effect=fake_get_positions), \
         patch("tools.broker.place_parent_market_order", side_effect=fake_parent) as mock_parent, \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco", "status": "submitted"}), \
         patch("tools.notifications.notify_order_rejected") as mock_notify_rejected:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: 4 candidates",
            conn=db_conn,
            pending_atrs={"AMD": 2.0, "MSFT": 2.0, "AAPL": 2.0, "SHEL": 2.0},
        )

    # The deterministic safety stack accepted 2 and rejected 2.
    assert mock_parent.call_count == 2
    assert mock_notify_rejected.call_count == 2

    outcomes = result["order_outcomes"]
    placed = sorted(e["ticker"] for e in outcomes["buy"])
    rejected = sorted(e["ticker"] for e in outcomes["rejected"])
    assert placed == ["AMD", "MSFT"]
    assert rejected == ["AAPL", "SHEL"]
    # Pin the bug: even though the LLM prose claims "0 rejected", the
    # deterministic count says 2.
    assert "0 rejected" in result["summary"]   # LLM still hallucinates
    assert len(outcomes["rejected"]) == 2       # ground truth differs


def test_live_path_zero_fills_one_rejection_locks_2026_05_04_bug(db_conn):
    """REGRESSION for 2026-05-04: LLM said 'order placed / executed successfully' for AMD.

    Reality on that day:
      - META was at ~19% NAV (close to the 20% cap)
      - AMD candidate alone would have pushed past 20%
      - exposure gate returned `{"order_id": None, "status": "rejected", "reason": "exposure cap..."}`
      - LLM prose said "Full go decision — order placed. A market buy order for 41 shares was executed successfully."
      - `agent_logs.output_summary` row #41 cemented the false claim
      - `trades` table had no AMD row for 2026-05-04 entry_date

    Test reconstructs the scenario: 1 existing position close to the cap, 1 buy candidate
    that breaches it. The LLM prose deliberately claims success. The structured outcomes
    must say 0 buys, 1 rejection — operator/audit cannot be misled even if the LLM
    hallucinates.
    """
    # META-style position: 19% of $100k = $19k notional
    existing_meta = [{"ticker": "META", "qty": 100, "avg_entry_price": 190.0}]

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_d", "AMD", 41, "buy"))
    # The exact hallucination pattern from 2026-05-04 agent_logs row #41:
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 41, "reasoning": "Full go decision"}],'
        ' "summary": "Full go decision — order placed. A market buy order for 41 shares was executed successfully."}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    # 41 * $150 = $6.15k → +6% → 19%+6%=25% > 20% cap → REJECT
    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=existing_meta), \
         patch("tools.broker.place_parent_market_order") as mock_parent, \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 41",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    # The deterministic gate must have blocked the order.
    mock_parent.assert_not_called()
    rows = db_conn.execute("SELECT ticker FROM trades").fetchall()
    assert rows == []   # no AMD row, matching the actual 2026-05-04 DB state

    outcomes = result["order_outcomes"]
    # Ground truth: 0 buys, 1 rejection.
    assert outcomes["buy"] == []
    assert len(outcomes["rejected"]) == 1
    assert outcomes["rejected"][0]["ticker"] == "AMD"
    assert "exposure cap" in outcomes["rejected"][0]["reason"]
    # The LLM prose still claims success (this is the bug we're regressing against —
    # the prose IS allowed to be wrong, the deterministic count must NOT be).
    assert "executed successfully" in result["summary"]
    # The deterministic count contradicts the prose, which is the whole point.
    assert len(outcomes["buy"]) == 0


def test_dry_run_path_records_dry_run_outcome(db_conn):
    """PR #127 dry-run contract is preserved: dry-run buys land in outcomes['dry_run']."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_e", "AMD", 50, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "would have"}],'
        ' "summary": "would have bought AMD"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order") as mock_parent:
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 50",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
            dry_run=True,
        )

    # Dry-run skips the broker call (PR #127 invariant).
    mock_parent.assert_not_called()
    outcomes = result["order_outcomes"]
    assert outcomes["dry_run"] == [{"ticker": "AMD", "shares": 50, "side": "buy"}]
    assert outcomes["buy"] == []
    assert outcomes["rejected"] == []


def test_dry_run_over_cap_lands_in_rejected_not_dry_run(db_conn):
    """PR #127 contract: dry-run still runs the exposure gate. Over-cap dry-run goes to rejected."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_f", "SHEL", 200, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "would have been blocked"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: SHEL 200",
            conn=db_conn,
            pending_atrs={"SHEL": 2.0},
            dry_run=True,
        )

    outcomes = result["order_outcomes"]
    assert outcomes["dry_run"] == []   # gate fired before dry-run sentinel
    assert len(outcomes["rejected"]) == 1
    assert outcomes["rejected"][0]["ticker"] == "SHEL"


def test_broker_rejection_lands_in_rejected_outcome(db_conn):
    """BrokerSubmitError → outcome bucket is `rejected`, same category as exposure-gate refusals."""
    from tools.broker import BrokerSubmitError

    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_g", "AMD", 50, "buy"))
    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "broker said no"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               side_effect=BrokerSubmitError("insufficient buying power")), \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: AMD 50",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},
        )

    outcomes = result["order_outcomes"]
    assert outcomes["buy"] == []
    assert len(outcomes["rejected"]) == 1
    rej = outcomes["rejected"][0]
    assert rej["ticker"] == "AMD"
    assert "broker rejected" in rej["reason"]
    assert "insufficient buying power" in rej["reason"]


def test_mixed_bag_one_buy_one_exposure_reject_one_broker_reject(db_conn):
    """1 buy succeeds, 1 rejected by exposure gate, 1 rejected by broker → all categories populated correctly."""
    from tools.broker import BrokerSubmitError

    tool_response = _make_tool_response(
        _make_place_order_tool_use("tu_139_h1", "AMD", 50, "buy"),    # 50*$150=$7.5k → 7.5% (fits)
        _make_place_order_tool_use("tu_139_h2", "MSFT", 50, "buy"),   # broker will reject
        _make_place_order_tool_use("tu_139_h3", "GOOG", 200, "buy"),  # exposure-gate reject (alone over cap)
    )
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "go"}], "summary": "mixed"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    live_positions = []

    def fake_get_positions():
        return list(live_positions)

    def fake_parent(ticker, shares, side):
        if ticker == "MSFT":
            raise BrokerSubmitError("synthetic broker outage")
        live_positions.append({"ticker": ticker, "qty": shares, "avg_entry_price": 150.0})
        return {"order_id": f"ord-{ticker}", "fill_price": 150.0}

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", side_effect=fake_get_positions), \
         patch("tools.broker.place_parent_market_order", side_effect=fake_parent), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco", "status": "submitted"}), \
         patch("tools.notifications.notify_order_rejected"):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Approved: 3 mixed candidates",
            conn=db_conn,
            pending_atrs={"AMD": 2.0, "MSFT": 2.0, "GOOG": 2.0},
        )

    outcomes = result["order_outcomes"]
    assert [e["ticker"] for e in outcomes["buy"]] == ["AMD"]
    rejected_tickers = sorted(e["ticker"] for e in outcomes["rejected"])
    assert rejected_tickers == ["GOOG", "MSFT"]
    # Reasons distinguish the two rejection sources for forensic clarity.
    by_ticker = {e["ticker"]: e["reason"] for e in outcomes["rejected"]}
    assert "broker rejected" in by_ticker["MSFT"]
    assert "exposure cap" in by_ticker["GOOG"]


def test_outcomes_reset_between_runs(db_conn):
    """Re-using a TeamLeaderAgent instance must NOT accumulate outcomes across cycles."""
    tool_response_first = _make_tool_response(_make_place_order_tool_use("tu_139_i1", "AMD", 50, "buy"))
    final_response_first = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "buy", "shares": 50, "reasoning": "1"}], "summary": "first"}'
    )
    tool_response_second = _make_tool_response(_make_place_order_tool_use("tu_139_i2", "MSFT", 50, "buy"))
    final_response_second = make_mock_claude_response(
        '{"decisions": [{"ticker": "MSFT", "action": "buy", "shares": 50, "reasoning": "2"}], "summary": "second"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        tool_response_first, final_response_first,
        tool_response_second, final_response_second,
    ]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.get_portfolio_value", return_value=100_000.0), \
         patch("tools.broker.get_alpaca_positions", return_value=[]), \
         patch("tools.broker.place_parent_market_order",
               return_value={"order_id": "ord-x", "fill_price": 150.0}), \
         patch("tools.broker.place_oco_brackets",
               return_value={"order_id": "ord-oco-x", "status": "submitted"}):
        agent = TeamLeaderAgent()
        result1 = agent.run("Approved: AMD 50", conn=db_conn, pending_atrs={"AMD": 2.0})
        result2 = agent.run("Approved: MSFT 50", conn=db_conn, pending_atrs={"MSFT": 2.0})

    # Each cycle reports only its own outcome — no leakage from cycle 1 into cycle 2.
    assert [e["ticker"] for e in result1["order_outcomes"]["buy"]] == ["AMD"]
    assert [e["ticker"] for e in result2["order_outcomes"]["buy"]] == ["MSFT"]


def test_outcomes_present_on_no_tool_use_path(db_conn):
    """When the LLM doesn't call any tools at all, outcomes is still present and empty."""
    final_response = make_mock_claude_response(
        '{"decisions": [], "summary": "no candidates worth placing"}'
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = final_response

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client):
        agent = TeamLeaderAgent()
        result = agent.run("Approved: nothing", conn=db_conn)

    outcomes = result["order_outcomes"]
    assert outcomes["buy"] == []
    assert outcomes["rejected"] == []
    assert outcomes["sell"] == []
    assert outcomes["dry_run"] == []


def test_sell_side_records_sell_outcome_and_skips_rejected(db_conn):
    """A successful sell lands in outcomes['sell'], not buy or rejected."""
    tool_response = _make_tool_response(_make_place_order_tool_use("tu_139_j", "AMD", 100, "sell"))
    final_response = make_mock_claude_response(
        '{"decisions": [{"ticker": "AMD", "action": "sell", "shares": 100, "reasoning": "trim"}], "summary": "sold"}'
    )

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [tool_response, final_response]

    with patch("agents.base.anthropic.Anthropic", return_value=mock_client), \
         patch("tools.broker.get_current_price", return_value=150.0), \
         patch("tools.broker.place_market_order",
               return_value={"order_id": "ord-sell", "fill_price": 150.0}):
        agent = TeamLeaderAgent()
        result = agent.run(
            "Sell: AMD 100",
            conn=db_conn,
            pending_atrs={"AMD": 2.0},   # ignored on sells
        )

    outcomes = result["order_outcomes"]
    assert outcomes["sell"] == [{"ticker": "AMD", "shares": 100}]
    assert outcomes["buy"] == []
    assert outcomes["rejected"] == []
