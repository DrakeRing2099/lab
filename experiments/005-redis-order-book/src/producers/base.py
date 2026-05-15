"""
Abstract base class for all producers.

Every producer shares the same skeleton:
  - holds a Redis connection
  - knows the current mid price (read from Redis)
  - implements generate_orders() — the behavioral logic
  - runs in an async loop via run()

WHY READ MID PRICE FROM REDIS?
────────────────────────────────
All three producers need a shared reference price to quote around.
We store it in Redis (book:mid) so every producer sees the same
value — even if you later run producers in separate processes.
This is the "single source of truth" pattern. If each producer
tracked its own mid price internally, they'd drift apart and
produce unrealistic order flow.

The matching engine updates book:mid every time a trade executes.
Producers poll it at the start of each cycle. So price discovery
is real — trades move the mid, producers react to the new mid.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import redis.asyncio as aioredis

from src.config import INITIAL_MID_PRICE, MID_PRICE_KEY, get_async_redis
from src.consumer.book import publish_order
from src.models import Order


class BaseProducer(ABC):
    def __init__(self, trader_id: str, interval: float):
        """
        trader_id : identifies this producer in trade records
        interval  : seconds between order generation cycles
        """
        self.trader_id = trader_id
        self.interval  = interval
        self.r: aioredis.Redis | None = None

    async def get_mid_price(self) -> float:
        """
        Read current mid price from Redis.
        Falls back to INITIAL_MID_PRICE if not set yet.
        """
        val = await self.r.get(MID_PRICE_KEY)
        return float(val) if val else INITIAL_MID_PRICE

    async def send(self, order: Order) -> None:
        """Publish one order to the stream."""
        await publish_order(self.r, order)

    @abstractmethod
    async def generate_orders(self, mid: float) -> list[Order]:
        """
        Given the current mid price, return orders to send this cycle.
        Each subclass implements its own behavioral logic here.
        """
        ...

    async def run(self) -> None:
        """
        Main loop. Runs forever until cancelled.

        Each cycle:
          1. Read mid price
          2. Generate orders (subclass logic)
          3. Publish each order to the stream
          4. Sleep for interval

        asyncio.CancelledError is the clean shutdown signal —
        we let it propagate so the gather() in run_producers.py
        can shut everything down gracefully.
        """
        self.r = get_async_redis()
        print(f"[{self.trader_id}] starting, interval={self.interval}s")
        try:
            while True:
                mid = await self.get_mid_price()
                orders = await self.generate_orders(mid)
                for order in orders:
                    await self.send(order)
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            print(f"[{self.trader_id}] shutting down")
            await self.r.aclose()