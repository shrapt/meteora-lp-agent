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
    """Volatility-adaptive LP strategy with aggressive capital deployment in calm markets.

    Key changes:
    - Increased base capital fraction from 80% to 87% to capture more fees
    - More aggressive capital deployment when recent volatility is low
    - Tighter rebalance thresholds for stable pairs to reduce unnecessary rebalancing
    """
    pair_type = pool_context.get("pair_type", "volatile")
    volatility = pool_context.get("volatility", 0.04)
    bin_step = pool_context.get("bin_step", 10)

    # --- Calculate recent realized volatility for adaptive behavior ---
    recent_vol = volatility  # fallback
    if len(prices_so_far) >= 5:
        # Use last 5 prices to estimate recent volatility
        recent_prices = prices_so_far[-5:]
        log_returns = np.diff(np.log(recent_prices))
        recent_vol = np.std(log_returns) if len(log_returns) > 0 else volatility

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

    # --- Rebalance logic with volatility-adaptive threshold ---
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

        # Adaptive rebalance threshold: tighter in calm markets, looser in volatile ones
        # Pair-type specific base thresholds
        if pair_type == "stable":
            base_threshold = 0.60  # Tighter threshold for stables (rebalance more often)
        else:
            base_threshold = 0.70  # Standard threshold for volatile pairs
        
        threshold = base_threshold + (recent_vol * 0.5)  # Higher vol → higher threshold
        threshold = min(threshold, 0.90)  # Cap at 90%

        # Rebalance when price moves beyond threshold of range
        if range_half > 0:
            displacement = abs(price - range_mid) / range_half
            if displacement > threshold:
                should_rebalance = True

        # Minimum interval: don't rebalance more than once every 2 steps (2 hours)
        steps_since = step - state.get("last_rebalance_step", 0)
        if steps_since < 2:
            should_rebalance = False

    if should_rebalance:
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        lower_price = state.get("last_lower", lower_price)
        upper_price = state.get("last_upper", upper_price)

    # --- Volatility-adaptive capital deployment (more aggressive) ---
    # Deploy more capital when volatility is low (safer), less when high
    # Increased base from 80% to 87% for better fee capture
    base_capital = 0.87
    vol_adjustment = -0.35 * (recent_vol / 0.05)  # Normalize to 5% vol baseline, steeper decay
    capital_fraction = base_capital + vol_adjustment
    capital_fraction = max(0.55, min(0.98, capital_fraction))  # Increased max from 0.95 to 0.98

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }