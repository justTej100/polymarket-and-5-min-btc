"""Strategy 8 -- Binary Momentum (MACD / RSI / VWAP confluence).

Port of lib/strategies/momentumConfluence.ts.

Three indicators on 5-second bars of the token price, combined into a
confluence score. Replaces (and dedupes) the old separate MACD, RSI, VWAP and
stacking strategies -- one strategy, one score.

Score:  MACD trend state +2 - histogram building +1 - RSI 40-65 +1 -
        price on the right side of the session average +1 - minus 1 when
        stretched >10c from that average.
Enter at score >=4, hold while >=3, flat below that or on RSI extremes.
"""

from __future__ import annotations

from .base import (
    NEUTRAL,
    NO,
    YES,
    MarketHistory,
    MarketSnapshot,
    Signal,
    Strategy,
    clamp,
    ema,
    resample_bars,
    rsi,
)

BAR_SECONDS = 5
MACD_FAST = 3
MACD_SLOW = 8
MACD_SIGNAL = 3
RSI_PERIOD = 14
STRETCH_LIMIT = 0.1
ENTER_SCORE = 4
HOLD_SCORE = 3


class MomentumConfluence(Strategy):
    id = "momentum-confluence"
    name = "Momentum Confluence"
    description = (
        "MACD (3/8/3), RSI (14) and a session-average anchor, all on 5-second bars of the token "
        "price, rolled into one confluence score. Enters only when 4+ points of signal agree, "
        "holds at 3, and flattens below that \u2014 or immediately on an RSI extreme (>75 / <25), "
        "which it treats as a take-profit bell. One strategy instead of four separate indicator "
        "bots."
    )

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        bars = resample_bars(history, BAR_SECONDS, lambda s: s.yes_price)
        if len(bars) < MACD_SLOW + MACD_SIGNAL + 1:
            return Signal(NEUTRAL, 0, "Warming up (needs ~1 min of 5s bars)")

        fast = ema(bars, MACD_FAST)
        slow = ema(bars, MACD_SLOW)
        macd_line = [fast[i] - slow[i] for i in range(len(fast))]
        signal_line = ema(macd_line, MACD_SIGNAL)
        hist = macd_line[-1] - signal_line[-1]
        prev_hist = macd_line[-2] - signal_line[-2]

        rsi_val = rsi(bars, RSI_PERIOD)
        # TWAP stand-in for VWAP (the token feed has no per-trade volume).
        anchor = sum(bars) / len(bars)
        price = snapshot.yes_price
        stretched = abs(price - anchor) > STRETCH_LIMIT

        bull_score = 0
        if hist > 0:
            bull_score += 2  # MACD above its signal line
        if hist > prev_hist:
            bull_score += 1  # histogram building
        if rsi_val is not None and 40 <= rsi_val <= 65:
            bull_score += 1
        if price > anchor:
            bull_score += 1
        if stretched:
            bull_score -= 1

        bear_score = 0
        if hist < 0:
            bear_score += 2
        if hist < prev_hist:
            bear_score += 1
        if rsi_val is not None and 35 <= rsi_val <= 60:
            bear_score += 1
        if price < anchor:
            bear_score += 1
        if stretched:
            bear_score -= 1

        # RSI extremes are exit bells regardless of score.
        if rsi_val is not None and rsi_val >= 75 and bull_score >= bear_score:
            return Signal(NEUTRAL, 0, f"RSI {rsi_val:.0f} overbought \u2014 taking profit")
        if rsi_val is not None and rsi_val <= 25 and bear_score >= bull_score:
            return Signal(NEUTRAL, 0, f"RSI {rsi_val:.0f} oversold \u2014 taking profit")

        rsi_label = f"{rsi_val:.0f}" if rsi_val is not None else "\u2013"

        if bull_score >= ENTER_SCORE and bull_score > bear_score:
            return Signal(
                YES,
                clamp(bull_score / 5, 0.4, 1),
                f"Bullish confluence {bull_score}/5 (MACD+, RSI {rsi_label}, above anchor)",
            )
        if bear_score >= ENTER_SCORE and bear_score > bull_score:
            return Signal(
                NO,
                clamp(bear_score / 5, 0.4, 1),
                f"Bearish confluence {bear_score}/5 (MACD-, RSI {rsi_label}, below anchor)",
            )
        if bull_score >= HOLD_SCORE and bull_score > bear_score:
            return Signal(YES, 0.3, f"Holding \u2014 bullish score {bull_score}/5")
        if bear_score >= HOLD_SCORE and bear_score > bull_score:
            return Signal(NO, 0.3, f"Holding \u2014 bearish score {bear_score}/5")

        return Signal(
            NEUTRAL,
            0,
            f"Score too low (bull {max(bull_score, 0)}, bear {max(bear_score, 0)}) \u2014 need 4+ "
            f"to enter",
        )


momentum_confluence = MomentumConfluence()
