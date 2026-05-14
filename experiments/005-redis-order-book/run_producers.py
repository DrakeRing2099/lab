"""
Burst producer — fires synthetic orders to test the matching engine.

This is a temporary script for Phase 2 testing. In Phase 3 we'll
replace this with three behavioral producer classes that run
continuously with realistic order flow.

HOW IT WORKS
─────────────
Sends a scripted sequence of orders designed to produce:
  - Some resting orders (bids and asks that don't cross)
  - Some immediate matches (crossing orders)
  - A partial fill scenario
  - A market order

Run this AFTER starting run_consumer.py so you can watch the
engine process each order in real time.
"""

import asyncio
import sys
import time

sys.path.insert(0, ".")

from src.config import get_async_redis, STREAM_KEY, BIDS_KEY, ASKS_KEY
from src.consumer.book import publish_order
from src.models import Order, OrderType, Side


async def burst():
    r = get_async_redis()

    # Clean slate
    print("🧹  Flushing book...")
    await r.delete(BIDS_KEY, ASKS_KEY)

    print("📤  Sending orders...\n")
    await asyncio.sleep(0.1)

    async def send(order: Order, label: str = ""):
        sid = await publish_order(r, order)
        price_str = f"{order.price:.2f}" if order.price else "MARKET"
        print(f"  → {order.side.value.upper():3s}  {order.qty:5.1f} @ {price_str:>8}  "
              f"trader={order.trader_id:15s}  stream_id={sid}  {label}")
        await asyncio.sleep(0.15)   # small delay so engine can keep up

    # ── Phase 1: seed the book with resting orders ───────────────
    print("── Seeding book (no matches expected) ──")
    await send(Order.create("market-maker", Side.BID, qty=10.0, price=99.0),  "rests in book")
    await send(Order.create("market-maker", Side.BID, qty=5.0,  price=98.5),  "rests in book")
    await send(Order.create("market-maker", Side.BID, qty=8.0,  price=98.0),  "rests in book")
    await send(Order.create("market-maker", Side.ASK, qty=10.0, price=101.0), "rests in book")
    await send(Order.create("market-maker", Side.ASK, qty=5.0,  price=101.5), "rests in book")
    await send(Order.create("market-maker", Side.ASK, qty=8.0,  price=102.0), "rests in book")
    await asyncio.sleep(0.5)

    # ── Phase 2: crossing orders — should generate trades ────────
    print("\n── Crossing orders (matches expected) ──")

    # This bid at 101.5 crosses the ask at 101.0 → TRADE
    await send(Order.create("trend-follower", Side.BID, qty=10.0, price=101.5), "should MATCH ask@101.0")
    await asyncio.sleep(0.3)

    # This ask at 98.0 crosses the bid at 99.0 → TRADE
    await send(Order.create("trend-follower", Side.ASK, qty=5.0, price=98.0), "should MATCH bid@99.0 (partial)")
    await asyncio.sleep(0.3)

    # ── Phase 3: partial fill ────────────────────────────────────
    print("\n── Partial fill scenario ──")
    # Bid qty=3 against a resting ask qty=8 → 3 fills, ask qty becomes 5
    await send(Order.create("noise-trader", Side.BID, qty=3.0, price=101.5), "should partially fill ask@101.0")
    await asyncio.sleep(0.3)

    # ── Phase 4: market order ────────────────────────────────────
    print("\n── Market order (no price) ──")
    await send(
        Order.create("noise-trader", Side.BID, qty=2.0, order_type=OrderType.MARKET),
        "market order — takes best ask"
    )
    await asyncio.sleep(0.3)

    # ── Phase 5: sweep multiple levels ──────────────────────────
    print("\n── Large order sweeping multiple levels ──")
    await send(Order.create("whale", Side.BID, qty=20.0, price=103.0), "should sweep all ask levels")

    await asyncio.sleep(0.5)
    print("\n✅  All orders sent.")
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(burst())