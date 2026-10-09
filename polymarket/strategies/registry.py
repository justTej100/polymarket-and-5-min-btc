"""The canonical strategy set (port of lib/strategies/index.ts).

Single source of truth: the runner, the paper-trading engine, the copy trader
and the browser payload all read from here. Add a strategy by writing a file
that exports a Strategy instance and adding it to this list -- nothing else
needs to change.

The strategies mirror the strategy spec 1:1 (the old separate MACD, RSI, VWAP
and stacking bots were merged into momentum-confluence so there are no
duplicates). Strategy 1 runs in three flavors with different entry thresholds
so the leaderboard shows which "cheap" actually pays -- 9 strategies, 11 books.
"""

from __future__ import annotations

from .base import Strategy
from .cross_market_lag import cross_market_lag
from .dual_reversion import dual_reversion
from .dump_hedge import dump_hedge
from .fibonacci import fibonacci
from .lottery import lottery_5c, lottery_30c, lottery_40c
from .martingale45 import martingale45
from .momentum_confluence import momentum_confluence
from .pre_order_open import pre_order_open
from .sniper99 import sniper99

STRATEGIES: list[Strategy] = [
    lottery_5c,  # 1a -- lottery ticket, side under 5c
    lottery_30c,  # 1b -- underdog under 30c
    lottery_40c,  # 1c -- underdog under 40c
    sniper99,  # 2 -- 99c Sniper (Near-Resolution Strike)
    dual_reversion,  # 3 -- Low-Side Dual Reversion
    pre_order_open,  # 4 -- Pre-Order Market (Queue Positioning)
    cross_market_lag,  # 5 -- Cross-Market Bot (Lead-Lag)
    martingale45,  # 6 -- Martingale / Anti-Martingale at 45c
    fibonacci,  # 7 -- Fibonacci Levels
    momentum_confluence,  # 8 -- Binary Momentum (MACD / RSI / VWAP)
    dump_hedge,  # 9 -- Dump-Hedge (Sharp Move Arbitrage)
]

STRATEGIES_BY_ID: dict[str, Strategy] = {s.id: s for s in STRATEGIES}
