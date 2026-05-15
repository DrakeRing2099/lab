"""
Continuous producer runner.

Runs all three producers concurrently via asyncio.gather().

WHY asyncio.gather()?
──────────────────────
Each producer is an infinite async loop. gather() runs them
concurrently on a single thread — no OS threads, no GIL issues.
While one producer is awaiting asyncio.sleep(), the event loop
switches to another. This is cooperative multitasking.

The key insight: our producers spend most of their time sleeping
(waiting between cycles). async/await is perfect for I/O-bound
and sleep-heavy workloads. If we were doing CPU-heavy work (e.g.
running a neural net to generate orders), we'd use ProcessPoolExecutor
instead. But for network I/O + sleeps, asyncio is ideal.

SHUTDOWN
─────────
Ctrl+C raises KeyboardInterrupt → we cancel all tasks →
each producer catches CancelledError and closes its Redis connection.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from src.config import BIDS_KEY, ASKS_KEY, MID_PRICE_KEY, get_async_redis
from src.producers.market_maker import MarketMaker
from src.producers.trend_follower import TrendFollower
from src.producers.noise_trader import NoiseTrader


async def main():
    # Fresh start — clear the book and reset mid price
    r = get_async_redis()
    await r.delete(BIDS_KEY, ASKS_KEY, MID_PRICE_KEY)
    await r.aclose()
    print("[producers] Book cleared, starting producers...\n")

    producers = [
        MarketMaker(
            trader_id="market-maker",
            spread_bps=50.0,
            base_qty=8.0,
            interval=0.4,
        ),
        TrendFollower(
            trader_id="trend-follower",
            window=8,
            threshold=0.0015,
            base_qty=12.0,
            interval=1.2,
        ),
        NoiseTrader(
            trader_id="noise-trader",
            mu=0.0,
            sigma=0.002,
            base_qty=5.0,
            interval=0.6,
        ),
    ]

    tasks = [asyncio.create_task(p.run()) for p in producers]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[producers] Cancelling tasks...")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("[producers] Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass