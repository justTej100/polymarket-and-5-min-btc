# rl — future work

Future work: an RL agent trained on this same strategy interface.

Nothing here yet. The interface it would implement already exists and is
stable — every strategy in `polymarket/strategies/` is the same shape:

```python
class Strategy:
    id: str
    name: str
    description: str

    def evaluate(self, snapshot: MarketSnapshot, history: MarketHistory) -> Signal:
        ...
```

A learned policy is a `Strategy` whose `evaluate` runs a forward pass instead
of a rule. Drop it into `polymarket/strategies/registry.py` and it gets a
$1,000 paper bankroll, a row on the leaderboard and the ability to be copy
traded, exactly like the nine hand-written ones — no other code changes.

That also makes the board a ready-made evaluation harness: the rule-based
strategies become baselines an agent has to beat on the same live feed, with
the same fills, over the same 5-minute windows.
