"""
Phase 1 smoke test.

Verifies:
  1. We can connect to Redis
  2. XADD an order to the stream
  3. XREAD it back and deserialize correctly
  4. ZADD it to the book sorted sets
  5. Read back best bid / best ask

Run with:  python smoke_test.py
(Redis must be running: docker compose up -d)
"""

import asyncio
import sys

# Make src importable
sys.path.insert(0, ".")

from src.config import get_async_redis, STREAM_KEY, BIDS_KEY, ASKS_KEY
from src.models import Order, Side, OrderType
from src.consumer.book import (
    publish_order,
    read_orders_simple,
    add_to_book,
    get_best_bid,
    get_best_ask,
    get_book_snapshot,
)


async def main():
    r = get_async_redis()

    print("\n📡  Connecting to Redis...")
    await r.ping()
    print("✅  Connected\n")

    # ── Clean slate ──────────────────────────────────────────────
    print("🧹  Flushing test keys...")
    await r.delete(STREAM_KEY, BIDS_KEY, ASKS_KEY)
    print("✅  Clean\n")

    # ── Publish some orders ──────────────────────────────────────
    print("📤  Publishing orders to stream...")

    orders = [
        Order.create("market-maker", Side.BID, qty=10.0, price=99.5),
        Order.create("market-maker", Side.BID, qty=5.0,  price=99.0),
        Order.create("market-maker", Side.ASK, qty=10.0, price=100.5),
        Order.create("market-maker", Side.ASK, qty=5.0,  price=101.0),
        Order.create("trend-follow", Side.BID, qty=3.0,  price=99.8),
    ]

    stream_ids = []
    for order in orders:
        sid = await publish_order(r, order)
        stream_ids.append(sid)
        print(f"   XADD → {sid}  |  {order.side.value:3s}  {order.qty:5.1f} @ {order.price}")

    print(f"\n✅  {len(orders)} orders written to stream '{STREAM_KEY}'\n")

    # ── Read back from stream ────────────────────────────────────
    print("📥  Reading back from stream (XREAD from '0')...")
    read_back, cursor = await read_orders_simple(r, last_id="0", count=100)

    assert len(read_back) == len(orders), f"Expected {len(orders)}, got {len(read_back)}"
    print(f"✅  Read back {len(read_back)} orders. Cursor now: {cursor}\n")

    for sid, order in read_back:
        print(f"   {sid}  |  {order.side.value:3s}  {order.qty:5.1f} @ {order.price}  trader={order.trader_id}")

    # ── Add to book (sorted sets) ────────────────────────────────
    print("\n📚  Adding limit orders to book (ZADD)...")
    for _, order in read_back:
        await add_to_book(r, order)
    print(f"✅  Book populated\n")

    # ── Read book state ──────────────────────────────────────────
    best_bid = await get_best_bid(r)
    best_ask = await get_best_ask(r)
    spread   = (best_ask - best_bid) if (best_bid and best_ask) else None

    print(f"   Best bid : {best_bid}")
    print(f"   Best ask : {best_ask}")
    print(f"   Spread   : {spread:.2f}" if spread else "   Spread  : N/A")

    assert best_bid == 99.8, f"Expected 99.8, got {best_bid}"
    assert best_ask == 100.5, f"Expected 100.5, got {best_ask}"
    print("\n✅  Best bid/ask correct\n")

    # ── Book snapshot ────────────────────────────────────────────
    bids, asks = await get_book_snapshot(r, depth=5)
    print("ORDER BOOK SNAPSHOT")
    print("─" * 40)
    print(f"  {'ASKS':^36}")
    for oid, price in reversed(asks):
        print(f"  {'':>18}  {price:>8.2f}  {oid}")
    print(f"  {'--- spread ---':^40}")
    for oid, price in bids:
        print(f"  {oid}  {price:>8.2f}")
    print(f"  {'BIDS':^36}")
    print("─" * 40)

    print("\n🎉  Phase 1 complete — all plumbing works!\n")
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())