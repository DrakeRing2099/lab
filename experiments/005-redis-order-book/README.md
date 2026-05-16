# Redis Order Book Simulator

A real-time limit order book simulator built entirely on Redis primitives. Three async producer archetypes generate continuous order flow; a matching engine processes it with price-time priority; a Rich terminal dashboard renders the live book and trade tape.

Built to learn Redis data structures deeply — not as an abstraction, but as the actual engine.

---

## Architecture

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ market maker │  │trend follower│  │ noise trader │
│  (quotes)    │  │ (momentum)   │  │  (GBM + rand)│
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────▼─────────────────┘
                  XADD orders:stream
                         │
               ┌─────────▼──────────┐
               │   matching engine   │
               │  (XREADGROUP loop)  │
               └──┬──────────────┬──┘
                  │              │
          ZADD book:bids    ZADD book:asks
          ZADD book:asks    PUBLISH trades:channel
                  │
         ┌────────▼────────┐
         │  Rich dashboard  │
         │  (polls Redis)   │
         └─────────────────┘
```

## Redis data structures used

| Key | Structure | Purpose |
|-----|-----------|---------|
| `orders:stream` | Stream | Append-only order log. Producers `XADD`, engine reads via `XREADGROUP`. |
| `book:bids` | Sorted Set | Live bid side. Score = price. `ZREVRANGE` gives best bid first. |
| `book:asks` | Sorted Set | Live ask side. Score = price. `ZRANGE` gives best ask first. |
| `order:{id}` | Hash | Full order data. Sorted sets store only `(price, order_id)` — hashes hold the rest. |
| `book:mid` | String | Current mid price. Written by noise trader (GBM) and engine (last trade). |
| `trades:latest` | Hash | Recent fills for dashboard display. |
| `trades:channel` | Pub/Sub | Engine publishes fills here. Dashboard can subscribe for push notifications. |

## Why each structure was chosen

**Stream over List for the order queue**
Lists (`LPUSH`/`BRPOP`) are the classic Redis queue, but they're destructive — once consumed, the message is gone. Streams are append-only. The engine can replay from any cursor, multiple consumer groups can read independently, and the PEL (Pending Entry List) tracks unacknowledged messages for fault tolerance.

**Sorted Set for the book**
An order book is just a sorted collection of prices. Redis Sorted Sets are exactly that — O(log N) insert, O(log N + M) range query. `ZRANGEBYSCORE` and `ZREVRANGEBYSCORE` give you a price slice instantly with no sorting on your end. The alternative (a list you sort in Python) would be O(N log N) on every read.

**Hash per order**
Sorted Sets only store `(score, member)`. Encoding the full order as JSON in the member works but makes partial fills expensive — you'd have to delete and reinsert to update qty. Keeping `order_id` as the member and the full data in a hash gives clean separation: the sorted set is the index, the hash is the record. Exactly the pattern you'd use in a relational database.

**Pipeline for paired writes**
Every write that touches both a sorted set and a hash (add to book, remove from book, cancel quote) is pipelined — both commands sent in one round-trip. This is both faster and safer: you can't crash between the two and leave state inconsistent.

## Producer archetypes

**Market maker** — quotes both sides continuously at `mid ± spread`. Cancels and refreshes quotes every 0.4s. Widens spread with random jitter to simulate volatility response. Models Citadel/Virtu-style HFT.

**Trend follower** — computes momentum over a rolling window of mid prices. When momentum exceeds a threshold, sends an aggressive crossing order in the trend direction. Models CTA/momentum funds.

**Noise trader** — drives the mid price via GBM (`dS = μS dt + σS dW`, discretized with Itô correction). Also generates random limit and market orders as background noise. Models uninformed retail flow.

## Matching algorithm

Price-time priority — standard on all major exchanges.

1. For each incoming order, find all resting orders on the opposite side where prices cross.
2. Sort candidates by timestamp (earlier = higher priority).
3. Fill greedily: `fill_qty = min(remaining, resting.qty)`.
4. If resting order fully consumed → remove from book. If partially consumed → update qty in hash.
5. If incoming order not fully filled → remainder rests in book as a limit order.

Self-trade prevention (STP) is enforced at the engine level: if `resting.trader_id == incoming.trader_id`, the match is skipped. Standard on every real exchange.

## Running it

```bash
# 1. Start Redis
docker compose up -d

# 2. Install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -e .

# 3. Three terminals
python run_consumer.py     # terminal 1 — matching engine
python run_producers.py    # terminal 2 — order flow
python run_dashboard.py    # terminal 3 — live view
```

RedisInsight (GUI for inspecting keys live) runs at `http://localhost:5540`.

## Project structure

```
src/
├── config.py              # Redis connection + all key names
├── models.py              # Order, Trade dataclasses
├── producers/
│   ├── base.py            # Abstract producer + run loop
│   ├── market_maker.py    # Tight spread quoting + quote cancellation
│   ├── trend_follower.py  # Momentum-based directional orders
│   └── noise_trader.py    # GBM price process + random flow
├── consumer/
│   ├── engine.py          # XREADGROUP loop + matching logic
│   └── book.py            # Redis read/write helpers
└── dashboard/
    └── view.py            # Rich terminal UI
```

## Known design tradeoffs

**`book:mid` is one variable doing three jobs** — it conflates the GBM theoretical fair value (written by noise trader), the last trade price (written by engine), and an approximation of the quoted mid. A cleaner model would separate these into `book:mid:theoretical`, `book:mid:last_trade`, and derive `(best_bid + best_ask) / 2` on demand. Collapsed here intentionally for simplicity.

**No order expiry** — in a real system, orders have a time-in-force (GTC, IOC, FOK, GTD). We have none of that; orders rest until filled or cancelled. Adding IOC (immediate-or-cancel) would mean: if the order doesn't cross immediately, discard it rather than adding to book.

**Single consumer** — the consumer group infrastructure is in place for multiple consumers, but we only run one. Running N consumers on the same group would partition the stream across them — each message delivered to exactly one consumer.