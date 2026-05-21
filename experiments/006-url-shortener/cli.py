"""
CLI for the URL shortener.

Usage:
  python cli.py setup                                    — create table
  python cli.py user <user_id> <email>                  — create user
  python cli.py shorten <url> --user <id> [--code CODE] — shorten a URL
  python cli.py redirect <code>                         — resolve a short code
  python cli.py stats <code>                            — click analytics
  python cli.py dashboard <user_id>                     — all URLs for a user
  python cli.py click <code> [--times N]                — simulate clicks
"""

import sys
sys.path.insert(0, ".")

from src.db import create_table, put_user, get_user
from src.models import User
from src.shortener import shorten_url, redirect, get_stats, get_dashboard
from datetime import datetime


def fmt_url(url: str, max_len: int = 60) -> str:
    return url if len(url) <= max_len else url[:max_len - 3] + "..."


def cmd_setup(args):
    create_table()


def cmd_user(args):
    if len(args) < 2:
        print("Usage: python cli.py user <user_id> <email>")
        return
    user_id, email = args[0], args[1]
    existing = get_user(user_id)
    if existing:
        print(f"User '{user_id}' already exists ({existing.email})")
        return
    user = User(user_id=user_id, email=email)
    put_user(user)
    print(f"✅  Created user '{user_id}' ({email})")


def cmd_shorten(args):
    # parse: <url> --user <id> [--code <code>] [--days <n>]
    if not args:
        print("Usage: python cli.py shorten <url> --user <id> [--code CODE] [--days N]")
        return

    original_url = args[0]
    user_id      = None
    custom_code  = None
    ttl_days     = 30

    i = 1
    while i < len(args):
        if args[i] == "--user" and i + 1 < len(args):
            user_id = args[i + 1]; i += 2
        elif args[i] == "--code" and i + 1 < len(args):
            custom_code = args[i + 1]; i += 2
        elif args[i] == "--days" and i + 1 < len(args):
            ttl_days = int(args[i + 1]); i += 2
        else:
            i += 1

    if not user_id:
        print("Error: --user is required")
        return

    try:
        url = shorten_url(original_url, user_id, ttl_days, custom_code)
        print(f"✅  Shortened:")
        print(f"   code     : {url.short_code}")
        print(f"   original : {fmt_url(url.original_url)}")
        print(f"   expires  : {url.expires_in_days} days")
    except ValueError as e:
        print(f"❌  {e}")
    except Exception as e:
        print(f"❌  Failed: {e}")


def cmd_redirect(args):
    if not args:
        print("Usage: python cli.py redirect <code>")
        return
    code = args[0]
    original = redirect(code)
    if original:
        print(f"→  {original}")
        print(f"   (click recorded)")
    else:
        print(f"❌  '{code}' not found or expired")


def cmd_stats(args):
    if not args:
        print("Usage: python cli.py stats <code>")
        return
    code = args[0]
    stats = get_stats(code)
    if not stats:
        print(f"❌  '{code}' not found or expired")
        return

    print(f"\n  short code  : {stats['short_code']}")
    print(f"  url         : {fmt_url(stats['original_url'])}")
    print(f"  total clicks: {stats['total_clicks']}")
    print(f"  expires in  : {stats['expires_in']} days")

    if stats['daily_clicks']:
        print(f"\n  click history:")
        for day in stats['daily_clicks']:
            bar = "█" * min(day['count'], 40)
            print(f"    {day['date']}  {bar} {day['count']}")
    else:
        print(f"\n  no clicks yet")


def cmd_dashboard(args):
    if not args:
        print("Usage: python cli.py dashboard <user_id>")
        return
    user_id = args[0]
    urls = get_dashboard(user_id)
    if not urls:
        print(f"No URLs found for '{user_id}'")
        return

    print(f"\n  URLs for '{user_id}' ({len(urls)} total)\n")
    print(f"  {'code':<10} {'clicks':>6}  {'expires':>8}  url")
    print(f"  {'─'*10} {'─'*6}  {'─'*8}  {'─'*40}")
    for u in urls:
        print(f"  {u['short_code']:<10} {u['click_count']:>6}  {u['expires_in']:>7}d  {fmt_url(u['original_url'], 45)}")


def cmd_click(args):
    """Simulate clicks — useful for testing analytics."""
    if not args:
        print("Usage: python cli.py click <code> [--times N]")
        return
    code = args[0]
    times = 1
    if len(args) >= 3 and args[1] == "--times":
        times = int(args[2])

    from src.db import record_click
    for _ in range(times):
        record_click(code)
    print(f"✅  Recorded {times} click(s) on '{code}'")


COMMANDS = {
    "setup":     cmd_setup,
    "user":      cmd_user,
    "shorten":   cmd_shorten,
    "redirect":  cmd_redirect,
    "stats":     cmd_stats,
    "dashboard": cmd_dashboard,
    "click":     cmd_click,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Commands: setup | user | shorten | redirect | stats | dashboard | click")
        sys.exit(1)

    cmd  = sys.argv[1]
    args = sys.argv[2:]
    COMMANDS[cmd](args)