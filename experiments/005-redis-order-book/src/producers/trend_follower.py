"""
Trend Follower producer.

REAL-WORLD ANALOGY
───────────────────
A trend follower (CTA, momentum fund) bets that price will continue
moving in the direction it's already going. They buy when price is
rising, sell when it's falling. They're often the ones who cause
overshoots and reversals.

BEHAVIOR
─────────
Tracks the last N mid prices (rolling window). Computes a simple
momentum signal: (current_mid - oldest_mid) / oldest_mid.

  momentum > +threshold  → send aggressive BID (buy into the rally)
  momentum < -threshold  → send aggressive ASK (sell into the drop)
  |momentum| < threshold → do nothing (no clear trend)

"Aggressive" means pricing slightly THROUGH the mid — a bid slightly
above mid, ask slightly below. This ensures the order crosses the
book immediately rather than resting. The trend follower is a taker,
not a maker.

This is why trend followers cause momentum: they pile on in the
direction of price movement, which pushes price further.

PARAMETERS
───────────
window       : number of mid price observations to track
threshold    : minimum momentum (as fraction) to trigger an order
aggression   : how far through the mid to price (as bps)
base_qty     : order size
interval     : seconds between checks (slower than MM — 1.2s)
"""

from __future__ import annotations

import random
from collections import deque

from src.models import Order, OrderType, Side
from src.producers.base import BaseProducer


class TrendFollower(BaseProducer):
    def __init__(
        self,
        trader_id: str  = "trend-follower",
        window: int     = 8,
        threshold: float= 0.0015,   # 0.15% move triggers a trade
        aggression: float = 30.0,   # bps through mid
        base_qty: float = 12.0,
        interval: float = 1.2,
    ):
        super().__init__(trader_id, interval)
        self.window     = window
        self.threshold  = threshold
        self.aggression = aggression
        self.base_qty   = base_qty
        self._price_history: deque[float] = deque(maxlen=window)

    async def generate_orders(self, mid: float) -> list[Order]:
        self._price_history.append(mid)

        # Need a full window before we can compute momentum
        if len(self._price_history) < self.window:
            return []

        oldest  = self._price_history[0]
        momentum = (mid - oldest) / oldest

        if abs(momentum) < self.threshold:
            return []   # flat market, sit on hands

        # Price aggressively through mid to ensure immediate execution
        through = mid * (self.aggression / 10_000)
        qty     = round(self.base_qty * random.uniform(0.8, 1.3), 1)

        if momentum > 0:
            # Uptrend — buy aggressively
            price = round(mid + through, 2)
            return [Order.create(self.trader_id, Side.BID, qty=qty,
                                 price=price, order_type=OrderType.LIMIT)]
        else:
            # Downtrend — sell aggressively
            price = round(mid - through, 2)
            return [Order.create(self.trader_id, Side.ASK, qty=qty,
                                 price=price, order_type=OrderType.LIMIT)]