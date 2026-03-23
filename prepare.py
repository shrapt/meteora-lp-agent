"""READ-ONLY: Data prep, evaluation harness, and top LP data loading.

DO NOT MODIFY THIS FILE during experiments.

This file:
1. Fetches/caches pool data and price series for simulation
2. Defines the evaluation harness that simulate.py calls
3. Loads top LP patterns as "mentor data" for strategy.py
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.common.config import CACHE_DIR, ROOT_DIR
from src.common.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants — target pools for simulation
# ---------------------------------------------------------------------------

# Pool configs: (name, pair_type, base_fee_bps, bin_step, volatility_class)
TARGET_POOLS = [
    {
        "name": "SOL-USDC",
        "pair_type": "volatile",
        "base_fee_bps": 15,
        "bin_step": 10,
        "initial_price": 150.0,
        "volatility": 0.04,  # daily vol
    },
    {
        "name": "JUP-USDC",
        "pair_type": "volatile",
        "base_fee_bps": 25,
        "bin_step": 20,
        "initial_price": 1.20,
        "volatility": 0.06,
    },
    {
        "name": "JTO-USDC",
        "pair_type": "volatile",
        "base_fee_bps": 25,
        "bin_step": 20,
        "initial_price": 3.50,
        "volatility": 0.07,
    },
    {
        "name": "USDC-USDT",
        "pair_type": "stable",
        "base_fee_bps": 1,
        "bin_step": 1,
        "initial_price": 1.0,
        "volatility": 0.001,
    },
    {
        "name": "mSOL-SOL",
        "pair_type": "correlated",
        "base_fee_bps": 5,
        "bin_step": 5,
        "initial_price": 1.08,
        "volatility": 0.005,
    },
]

# Simulation parameters
SIM_DAYS = 30
SIM_STEPS_PER_DAY = 24  # hourly steps
INITIAL_CAPITAL_USD = 10_000.0
TX_COST_USD = 0.01  # Solana tx cost

# ---------------------------------------------------------------------------
# Synthetic price generation (for simulation without live data)
# ---------------------------------------------------------------------------


def generate_price_series(
    initial_price: float,
    daily_volatility: float,
    days: int = SIM_DAYS,
    steps_per_day: int = SIM_STEPS_PER_DAY,
    seed: int | None = None,
) -> np.ndarray:
    """Generate a synthetic price series using geometric Brownian motion."""
    rng = np.random.default_rng(seed)
    total_steps = days * steps_per_day
    dt = 1.0 / steps_per_day
    # GBM: dS = mu*S*dt + sigma*S*dW
    mu = 0.0  # drift-free for fair simulation
    sigma = daily_volatility
    log_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rng.standard_normal(total_steps)
    prices = initial_price * np.exp(np.cumsum(log_returns))
    prices = np.insert(prices, 0, initial_price)
    return prices


def generate_volume_series(
    base_volume: float,
    days: int = SIM_DAYS,
    steps_per_day: int = SIM_STEPS_PER_DAY,
    seed: int | None = None,
) -> np.ndarray:
    """Generate synthetic trading volume series."""
    rng = np.random.default_rng(seed)
    total_steps = days * steps_per_day + 1
    # Log-normal volume with some autocorrelation
    raw = rng.lognormal(mean=0, sigma=0.5, size=total_steps)
    # Apply simple smoothing
    smoothed = np.convolve(raw, np.ones(3) / 3, mode="same")
    return smoothed * base_volume / smoothed.mean()


# ---------------------------------------------------------------------------
# Pool simulation data
# ---------------------------------------------------------------------------


@dataclass
class PoolSimContext:
    """All data needed to simulate one pool."""

    name: str
    pair_type: str
    base_fee_bps: int
    bin_step: int
    initial_price: float
    volatility: float
    prices: np.ndarray = field(default_factory=lambda: np.array([]))
    volumes: np.ndarray = field(default_factory=lambda: np.array([]))
    timestamps: np.ndarray = field(default_factory=lambda: np.array([]))


def prepare_pool(pool_config: dict, seed: int = 42) -> PoolSimContext:
    """Prepare simulation data for one pool."""
    prices = generate_price_series(
        pool_config["initial_price"],
        pool_config["volatility"],
        seed=seed,
    )
    # Base daily volume proportional to price and volatility
    base_vol = pool_config["initial_price"] * 1_000_000 * pool_config["volatility"]
    volumes = generate_volume_series(base_vol, seed=seed + 1)

    total_steps = SIM_DAYS * SIM_STEPS_PER_DAY + 1
    now = int(time.time())
    timestamps = np.array(
        [now - (total_steps - i) * 3600 for i in range(total_steps)]
    )

    return PoolSimContext(
        name=pool_config["name"],
        pair_type=pool_config["pair_type"],
        base_fee_bps=pool_config["base_fee_bps"],
        bin_step=pool_config["bin_step"],
        initial_price=pool_config["initial_price"],
        volatility=pool_config["volatility"],
        prices=prices,
        volumes=volumes,
        timestamps=timestamps,
    )


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------


@dataclass
class SimResult:
    """Result of simulating a strategy on one pool."""

    pool_name: str
    net_yield: float = 0.0  # (final_value - initial) / initial
    time_in_range: float = 0.0  # fraction of time position was in range
    max_drawdown: float = 0.0  # worst peak-to-trough
    total_fees_earned: float = 0.0
    total_il: float = 0.0  # impermanent loss
    num_rebalances: int = 0
    tx_costs: float = 0.0


def evaluate_strategy(
    strategy_fn,
    pool: PoolSimContext,
    capital: float = INITIAL_CAPITAL_USD,
) -> SimResult:
    """Run a strategy on a pool's price series and compute metrics.

    The strategy_fn signature:
        strategy_fn(
            step: int,
            price: float,
            prices_so_far: np.ndarray,
            volumes_so_far: np.ndarray,
            pool_context: dict,
            state: dict,
        ) -> dict

    The strategy returns a dict with:
        - "lower_price": float — lower bound of LP range
        - "upper_price": float — upper bound of LP range
        - "rebalance": bool — whether to rebalance this step
        - "capital_fraction": float — fraction of capital to deploy (0-1)
    """
    n_steps = len(pool.prices)
    pool_ctx = {
        "name": pool.name,
        "pair_type": pool.pair_type,
        "base_fee_bps": pool.base_fee_bps,
        "bin_step": pool.bin_step,
        "initial_price": pool.initial_price,
        "volatility": pool.volatility,
    }

    # Strategy state (persists across steps)
    state: dict = {}

    # Tracking variables
    current_lower = 0.0
    current_upper = 0.0
    deployed_capital = 0.0
    reserve_capital = capital
    total_fees = 0.0
    total_il = 0.0
    num_rebalances = 0
    in_range_steps = 0
    portfolio_values = [capital]

    for step in range(n_steps):
        price = float(pool.prices[step])
        prices_so_far = pool.prices[: step + 1]
        volumes_so_far = pool.volumes[: step + 1]

        # Get strategy decision
        try:
            decision = strategy_fn(
                step=step,
                price=price,
                prices_so_far=prices_so_far,
                volumes_so_far=volumes_so_far,
                pool_context=pool_ctx,
                state=state,
            )
        except Exception as e:
            log.error("Strategy error at step %d: %s", step, e)
            return SimResult(pool_name=pool.name)

        lower = decision.get("lower_price", price * 0.95)
        upper = decision.get("upper_price", price * 1.05)
        should_rebalance = decision.get("rebalance", step == 0)
        cap_fraction = decision.get("capital_fraction", 0.8)
        cap_fraction = max(0.0, min(1.0, cap_fraction))

        # Handle rebalance
        if should_rebalance and (lower != current_lower or upper != current_upper):
            # Return deployed capital (with IL) to reserve
            if deployed_capital > 0:
                reserve_capital += deployed_capital + _compute_step_il(
                    current_lower, current_upper, price, deployed_capital
                )
                deployed_capital = 0.0

            # Deploy new position
            current_lower = lower
            current_upper = upper
            deployed_capital = reserve_capital * cap_fraction
            reserve_capital -= deployed_capital
            num_rebalances += 1

        # Check if in range
        in_range = current_lower <= price <= current_upper if deployed_capital > 0 else False
        if in_range:
            in_range_steps += 1

        # Compute fees earned this step (proportional to volume and position)
        if in_range and deployed_capital > 0:
            volume = float(pool.volumes[step]) if step < len(pool.volumes) else 0
            fee_rate = pool.base_fee_bps / 10_000
            # Simplified: fees proportional to (your_liquidity / total_pool) * volume * fee_rate
            # Assume your share is small relative to pool
            range_width = max(upper - lower, 1e-10)
            concentration = price / range_width  # tighter range = more concentrated
            step_fees = volume * fee_rate * (deployed_capital / 1_000_000) * min(concentration, 10)
            total_fees += step_fees

        # Compute IL for this step
        if deployed_capital > 0:
            step_il = _compute_step_il(current_lower, current_upper, price, deployed_capital)
        else:
            step_il = 0.0

        # Track portfolio value
        portfolio_value = reserve_capital + deployed_capital + step_il + total_fees
        portfolio_values.append(portfolio_value)

    # Compute final metrics
    tx_costs = num_rebalances * TX_COST_USD
    final_value = portfolio_values[-1] - tx_costs
    net_yield = (final_value - capital) / capital

    # Max drawdown
    peak = capital
    max_dd = 0.0
    for v in portfolio_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    time_in_range = in_range_steps / max(n_steps, 1)

    return SimResult(
        pool_name=pool.name,
        net_yield=net_yield,
        time_in_range=time_in_range,
        max_drawdown=max_dd,
        total_fees_earned=total_fees,
        total_il=total_il,
        num_rebalances=num_rebalances,
        tx_costs=tx_costs,
    )


def _compute_step_il(lower: float, upper: float, current_price: float, capital: float) -> float:
    """Simplified impermanent loss calculation for concentrated liquidity.

    IL for concentrated LP is amplified relative to full-range LP.
    """
    if lower <= 0 or upper <= lower:
        return 0.0
    mid = (lower + upper) / 2
    if mid <= 0:
        return 0.0
    price_ratio = current_price / mid
    # Concentrated IL approximation
    if price_ratio <= 0:
        return 0.0
    # Standard IL formula adjusted for concentration
    sqrt_r = np.sqrt(price_ratio)
    il_pct = 2 * sqrt_r / (1 + price_ratio) - 1  # always <= 0
    concentration_factor = mid / max(upper - lower, 1e-10)
    amplified_il = il_pct * min(concentration_factor, 10)
    return capital * amplified_il


# ---------------------------------------------------------------------------
# Top LP data loading (mentor data for strategy.py)
# ---------------------------------------------------------------------------


def load_top_lp_patterns() -> dict:
    """Load aggregated top LP patterns from cache."""
    path = CACHE_DIR / "top_lps" / "aggregated.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def load_top_lp_individual() -> list[dict]:
    """Load individual top LP patterns from cache."""
    path = CACHE_DIR / "top_lps" / "latest.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


# ---------------------------------------------------------------------------
# Main — prepare all simulation data
# ---------------------------------------------------------------------------


def prepare_all(seed: int = 42) -> list[PoolSimContext]:
    """Prepare simulation contexts for all target pools."""
    pools = []
    for i, cfg in enumerate(TARGET_POOLS):
        pool = prepare_pool(cfg, seed=seed + i * 100)
        pools.append(pool)
        log.info(
            "Prepared %s: %d price steps, vol=%.3f",
            pool.name,
            len(pool.prices),
            pool.volatility,
        )
    return pools


if __name__ == "__main__":
    log.info("Preparing simulation data...")
    pools = prepare_all()
    log.info("Done. %d pools ready for simulation.", len(pools))

    mentor = load_top_lp_patterns()
    if mentor:
        log.info("Top LP patterns loaded: %s", json.dumps(mentor, indent=2))
    else:
        log.info("No top LP patterns cached yet. Run: uv run python -m src.scraper.top_lps")
