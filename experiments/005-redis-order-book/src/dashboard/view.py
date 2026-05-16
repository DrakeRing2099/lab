"""
Live terminal dashboard using Rich.

ARCHITECTURE
─────────────
Rich's Live context manager takes over the terminal and re-renders
a Layout on every refresh cycle. We poll Redis every 0.5s and
rebuild the tables from the current sorted set state.

We use the SYNC Redis client here because Rich's Live runs in the
main thread (sync context). The async client would require running
an event loop inside the Live loop — unnecessary complexity.

WHY POLLING INSTEAD OF PUB/SUB FOR THE DASHBOARD?
────────────────────────────────────────────────────
Pub/Sub would give us instant trade notifications but:
  1. It doesn't give us the full book state — just trade events
  2. It requires a blocking subscribe loop which conflicts with
     Rich's own render loop
  3. For a 0.5s refresh rate, polling Redis is trivially cheap

The trades hash (trades:latest) gives us everything we need.
Pub/Sub would be the right choice if we were building a WebSocket
server that pushes updates to a browser — different use case.

LAYOUT
───────
┌─────────────────────────────────────────────────────┐
│                    header                           │
├─────────────────┬───────────────────────────────────┤
│   order book    │         trade tape                │
│   (bids/asks    │         (recent fills)            │
│    ladder)      │                                   │
├─────────────────┴───────────────────────────────────┤
│                    footer / stats                   │
└─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from datetime import datetime

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.config import get_sync_redis, INITIAL_MID_PRICE
from src.consumer.book import (
    sync_get_book_snapshot,
    sync_get_mid_price,
    sync_get_recent_trades,
)


REFRESH_RATE = 0.5   # seconds between renders
BOOK_DEPTH   = 10    # price levels shown per side
TAPE_DEPTH   = 15    # recent trades shown


def build_book_table(
    bids: list[tuple[str, float]],
    asks: list[tuple[str, float]],
    mid: float | None,
) -> Table:
    """
    Renders the order book ladder.

    Asks displayed top (lowest ask first, ascending up the table).
    Mid price in the center.
    Bids displayed below (highest bid first, descending).

    Colors:
      Asks = red (sellers want higher price)
      Bids = green (buyers want lower price)
      Mid  = yellow
    """
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("order id",  style="dim",    width=10)
    table.add_column("price",     justify="right", width=10)
    table.add_column("side",      justify="center",width=6)

    # Asks: show in reverse (lowest ask at the bottom, closest to mid)
    for oid, price in reversed(asks[:BOOK_DEPTH]):
        table.add_row(
            Text(oid[:8], style="dim"),
            Text(f"{price:.2f}", style="bold red"),
            Text("ASK", style="red"),
        )

    # Mid price separator
    mid_str = f"{mid:.4f}" if mid else "---"
    table.add_row(
        Text("", style=""),
        Text(f"~{mid_str}", style="bold yellow"),
        Text("mid", style="yellow dim"),
    )

    # Bids: highest first
    for oid, price in bids[:BOOK_DEPTH]:
        table.add_row(
            Text(oid[:8], style="dim"),
            Text(f"{price:.2f}", style="bold green"),
            Text("BID", style="green"),
        )

    return table


def build_tape_table(trades: list[dict]) -> Table:
    """
    Renders the trade tape — most recent fills.

    Each row shows: price, qty, buyer, seller, time.
    """
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("price",   justify="right", width=9)
    table.add_column("qty",     justify="right", width=6)
    table.add_column("buyer",   width=14)
    table.add_column("seller",  width=14)
    table.add_column("time",    justify="right", width=8, style="dim")

    for t in trades[:TAPE_DEPTH]:
        try:
            price    = float(t.get("price", 0))
            qty      = float(t.get("qty", 0))
            buyer    = str(t.get("buyer_id", "?"))[:13]
            seller   = str(t.get("seller_id", "?"))[:13]
            ts       = float(t.get("timestamp", 0))
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
        except (ValueError, TypeError):
            continue

        table.add_row(
            Text(f"{price:.2f}", style="bold cyan"),
            Text(f"{qty:.1f}",   style="white"),
            Text(buyer,          style="green dim"),
            Text(seller,         style="red dim"),
            time_str,
        )

    if not trades:
        table.add_row(
            Text("waiting...", style="dim"), "", "", "", "",
        )

    return table


def build_stats_bar(
    mid: float | None,
    bids: list,
    asks: list,
    trade_count: int,
) -> Text:
    """Footer stats line."""
    best_bid = bids[0][1]  if bids  else None
    best_ask = asks[0][1]  if asks  else None
    spread   = (best_ask - best_bid) if (best_bid and best_ask) else None

    parts = []
    parts.append(f"mid: [yellow]{mid:.4f}[/yellow]" if mid else "mid: [dim]---[/dim]")
    parts.append(f"bid: [green]{best_bid:.2f}[/green]" if best_bid else "bid: [dim]---[/dim]")
    parts.append(f"ask: [red]{best_ask:.2f}[/red]" if best_ask else "ask: [dim]---[/dim]")
    parts.append(f"spread: [cyan]{spread:.4f}[/cyan]" if spread else "spread: [dim]---[/dim]")
    parts.append(f"trades: [white]{trade_count}[/white]")
    parts.append(f"depth: [dim]{len(bids)}b / {len(asks)}a[/dim]")

    return Text.from_markup("   |   ".join(parts))


def run_dashboard() -> None:
    """
    Main dashboard loop.

    Rich's Live context manager handles terminal takeover and
    cleanup. On every tick we fetch state from Redis and rebuild
    all tables from scratch — simple and always consistent.
    """
    r       = get_sync_redis()
    console = Console()
    trade_count = 0

    with Live(
        console=console,
        refresh_per_second=int(1 / REFRESH_RATE),
        screen=True,          # takes over full terminal
    ) as live:
        while True:
            try:
                bids, asks  = sync_get_book_snapshot(r, depth=BOOK_DEPTH)
                mid         = sync_get_mid_price(r)
                trades      = sync_get_recent_trades(r, n=TAPE_DEPTH)
                trade_count = len(trades)

                book_panel  = Panel(
                    build_book_table(bids, asks, mid),
                    title="[bold]order book[/bold]",
                    border_style="dim",
                    padding=(0, 1),
                )
                tape_panel  = Panel(
                    build_tape_table(trades),
                    title="[bold]trade tape[/bold]",
                    border_style="dim",
                    padding=(0, 1),
                )
                stats       = build_stats_bar(mid, bids, asks, trade_count)

                layout = Layout()
                layout.split_column(
                    Layout(
                        Panel(
                            Text.from_markup(
                                f"[bold]redis order book simulator[/bold]   "
                                f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"
                            ),
                            border_style="dim",
                        ),
                        name="header",
                        size=3,
                    ),
                    Layout(name="body", ratio=1),
                    Layout(
                        Panel(stats, border_style="dim"),
                        name="footer",
                        size=3,
                    ),
                )
                layout["body"].split_row(
                    Layout(book_panel,  name="book", ratio=1),
                    Layout(tape_panel,  name="tape", ratio=2),
                )

                live.update(layout)
                time.sleep(REFRESH_RATE)

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]dashboard error: {e}[/red]")
                time.sleep(1)