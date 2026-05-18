"""
Config — DynamoDB connection and table constants.

Boto3:

  client   (low level) — maps 1:1 to the DynamoDB HTTP API.
                          Returns raw dicts with DynamoDB type annotations.
                          e.g. {'S': 'hello'} for a string, {'N': '42'} for a number.

  resource (high level) — wraps the client, handles type annotations
                          automatically. 

DYNAMODB TYPE SYSTEM
─────────────────────
DynamoDB is schemaless per item, but it has a strict type system:
  S   — string
  N   — number (stored as string internally, boto3 handles conversion)
  B   — binary
  BOOL— boolean
  NULL— null
  L   — list
  M   — map (nested dict)
  SS  — string set
  NS  — number set

"""

import boto3
from boto3.dynamodb.conditions import Key, Attr  # noqa: F401 — re-exported for convenience

# ── Table constants ───────────────────────────────────────────────
TABLE_NAME = "urls"

# Primary key field names
PK = "PK"
SK = "SK"

# GSI name and its key fields
USER_INDEX      = "UserIndex"
USER_INDEX_PK   = "user_id"
USER_INDEX_SK   = "created_at"

# TTL attribute name — must match what you configure in the AWS console
# (or in create_table). DynamoDB reads this field and auto-deletes items.
TTL_ATTRIBUTE = "expires_at"

# Key prefixes — prevents collisions in single table design
PREFIX_URL  = "URL#"
PREFIX_USER = "USER#"

# Sort key constants
SK_META  = "META"
SK_CLICK = "CLICK#"   # followed by date string: "CLICK#2024-01-15"

# ── Short code config ─────────────────────────────────────────────
SHORT_CODE_LENGTH = 7   # e.g. "x7k2p9q" — 7 chars gives 37^7 = 94B combinations
DEFAULT_TTL_DAYS  = 30  # links expire after 30 days by default


# ── Connection factory ────────────────────────────────────────────
def get_dynamodb():
    """
    Returns a boto3 DynamoDB resource pointed at DynamoDB Local.

    For real AWS you'd remove endpoint_url and set real credentials
    via environment variables or IAM role. Everything else stays identical.

    region_name must be set even for local — boto3 requires it.
    The actual value doesn't matter for local, but 'us-east-1' is convention.
    """
    return boto3.resource(
        "dynamodb",
        region_name="us-east-1",
        endpoint_url="http://localhost:8000",
        aws_access_key_id="fake",
        aws_secret_access_key="fake",
    )


def get_table():
    """Returns the urls table resource. Use this everywhere."""
    return get_dynamodb().Table(TABLE_NAME)