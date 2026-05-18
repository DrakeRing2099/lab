"""
Database layer — all DynamoDB operations.

Each function maps to specific DynamoDB API calls.
The comment above each function explains:
  - which DynamoDB operation is used
  - why that operation (not alternatives)
  - what the request/response looks like

DYNAMODB OPERATIONS QUICK REFERENCE
──────────────────────────────────────
PutItem    — write one item (overwrites if exists)
GetItem    — read one item by exact PK + SK (fastest possible read)
UpdateItem — modify specific attributes of an existing item
             without fetching and rewriting the whole item
DeleteItem — delete one item by PK + SK
Query      — fetch multiple items sharing a PK, optionally
             filtering on SK. Always scoped to one partition.
Scan       — read every item in the table. Expensive. Avoid.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from src.config import (
    PREFIX_URL, PREFIX_USER, SK_CLICK, SK_META,
    TABLE_NAME, TTL_ATTRIBUTE, USER_INDEX, USER_INDEX_PK,
    get_table,
)
from src.models import URL, ClickAggregate, User


# ── Table setup ───────────────────────────────────────────────────

def create_table() -> None:
    """
    Creates the urls table with the UserIndex GSI.

    This only needs to run once. In production you'd use
    infrastructure-as-code (CloudFormation, Terraform) instead.

    KEY SCHEMA
    ───────────
    AttributeDefinitions only lists attributes used as keys —
    PK, SK, and the GSI keys. DynamoDB is schemaless for everything
    else. You do NOT declare original_url, click_count, etc. here.
    That's different from SQL where you define every column upfront.

    BILLING MODE
    ─────────────
    PAY_PER_REQUEST (on-demand) vs PROVISIONED.
    Provisioned: you specify read/write capacity units upfront,
                 pay for them whether you use them or not.
    On-demand:   you pay per request, DynamoDB scales automatically.
    For learning and low traffic: on-demand. Always.

    GSI PROJECTION
    ───────────────
    INCLUDE means "copy these specific attributes into the GSI."
    We include original_url so the user dashboard can show the
    URL without fetching each item individually.
    ALL would copy every attribute — more storage, higher write cost.
    KEYS_ONLY would only copy PK, SK, and GSI keys — cheapest,
    but then you'd need a second GetItem per URL for the dashboard.
    """
    dynamodb = boto3.resource(
        "dynamodb",
        region_name="us-east-1",
        endpoint_url="http://localhost:8000",
        aws_access_key_id="fake",
        aws_secret_access_key="fake",
    )

    try:
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},   # partition key
                {"AttributeName": "SK", "KeyType": "RANGE"},  # sort key
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK",         "AttributeType": "S"},
                {"AttributeName": "SK",         "AttributeType": "S"},
                {"AttributeName": "user_id",    "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": USER_INDEX,     # "UserIndex"
                    "KeySchema": [
                        {"AttributeName": "user_id",    "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {
                        "ProjectionType": "INCLUDE",
                        "NonKeyAttributes": ["original_url", "short_code", "expires_at", "click_count"],
                    },
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        print(f"[db] Table '{TABLE_NAME}' created")

        # Enable TTL on the expires_at attribute.
        # DynamoDB checks this attribute periodically and deletes
        # items where expires_at < current Unix timestamp.
        # Deletion isn't instant — can take up to 48h — but the
        # item won't be returned in reads once expired.
        dynamodb.meta.client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": TTL_ATTRIBUTE,
            },
        )
        print(f"[db] TTL enabled on '{TTL_ATTRIBUTE}'")

    except dynamodb.meta.client.exceptions.ResourceInUseException:
        print(f"[db] Table '{TABLE_NAME}' already exists")


# ── URL operations ────────────────────────────────────────────────

def put_url(url: URL) -> None:
    """
    Write a URL item to DynamoDB.

    PutItem — writes one item. If an item with the same PK+SK
    exists, it's completely overwritten. This is fine for creation
    but dangerous for updates (you'd lose any concurrent changes).
    For updates, use UpdateItem instead (see record_click).

    ConditionExpression: attribute_not_exists(PK)
    ─────────────────────────────────────────────
    This makes PutItem conditional — only succeeds if no item
    with this PK exists yet. If the short code is already taken,
    DynamoDB raises ConditionalCheckFailedException instead of
    silently overwriting. This is optimistic locking — no SELECT
    then INSERT, just one atomic conditional write.
    """
    table = get_table()
    table.put_item(
        Item=url.to_item(),
        ConditionExpression="attribute_not_exists(PK)",
    )


def get_url(short_code: str) -> URL | None:
    """
    Fetch a URL by short code. The hot path — called on every redirect.

    GetItem — single item lookup by exact PK + SK.
    This is the fastest DynamoDB operation: one network hop,
    one partition, one item. O(1). This is why the short code
    is the partition key — the redirect must be instant.

    We check expiry in application code too, even though DynamoDB
    TTL handles deletion. Why? TTL deletion can lag up to 48h.
    During that window, expired items are still readable.
    The attribute_not_exists check in queries filters them, but
    GetItem doesn't filter — it returns whatever is there.
    So we check is_expired ourselves.
    """
    table = get_table()
    response = table.get_item(
        Key={
            "PK": f"{PREFIX_URL}{short_code}",
            "SK": SK_META,
        }
    )
    item = response.get("Item")
    if not item:
        return None
    url = URL.from_item(item)
    return None if url.is_expired else url


def get_urls_for_user(user_id: str) -> list[URL]:
    """
    Fetch all URLs created by a user, newest first.

    Query on UserIndex GSI — not the main table.
    This is why the GSI exists: the main table is partitioned by
    short code, so Drake's URLs are scattered everywhere.
    The GSI is partitioned by user_id, so all of Drake's URLs
    are co-located in the GSI and fetchable in one Query.

    ScanIndexForward=False — sort descending (newest first).
    Default is ascending. For a dashboard you want newest first.

    The response includes only attributes we projected into the GSI
    (short_code, original_url, expires_at, click_count + keys).
    If you need more, you'd fetch each item individually — called
    "GSI + GetItem" pattern. We have enough for a dashboard.
    """
    table = get_table()
    response = table.query(
        IndexName=USER_INDEX,
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,   # newest first
    )
    return [URL.from_item(item) for item in response.get("Items", [])]


# ── Click operations ──────────────────────────────────────────────

def record_click(short_code: str) -> None:
    """
    Record one click — atomically increments two counters.

    Two UpdateItem calls (could pipeline, but DynamoDB doesn't have
    native pipelining like Redis — we use TransactWrite for atomicity
    if needed, but for click counting eventual consistency is fine):

    1. Increment click_count on the META item (total lifetime clicks)
    2. Increment count on today's CLICK aggregate item

    UpdateItem with ADD
    ────────────────────
    UpdateExpression="ADD click_count :one"
    This is DynamoDB's atomic increment. Equivalent to Redis INCR.
    ADD on a number attribute adds the value atomically — no read
    needed, no race condition. Two simultaneous clicks both succeed
    and the final count is correct.

    attribute_not_exists check in UpdateExpression
    ────────────────────────────────────────────────
    For the daily CLICK item: if today's item doesn't exist yet
    (first click of the day), ADD creates it with count=1.
    DynamoDB initializes missing numeric attributes to 0 before
    adding. So ADD :one on a missing attribute → count = 1.
    No need to check if the item exists first.
    """
    table = get_table()
    today = date.today().isoformat()

    # 1. Increment total click count on META item
    table.update_item(
        Key={
            "PK": f"{PREFIX_URL}{short_code}",
            "SK": SK_META,
        },
        UpdateExpression="ADD click_count :one",
        ExpressionAttributeValues={":one": 1},
    )

    # 2. Increment today's daily aggregate
    # If the item doesn't exist, DynamoDB creates it automatically
    table.update_item(
        Key={
            "PK": f"{PREFIX_URL}{short_code}",
            "SK": f"{SK_CLICK}{today}",
        },
        UpdateExpression="ADD #count :one SET short_code = if_not_exists(short_code, :code), #date = if_not_exists(#date, :date)",
        ExpressionAttributeNames={
            "#count": "count",   # 'count' is a reserved word in DynamoDB
            "#date":  "date",    # 'date' is also reserved
        },
        ExpressionAttributeValues={
            ":one":  1,
            ":code": short_code,
            ":date": today,
        },
    )
    #
    # ExpressionAttributeNames
    # ─────────────────────────
    # DynamoDB has reserved words (count, date, name, status, etc.)
    # If your attribute name is a reserved word, the query fails.
    # Fix: use a placeholder like #count and map it in ExpressionAttributeNames.
    # This is annoying but unavoidable. Always check the reserved words list
    # if you get a ValidationException on an UpdateExpression.


def get_click_history(short_code: str) -> list[ClickAggregate]:
    """
    Fetch all daily click aggregates for a URL.

    Query on the main table, filtering SK to only CLICK# items.
    This is the sort key range query pattern we designed for:
      PK = "URL#x7k2p"   (one partition)
      SK begins_with "CLICK#"   (all daily aggregates)

    Returns all items in that partition whose SK starts with "CLICK#".
    Result is sorted by SK ascending = chronological order (because
    SK is "CLICK#2024-01-01", "CLICK#2024-01-02" etc — lexicographic
    sort on ISO dates is the same as chronological sort).

    This query costs exactly one read unit per item returned —
    no scanning, no cross-partition hops.
    """
    table = get_table()
    response = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"{PREFIX_URL}{short_code}") &
            Key("SK").begins_with(SK_CLICK)
        ),
    )
    return [ClickAggregate.from_item(item) for item in response.get("Items", [])]


# ── User operations ───────────────────────────────────────────────

def put_user(user: User) -> None:
    """Create a user. Same conditional PutItem pattern as put_url."""
    table = get_table()
    table.put_item(
        Item=user.to_item(),
        ConditionExpression="attribute_not_exists(PK)",
    )


def get_user(user_id: str) -> User | None:
    """Fetch a user by ID."""
    table = get_table()
    response = table.get_item(
        Key={
            "PK": f"{PREFIX_USER}{user_id}",
            "SK": "PROFILE",
        }
    )
    item = response.get("Item")
    return User.from_item(item) if item else None


def increment_user_url_count(user_id: str) -> None:
    """Atomically increment the user's URL count."""
    table = get_table()
    table.update_item(
        Key={
            "PK": f"{PREFIX_USER}{user_id}",
            "SK": "PROFILE",
        },
        UpdateExpression="ADD url_count :one",
        ExpressionAttributeValues={":one": 1},
    )