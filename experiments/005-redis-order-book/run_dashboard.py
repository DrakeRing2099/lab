"""
Entry point for the terminal dashboard.

Run this in a third terminal alongside run_consumer.py
and run_producers.py.
"""

import sys
sys.path.insert(0, ".")

from src.dashboard.view import run_dashboard

if __name__ == "__main__":
    try:
        run_dashboard()
    except KeyboardInterrupt:
        print("\n[dashboard] Closed.")