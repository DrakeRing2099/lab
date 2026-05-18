"""
Data models for the URL shortener.

DYNAMODB SERIALIZATION GOTCHA: DECIMAL
────────────────────────────────────────
When boto3 reads a Number ('N') attribute from DynamoDB, it returns
a Python Decimal, not int or float. This is because DynamoDB stores
numbers as strings with arbitrary precision, and float can't represent
all of them exactly.

This means:
  table.get_item(...)['Item']['created_at']  →  Decimal('1715000000')

Not an int. If you try to serialize this to JSON (e.g. for an API
response), json.dumps() will raise TypeError because Decimal isn't
JSON serializable by default.

The fix: convert Decimal to int or float on the way out.
We do this in the from_item() classmethods below.

We use int() for timestamps (whole numbers) and float() for prices/counts
that might have decimals. For click counts we use int().
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from src.config import (
    PREFIX_URL, PREFIX_USER, SK_CLICK, SK_META,
    TTL_ATTRIBUTE, USER_INDEX_PK, USER_INDEX_SK, DEFAULT_TTL_DAYS,
)


# ── URL model ─────────────────────────────────────────────────────

@dataclass
class URL:
    """
    Represents a shortened URL.

    Maps to the META item in DynamoDB:
      PK = "URL#<short_code>"
      SK = "META"
    """
    short_code:   str
    original_url: str
    user_id:      str
    created_at:   int              # Unix timestamp
    expires_at:   int              # Unix timestamp — DynamoDB TTL reads this
    click_count:  int = 0

    @classmethod
    def create(
        cls,
        short_code: str,
        original_url: str,
        user_id: str,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> URL:
        now = int(time.time())
        expires = now + (ttl_days * 86400)  # 86400 seconds per day
        return cls(
            short_code=short_code,
            original_url=original_url,
            user_id=user_id,
            created_at=now,
            expires_at=expires,
        )

    def to_item(self) -> dict:
        """
        Serialize to a DynamoDB item dict.

        Note we include user_id and created_at at the top level —
        these are the GSI keys. DynamoDB automatically picks them
        up for the UserIndex GSI because we configured it to use
        those attribute names as keys.

        The GSI doesn't need special treatment here — just make sure
        the attributes exist on the item and DynamoDB handles the rest.
        """
        return {
            "PK":           f"{PREFIX_URL}{self.short_code}",
            "SK":           SK_META,
            "short_code":   self.short_code,
            "original_url": self.original_url,
            USER_INDEX_PK:  self.user_id,       # "user_id" — GSI partition key
            USER_INDEX_SK:  self.created_at,    # "created_at" — GSI sort key
            TTL_ATTRIBUTE:  self.expires_at,    # "expires_at" — TTL attribute
            "click_count":  self.click_count,
        }

    @classmethod
    def from_item(cls, item: dict) -> URL:
        """
        Deserialize from a DynamoDB item.

        Converts Decimal → int for numeric fields.
        This is the standard pattern — always convert on read.
        """
        return cls(
            short_code=   item["short_code"],
            original_url= item["original_url"],
            user_id=      item["user_id"],
            created_at=   int(item["created_at"]),
            expires_at=   int(item["expires_at"]),
            click_count=  int(item.get("click_count", 0)),
        )

    @property
    def is_expired(self) -> bool:
        return int(time.time()) > self.expires_at

    @property
    def expires_in_days(self) -> int:
        remaining = self.expires_at - int(time.time())
        return max(0, remaining // 86400)


# ── Click aggregate model ─────────────────────────────────────────

@dataclass
class ClickAggregate:
    """
    Daily click count for a URL.

    Maps to a CLICK item in DynamoDB:
      PK = "URL#<short_code>"
      SK = "CLICK#2024-01-15"

    Stored in the same partition as the URL's META item,
    so fetching a URL + all its click history is one Query.
    """
    short_code: str
    date_str:   str    # "2024-01-15"
    count:      int = 0

    @classmethod
    def for_today(cls, short_code: str) -> ClickAggregate:
        today = date.today().isoformat()  # "2024-01-15"
        return cls(short_code=short_code, date_str=today)

    def to_item(self) -> dict:
        return {
            "PK":    f"{PREFIX_URL}{self.short_code}",
            "SK":    f"{SK_CLICK}{self.date_str}",
            "short_code": self.short_code,
            "date":  self.date_str,
            "count": self.count,
        }

    @classmethod
    def from_item(cls, item: dict) -> ClickAggregate:
        return cls(
            short_code= item["short_code"],
            date_str=   item["date"],
            count=      int(item.get("count", 0)),
        )


# ── User model ────────────────────────────────────────────────────

@dataclass
class User:
    """
    A registered user.

    Maps to:
      PK = "USER#<user_id>"
      SK = "PROFILE"
    """
    user_id:    str
    email:      str
    created_at: int = field(default_factory=lambda: int(time.time()))
    url_count:  int = 0

    def to_item(self) -> dict:
        return {
            "PK":        f"{PREFIX_USER}{self.user_id}",
            "SK":        "PROFILE",
            "user_id":   self.user_id,
            "email":     self.email,
            "created_at":self.created_at,
            "url_count": self.url_count,
        }

    @classmethod
    def from_item(cls, item: dict) -> User:
        return cls(
            user_id=    item["user_id"],
            email=      item["email"],
            created_at= int(item["created_at"]),
            url_count=  int(item.get("url_count", 0)),
        )