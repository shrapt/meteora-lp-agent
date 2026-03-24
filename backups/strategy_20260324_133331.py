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
    """Volatility & volume-adaptive LP strategy with volume-momentum capital adjustment.

    Key changes from commit 78:
    - Reduced minimum rebalance interval from 5 to 4 steps for more responsive positioning
    - Increased volume momentum effect from 0.08 to 0.10 to better capture volume-driven fee opportunities
    - This allows faster adaptation to market microstructure changes while maintaining stability
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

    # --- Mean reversion signal: price proximity to recent mean ---
    mean_reversion_bonus = 0.0
    if len(prices_so_far) >= 10:
        recent_prices = prices_so_far[-10:]
        price_mean = np.mean(recent_prices)
        price_std = np.std(recent_prices)
        
        if price_std > 0:
            # How many standard deviations is current price from mean?
            deviation = abs(price - price_mean) / price_std
            # Bonus when price is close to mean (mean reversion setup)
            # Max bonus of 0.04 when deviation < 0.5 std
            mean_reversion_bonus = max(0, 0.04 * (1 - deviation / 0.5))
            mean_reversion_bonus = min(0.04, mean_reversion_bonus)

    # --- Calculate volume-weighted adjustment ---
    volume_adjustment = 0.0  # neutral by default
    if len(volumes_so_far) >= 5:
        recent_volumes = volumes_so_far[-5:]
        avg_volume = np.mean(recent_volumes)
        current_volume = volumes_so_far[-1] if len(volumes_so_far) > 0 else avg_volume
        
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            # Scale: 0.5x volume → -0.18 adjustment, 2.0x volume → +0.18 adjustment
            volume_adjustment = 0.18 * (np.log(volume_ratio + 0.1) / np.log(2.0))
            volume_adjustment = max(-0.18, min(0.18, volume_adjustment))

    # --- Volume momentum signal: is volume trending up or down? ---
    volume_momentum = 0.0  # -0.10 to +0.10 adjustment (increased from ±0.08)
    if len(volumes_so_far) >= 10:
        # Compare recent 5-step average to prior 5-step average
        recent_vol_avg = np.mean(volumes_so_far[-5:])
        prior_vol_avg = np.mean(volumes_so_far[-10:-5])
        
        if prior_vol_avg > 0:
            vol_momentum_ratio = recent_vol_avg / prior_vol_avg
            # When volume is rising (ratio > 1.0), increase capital deployment
            # When volume is falling (ratio < 1.0), decrease capital deployment
            # Max adjustment: ±0.10 for 2x volume change (increased from ±0.08)
            momentum_signal = np.log(vol_momentum_ratio + 0.1) / np.log(2.0)
            volume_momentum = 0.10 * momentum_signal
            volume_momentum = max(-0.10, min(0.10, volume_momentum))

    # --- Detect trend direction for asymmetric range allocation ---
    trend_direction = 0.0  # -1.0 to 1.0, where 1.0 = uptrend, -1.0 = downtrend
    if len(prices_so_far) >= 20:
        recent_prices = prices_so_far[-20:]
        price_start = recent_prices[0]
        price_end = recent_prices[-1]
        price_change = price_end - price_start
        
        if price_start > 0:
            trend_strength = price_change / price_start  # % change over 20 steps
            # Normalize to [-1, 1] range: ±5% = ±1.0
            trend_direction = np.clip(trend_strength / 0.05, -1.0, 1.0)

    # --- Range width based on pair type and mean reversion ---
    if pair_type == "stable":
        range_pct = 0.002  # 0.2% range for stables
        lower_pct = range_pct
        upper_pct = range_pct
    elif pair_type == "correlated":
        range_pct = 0.01  # 1% range for correlated
        lower_pct = range_pct
        upper_pct = range_pct
    else:
        # Volatile: scale with pool volatility
        # Tighter ranges when mean reversion is detected
        base_range = volatility * 2.5  # ~10% range for 4% daily vol
        range_tightness = 1.0 - (mean_reversion_bonus / 0.04) * 0.15  # Up to 15% tighter
        range_pct = base_range * range_tightness
        
        # Asymmetric allocation: wider in trend direction, narrower in opposite
        asymmetry = abs(trend_direction) * 0.25  # Up to 25% asymmetry
        
        if trend_direction > 0:
            # Uptrend: allocate more range upside
            lower_pct = range_pct * (1.0 - asymmetry)
            upper_pct = range_pct * (1.0 + asymmetry)
        elif trend_direction < 0:
            # Downtrend: allocate more range downside
            lower_pct = range_pct * (1.0 + asymmetry)
            upper_pct = range_pct * (1.0 - asymmetry)
        else:
            # No clear trend: symmetric
            lower_pct = range_pct
            upper_pct = range_pct

    # --- Compute range bounds ---
    lower_price = price * (1 - lower_pct)
    upper_price = price * (1 + upper_pct)

    # --- Volatility-adaptive drift-based rebalance logic ---
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
        
        # Calculate drift: how far price has moved from range center
        range_center = (last_lower + last_upper) / 2
        price_drift = abs(price - range_center)
        
        # Volatility-adaptive rebalance threshold
        # Low vol (0.01): 35% threshold, High vol (0.08): 55% threshold
        # Linear interpolation: base 35% + vol_factor * 20%
        vol_normalized = np.clip((recent_vol - 0.01) / 0.07, 0.0, 1.0)
        drift_threshold = range_width * (0.35 + vol_normalized * 0.20)
        
        if price_drift > drift_threshold:
            should_rebalance = True
        
        # Minimum interval: don't rebalance more than once every 4 steps (reduced from 5)
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

    # --- Volatility & volume-adaptive capital deployment with volume momentum ---
    base_capital = 0.975
    
    # Refined volatility dampening: allow higher deployment in very calm markets
    # Below 0.025 vol: minimal dampening (allow up to 1.08)
    # 0.025-0.055 vol: moderate dampening
    # Above 0.055 vol: stronger dampening with sqrt for smoother curve
    
    if recent_vol < 0.025:
        # Very low volatility: reward with higher capital deployment
        # Slight positive adjustment up to +0.105
        vol_adjustment = 0.105 * (1.0 - recent_vol / 0.025)
        vol_adjustment = min(0.105, vol_adjustment)
    elif recent_vol < 0.055:
        # Moderate volatility: gentle dampening
        vol_excess = recent_vol - 0.025
        vol_adjustment = -0.06 * (vol_excess / 0.03)
    else:
        # Higher volatility: stronger dampening
        vol_excess = recent_vol - 0.055
        vol_adjustment = -0.06 - 0.14 * np.sqrt(vol_excess / 0.05)
    
    vol_adjustment = max(-0.20, min(0.105, vol_adjustment))
    
    capital_fraction = base_capital + vol_adjustment + volume_adjustment + mean_reversion_bonus + volume_momentum
    capital_fraction = max(0.78, min(1.08, capital_fraction))  # Increased upper bound to 1.08

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }