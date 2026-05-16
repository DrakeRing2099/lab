"""
Matching Engine — the core of the order book simulator.

WHAT THIS FILE DOES
────────────────────
1. Creates (or joins) a Redis consumer group on the stream
2. Loops forever reading new orders via XREADGROUP
3. For each order: attempts to match against the opposite side
4. If matched  → create Trade, remove filled orders, publish to Pub/Sub
5. If unmatched → add order to the book (rests as a limit order)
6. XACK every message after processing

THE KEY REDIS CONCEPT: CONSUMER GROUPS
────────────────────────────────────────
Regular XREAD: "give me messages after cursor X"
  - Simple, stateless, no delivery guarantees
  - If you crash mid-processing, you lose that message

XREADGROUP: "give me undelivered messages for my group"
  - Redis tracks which messages each group has seen
  - Delivered-but-unacknowledged messages sit in the PEL
    (Pending Entry List)
  - XACK removes a message from the PEL
  - On restart, you can call XAUTOCLAIM to reclaim PEL messages

It's the difference between reading a file (XREAD) and a job queue
where the server tracks what you've actually finished (XREADGROUP).

MATCHING ALGORITHM: PRICE-TIME PRIORITY
─────────────────────────────────────────
For a new BID at price P:
  1. Get all asks with price ≤ P (these are crossable)
  2. Sort by price ascending (best ask first), then by timestamp
  3. Fill greedily until our qty is exhausted or no more matches

Same logic mirrored for ASKs.

Partial fills: if the resting order has qty=10 and we only need 5,
the resting order stays in the book with qty=5. We do this by
deleting the old hash entry and reinserting with reduced qty.
The sorted set entry (price, order_id) doesn't change — only the
hash changes. This is why we separated them.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import redis.asyncio as aioredis

from src.config import (
    ASKS_KEY, BIDS_KEY, CONSUMER_GROUP, CONSUMER_NAME,
    ORDER_DATA_PREFIX, STREAM_KEY, TRADES_CHANNEL,
    get_async_redis,
)
from src.consumer.book import (
    add_to_book, get_order_by_id, record_trade, remove_from_book,
)
from src.models import Order, OrderType, Side, Trade


# ── Consumer group setup ─────────────────────────────────────────

async def ensure_consumer_group(r: aioredis.Redis) -> None:
    """
    Create the consumer group if it doesn't exist.

    XGROUP CREATE stream group $ MKSTREAM
                               ^
                               '$' means "start from the latest message"
                               '0' would mean "start from the beginning"

    We use '$' so on a fresh start we don't replay old messages.
    MKSTREAM creates the stream itself if it doesn't exist yet.

    The try/except is intentional — if the group already exists,
    Redis raises a BusyGroup error. That's fine, we just continue.
    """
    try:
        await r.xgroup_create(
            STREAM_KEY,
            CONSUMER_GROUP,
            id="$",
            mkstream=True,
        )
        print(f"[engine] Created consumer group '{CONSUMER_GROUP}'")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"[engine] Consumer group '{CONSUMER_GROUP}' already exists")
        else:
            raise


# ── The XREADGROUP loop ──────────────────────────────────────────

async def order_stream(r: aioredis.Redis) -> AsyncIterator[tuple[str, Order]]:
    """
    Async generator that yields (stream_id, Order) forever.

    Uses XREADGROUP so Redis tracks what we've processed.

    XREADGROUP GROUP group consumer COUNT 10 BLOCK 2000 STREAMS key >
                                                                   ^
                                                                   '>' means "give me messages
                                                                   not yet delivered to any
                                                                   consumer in this group"

    BLOCK 2000: wait up to 2000ms for new messages before returning
    empty. This is long-polling — we don't spin-wait, Redis wakes us
    up when something arrives. Far better than sleep() in a loop.
    """
    while True:
        try:
            response = await r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=10,
                block=2000,
            )
        except aioredis.ConnectionError:
            print("[engine] Redis connection lost, retrying in 1s...")
            await asyncio.sleep(1)
            continue

        if not response:
            continue  # timeout, no new messages, loop again

        # response: [(b"orders:stream", [(b"id", {fields}), ...])]
        stream_entries = response[0][1]
        for stream_id, fields in stream_entries:
            order = Order.from_stream_dict(fields)
            yield stream_id.decode(), order


# ── Matching logic ───────────────────────────────────────────────

async def get_crossable_orders(
    r: aioredis.Redis,
    incoming: Order,
) -> list[Order]:
    """
    Find all resting orders that can trade against the incoming order.

    For a BID at price P: find asks where ask_price <= P
      ZRANGEBYSCORE book:asks -inf P WITHSCORES
      Sorted low→high, so we get cheapest asks first. Good.

    For an ASK at price P: find bids where bid_price >= P
      ZREVRANGEBYSCORE book:bids +inf P WITHSCORES
      Sorted high→low, so we get most generous bids first. Good.

    Then we look up the full Order object for each match via HGETALL.
    """
    if incoming.price is None:
        # Market order — crosses at any price
        if incoming.side == Side.BID:
            raw = await r.zrange(ASKS_KEY, 0, -1, withscores=True)
        else:
            raw = await r.zrevrange(BIDS_KEY, 0, -1, withscores=True)
    else:
        if incoming.side == Side.BID:
            # Find asks priced at or below what we're willing to pay
            raw = await r.zrangebyscore(
                ASKS_KEY, "-inf", incoming.price, withscores=True
            )
        else:
            # Find bids priced at or above what we're willing to accept
            raw = await r.zrevrangebyscore(
                BIDS_KEY, "+inf", incoming.price, withscores=True
            )

    if not raw:
        return []

    # Fetch full order data for each candidate
    crossable = []
    for order_id_bytes, _ in raw:
        order = await get_order_by_id(r, order_id_bytes.decode())
        if order:
            crossable.append(order)

    # Self-trade prevention (STP) — standard on every real exchange.
    # If the resting order belongs to the same trader as the incoming
    # order, skip it. Without this, a market maker's new quotes cross
    # against its own stale resting quotes, producing phantom trades
    # with buyer == seller. No real P&L changes hands; it just
    # pollutes the tape and inflates volume statistics.
    crossable = [o for o in crossable if o.trader_id != incoming.trader_id]

    # Preserve price-time priority: best price first, then earliest arrival.
    if incoming.side == Side.BID:
        crossable.sort(
            key=lambda o: (
                o.price if o.price is not None else float("inf"),
                o.timestamp,
            )
        )
    else:
        crossable.sort(
            key=lambda o: (
                -(o.price if o.price is not None else float("-inf")),
                o.timestamp,
            )
        )
    return crossable


async def match_order(
    r: aioredis.Redis,
    incoming: Order,
) -> list[Trade]:
    """
    Attempt to match an incoming order against the book.

    Returns a list of Trade objects (could be multiple if the
    incoming order sweeps through several price levels).

    PARTIAL FILL LOGIC
    ───────────────────
    remaining_qty tracks how much of the incoming order is left.
    For each resting order we can match:
      fill_qty = min(remaining_qty, resting_order.qty)
      - If fill_qty == resting_order.qty → resting order fully filled → remove it
      - If fill_qty <  resting_order.qty → resting order partially filled →
        update its qty in the hash (keep it in the sorted set, same price)
      - Subtract fill_qty from remaining_qty
      - If remaining_qty == 0 → incoming order fully filled → stop
    If remaining_qty > 0 after all matches → add remainder to book
    """
    trades: list[Trade] = []
    remaining_qty = incoming.qty

    crossable = await get_crossable_orders(r, incoming)

    for resting in crossable:
        if remaining_qty <= 0:
            break

        fill_qty = min(remaining_qty, resting.qty)

        # Determine bid/ask sides for the Trade record
        if incoming.side == Side.BID:
            bid_order, ask_order = incoming, resting
        else:
            bid_order, ask_order = resting, incoming

        trade = Trade.create(bid_order, ask_order, fill_qty)
        trade.price = resting.price  # trades clear at the resting/maker price
        trades.append(trade)

        remaining_qty -= fill_qty

        if fill_qty >= resting.qty - 1e-9:
            # Resting order fully consumed — remove from book
            await remove_from_book(r, resting.order_id, resting.side.value)
        else:
            # Resting order partially filled — update qty in hash
            new_qty = resting.qty - fill_qty
            await r.hset(
                f"{ORDER_DATA_PREFIX}{resting.order_id}",
                "qty",
                str(new_qty),
            )

    # If the incoming order wasn't fully filled, add remainder to book
    if remaining_qty > 0 and incoming.order_type == OrderType.LIMIT:
        # Create a new Order with the remaining qty (frozen dataclass)
        remainder = Order(
            order_id=  incoming.order_id,
            trader_id= incoming.trader_id,
            side=      incoming.side,
            order_type=incoming.order_type,
            price=     incoming.price,
            qty=       remaining_qty,
            timestamp= incoming.timestamp,
        )
        await add_to_book(r, remainder)

    return trades


# ── Trade publishing ─────────────────────────────────────────────

async def publish_trades(r: aioredis.Redis, trades: list[Trade]) -> None:
    """
    For each trade:
      1. Store in the trades:latest hash (for dashboard polling)
      2. PUBLISH to trades:channel (for dashboard Pub/Sub)

    PUBLISH channel message
      Delivers message to all current subscribers instantly.
      Zero persistence — if nobody is subscribed right now, the
      message is gone. That's fine; we have the hash as a fallback.
    """
    for trade in trades:
        await record_trade(r, trade)
        payload = json.dumps(trade.to_hash_dict())
        await r.publish(TRADES_CHANNEL, payload)
        print(
            f"[engine] TRADE  {trade.qty:6.1f} @ {trade.price:8.2f}"
            f"  buyer={trade.buyer_id}  seller={trade.seller_id}"
        )


# ── Main engine loop ─────────────────────────────────────────────

async def run_engine() -> None:
    """
    The main engine loop.

    For each order arriving from the stream:
      1. Try to match it
      2. Publish any resulting trades
      3. XACK the stream message

    XACK is always called — even if matching produced no trades.
    This tells Redis "I have fully processed this message, remove
    it from my PEL." If we crash before XACK, the message stays
    in the PEL and will be redelivered on restart.
    """
    r = get_async_redis()
    await ensure_consumer_group(r)

    print(f"[engine] Listening on '{STREAM_KEY}'...")
    print(f"[engine] Consumer group: '{CONSUMER_GROUP}' / '{CONSUMER_NAME}'")
    print()

    orders_processed = 0
    trades_executed  = 0

    async for stream_id, order in order_stream(r):
        try:
            trades = await match_order(r, order)

            if trades:
                await publish_trades(r, trades)
                trades_executed += len(trades)
            else:
                side_str = "BID" if order.side == Side.BID else "ASK"
                price_str = f"{order.price:.2f}" if order.price else "MARKET"
                print(
                    f"[engine] RESTED {side_str:3s}  {order.qty:6.1f} @ {price_str:>8}"
                    f"  trader={order.trader_id}"
                )

            # ✅ Acknowledge — removes from PEL
            await r.xack(STREAM_KEY, CONSUMER_GROUP, stream_id)
            orders_processed += 1

            if orders_processed % 50 == 0:
                print(
                    f"[engine] --- {orders_processed} orders processed, "
                    f"{trades_executed} trades executed ---"
                )

        except Exception as e:
            # Don't XACK on error — message stays in PEL for retry
            print(f"[engine] ERROR processing {stream_id}: {e}")
            import traceback; traceback.print_exc()
