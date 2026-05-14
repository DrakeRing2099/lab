"""
Redis helpers for reading and writing order book state.

This is the layer that actually *touches* Redis data structures.
Each function maps to one or two specific Redis commands — the
comment above each function explains why that structure was chosen.

DATA MODEL SUMMARY
──────────────────
  Stream (orders:stream)
    The incoming order log. Append-only. Producers write here,
    consumer reads here. Think of it like Kafka but built into Redis.

  Sorted Sets (book:bids, book:asks)
    The live order book. Score = price. This is the key insight:
    Redis Sorted Sets are ordered by score, so ZRANGEBYSCORE and
    ZREVRANGEBYSCORE give you a slice of the book instantly, with
    no sorting on our end.

    Bids:  highest price = best bid → read with ZREVRANGEBYSCORE
    Asks:  lowest price  = best ask → read with ZRANGEBYSCORE

  Hashes (order:{id}, trades:latest)
    Full order/trade data. The Sorted Set only stores (price, order_id).
    To reconstruct an order we look up order:{id} in the hash.
    This is the Redis equivalent of a "foreign key" join.

  String (book:mid)
    Just the current mid price. INCRBYFLOAT would work too, but
    a plain SET/GET is clearest for a single float.
"""

from __future__ import annotations

import redis.asyncio as aioredis
import redis as syncredis

from src.config import (
    ASKS_KEY, BIDS_KEY, MAX_BOOK_DEPTH, MAX_TRADES_STORED,
    MID_PRICE_KEY, ORDER_DATA_PREFIX, STREAM_KEY, STREAM_MAX_LEN,
    TRADES_KEY,
)
from src.models import Order, Trade


# ── Stream operations ────────────────────────────────────────────

async def publish_order(r: aioredis.Redis, order: Order) -> str:
    """
    Write one order to the stream.

    XADD orders:stream MAXLEN ~ 10000 * field value [field value ...]
         ^key           ^trim   ^approx ^auto-id
    
    '*' as the ID means "generate a timestamp-based ID for me".
    Redis uses millisecond Unix time + sequence number: "1715000000000-0"
    This is monotonically increasing, which is exactly what we want —
    it gives us arrival order for free.

    MAXLEN ~ 10000: the '~' means "approximately" — Redis won't trim on
    every single write (that's expensive), it'll do it in chunks. Keeps
    the stream from growing unbounded without hurting write performance.
    """
    stream_id = await r.xadd(
        STREAM_KEY,
        order.to_stream_dict(),
        maxlen=STREAM_MAX_LEN,
        approximate=True,
    )
    return stream_id.decode()


async def read_orders_simple(
    r: aioredis.Redis,
    last_id: str = "0",
    count: int = 100,
) -> tuple[list[tuple[str, Order]], str]:
    """
    Read new orders from the stream (simple XREAD, no consumer group).

    Used only in Phase 1 for smoke-testing. Phase 2 replaces this with
    XREADGROUP for fault-tolerant consumption.

    XREAD COUNT 100 STREAMS orders:stream 0
                              ^key         ^start from beginning

    '0' = "give me everything from the start"
    '$' = "give me only new messages arriving after I start reading"

    Returns: (list of (stream_id, Order), new cursor)
    The cursor is the ID of the last message we saw — pass it back
    next time to get only new messages (like an offset in Kafka).
    """
    response = await r.xread(
        {STREAM_KEY: last_id},
        count=count,
        block=0,      # block=0 means "wait forever for a message"
    )
    if not response:
        return [], last_id

    # response shape: [(b"orders:stream", [(b"id", {field: value}), ...])]
    stream_entries = response[0][1]
    orders = []
    new_cursor = last_id

    for stream_id, fields in stream_entries:
        order = Order.from_stream_dict(fields)
        orders.append((stream_id.decode(), order))
        new_cursor = stream_id.decode()

    return orders, new_cursor


# ── Order book state (Sorted Sets + Hashes) ──────────────────────

async def add_to_book(r: aioredis.Redis, order: Order) -> None:
    """
    Add a limit order to the book.

    Two writes, always together:
      1. ZADD book:bids <price> <order_id>   — adds to the sorted set
      2. HSET order:<order_id> <all fields>  — stores full order data

    Why not store everything in the sorted set?
      Sorted Sets only have (score, member). Member is a single string.
      We could encode the whole order as JSON in the member, but then
      we can't update qty on a partial fill without removing+reinserting.
      Keeping the sorted set lean (just price + order_id) and the full
      data in a hash gives us clean separation.
    """
    if order.price is None:
        return  # market orders don't rest in the book

    book_key = BIDS_KEY if order.side.value == "bid" else ASKS_KEY

    pipe = r.pipeline()
    # ZADD key score member — sorted set insert
    pipe.zadd(book_key, {order.order_id: order.price})
    # HSET key field value [field value ...] — store full order
    pipe.hset(f"{ORDER_DATA_PREFIX}{order.order_id}", mapping=order.to_stream_dict())
    await pipe.execute()
    #
    # pipeline() batches both commands into one round-trip to Redis.
    # Always pipeline writes that logically belong together — it's
    # both faster and less likely to leave state partially written.


async def remove_from_book(r: aioredis.Redis, order_id: str, side: str) -> None:
    """
    Remove a fully-filled or cancelled order from the book.

    ZREM key member — O(log N)
    DEL key         — O(1)
    """
    book_key = BIDS_KEY if side == "bid" else ASKS_KEY
    pipe = r.pipeline()
    pipe.zrem(book_key, order_id)
    pipe.delete(f"{ORDER_DATA_PREFIX}{order_id}")
    await pipe.execute()


async def get_best_bid(r: aioredis.Redis) -> float | None:
    """
    Best bid = highest price willing to buy.

    ZREVRANGEBYSCORE key +inf -inf WITHSCORES LIMIT 0 1
                         ^max  ^min            ^offset ^count

    ZREVRANGE sorts high→low, so index 0 is the highest bid.
    We use WITHSCORES to get the price back directly.
    """
    result = await r.zrevrange(BIDS_KEY, 0, 0, withscores=True)
    if not result:
        return None
    return result[0][1]  # (member, score) → score is the price


async def get_best_ask(r: aioredis.Redis) -> float | None:
    """
    Best ask = lowest price willing to sell.

    ZRANGE sorts low→high, so index 0 is the lowest ask.
    """
    result = await r.zrange(ASKS_KEY, 0, 0, withscores=True)
    if not result:
        return None
    return result[0][1]


async def get_order_by_id(r: aioredis.Redis, order_id: str) -> Order | None:
    """Fetch full order data from the hash."""
    data = await r.hgetall(f"{ORDER_DATA_PREFIX}{order_id}")
    if not data:
        return None
    return Order.from_stream_dict(data)


async def get_book_snapshot(
    r: aioredis.Redis,
    depth: int = MAX_BOOK_DEPTH,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """
    Return top N bids and asks as (order_id, price) pairs.

    Used by the dashboard to render the book ladder.
    Both calls are O(log N + M) where M is the depth requested.
    """
    bids_raw = await r.zrevrange(BIDS_KEY, 0, depth - 1, withscores=True)
    asks_raw = await r.zrange(ASKS_KEY, 0, depth - 1, withscores=True)

    bids = [(oid.decode(), price) for oid, price in bids_raw]
    asks = [(oid.decode(), price) for oid, price in asks_raw]
    return bids, asks


# ── Trade recording ──────────────────────────────────────────────

async def record_trade(r: aioredis.Redis, trade: Trade) -> None:
    """
    Store a completed trade + update mid price.

    HSET trades:latest <trade_id> <json>
    We store at most MAX_TRADES_STORED trades by deleting oldest when
    we exceed the limit. There's no TTL-based eviction here — we
    manage it manually so the dashboard always sees exactly N trades.
    """
    pipe = r.pipeline()
    pipe.hset(TRADES_KEY, trade.trade_id, str(trade.to_hash_dict()))
    pipe.set(MID_PRICE_KEY, str(trade.price))
    await pipe.execute()

    # Trim to max stored: count current, delete if over limit
    count = await r.hlen(TRADES_KEY)
    if count > MAX_TRADES_STORED:
        # Get all keys, delete the oldest (we'd need timestamps for proper trim)
        # Simple approach: just let it grow to MAX + batch trim
        all_keys = await r.hkeys(TRADES_KEY)
        to_delete = all_keys[:count - MAX_TRADES_STORED]
        if to_delete:
            await r.hdel(TRADES_KEY, *to_delete)


# ── Sync versions for dashboard ──────────────────────────────────

def sync_get_book_snapshot(
    r: syncredis.Redis,
    depth: int = MAX_BOOK_DEPTH,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Sync version of get_book_snapshot for the Rich dashboard."""
    bids_raw = r.zrevrange(BIDS_KEY, 0, depth - 1, withscores=True)
    asks_raw = r.zrange(ASKS_KEY, 0, depth - 1, withscores=True)
    bids = [(oid.decode(), price) for oid, price in bids_raw]
    asks = [(oid.decode(), price) for oid, price in asks_raw]
    return bids, asks


def sync_get_mid_price(r: syncredis.Redis) -> float | None:
    val = r.get(MID_PRICE_KEY)
    return float(val) if val else None


def sync_get_recent_trades(r: syncredis.Redis, n: int = 10) -> list[dict]:
    """Return the n most recent trades from the hash."""
    raw = r.hgetall(TRADES_KEY)
    trades = []
    for _, v in raw.items():
        try:
            trades.append(eval(v.decode()))  # stored as str(dict)
        except Exception:
            pass
    trades.sort(key=lambda t: float(t.get("timestamp", 0)), reverse=True)
    return trades[:n]