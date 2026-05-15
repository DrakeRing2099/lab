"""
Market Maker producer.

REAL-WORLD ANALOGY
───────────────────
A market maker (Citadel, Virtu, Jane Street) continuously quotes
both a bid and an ask. They profit from the spread — buy at bid,
sell at ask, pocket the difference. They don't have a directional
view; they just want volume and tight spreads.

BEHAVIOR
─────────
Every cycle, quotes TWO orders simultaneously:
  BID at (mid - half_spread)
  ASK at (mid + half_spread)

Both at randomized qty around a base size.
High frequency, small spread, consistent presence.

The spread itself widens slightly with a volatility term — when
the market is moving fast (simulated by spread_bps jitter), the
market maker protects itself by quoting wider. This is realistic:
real MMs widen spreads during volatile periods to avoid getting
picked off by informed traders.

PARAMETERS
───────────
spread_bps  : half-spread in basis points (1 bps = 0.01%)
              100 bps = 1% of mid. Default 50bps = 0.5%.
base_qty    : base order size (randomized ±50%)
interval    : seconds between quote cycles (fast — 0.4s)
"""

from __future__ import annotations

import random

from src.models import Order, OrderType, Side
from src.producers.base import BaseProducer


class MarketMaker(BaseProducer):
    def __init__(
        self,
        trader_id: str = "market-maker",
        spread_bps: float = 50.0,
        base_qty: float = 8.0,
        interval: float = 0.4,
    ):
        super().__init__(trader_id, interval)
        self.spread_bps = spread_bps
        self.base_qty   = base_qty

    async def generate_orders(self, mid: float) -> list[Order]:
        # Add a small random jitter to the spread each cycle —
        # simulates the MM adjusting to perceived volatility
        spread_jitter = random.uniform(0.8, 1.4)
        half_spread   = mid * (self.spread_bps / 10_000) * spread_jitter

        bid_price = round(mid - half_spread, 2)
        ask_price = round(mid + half_spread, 2)

        # Randomize qty ±50% around base — MMs vary their size
        qty_bid = round(self.base_qty * random.uniform(0.5, 1.5), 1)
        qty_ask = round(self.base_qty * random.uniform(0.5, 1.5), 1)

        return [
            Order.create(self.trader_id, Side.BID, qty=qty_bid,
                         price=bid_price, order_type=OrderType.LIMIT),
            Order.create(self.trader_id, Side.ASK, qty=qty_ask,
                         price=ask_price, order_type=OrderType.LIMIT),
        ]