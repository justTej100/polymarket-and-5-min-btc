"""Replay historical snapshots through the live strategy functions.

Port of lib/worker/backtestRunner.ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from polymarket.strategies.base import BOTH, NEUTRAL, YES, MarketHistory, MarketSnapshot
from polymarket.strategies.registry import STRATEGIES


@dataclass
class BacktestResult:
    strategy_id: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    pnl_usd: float
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategyId": self.strategy_id,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "winRate": self.win_rate,
            "pnlUsd": self.pnl_usd,
            "history": self.history,
        }


def run_backtest_on_window(
    snapshots: list[MarketSnapshot], final_outcome: str
) -> list[BacktestResult]:
    """Evaluate every strategy across one window; BOTH counts as a win."""
    results: list[BacktestResult] = []

    for strategy in STRATEGIES:
        trades = 0
        wins = 0
        losses = 0
        pnl_usd = 0.0
        history: list[dict] = []
        last_direction: Optional[str] = None

        for i, snapshot in enumerate(snapshots):
            past = MarketHistory(snapshots=snapshots[: i + 1])
            signal = strategy.evaluate(snapshot, past)

            if signal.direction == BOTH:
                entry_cost_usd = snapshot.yes_price + snapshot.no_price
            elif signal.direction == YES:
                entry_cost_usd = snapshot.yes_price
            else:
                entry_cost_usd = snapshot.no_price

            trade_pnl = 0.0
            if signal.direction != NEUTRAL and signal.direction != last_direction:
                if signal.direction == BOTH or signal.direction == final_outcome:
                    trade_pnl = 1 - entry_cost_usd
                else:
                    trade_pnl = -entry_cost_usd

            history.append(
                {
                    "timestamp": snapshot.timestamp,
                    "direction": signal.direction,
                    "confidence": signal.confidence,
                    "pnlUsd": trade_pnl,
                }
            )

            if signal.direction != NEUTRAL and signal.direction != last_direction:
                trades += 1
                pnl_usd += trade_pnl
                if signal.direction == BOTH or signal.direction == final_outcome:
                    wins += 1
                else:
                    losses += 1

            if signal.direction != NEUTRAL:
                last_direction = signal.direction

        results.append(
            BacktestResult(
                strategy_id=strategy.id,
                trades=trades,
                wins=wins,
                losses=losses,
                win_rate=(wins / trades) if trades > 0 else 0.0,
                pnl_usd=pnl_usd,
                history=history,
            )
        )

    return results


def run_backtest_on_many_windows(
    windows: list[dict],
) -> dict[str, dict]:
    """Aggregate per-strategy stats across many windows."""
    totals: dict[str, dict] = {}

    for window in windows:
        results = run_backtest_on_window(window["snapshots"], window["final_outcome"])
        for r in results:
            prev = totals.get(r.strategy_id) or {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnlUsd": 0.0,
            }
            totals[r.strategy_id] = {
                "trades": prev["trades"] + r.trades,
                "wins": prev["wins"] + r.wins,
                "losses": prev["losses"] + r.losses,
                "pnlUsd": prev["pnlUsd"] + r.pnl_usd,
            }

    summary: dict[str, dict] = {}
    for strategy_id, t in totals.items():
        trades = t["trades"]
        summary[strategy_id] = {
            **t,
            "winRate": (t["wins"] / trades) if trades > 0 else 0.0,
        }
    return summary


def build_ticks(snapshots: list[MarketSnapshot]) -> list[dict]:
    """Per-tick signals for the simulation scrubber (strategies stay server-side)."""
    ticks: list[dict] = []
    for i, snapshot in enumerate(snapshots):
        past = MarketHistory(snapshots=snapshots[: i + 1])
        signals = [
            {
                "id": strategy.id,
                "name": strategy.name,
                "description": strategy.description,
                "signal": strategy.evaluate(snapshot, past).to_dict(),
            }
            for strategy in STRATEGIES
        ]
        ticks.append({"signals": signals})
    return ticks


async def build_backtest_payload() -> dict:
    """Historical if possible, else synthetic — same fallback as the Next.js API."""
    from polymarket.feed.historical import fetch_historical_window
    from polymarket.feed.synthetic import generate_synthetic_window

    source = "historical"
    try:
        window = await fetch_historical_window()
    except Exception:  # noqa: BLE001
        window = generate_synthetic_window()
        source = "synthetic"

    results = run_backtest_on_window(window.snapshots, window.final_outcome)
    ticks = build_ticks(window.snapshots)

    return {
        "source": source,
        "conditionId": window.condition_id,
        "priceToBeat": window.price_to_beat,
        "finalOutcome": window.final_outcome,
        "snapshots": [s.to_dict() for s in window.snapshots],
        "results": [r.to_dict() for r in results],
        "ticks": ticks,
    }
