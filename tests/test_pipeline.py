"""End-to-end pipeline test, no network.

Feeds synthetic Chainlink ticks and order-book quotes straight into the runner
the way the real sockets would, then checks that the whole chain works:
snapshot assembly -> market state -> 9 strategies -> paper trading -> the JSON
payload the browser receives.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from polymarket.engine import runner as runner_module
from polymarket.engine.paper_trading import STARTING_BANKROLL, PaperTradingEngine
from polymarket.feed.chainlink_ws import PriceTick
from polymarket.feed.clob_ws import TokenQuote, best_ask, best_bid
from polymarket.feed.gamma_client import ActiveMarketMeta, slug_for_window, window_start_sec
from polymarket.feed.state import market_state
from polymarket.strategies import STRATEGIES
from polymarket.strategies.base import MarketSnapshot

UP_TOKEN = "up-token-id"
DOWN_TOKEN = "down-token-id"


@pytest.fixture
def pipeline():
    """A runner wired to a synthetic 5-minute window that opened just now."""
    start_sec = window_start_sec()
    market = ActiveMarketMeta(
        condition_id="0xtest",
        slug=slug_for_window(start_sec),
        question="Bitcoin Up or Down - test window",
        up_token_id=UP_TOKEN,
        down_token_id=DOWN_TOKEN,
        open_time_ms=start_sec * 1000,
        close_time_ms=(start_sec + 300) * 1000,
    )

    state = runner_module.S
    state.current_market = market
    state.price_to_beat = None
    state.price_to_beat_pending = False
    state.chainlink_ticks = []
    state.latest_chainlink = None
    state.latest_eth = None
    state.quotes = {}
    market_state.reset()

    live = runner_module.LiveRunner()
    # A fresh book of record per test, so ledgers don't leak between them.
    runner_module.paper_engine = PaperTradingEngine()

    yield live, market, state

    market_state.reset()


def feed(state, live, *, seconds_offset: int, btc: float, up: TokenQuote, down: TokenQuote):
    """One tick of everything, as the two sockets would deliver it."""
    timestamp = state.current_market.open_time_ms + seconds_offset * 1000
    runner_module._record_chainlink_tick(PriceTick(timestamp_ms=timestamp, value=btc))
    runner_module._resolve_price_to_beat()
    state.quotes[UP_TOKEN] = up
    state.quotes[DOWN_TOKEN] = down
    runner_module._emit_snapshot(timestamp)


def test_order_book_helpers_pick_the_best_levels():
    bids = [{"price": "0.41", "size": "10"}, {"price": "0.44", "size": "5"}]
    asks = [{"price": "0.47", "size": "8"}, {"price": "0.46", "size": "3"}]
    assert best_bid(bids) == 0.44
    assert best_ask(asks) == 0.46
    assert best_bid([]) is None
    assert best_ask(None) is None


def test_snapshot_assembly_carries_real_quotes(pipeline):
    live, market, state = pipeline

    feed(
        state,
        live,
        seconds_offset=1,
        btc=100_000.0,
        up=TokenQuote(bid=0.44, ask=0.46),
        down=TokenQuote(bid=0.53, ask=0.55),
    )

    snapshot = market_state.get_latest()
    assert snapshot is not None
    assert snapshot.condition_id == "0xtest"
    assert snapshot.price_to_beat == 100_000.0  # first print at/after open
    assert snapshot.price_to_beat_pending is False
    assert snapshot.up_ask == 0.46 and snapshot.up_bid == 0.44
    assert snapshot.yes_price == pytest.approx(0.45)  # midpoint of the book
    assert snapshot.no_price == pytest.approx(0.54)
    assert snapshot.seconds_remaining == 299
    assert snapshot.question == "Bitcoin Up or Down - test window"


def test_strike_is_provisional_when_the_window_opened_before_the_server(pipeline):
    live, market, state = pipeline

    # First tick arrives a minute into the window: we missed the boundary.
    feed(
        state,
        live,
        seconds_offset=60,
        btc=100_500.0,
        up=TokenQuote(bid=0.6, ask=0.62),
        down=TokenQuote(bid=0.38, ask=0.4),
    )

    snapshot = market_state.get_latest()
    assert snapshot.price_to_beat == 100_500.0
    assert snapshot.price_to_beat_pending is True


def test_paper_trading_runs_a_full_window_and_settles(pipeline):
    live, market, state = pipeline
    engine = runner_module.paper_engine

    # A compressed book for the first two minutes: both sides sit in the
    # 30-48c band and cost 93c together, so the arbitrage strategies (dual
    # reversion, pre-order) should buy the pair.
    for offset in range(0, 120, 2):
        feed(
            state,
            live,
            seconds_offset=offset,
            btc=100_000.0,
            up=TokenQuote(bid=0.45, ask=0.46),
            down=TokenQuote(bid=0.46, ask=0.47),
        )

    standings = {
        row["strategyId"]: row
        for row in engine.get_public_state(market_state.get_latest())["standings"]
    }
    assert len(standings) == len(STRATEGIES)

    arb = standings["dual-reversion"]
    assert arb["trades"] >= 2  # bought both sides
    assert arb["bankroll"] < STARTING_BANKROLL  # cash went out the door
    assert len(arb["openPositions"]) == 2

    # Close the window with BTC above the strike: Up settles at $1, Down at $0.
    final = market_state.get_latest()
    engine.on_window_end(final)

    settled = {
        row["strategyId"]: row for row in engine.get_public_state(None)["standings"]
    }
    arb_after = settled["dual-reversion"]
    assert arb_after["openPositions"] == []
    assert arb_after["wins"] + arb_after["losses"] == 1
    # Buying a $0.97 pair that pays $1 is a locked profit.
    assert arb_after["totalPnl"] > 0
    assert arb_after["bankroll"] > STARTING_BANKROLL

    state_after = engine.get_public_state(None)
    assert len(state_after["windows"]) == 1
    assert state_after["windows"][0]["outcome"] == "UP"
    assert state_after["windows"][0]["results"][0]["pnlUsd"] >= state_after["windows"][0][
        "results"
    ][-1]["pnlUsd"]


def test_payload_is_json_serialisable_and_complete(pipeline):
    live, market, state = pipeline

    for offset in range(0, 30, 2):
        feed(
            state,
            live,
            seconds_offset=offset,
            btc=100_000.0 + offset,
            up=TokenQuote(bid=0.5, ask=0.52),
            down=TokenQuote(bid=0.47, ask=0.49),
        )

    payload = live.build_payload(include_history=True)
    assert payload is not None

    encoded = json.dumps(payload)  # must survive the wire
    decoded = json.loads(encoded)

    assert decoded["snapshot"]["conditionId"] == "0xtest"
    assert len(decoded["signals"]) == len(STRATEGIES)
    assert "_signal" not in decoded["signals"][0]  # internal field is stripped
    for entry in decoded["signals"]:
        assert entry["signal"]["direction"] in ("YES", "NO", "BOTH", "NEUTRAL")
        assert entry["signal"]["note"]
        assert entry["description"]
    assert len(decoded["paper"]["standings"]) == len(STRATEGIES)
    assert decoded["paper"]["startingBankroll"] == STARTING_BANKROLL
    assert decoded["copy"]["enabled"] is False  # off unless .env says otherwise
    assert decoded["copy"]["available"] is False
    assert len(decoded["history"]) > 1


def test_history_is_sampled_at_about_one_hertz(pipeline):
    live, market, state = pipeline

    # Twenty ticks inside two seconds: a burst of order-book updates.
    for i in range(20):
        timestamp = state.current_market.open_time_ms + i * 100
        runner_module._record_chainlink_tick(
            PriceTick(timestamp_ms=timestamp, value=100_000.0 + i)
        )
        runner_module._resolve_price_to_beat()
        state.quotes[UP_TOKEN] = TokenQuote(bid=0.5, ask=0.52)
        state.quotes[DOWN_TOKEN] = TokenQuote(bid=0.47, ask=0.49)
        runner_module._emit_snapshot(timestamp)

    history = market_state.get_history()
    assert len(history) <= 3  # ~1Hz, not 20 entries
    assert market_state.get_latest().current_price == 100_019.0  # latest stays real-time
