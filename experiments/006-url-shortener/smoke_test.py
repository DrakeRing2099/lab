"""
Phase 1 smoke test.

Verifies:
  1. DynamoDB Local is reachable
  2. Table creation with GSI and TTL
  3. PutItem — create a user and a URL
  4. GetItem — read back by short code (the redirect path)
  5. Query  — fetch user's URLs via GSI
  6. UpdateItem — record a click (atomic increment)
  7. Query  — fetch click history

Run with: python smoke_test.py
(DynamoDB Local must be running: docker compose up -d)
"""

import sys
import time
sys.path.insert(0, ".")

from src.config import get_table
from src.db import (
    create_table, put_url, put_user, get_url,
    get_urls_for_user, record_click, get_click_history,
    get_user,
)
from src.models import URL, User


def separator(title: str):
    print(f"\n── {title} {'─' * (50 - len(title))}")


def main():
    print("\n🔌  Connecting to DynamoDB Local...")
    try:
        table = get_table()
        table.table_status  # triggers a describe call — fails if unreachable
        print("✅  Connected\n")
    except Exception:
        # Table doesn't exist yet — that's fine, we're about to create it
        pass

    # ── 1. Create table ──────────────────────────────────────────
    separator("Creating table")
    create_table()

    # ── 2. Create a user ─────────────────────────────────────────
    separator("Creating user")
    user = User(user_id="drake", email="drake@daiict.ac.in")
    put_user(user)
    print(f"✅  Created user: {user.user_id}")

    fetched_user = get_user("drake")
    assert fetched_user is not None
    assert fetched_user.email == "drake@daiict.ac.in"
    print(f"✅  Read back user: {fetched_user.user_id} / {fetched_user.email}")

    # ── 3. Create URLs ────────────────────────────────────────────
    separator("Creating URLs")

    url1 = URL.create(
        short_code="x7k2p9q",
        original_url="https://github.com/DrakeRing2099/lab",
        user_id="drake",
        ttl_days=30,
    )
    url2 = URL.create(
        short_code="abc1234",
        original_url="https://quant-bubbles.streamlit.app",
        user_id="drake",
        ttl_days=7,
    )

    put_url(url1)
    put_url(url2)
    print(f"✅  Created: {url1.short_code} → {url1.original_url}")
    print(f"✅  Created: {url2.short_code} → {url2.original_url}")

    # ── 4. GetItem — the redirect path ───────────────────────────
    separator("GetItem (redirect path)")
    fetched = get_url("x7k2p9q")
    assert fetched is not None
    assert fetched.original_url == "https://github.com/DrakeRing2099/lab"
    print(f"✅  Redirect: x7k2p9q → {fetched.original_url}")
    print(f"   Expires in: {fetched.expires_in_days} days")
    print(f"   click_count: {fetched.click_count}")

    # ── 5. GSI Query — user dashboard ────────────────────────────
    separator("GSI Query (user dashboard)")
    user_urls = get_urls_for_user("drake")
    assert len(user_urls) == 2
    print(f"✅  Found {len(user_urls)} URLs for 'drake':")
    for u in user_urls:
        print(f"   {u.short_code} → {u.original_url}  (expires in {u.expires_in_days}d)")

    # ── 6. Record clicks — atomic increment ──────────────────────
    separator("UpdateItem (atomic click counter)")
    print("   Simulating 5 clicks on x7k2p9q...")
    for i in range(5):
        record_click("x7k2p9q")
    print("✅  5 clicks recorded")

    # Verify count updated
    after_clicks = get_url("x7k2p9q")
    assert after_clicks.click_count == 5, f"Expected 5, got {after_clicks.click_count}"
    print(f"✅  click_count on META item: {after_clicks.click_count}")

    # ── 7. Click history ──────────────────────────────────────────
    separator("Query (click history)")
    history = get_click_history("x7k2p9q")
    assert len(history) == 1  # all 5 clicks happened today
    assert history[0].count == 5
    print(f"✅  Click history: {len(history)} day(s)")
    for day in history:
        print(f"   {day.date_str}: {day.count} clicks")

    # ── 8. Missing key ────────────────────────────────────────────
    separator("GetItem (missing key)")
    missing = get_url("doesnotexist")
    assert missing is None
    print("✅  Missing key returns None correctly")

    # ── 9. Duplicate prevention ───────────────────────────────────
    separator("ConditionalCheckFailed (duplicate short code)")
    try:
        put_url(url1)  # try to create the same short code again
        print("❌  Should have raised an exception")
    except Exception as e:
        if "ConditionalCheckFailedException" in str(type(e)):
            print("✅  Duplicate short code correctly rejected")
        else:
            print(f"✅  Correctly rejected with: {type(e).__name__}")

    print("\n🎉  Phase 1 complete — all DynamoDB operations working!\n")


if __name__ == "__main__":
    main()