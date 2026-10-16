"""Backtest runner + synthetic window (port of the TS backtest cases)."""

from __future__ import annotations

from polymarket.engine.backtest import (
    build_ticks,
    run_backtest_on_many_windows,
    run_backtest_on_window,
)
from polymarket.feed.synthetic import generate_synthetic_window
from polymarket.strategies.base import MarketSnapshot
from polymarket.strategies.registry import STRATEGIES


def _snapshot(**overrides) -> MarketSnapshot:
    base = dict(
        condition_id="test-window",
        asset="BTC",
        price_to_beat=65000.0,
        current_price=65000.0,
        yes_price=0.5,
        no_price=0.5,
        yes_bid_ask_spread=0.01,
        seconds_remaining=150,
        timestamp=1,
        up_bid=0.49,
        up_ask=0.51,
        down_bid=0.49,
        down_ask=0.51,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def test_synthetic_window_is_runnable():
    window = generate_synthetic_window()
    assert window.condition_id == "synthetic-demo-window"
    assert window.final_outcome in ("YES", "NO")
    assert len(window.snapshots) > 10
    assert window.snapshots[0].price_to_beat == window.price_to_beat


def test_backtest_runner_evaluates_every_strategy_and_counts_both_as_a_win():
    snapshots = [
        _snapshot(
            yes_price=0.44,
            no_price=0.45,
            up_ask=0.44,
            down_ask=0.45,
            seconds_remaining=150,
            timestamp=1,
        ),
        _snapshot(
            yes_price=0.44,
            no_price=0.45,
            up_ask=0.44,
            down_ask=0.45,
            seconds_remaining=149,
            timestamp=2,
        ),
    ]

    results = run_backtest_on_window(snapshots, "YES")
    assert len(results) == len(STRATEGIES)

    arb = next(r for r in results if r.strategy_id == "dual-reversion")
    assert arb.trades == 1
    assert arb.wins == 1
    assert arb.win_rate == 1

    summary = run_backtest_on_many_windows(
        [{"snapshots": snapshots, "final_outcome": "YES"}]
    )
    assert summary["dual-reversion"]["trades"] == 1
    assert summary["dual-reversion"]["wins"] == 1


def test_build_ticks_covers_every_snapshot():
    window = generate_synthetic_window()
    ticks = build_ticks(window.snapshots)
    assert len(ticks) == len(window.snapshots)
    assert len(ticks[0]["signals"]) == len(STRATEGIES)
    assert "direction" in ticks[0]["signals"][0]["signal"]
