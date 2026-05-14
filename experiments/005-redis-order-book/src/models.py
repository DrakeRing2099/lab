"""
Core data models for the order book simulator.

Why dataclasses?
  Clean, typed, no boilerplate. We'll serialize to/from Redis
  manually (dicts of strings) so we don't need Pydantic here.

Why frozen=True on Order?
  Orders should be immutable once created. If the matching engine
  needs to partially fill an order it creates a *new* Order with
  reduced qty — it never mutates the original. This keeps the
  stream log accurate (the stream entry always reflects the
  original intent).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    BID = "bid"   # buy order — willing to pay UP TO price
    ASK = "ask"   # sell order — willing to accept AT LEAST price


class OrderType(StrEnum):
    LIMIT = "limit"    # sit in the book at a specific price
    MARKET = "market"  # execute immediately at best available price


@dataclass(frozen=True)
class Order:
    """
    A single order in the system.

    Fields that go INTO Redis Stream (via XADD):
      All of them. Redis stores everything as strings, so we convert
      on the way in (to_stream_dict) and on the way out (from_stream_dict).

    price: float | None
      None only for MARKET orders. The engine handles this specially —
      a market order crosses at whatever the best opposing price is.
    """
    order_id: str
    trader_id: str
    side: Side
    order_type: OrderType
    price: float | None   # None = market order
    qty: float
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        trader_id: str,
        side: Side,
        qty: float,
        price: float | None = None,
        order_type: OrderType = OrderType.LIMIT,
    ) -> Order:
        """Factory — auto-generates order_id and timestamp."""
        return cls(
            order_id=str(uuid.uuid4())[:8],
            trader_id=trader_id,
            side=side,
            order_type=order_type,
            price=price,
            qty=qty,
        )

    def to_stream_dict(self) -> dict[str, str]:
        """
        Serialize to a flat dict of strings for XADD.

        Redis Streams store fields as key-value string pairs.
        XADD orders:stream '*' side bid price 100.5 qty 10.0 ...
                                  ^   ^    ^    ^      ^   ^
                                  field   value pairs, all strings
        """
        return {
            "order_id":   self.order_id,
            "trader_id":  self.trader_id,
            "side":       self.side.value,
            "order_type": self.order_type.value,
            "price":      str(self.price) if self.price is not None else "market",
            "qty":        str(self.qty),
            "timestamp":  str(self.timestamp),
        }

    @classmethod
    def from_stream_dict(cls, data: dict[bytes, bytes]) -> Order:
        """
        Deserialize from the dict redis-py gives us after XREAD.

        redis-py returns bytes by default, so we decode everything.
        The 'price' field is special: "market" → None, else float.
        """
        price_raw = data[b"price"].decode()
        return cls(
            order_id=   data[b"order_id"].decode(),
            trader_id=  data[b"trader_id"].decode(),
            side=       Side(data[b"side"].decode()),
            order_type= OrderType(data[b"order_type"].decode()),
            price=      None if price_raw == "market" else float(price_raw),
            qty=        float(data[b"qty"]),
            timestamp=  float(data[b"timestamp"]),
        )


@dataclass
class Trade:
    """
    A matched trade — produced by the matching engine when a bid
    crosses an ask.

    Why NOT frozen?
      Trades are created once and never read back from Redis in this
      phase — they're published to Pub/Sub and stored in a hash.
      No need for immutability here.
    """
    trade_id: str
    bid_order_id: str
    ask_order_id: str
    buyer_id: str
    seller_id: str
    price: float    # always the resting order's price (maker price)
    qty: float
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(cls, bid: Order, ask: Order, qty: float) -> Trade:
        """
        The matched price is always the *maker* (resting) order's price.

        This is standard exchange convention. The maker sat in the book
        waiting. The taker arrived and crossed. The trade clears at the
        price the maker was advertising.

        In our case: whichever order had the earlier timestamp is the maker.
        """
        maker = bid if bid.timestamp < ask.timestamp else ask
        return cls(
            trade_id=     str(uuid.uuid4())[:8],
            bid_order_id= bid.order_id,
            ask_order_id= ask.order_id,
            buyer_id=     bid.trader_id,
            seller_id=    ask.trader_id,
            price=        maker.price,  # type: ignore[arg-type]
            qty=          qty,
        )

    def to_hash_dict(self) -> dict[str, str]:
        """Serialize for HSET into trades:latest hash."""
        return {
            "trade_id":     self.trade_id,
            "bid_order_id": self.bid_order_id,
            "ask_order_id": self.ask_order_id,
            "buyer_id":     self.buyer_id,
            "seller_id":    self.seller_id,
            "price":        str(self.price),
            "qty":          str(self.qty),
            "timestamp":    str(self.timestamp),
        }