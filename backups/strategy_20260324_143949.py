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
    """Volatility & volume-adaptive LP strategy with adaptive rebalance frequency.

    Key changes from commit 78:
    - Added adaptive rebalance frequency based on price momentum and range position
    - When price is moving away from range center, allow more frequent rebalances (2 steps)
    - When price is stable/centered, enforce longer intervals (6 steps) to reduce churn
    - Refined proximity bonus to be more conservative
    - Slight reduction in capital ceiling during normal conditions
    """
    pair_type = pool_context.get("pair_type", "volatile")
    volatility = pool_context.get("volatility", 0.04)
    bin_step = pool_context.get("bin_step", 10)

    # --- Calculate recent realized volatility for adaptive behavior ---
    recent_vol = volatility  # fallback
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

    # --- Calculate volume-weighted adjustment ---
    volume_adjustment = 0.0
    if len(volumes_so_far) >= 5:
        recent_volumes = volumes_so_far[-5:]
        avg_volume = np.mean(recent_volumes)
        current_volume = volumes_so_far[-1] if len(volumes_so_far) > 0 else avg_volume
        
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            volume_adjustment = 0.18 * (np.log(volume_ratio + 0.1) / np.log(2.0))
            volume_adjustment = max(-0.18, min(0.18, volume_adjustment))

    # --- Volume momentum signal ---
    volume_momentum = 0.0
    if len(volumes_so_far) >= 10:
        recent_vol_avg = np.mean(volumes_so_far[-5:])
        prior_vol_avg = np.mean(volumes_so_far[-10:-5])
        
        if prior_vol_avg > 0:
            vol_momentum_ratio = recent_vol_avg / prior_vol_avg
            momentum_signal = np.log(vol_momentum_ratio + 0.1) / np.log(2.0)
            volume_momentum = 0.10 * momentum_signal
            volume_momentum = max(-0.10, min(0.10, volume_momentum))

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

    # --- Range width based on pair type and mean reversion ---
    if pair_type == "stable":
        range_pct = 0.002
        lower_pct = range_pct
        upper_pct = range_pct
    elif pair_type == "correlated":
        range_pct = 0.01
        lower_pct = range_pct
        upper_pct = range_pct
    else:
        # Volatile: scale with pool volatility
        base_range = volatility * 2.5
        range_tightness = 1.0 - (mean_reversion_bonus / 0.04) * 0.15
        range_pct = base_range * range_tightness
        
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
        
        # Calculate price momentum: how fast is price moving?
        price_momentum = 0.0
        if len(prices_so_far) >= 3:
            recent_prices = prices_so_far[-3:]
            momentum_change = recent_prices[-1] - recent_prices[0]
            if recent_prices[0] > 0:
                price_momentum = abs(momentum_change / recent_prices[0])
        
        # Adaptive minimum interval:
        # - If price is moving fast away from center: allow rebalance every 2 steps
        # - If price is stable/centered: require 6 steps minimum
        # - Otherwise: 4 steps (baseline)
        if price_drift > range_width * 0.4 and price_momentum > 0.005:
            # Price moving away from center - be responsive
            min_interval = 2
        elif price_drift < range_width * 0.2 and price_momentum < 0.002:
            # Price stable and centered - reduce churn
            min_interval = 6
        else:
            # Normal case
            min_interval = 4
        
        # Volatility-adaptive rebalance threshold
        vol_normalized = np.clip((recent_vol - 0.01) / 0.07, 0.0, 1.0)
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

    # --- Price proximity bonus (slightly more conservative) ---
    range_center = (lower_price + upper_price) / 2
    range_width = upper_price - lower_price
    if range_width > 0:
        price_offset = abs(price - range_center) / (range_width / 2)
        if price_offset < 0.5:
            proximity_bonus = 0.040 * (1.0 - price_offset / 0.5)
        elif price_offset > 0.75:
            proximity_bonus = -0.055 * ((price_offset - 0.75) / 0.25)
        else:
            proximity_bonus = 0.040 * (1.0 - (price_offset - 0.5) / 0.25)
        proximity_bonus = max(-0.055, min(0.040, proximity_bonus))
    else:
        proximity_bonus = 0.0

    # --- Fee-rate signal ---
    fee_signal = 0.0
    fee_rate = pool_context.get("fee_rate", 0.001)
    
    if "fee_history" not in state:
        state["fee_history"] = []
    
    state["fee_history"].append(fee_rate)
    if len(state["fee_history"]) > 20:
        state["fee_history"] = state["fee_history"][-20:]
    
    if len(state["fee_history"]) >= 5:
        recent_fees = state["fee_history"][-5:]
        avg_fee = np.mean(recent_fees)
        current_fee = state["fee_history"][-1]
        
        if avg_fee > 0:
            fee_ratio = current_fee / avg_fee
            fee_signal = 0.08 * (np.log(fee_ratio + 0.1) / np.log(2.0))
            fee_signal = max(-0.05, min(0.08, fee_signal))

    # --- Volatility-adaptive capital deployment ---
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
    
    # Slightly reduced capital ceiling for stability
    capital_ceiling = 1.10
    if fee_signal > 0.04 and recent_vol < 0.025:
        capital_ceiling = 1.18
    
    capital_fraction = base_capital + vol_adjustment + volume_adjustment + mean_reversion_bonus + volume_momentum + proximity_bonus + fee_signal
    capital_fraction = max(0.78, min(capital_ceiling, capital_fraction))

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }