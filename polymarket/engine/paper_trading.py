"""Paper-trading engine.

Port of lib/worker/paperTrading.ts.

Every strategy gets an imaginary bankroll and trades it live. Entries fill at
the real ask, exits at the real bid, and anything still held when the 5-minute
window closes settles at $1 (win) or $0 (loss). The engine keeps a full trade
ledger plus per-window standings so the UI can show who made the most money,
when they traded, and for how much.

It also fires a "trade" callback for every BUY/SELL, which the copy trader
(engine/copy_trading.py) mirrors onto a real Polymarket account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..strategies import STRATEGIES
from ..strategies.base import BOTH, NEUTRAL, NO, YES, MarketHistory, MarketSnapshot

STARTING_BANKROLL = 1_000
MAX_STAKE_USD = 100
MIN_STAKE_USD = 5
LEDGER_LIMIT = 250
WINDOW_HISTORY_LIMIT = 24
EVAL_MIN_GAP_MS = 900

# TradeAction: "BUY" | "SELL" | "WIN" | "LOSS"
# TradeSide:   "UP" | "DOWN"


@dataclass
class PaperTrade:
    id: str
    strategy_id: str
    strategy_name: str
    timestamp: int
    action: str
    side: str
    price: float  # per-share fill price (0-1)
    shares: float
    amount_usd: float  # cost for BUY, proceeds for SELL/WIN/LOSS
    note: str
    condition_id: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategyId": self.strategy_id,
            "strategyName": self.strategy_name,
            "timestamp": self.timestamp,
            "action": self.action,
            "side": self.side,
            "price": self.price,
            "shares": self.shares,
            "amountUsd": self.amount_usd,
            "note": self.note,
            "conditionId": self.condition_id,
        }


@dataclass
class OpenLot:
    side: str
    shares: float
    cost_usd: float
    entry_price: float
    opened_at: int


@dataclass
class StrategyBook:
    bankroll: float = STARTING_BANKROLL
    lots: list[OpenLot] = field(default_factory=list)
    last_direction: str = NEUTRAL
    window_pnl: float = 0.0
    total_pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    trades: int = 0


@dataclass
class WindowResult:
    condition_id: str
    question: str
    closed_at: int
    outcome: str
    results: list[dict]
    winner_id: Optional[str]

    def to_dict(self) -> dict:
        return {
            "conditionId": self.condition_id,
            "question": self.question,
            "closedAt": self.closed_at,
            "outcome": self.outcome,
            "results": self.results,
            "winnerId": self.winner_id,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def _round2(value: float) -> float:
    """JavaScript's Math.round(v * 100) / 100 -- half away from zero, unlike
    Python's banker's rounding, so the ledger matches the original cent for
    cent."""
    scaled = value * 100
    rounded = int(scaled + 0.5) if scaled >= 0 else -int(-scaled + 0.5)
    return rounded / 100


class PaperTradingEngine:
    def __init__(self) -> None:
        self._books: dict[str, StrategyBook] = {s.id: StrategyBook() for s in STRATEGIES}
        self._ledger: list[PaperTrade] = []
        self._windows: list[WindowResult] = []
        self._last_eval_ts = 0
        self._trade_seq = 0
        self._trade_listeners: list[Callable[[PaperTrade], None]] = []

    def on_trade(self, listener: Callable[[PaperTrade], None]) -> None:
        self._trade_listeners.append(listener)

    # -- fill prices ---------------------------------------------------------

    def _ask_for(self, side: str, snapshot: MarketSnapshot) -> float:
        if side == "UP":
            price = snapshot.up_ask if snapshot.up_ask is not None else snapshot.yes_price
        else:
            price = snapshot.down_ask if snapshot.down_ask is not None else snapshot.no_price
        return _clamp(price, 0.01, 0.99)

    def _bid_for(self, side: str, snapshot: MarketSnapshot) -> float:
        if side == "UP":
            price = snapshot.up_bid if snapshot.up_bid is not None else snapshot.yes_price
        else:
            price = snapshot.down_bid if snapshot.down_bid is not None else snapshot.no_price
        return _clamp(price, 0.01, 0.99)

    # -- ledger --------------------------------------------------------------

    def _record(self, **fields) -> PaperTrade:
        entry = PaperTrade(id=f"{fields['timestamp']}-{self._trade_seq}", **fields)
        self._trade_seq += 1
        self._ledger.insert(0, entry)
        if len(self._ledger) > LEDGER_LIMIT:
            self._ledger.pop()
        for listener in list(self._trade_listeners):
            listener(entry)
        return entry

    # -- trading -------------------------------------------------------------

    def _close_lots(
        self,
        strategy_id: str,
        strategy_name: str,
        book: StrategyBook,
        snapshot: MarketSnapshot,
        reason: str,
    ) -> None:
        for lot in book.lots:
            price = self._bid_for(lot.side, snapshot)
            proceeds = _round2(lot.shares * price)
            pnl = _round2(proceeds - lot.cost_usd)
            book.bankroll = _round2(book.bankroll + proceeds)
            book.window_pnl = _round2(book.window_pnl + pnl)
            book.total_pnl = _round2(book.total_pnl + pnl)

            sign = "+" if pnl >= 0 else ""
            self._record(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                timestamp=snapshot.timestamp,
                action="SELL",
                side=lot.side,
                price=price,
                shares=lot.shares,
                amount_usd=proceeds,
                note=(
                    f"{reason} \u00b7 entered at {lot.entry_price * 100:.1f}\u00a2, "
                    f"{sign}${pnl:.2f}"
                ),
                condition_id=snapshot.condition_id,
            )
        book.lots = []

    def _open_lot(
        self,
        strategy_id: str,
        strategy_name: str,
        book: StrategyBook,
        snapshot: MarketSnapshot,
        side: str,
        stake_usd: float,
        note: str,
    ) -> None:
        price = self._ask_for(side, snapshot)
        cost = _round2(min(stake_usd, book.bankroll))
        if cost < MIN_STAKE_USD:
            return

        shares = _round2(cost / price)
        book.bankroll = _round2(book.bankroll - cost)
        book.trades += 1
        book.lots.append(
            OpenLot(
                side=side,
                shares=shares,
                cost_usd=cost,
                entry_price=price,
                opened_at=snapshot.timestamp,
            )
        )

        self._record(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            timestamp=snapshot.timestamp,
            action="BUY",
            side=side,
            price=price,
            shares=shares,
            amount_usd=cost,
            note=note,
            condition_id=snapshot.condition_id,
        )

    def on_snapshot(self, snapshot: MarketSnapshot, history: list[MarketSnapshot]) -> None:
        """Runs every strategy against the latest snapshot and executes changes."""
        if snapshot.timestamp - self._last_eval_ts < EVAL_MIN_GAP_MS:
            return
        self._last_eval_ts = snapshot.timestamp

        market_history = MarketHistory(snapshots=history)

        for strategy in STRATEGIES:
            book = self._books[strategy.id]
            signal = strategy.evaluate(snapshot, market_history)

            if signal.direction == book.last_direction:
                continue

            # Direction changed: flatten the old position first.
            if book.lots:
                self._close_lots(strategy.id, strategy.name, book, snapshot, "flipped signal")

            stake = _round2(MAX_STAKE_USD * _clamp(signal.confidence, 0.25, 1))

            if signal.direction == YES:
                self._open_lot(
                    strategy.id, strategy.name, book, snapshot, "UP", stake, signal.note
                )
            elif signal.direction == NO:
                self._open_lot(
                    strategy.id, strategy.name, book, snapshot, "DOWN", stake, signal.note
                )
            elif signal.direction == BOTH:
                self._open_lot(
                    strategy.id, strategy.name, book, snapshot, "UP", stake / 2, signal.note
                )
                self._open_lot(
                    strategy.id, strategy.name, book, snapshot, "DOWN", stake / 2, signal.note
                )

            book.last_direction = signal.direction

    def on_window_end(self, final_snapshot: MarketSnapshot) -> None:
        """Settles all open positions when a 5-minute window closes."""
        outcome = "UP" if final_snapshot.current_price >= final_snapshot.price_to_beat else "DOWN"

        results: list[dict] = []

        for strategy in STRATEGIES:
            book = self._books[strategy.id]

            traded_this_window = bool(book.lots) or book.window_pnl != 0

            for lot in book.lots:
                won = lot.side == outcome
                payout = _round2(lot.shares) if won else 0  # $1 per winning share
                pnl = _round2(payout - lot.cost_usd)
                book.bankroll = _round2(book.bankroll + payout)
                book.window_pnl = _round2(book.window_pnl + pnl)
                book.total_pnl = _round2(book.total_pnl + pnl)

                sign = "+" if pnl >= 0 else ""
                self._record(
                    strategy_id=strategy.id,
                    strategy_name=strategy.name,
                    timestamp=final_snapshot.timestamp,
                    action="WIN" if won else "LOSS",
                    side=lot.side,
                    price=1 if won else 0,
                    shares=lot.shares,
                    amount_usd=payout,
                    note=f"window resolved {outcome} \u00b7 {sign}${pnl:.2f}",
                    condition_id=final_snapshot.condition_id,
                )

            # W/L = did the strategy end the window with more money than it
            # started with? Only windows where it actually traded count.
            if traded_this_window:
                if book.window_pnl > 0:
                    book.wins += 1
                elif book.window_pnl < 0:
                    book.losses += 1

            book.lots = []
            book.last_direction = NEUTRAL
            results.append(
                {
                    "strategyId": strategy.id,
                    "strategyName": strategy.name,
                    "pnlUsd": book.window_pnl,
                }
            )
            book.window_pnl = 0

        ordered = sorted(results, key=lambda r: r["pnlUsd"], reverse=True)
        winner = ordered[0] if ordered else None

        self._windows.insert(
            0,
            WindowResult(
                condition_id=final_snapshot.condition_id,
                question=final_snapshot.question or final_snapshot.condition_id,
                closed_at=final_snapshot.timestamp,
                outcome=outcome,
                results=ordered,
                winner_id=winner["strategyId"] if winner else None,
            ),
        )
        if len(self._windows) > WINDOW_HISTORY_LIMIT:
            self._windows.pop()

    # -- public state for the UI ---------------------------------------------

    def get_public_state(self, latest_snapshot: Optional[MarketSnapshot]) -> dict:
        standings = []
        for strategy in STRATEGIES:
            book = self._books[strategy.id]
            open_positions = []
            for lot in book.lots:
                mark_price = (
                    self._bid_for(lot.side, latest_snapshot)
                    if latest_snapshot
                    else lot.entry_price
                )
                open_positions.append(
                    {
                        "side": lot.side,
                        "shares": lot.shares,
                        "entryPrice": lot.entry_price,
                        "markPrice": mark_price,
                        "valueUsd": _round2(lot.shares * mark_price),
                    }
                )
            open_value = sum(p["valueUsd"] for p in open_positions)

            standings.append(
                {
                    "strategyId": strategy.id,
                    "strategyName": strategy.name,
                    "bankroll": book.bankroll,
                    "equity": _round2(book.bankroll + open_value),
                    "windowPnl": book.window_pnl,
                    "totalPnl": book.total_pnl,
                    "wins": book.wins,
                    "losses": book.losses,
                    "trades": book.trades,
                    "openPositions": open_positions,
                }
            )

        # Rank by plain cash -- real dollars in hand, no mark-to-market guessing.
        standings.sort(key=lambda s: s["bankroll"], reverse=True)

        return {
            "startingBankroll": STARTING_BANKROLL,
            "standings": standings,
            "ledger": [t.to_dict() for t in self._ledger[:80]],
            "windows": [w.to_dict() for w in self._windows[:12]],
        }


# One book of record for the whole process.
paper_engine = PaperTradingEngine()
