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
    """Volatility & volume-adaptive LP strategy with asymmetric ranges based on trend.

    Key changes from commit 28:
    - More responsive rebalancing: drift threshold reduced from 50% to 40% of range width
    - Minimum rebalance interval reduced from 5 steps to 3 steps
    - Captures more mean reversion opportunities while still avoiding excessive churn
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
            # Scale: 0.5x volume → -0.15 adjustment, 2.0x volume → +0.15 adjustment
            # Capped to ±0.15 to avoid over-deployment
            volume_adjustment = 0.15 * (np.log(volume_ratio + 0.1) / np.log(2.0))
            volume_adjustment = max(-0.15, min(0.15, volume_adjustment))

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
        # When uptrend (trend_direction > 0): wider upper, narrower lower
        # When downtrend (trend_direction < 0): wider lower, narrower upper
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

    # --- Drift-based rebalance logic ---
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
        
        # Rebalance threshold: trigger when price drifts beyond 40% of range width
        # (reduced from 50% for more responsive rebalancing)
        drift_threshold = range_width * 0.40
        
        if price_drift > drift_threshold:
            should_rebalance = True
        
        # Minimum interval: don't rebalance more than once every 3 steps (3 hours)
        # (reduced from 5 steps for more responsive rebalancing)
        # This allows capturing more mean reversion while still avoiding excessive churn
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
    # Deploy more capital when: low volatility, high volume, mean reversion signal
    # Deploy less when: high volatility, low volume, or price far from mean
    base_capital = 0.94  # Slightly increased from 0.92
    # Linear volatility adjustment: -0.20 per 0.05 volatility above baseline
    vol_adjustment = -0.20 * ((recent_vol - 0.02) / 0.05)
    vol_adjustment = max(-0.18, min(0.0, vol_adjustment))  # Cap between -0.18 and 0
    capital_fraction = base_capital + vol_adjustment + volume_adjustment + mean_reversion_bonus
    capital_fraction = max(0.76, min(1.0, capital_fraction))  # Clamp to [0.76, 1.0]

    return {
        "lower_price": lower_price,
        "upper_price": upper_price,
        "rebalance": should_rebalance,
        "capital_fraction": capital_fraction,
    }