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
Every cycle:
  1. Cancel all own resting orders (quote refresh)
  2. Quote new BID at (mid - half_spread)
  3. Quote new ASK at (mid + half_spread)

WHY CANCEL BEFORE REQUOTING?
──────────────────────────────
Without cancellation, old quotes pile up in the book at stale
prices. When the mid drifts, those stale quotes become mispriced —
e.g. a bid placed at 99.80 when mid was 100.0 is now a very
generous bid if mid has drifted to 98.0. Other traders will pick
it off immediately (this is called "being picked off" or "adverse
selection"). Real MMs cancel and requote hundreds of times per
second precisely to avoid this.

We track resting order IDs in self._resting. Before each cycle we
ZREM + DEL every ID we placed last cycle, then place fresh quotes.
This keeps the book clean — only the current cycle's MM orders
are ever live.

QUOTE CANCELLATION vs SELF-TRADE PREVENTION
─────────────────────────────────────────────
These solve different problems:
  STP (engine)          — prevents matching your own orders
  Quote cancellation    — prevents stale orders sitting in the book

Both are needed. STP alone means stale quotes rest forever,
blocking liquidity for other traders. Cancellation alone without
STP means a brief race window where new quote crosses old quote.
Together they're clean.

PARAMETERS
───────────
spread_bps  : half-spread in basis points (1 bps = 0.01%)
              100 bps = 1% of mid. Default 50bps = 0.5%.
base_qty    : base order size (randomized ±50%)
interval    : seconds between quote cycles (fast — 0.4s)
"""

from __future__ import annotations

import random

from src.config import BIDS_KEY, ASKS_KEY, ORDER_DATA_PREFIX
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
        # Track IDs of our own resting orders so we can cancel them
        self._resting_bid_id: str | None = None
        self._resting_ask_id: str | None = None

    async def _cancel_resting(self) -> None:
        """
        Remove our previous cycle's quotes from the book.

        ZREM book:bids <order_id>   — removes from sorted set
        DEL  order:<order_id>        — removes the hash

        We pipeline both sides together — 4 commands, 1 round-trip.
        If an order was already filled by the engine, ZREM and DEL
        are no-ops (Redis ignores missing keys), so this is safe.
        """
        if not self._resting_bid_id and not self._resting_ask_id:
            return

        pipe = self.r.pipeline()
        if self._resting_bid_id:
            pipe.zrem(BIDS_KEY, self._resting_bid_id)
            pipe.delete(f"{ORDER_DATA_PREFIX}{self._resting_bid_id}")
        if self._resting_ask_id:
            pipe.zrem(ASKS_KEY, self._resting_ask_id)
            pipe.delete(f"{ORDER_DATA_PREFIX}{self._resting_ask_id}")
        await pipe.execute()

        self._resting_bid_id = None
        self._resting_ask_id = None

    async def generate_orders(self, mid: float) -> list[Order]:
        # Cancel stale quotes before placing fresh ones
        await self._cancel_resting()

        # Add a small random jitter to the spread each cycle —
        # simulates the MM adjusting to perceived volatility
        spread_jitter = random.uniform(0.8, 1.4)
        half_spread   = mid * (self.spread_bps / 10_000) * spread_jitter

        bid_price = round(mid - half_spread, 2)
        ask_price = round(mid + half_spread, 2)

        qty_bid = round(self.base_qty * random.uniform(0.5, 1.5), 1)
        qty_ask = round(self.base_qty * random.uniform(0.5, 1.5), 1)

        bid = Order.create(self.trader_id, Side.BID, qty=qty_bid,
                           price=bid_price, order_type=OrderType.LIMIT)
        ask = Order.create(self.trader_id, Side.ASK, qty=qty_ask,
                           price=ask_price, order_type=OrderType.LIMIT)

        # Remember these IDs for cancellation next cycle
        self._resting_bid_id = bid.order_id
        self._resting_ask_id = ask.order_id

        return [bid, ask]