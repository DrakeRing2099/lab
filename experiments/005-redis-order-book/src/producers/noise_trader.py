"""
Noise Trader producer.

REAL-WORLD ANALOGY
───────────────────
Retail traders, uninformed flow, random hedging activity. They don't
have an edge — they trade for liquidity needs, not alpha. They're
essential for a realistic market because they provide the background
noise that hides informed traders' signals.

BEHAVIOR
─────────
Two responsibilities:

1. Generates random orders — random side, random price around mid
   with a wider distribution than the market maker, random qty.
   Sometimes fires a market order (no price) for extra realism.

2. Drives mid price via GBM (Geometric Brownian Motion).
   This is the key mechanism that makes the whole simulation live —
   without an exogenous price driver, the mid only moves when trades
   happen, which creates a chicken-and-egg problem.

GBM PRICE UPDATE
─────────────────
From your stochastic calc course: dS = μS dt + σS dW

Discretized:
  S(t+dt) = S(t) * exp((μ - σ²/2)dt + σ√dt * Z)
  where Z ~ N(0,1)

We use:
  μ = 0 (no drift — pure random walk)
  σ = 0.002 (0.2% vol per step — realistic for a liquid stock)
  dt = interval (time between steps)

The noise trader writes the new mid price to book:mid after each
step. All other producers read this. So GBM drives the whole market.

WHY THE NOISE TRADER OWNS THE PRICE PROCESS?
──────────────────────────────────────────────
In a real market, price is set by supply/demand across all participants.
Here we simplify: the noise trader IS the exogenous price process.
The market maker quotes around it. The trend follower reacts to it.
This is the "noise trader + informed trader" model from market
microstructure theory (Kyle 1985, if you want to go deep).

PARAMETERS
───────────
mu          : drift (annualized, 0 = pure random walk)
sigma       : volatility (per step)
interval    : seconds between steps (0.6s)
"""

from __future__ import annotations

import math
import random

import redis.asyncio as aioredis

from src.config import INITIAL_MID_PRICE, MID_PRICE_KEY
from src.models import Order, OrderType, Side
from src.producers.base import BaseProducer


class NoiseTrader(BaseProducer):
    def __init__(
        self,
        trader_id: str  = "noise-trader",
        mu: float       = 0.0,
        sigma: float    = 0.002,
        base_qty: float = 5.0,
        interval: float = 0.6,
    ):
        super().__init__(trader_id, interval)
        self.mu       = mu
        self.sigma    = sigma
        self.base_qty = base_qty
        self._mid     = INITIAL_MID_PRICE   # local price state for GBM

    def _gbm_step(self, dt: float) -> float:
        """
        One GBM step.

        S(t+dt) = S(t) * exp((μ - σ²/2)dt + σ√dt * Z)

        The (μ - σ²/2) term is the Itô correction — without it,
        E[S(t)] would drift upward even with μ=0. You know this
        from your stochastic calc course: it's the difference between
        the arithmetic and geometric mean in continuous time.
        """
        Z   = random.gauss(0, 1)
        dt  = self.interval
        log_return = (self.mu - 0.5 * self.sigma**2) * dt + self.sigma * math.sqrt(dt) * Z
        self._mid  = round(self._mid * math.exp(log_return), 4)
        return self._mid

    async def generate_orders(self, mid: float) -> list[Order]:
        # Step the GBM price process and write new mid to Redis
        new_mid = self._gbm_step(self.interval)
        await self.r.set(MID_PRICE_KEY, str(new_mid))

        # Random side
        side = random.choice([Side.BID, Side.ASK])

        # 15% chance of a market order — adds urgency/realism
        is_market = random.random() < 0.15

        if is_market:
            return [Order.create(
                self.trader_id, side,
                qty=round(self.base_qty * random.uniform(0.5, 1.5), 1),
                order_type=OrderType.MARKET,
            )]

        # Limit order: price randomly distributed around mid
        # Wider distribution than MM (±2% vs MM's ±0.5%)
        offset = new_mid * random.uniform(-0.02, 0.02)
        price  = round(new_mid + offset, 2)
        qty    = round(self.base_qty * random.uniform(0.5, 2.0), 1)

        return [Order.create(
            self.trader_id, side, qty=qty,
            price=price, order_type=OrderType.LIMIT,
        )]