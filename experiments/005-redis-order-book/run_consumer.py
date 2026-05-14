"""
Entry point for the matching engine.

Run this first, then run_producers.py in a second terminal.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from src.consumer.engine import run_engine

if __name__ == "__main__":
    try:
        asyncio.run(run_engine())
    except KeyboardInterrupt:
        print("\n[engine] Shutting down.")