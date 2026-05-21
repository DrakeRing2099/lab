"""
Shortener service layer.

Sits between the CLI/API and raw DynamoDB operations in db.py.
Handles business logic: short code generation, collision handling,
and transactional writes.

DYNAMODB TRANSACTIONS
──────────────────────
TransactWriteItems lets you write up to 25 items atomically across
any keys in the same table (or even different tables). Either ALL
writes succeed or NONE do. This is the DynamoDB equivalent of a
SQL transaction.

We use it for shorten_url():
  1. PutItem the new URL
  2. UpdateItem the user's url_count

If the short code is already taken (ConditionalCheckFailed on write 1),
the whole transaction fails and url_count is not incremented.
If the user doesn't exist (we could add a condition for this too),
same thing. Atomic, consistent, no cleanup needed on failure.

Cost: transactions cost 2x read/write units compared to non-transactional
operations. Worth it when consistency matters.

SHORT CODE GENERATION
──────────────────────
nanoid generates URL-safe random strings. 7 characters from the default
alphabet (A-Za-z0-9_-) gives 64^7 = 4.4 trillion combinations.
Collision probability is negligible at any realistic scale.

We still handle collisions with a retry loop — not because they're
likely, but because "negligible" isn't "impossible" and the
ConditionalCheckFailed on PutItem tells us cleanly if one occurs.
"""

from __future__ import annotations

from nanoid import generate

from src.config import (
    PREFIX_URL, PREFIX_USER, SK_META, SHORT_CODE_LENGTH,
    TABLE_NAME, TTL_ATTRIBUTE, USER_INDEX_PK, USER_INDEX_SK,
    get_dynamodb,
)
from src.db import get_url, get_urls_for_user, get_click_history, record_click
from src.models import URL, User


# ── Short code generation ─────────────────────────────────────────

# URL-safe alphabet — no +, /, = which cause issues in URLs
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_RETRIES = 5


def generate_short_code() -> str:
    return generate(ALPHABET, SHORT_CODE_LENGTH)


# ── Core operations ───────────────────────────────────────────────

def shorten_url(
    original_url: str,
    user_id: str,
    ttl_days: int = 30,
    custom_code: str | None = None,
) -> URL:
    """
    Create a shortened URL.

    Uses TransactWriteItems to atomically:
      1. PutItem the URL (with collision check)
      2. UpdateItem the user's url_count

    On collision (two requests generating the same code simultaneously),
    the transaction fails and we retry with a new code.
    On custom_code collision, we raise immediately — user asked for
    a specific code that's taken.

    TransactWriteItems structure
    ─────────────────────────────
    A list of up to 25 operations, each one of:
      Put, Update, Delete, ConditionCheck

    Each operation specifies its own ConditionExpression.
    If ANY condition fails, the ENTIRE transaction is cancelled
    and DynamoDB tells you which item(s) failed via
    CancellationReasons in the exception.
    """
    dynamodb = get_dynamodb()
    client = dynamodb.meta.client

    for attempt in range(MAX_RETRIES):
        short_code = custom_code if custom_code else generate_short_code()
        url = URL.create(short_code, original_url, user_id, ttl_days)
        item = url.to_item()

        try:
            client.transact_write_items(
                TransactItems=[
                    # Write 1: create the URL item
                    # Condition: short code must not already exist
                    {
                        "Put": {
                            "TableName": TABLE_NAME,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    # Write 2: increment user's URL count
                    # No condition — user must exist (we trust the caller)
                    {
                        "Update": {
                            "TableName": TABLE_NAME,
                            "Key": {
                                "PK": f"{PREFIX_USER}{user_id}",
                                "SK": "PROFILE",
                            },
                            "UpdateExpression": "ADD url_count :one",
                            "ExpressionAttributeValues": {":one": 1},
                        }
                    },
                ]
            )
            return url

        except client.exceptions.TransactionCanceledException as e:
            reasons = e.response["CancellationReasons"]
            # reasons[0] = URL PutItem result
            # reasons[1] = user UpdateItem result
            if reasons[0]["Code"] == "ConditionalCheckFailed":
                if custom_code:
                    raise ValueError(f"Short code '{custom_code}' is already taken") from e
                # Random collision — retry with a new code
                continue
            raise  # some other failure — propagate

    raise RuntimeError(f"Failed to generate unique short code after {MAX_RETRIES} attempts")


def redirect(short_code: str) -> str | None:
    """
    The hot path. Given a short code, return the original URL.
    Records the click asynchronously (in a real system this would
    be a background task — here we do it inline for simplicity).

    Returns None if the code doesn't exist or is expired.
    """
    url = get_url(short_code)
    if not url:
        return None

    # Record click — fire and forget in a real system
    record_click(short_code)
    return url.original_url


def get_stats(short_code: str) -> dict | None:
    """
    Return analytics for a URL.
    """
    url = get_url(short_code)
    if not url:
        return None

    history = get_click_history(short_code)

    return {
        "short_code":    url.short_code,
        "original_url":  url.original_url,
        "created_at":    url.created_at,
        "expires_in":    url.expires_in_days,
        "total_clicks":  url.click_count,
        "daily_clicks":  [
            {"date": day.date_str, "count": day.count}
            for day in history
        ],
    }


def get_dashboard(user_id: str) -> list[dict]:
    """Return summary of all URLs for a user."""
    urls = get_urls_for_user(user_id)
    return [
        {
            "short_code":   u.short_code,
            "original_url": u.original_url,
            "click_count":  u.click_count,
            "expires_in":   u.expires_in_days,
        }
        for u in urls
    ]


# ── Boto3 low-level serialization helper ──────────────────────────
#

