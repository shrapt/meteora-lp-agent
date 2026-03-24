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
    """Simplified profitability-aware LP strategy with consolidated capital signals.

    Key changes from previous:
    - Removed redundant volume_adjustment and volume_momentum (noisy short-term signals)
    - Consolidated capital deployment into: base + volatility + mean_reversion + profitability
    - Cleaner fee_to_tvl integration without conflicting signals
    - Reduced signal overlap for more stable deployments
    """
    pair_type = pool_context.get("pair_type", "volatile")
    volatility = pool_context.get("volatility", 0.04)
    bin_step = pool_context.get("bin_step", 10)
    fee_to_tvl = pool_context.get("fee_to_tvl_ratio", 0.01)

    # --- Calculate recent realized volatility for adaptive behavior ---
    recent_vol = volatility
    if len(prices_so_far) >= 5:
        recent_prices = prices_so_far[-5:]
        log_returns = np.diff(np.log(recent_prices))
        recent_vol = np.std(log_returns) if len(log_returns) > 0 else volatility

    # --- Mean reversion signal: price proximity to recent mean ---
    mean_reversion_bonus = 0.0
    if len(prices_so_far) >= 10:
        recent_prices = prices_so_far[-10:]
        price_mean = np.mean(recent_prices)
        price_std = np.std(recent_prices)
        
        if price_std > 0:
            deviation = abs(price - price_mean) / price_std
            mean_reversion_bonus = max(0, 0.04 * (1 - deviation / 0.5))
            mean_reversion_bonus = min(0.04, mean_reversion_bonus)

    # --- Detect trend direction for asymmetric range allocation ---
    trend_direction = 0.0
    if len(prices_so_far) >= 20:
        recent_prices = prices_so_far[-20:]
        price_start = recent_prices[0]
        price_end = recent_prices[-1]
        price_change = price_end - price_start
        
        if price_start > 0:
            trend_strength = price_change / price_start
            trend_direction = np.clip(trend_strength / 0.05, -1.0, 1.0)

    # --- Fee-to-TVL profitability signal (primary capital driver) ---
    fee_signal_capital = 0.0
    fee_signal_range = 0.0
    
    if fee_to_tvl > 0:
        fee_normalized = np.clip(np.log(fee_to_tvl / 0.01 + 0.1) / np.log(2.0), -0.5, 1.5)
        fee_signal_capital = 0.07 * fee_normalized  # Increased from 0.06
        fee_signal_range = -0.0008 * fee_normalized

    # --- Range width based on pair type and profitability ---
    if pair_type == "stable":
        range_pct = 0.0015 + fee_signal_range
        lower_pct = range_pct
        upper_pct = range_pct
    elif pair_type == "correlated":
        range_pct = 0.008 + fee_signal_range
        lower_pct = range_pct
        upper_pct = range_pct
    else:
        # Volatile: scale with pool volatility
        base_range = volatility * 2.5
        range_tightness = 1.0 - (mean_reversion_bonus / 0.04) * 0.15
        range_pct = base_range * range_tightness + fee_signal_range
        range_pct = max(0.001, range_pct)
        
        # Asymmetric allocation
        asymmetry = abs(trend_direction) * 0.25
        
        if trend_direction > 0:
            lower_pct = range_pct * (1.0 - asymmetry)
            upper_pct = range_pct * (1.0 + asymmetry)
        elif trend_direction < 0:
            lower_pct = range_pct * (1.0 + asymmetry)
            upper_pct = range_pct * (1.0 - asymmetry)
        else:
            lower_pct = range_pct
            upper_pct = range_pct

    # --- Compute range bounds ---
    lower_price = price * (1 - lower_pct)
    upper_price = price * (1 + upper_pct)

    # --- Adaptive rebalance frequency based on price momentum and position ---
    should_rebalance = False
    if step == 0:
        should_rebalance = True
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        last_lower = state.get("last_lower", lower_price)
        last_upper = state.get("last_upper", upper_price)
        range_width = last_upper - last_lower
        range_center = (last_lower + last_upper) / 2
        price_drift = abs(price - range_center)
        
        # Calculate price momentum
        price_momentum = 0.0
        if len(prices_so_far) >= 3:
            recent_prices = prices_so_far[-3:]
            momentum_change = recent_prices[-1] - recent_prices[0]
            if recent_prices[0] > 0:
                price_momentum = abs(momentum_change / recent_prices[0])
        
        # Adaptive minimum interval with pool-type awareness
        if pair_type == "stable":
            if price_drift > range_width * 0.3 and price_momentum > 0.003:
                min_interval = 1
            elif price_drift < range_width * 0.15 and price_momentum < 0.0015:
                min_interval = 3
            else:
                min_interval = 2
        elif pair_type == "correlated":
            if price_drift > range_width * 0.35 and price_momentum > 0.004:
                min_interval = 2
            elif price_drift < range_width * 0.18 and price_momentum < 0.002:
                min_interval = 4
            else:
                min_interval = 3
        else:
            # Volatile
            if price_drift > range_width * 0.4 and price_momentum > 0.005:
                min_interval = 2
            elif price_drift < range_width * 0.2 and price_momentum < 0.002:
                min_interval = 6
            else:
                min_interval = 4
        
        # Volatility-adaptive rebalance threshold
        vol_normalized = np.clip((recent_vol - 0.01) / 0.07, 0.0, 1.0)
        
        if pair_type == "stable":
            drift_threshold = range_width * (0.30 + vol_normalized * 0.15)
        elif pair_type == "correlated":
            drift_threshold = range_width * (0.33 + vol_normalized * 0.18)
        else:
            drift_threshold = range_width * (0.35 + vol_normalized * 0.20)
        
        if price_drift > drift_threshold:
            should_rebalance = True
        
        # Enforce minimum interval
        steps_since = step - state.get("last_rebalance_step", 0)
        if steps_since < min_interval:
            should_rebalance = False

    if should_rebalance:
        state["last_rebalance_step"] = step
        state["last_lower"] = lower_price
        state["last_upper"] = upper_price
    else:
        lower_price = state.get("last_lower", lower_price)
        upper_price = state.get("last_upper", upper_price)

    # --- Price proximity bonus (conservative) ---
    range_center = (lower_price + upper_price) / 2
    range_width = upper_price - lower_price
    if range_width > 0:
        price_offset = abs(price - range_center) / (range_width / 2)
        if price_offset < 0.5:
            proximity_bonus = 0.035 * (1.0 - price_offset / 0.5)
        elif price_offset > 0.75:
            proximity_bonus = -0.045 * ((price_offset - 0.75) / 0.25)
        else:
            proximity_bonus = 0.035 * (1.0 - (price_offset - 0.5) / 0.25)
        proximity_bonus = max(-0.045, min(0.035, proximity_bonus))
    else:
        proximity_bonus = 0.0

    # --- Volatility-adaptive capital deployment with pool-type-specific ceilings ---
    base_capital = 0.975
    
    if recent_vol < 0.020:
        vol_adjustment = 0.125 * (1.0 - recent_vol / 0.020)
        vol_adjustment = min(0.125, vol_adjustment)
    elif recent_vol < 0.030:
        vol_excess = recent_vol - 0.020
        vol_adjustment = 0.125 - 0.015 * (vol_excess / 0.010)
    elif recent_vol < 0.060:
        vol_excess = recent_vol - 0.030
        vol_adjustment = -0.05 * (vol_excess / 0.030)
    else:
        vol_excess = recent_vol - 0.060
        vol_adjustment = -0.05 - 0.14 * np.sqrt(vol_excess / 0.05)
    
    vol_adjustment = max(-0.20, min(0.125, vol_adjustment))
    
    # Pool-type-specific capital ceilings
    if pair_type == "stable":
        capital_ceiling = 1.25
        if fee_to_tvl > 0.05 and recent_vol < 0.015:
            capital_ceiling = 1.30
    elif pair_type == "correlated":
        capital_ceiling = 1.15
        if fee_to_tvl > 0.05 and recent_vol < 0.022:
            capital_ceiling = 1.22
    else:
        # Volatile
        capital_ceiling = 1.10
        if fee_to_tvl > 0.05 and recent_vol < 0.025:
            capital_ceiling = 1.18
    
    # Consolidated capital deployment: base + vol + profitability + mean_reversion + proximity
    # Removed volume_adjustment and volume_momentum to reduce noise
    capital_fraction = base_capital + vol_adjustment + fee_signal_capital + mean_reversion_bonus + proximity_bonus
    capital_fraction = max(0.78, min(capital_ceiling, capital_fraction))

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }