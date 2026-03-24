"""THE FILE YOU MODIFY: LP strategy logic.

This is the ONLY file the autoresearch loop modifies.
Everything else (prepare.py, simulate.py, src/) is read-only.

The strategy function is called at every simulation step with:
    - step: int — current timestep
    - price: float — current price
    - prices_so_far: np.ndarray — all prices up to now
    - volumes_so_far: np.ndarray — all volumes up to now
    - pool_context: dict — pool metadata (name, pair_type, bin_step, volatility, etc.)
    - state: dict — mutable state that persists across steps

It must return a dict with:
    - "lower_price": float — lower bound of LP range
    - "upper_price": float — upper bound of LP range
    - "rebalance": bool — whether to rebalance this step
    - "capital_fraction": float — fraction of capital to deploy (0-1)
"""

from __future__ import annotations

import numpy as np


def strategy(
    step: int,
    price: float,
    prices_so_far: np.ndarray,
    volumes_so_far: np.ndarray,
    pool_context: dict,
    state: dict,
) -> dict:
    """Baseline LP strategy — simple volatility-adaptive ranges.

    This is the starting point. The autoresearch loop will iterate on this.
    """
    pair_type = pool_context.get("pair_type", "volatile")
    volatility = pool_context.get("volatility", 0.04)
    bin_step = pool_context.get("bin_step", 10)

    # --- Range width based on pair type ---
    if pair_type == "stable":
        range_pct = 0.002  # 0.2% range for stables
    elif pair_type == "correlated":
        range_pct = 0.01  # 1% range for correlated
    else:
        # Volatile: scale with pool volatility
        range_pct = volatility * 2.5  # ~10% range for 4% daily vol

    # --- Compute range bounds ---
    lower_price = price * (1 - range_pct)
    upper_price = price * (1 + range_pct)

    # --- Rebalance logic ---
    # Rebalance on first step, or when price drifts near range edge
    should_rebalance = False
    if step == 0:
        should_rebalance = True
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        last_lower = state.get("last_lower", lower_price)
        last_upper = state.get("last_upper", upper_price)
        range_mid = (last_lower + last_upper) / 2
        range_half = (last_upper - last_lower) / 2

        # Rebalance when price moves beyond 80% of range
        if range_half > 0:
            displacement = abs(price - range_mid) / range_half
            if displacement > 0.80:
                should_rebalance = True

        # Minimum interval: don't rebalance more than once every 4 steps (4 hours)
        steps_since = step - state.get("last_rebalance_step", 0)
        if steps_since < 4:
            should_rebalance = False

    if should_rebalance:
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        lower_price = state.get("last_lower", lower_price)
        upper_price = state.get("last_upper", upper_price)

    # --- Capital deployment ---
    capital_fraction = 0.80  # Deploy 80% of capital

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }
