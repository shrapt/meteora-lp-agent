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
    """Volatility & volume-adaptive LP strategy with optimized capital deployment.

    Key changes from commit 10:
    - Adjusted capital fraction bounds from [0.65, 0.98] to [0.75, 1.0]
    - More aggressive capital deployment to maximize fee capture
    - Slightly reduced volatility penalty (from -0.20 to -0.18) for better capital utilization
    - Keeps all successful elements: volatility-adaptive ranges, volume-weighted adjustment, adaptive rebalance thresholds
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

    # --- Calculate volume-weighted adjustment ---
    volume_adjustment = 0.0  # neutral by default
    if len(volumes_so_far) >= 5:
        recent_volumes = volumes_so_far[-5:]
        avg_volume = np.mean(recent_volumes)
        current_volume = volumes_so_far[-1] if len(volumes_so_far) > 0 else avg_volume
        
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            # Scale: 0.5x volume → -0.15 adjustment, 2.0x volume → +0.15 adjustment
            # Capped to ±0.15 to avoid over-deployment
            volume_adjustment = 0.15 * (np.log(volume_ratio + 0.1) / np.log(2.0))
            volume_adjustment = max(-0.15, min(0.15, volume_adjustment))

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

        # Adaptive rebalance threshold: higher threshold = less frequent rebalancing
        if pair_type == "stable":
            base_threshold = 0.75  # Higher threshold for stables (rebalance less often)
        else:
            base_threshold = 0.70  # Standard threshold for volatile pairs
        
        threshold = base_threshold + (recent_vol * 0.5)  # Higher vol → higher threshold
        threshold = min(threshold, 0.90)  # Cap at 90%

        # Rebalance when price moves beyond threshold of range
        if range_half > 0:
            displacement = abs(price - range_mid) / range_half
            if displacement > threshold:
                should_rebalance = True

        # Minimum interval: don't rebalance more than once every 3 steps (3 hours)
        steps_since = step - state.get("last_rebalance_step", 0)
        if steps_since < 3:
            should_rebalance = False

    if should_rebalance:
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        lower_price = state.get("last_lower", lower_price)
        upper_price = state.get("last_upper", upper_price)

    # --- Volatility & volume-adaptive capital deployment ---
    # Deploy more capital when volatility is low AND volume is high (safer, better fee capture)
    # Deploy less when volatility is high OR volume is low (protect capital)
    base_capital = 0.91
    vol_adjustment = -0.18 * (recent_vol / 0.05)  # Slightly softer reduction: -0.18
    capital_fraction = base_capital + vol_adjustment + volume_adjustment
    capital_fraction = max(0.75, min(1.0, capital_fraction))  # Clamp to [0.75, 1.0]

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }