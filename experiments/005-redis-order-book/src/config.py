"""
Central config: Redis connection factory + all key names.

WHY CENTRALIZE KEY NAMES?
  Redis has no schema enforcement. If producer.py writes to "orders:stream"
  and consumer.py reads from "order:stream" (typo), you get a silent failure
  — the stream just has zero messages. Centralizing every key here means
  any typo is caught in one place, not hunted across files.

KEY NAMING CONVENTION: namespace:descriptor
  orders:stream   — the main event stream
  book:bids       — sorted set, bids side of the book
  book:asks       — sorted set, asks side of the book
  book:mid        — string, current mid price
  trades:latest   — hash, recent trades for display
  trades:channel  — pub/sub channel for live fill notifications
"""

import os
import redis.asyncio as aioredis
import redis as syncredis
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB",   "0"))

# ── Key names ────────────────────────────────────────────────────
STREAM_KEY        = "orders:stream"
CONSUMER_GROUP    = "book-engine"        # our consumer group name
CONSUMER_NAME     = "consumer-1"         # this consumer's identity within the group

BIDS_KEY          = "book:bids"          # Sorted Set: score=price, member=order_id
ASKS_KEY          = "book:asks"          # Sorted Set: score=price, member=order_id
ORDER_DATA_PREFIX = "order:"             # Hash per order: "order:{order_id}"

MID_PRICE_KEY     = "book:mid"           # String: current mid-market price
TRADES_KEY        = "trades:latest"      # Hash: recent fills keyed by trade_id
TRADES_CHANNEL    = "trades:channel"     # Pub/Sub channel

# ── Simulator constants ──────────────────────────────────────────
INITIAL_MID_PRICE  = 100.0   # starting mid-market price
MAX_BOOK_DEPTH     = 20      # max price levels to keep per side
MAX_TRADES_STORED  = 50      # max recent trades to keep in the hash
STREAM_MAX_LEN     = 10_000  # MAXLEN for the stream (ring buffer)

# ── Connection factories ─────────────────────────────────────────
def get_async_redis() -> aioredis.Redis:
    """
    Async Redis client for producers and consumer.

    redis-py's async client uses the same API as the sync client,
    just with 'await'. We use decode_responses=False (default) so
    we get bytes back — lets us detect missing keys as None rather
    than getting confusing empty strings.
    """
    return aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=False,
    )

def get_sync_redis() -> syncredis.Redis:
    """
    Sync Redis client for the dashboard (Rich runs in sync context).
    Same params as above.
    """
    return syncredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=False,
    )