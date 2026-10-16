"""Parity tests for the strategy port.

These are a direct port of the original project's tests/strategies.test.ts
(minus the backtest cases, which were dropped along with the feature). Each
case asserts the same strategy fires the same way on the same fixture, so a
drift in the Python port shows up here rather than in live trading.
"""

from __future__ import annotations

import time
from typing import Callable

from polymarket.strategies import DIRECTIONS, STRATEGIES, STRATEGIES_BY_ID, MarketHistory
from polymarket.strategies.base import MarketSnapshot


def snapshot(**overrides) -> MarketSnapshot:
    base = dict(
        condition_id="test-window",
        asset="BTC",
        price_to_beat=100,
        current_price=100,
        yes_price=0.5,
        no_price=0.5,
        yes_bid_ask_spread=0.01,
        seconds_remaining=120,
        timestamp=int(time.time() * 1000),
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def history_series(
    count: int, step_seconds: int, at: Callable[[int], dict]
) -> MarketHistory:
    """Builds a history of snapshots spaced `step_seconds` apart, ending 'now'."""
    end_ts = 1_700_000_000_000 + count * step_seconds * 1_000
    snaps = []
    for index in range(count):
        fields = dict(
            timestamp=end_ts - (count - 1 - index) * step_seconds * 1_000,
            seconds_remaining=max(0, 300 - index),
        )
        fields.update(at(index))
        snaps.append(snapshot(**fields))
    return MarketHistory(snapshots=snaps)


def assert_valid_signal(signal) -> None:
    assert signal.direction in DIRECTIONS
    assert 0 <= signal.confidence <= 1
    assert isinstance(signal.note, str)
    assert len(signal.note) > 0


def test_strategy_registry_is_the_canonical_strategy_set():
    assert [s.id for s in STRATEGIES] == [
        "lottery-5c",
        "lottery-30c",
        "lottery-40c",
        "sniper-99c",
        "dual-reversion",
        "pre-order-open",
        "cross-market-lag",
        "martingale-45",
        "fibonacci",
        "momentum-confluence",
        "dump-hedge",
    ]

    for strategy in STRATEGIES:
        assert isinstance(strategy.name, str) and strategy.name
        assert isinstance(strategy.description, str) and strategy.description
        assert_valid_signal(
            strategy.evaluate(snapshot(), MarketHistory(snapshots=[snapshot()]))
        )


def test_lottery_variants_respect_their_entry_thresholds():
    empty = MarketHistory(snapshots=[])

    # 1 -- an underdog below each variant's threshold is a buy; above it, not.
    assert (
        STRATEGIES_BY_ID["lottery-5c"]
        .evaluate(snapshot(yes_price=0.04, no_price=0.96, seconds_remaining=90), empty)
        .direction
        == "YES"
    )
    assert (
        STRATEGIES_BY_ID["lottery-5c"]
        .evaluate(snapshot(yes_price=0.28, no_price=0.72, seconds_remaining=90), empty)
        .direction
        == "NEUTRAL"
    )
    assert (
        STRATEGIES_BY_ID["lottery-30c"]
        .evaluate(snapshot(yes_price=0.28, no_price=0.72, seconds_remaining=90), empty)
        .direction
        == "YES"
    )
    assert (
        STRATEGIES_BY_ID["lottery-40c"]
        .evaluate(snapshot(yes_price=0.62, no_price=0.38, seconds_remaining=90), empty)
        .direction
        == "NO"
    )


def test_sniper_fires_in_the_final_minute_past_the_strike():
    # 2 -- final minute, spot clearly past strike, winner still asks <=99c.
    assert (
        STRATEGIES_BY_ID["sniper-99c"]
        .evaluate(
            snapshot(
                yes_price=0.97, no_price=0.03, seconds_remaining=40, current_price=100.3
            ),
            MarketHistory(snapshots=[]),
        )
        .direction
        == "YES"
    )


def test_dual_reversion_buys_the_compressed_pair():
    # 3 -- both sides compressed into 30-48c with 2+ minutes left.
    assert (
        STRATEGIES_BY_ID["dual-reversion"]
        .evaluate(
            snapshot(yes_price=0.44, no_price=0.45, seconds_remaining=150),
            MarketHistory(snapshots=[]),
        )
        .direction
        == "BOTH"
    )


def test_pre_order_buys_the_fresh_book():
    # 4 -- fresh window, both sides discounted before midpoint discovery.
    assert (
        STRATEGIES_BY_ID["pre-order-open"]
        .evaluate(
            snapshot(yes_price=0.45, no_price=0.45, seconds_remaining=280),
            MarketHistory(snapshots=[]),
        )
        .direction
        == "BOTH"
    )


def test_cross_market_lag_follows_a_leading_eth_move():
    # 5 -- ETH rips 0.4% in 30s while BTC and the token haven't moved yet.
    lag_history = history_series(
        40,
        1,
        lambda i: {
            "current_price": 100,
            "eth_price": 3000 if i < 10 else 3000 + ((i - 9) / 30) * 12,
        },
    )
    assert (
        STRATEGIES_BY_ID["cross-market-lag"]
        .evaluate(lag_history.snapshots[-1], lag_history)
        .direction
        == "YES"
    )


def test_martingale_buys_the_dip_in_a_chop_regime():
    # 6 -- dead-flat BTC (chop regime) with one side dipped to 45c.
    chop_history = history_series(
        130, 1, lambda i: {"current_price": 100, "yes_price": 0.45, "no_price": 0.55}
    )
    assert (
        STRATEGIES_BY_ID["martingale-45"]
        .evaluate(chop_history.snapshots[-1], chop_history)
        .direction
        == "YES"
    )


def test_fibonacci_buys_the_retracement_zone():
    # 7 -- Up token swung 42c -> 58c in the first 90s, now dipped to 50c
    # (inside the fib retracement zone) with 150s left.
    fib_history = history_series(
        150,
        1,
        lambda i: {
            "yes_price": 0.42 + (i / 39) * 0.16 if i < 40 else 0.5,
            "no_price": 0.58 - (i / 39) * 0.16 if i < 40 else 0.5,
            # window opened 150s before the last snapshot
            "seconds_remaining": 300 - (i + 1),
        },
    )
    assert (
        STRATEGIES_BY_ID["fibonacci"]
        .evaluate(fib_history.snapshots[-1], fib_history)
        .direction
        == "YES"
    )


def test_momentum_confluence_reads_an_up_grind():
    # 8 -- token grinding up on 5s bars with mild pullbacks (MACD bullish,
    # RSI neutral, price above the session anchor).
    def bar(i: int) -> dict:
        price = 0.45 + 0.0015 * i + (0.008 if i % 2 else 0)
        return {"yes_price": price, "no_price": 1 - price}

    confluence_history = history_series(30, 5, bar)
    assert (
        STRATEGIES_BY_ID["momentum-confluence"]
        .evaluate(confluence_history.snapshots[-1], confluence_history)
        .direction
        == "YES"
    )


def test_dump_hedge_buys_the_pair_after_a_dump():
    # 9 -- BTC dumps 0.4% in seconds, Up collapses to 10c while Down asks 85c:
    # buy the pair for 95c combined (locked edge).
    dump_history = history_series(
        30,
        1,
        lambda i: {
            "current_price": 100 if i < 25 else 100 - (i - 24) * 0.08,
            "yes_price": 0.1,
            "no_price": 0.85,
        },
    )
    assert (
        STRATEGIES_BY_ID["dump-hedge"]
        .evaluate(dump_history.snapshots[-1], dump_history)
        .direction
        == "BOTH"
    )
