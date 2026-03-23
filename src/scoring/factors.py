"""7 weighted scoring factors for wallet quality assessment.

Each factor returns a normalized score in [0, 100].
"""

from __future__ import annotations

import numpy as np


def win_rate_consistency(position_pnls: list[float]) -> float:
    """Factor 1 (weight: 0.20) — % of positions that were profitable, smoothed.

    Uses a smoothed win rate that penalizes small sample sizes through
    Bayesian shrinkage toward 50%.
    """
    if not position_pnls:
        return 0.0
    n = len(position_pnls)
    wins = sum(1 for p in position_pnls if p > 0)
    # Bayesian smoothing: add 2 pseudo-observations (1 win, 1 loss)
    smoothed_rate = (wins + 1) / (n + 2)
    return min(100.0, smoothed_rate * 100)


def fee_yield_efficiency(
    total_fees_usd: float, total_capital_usd: float, total_days: float
) -> float:
    """Factor 2 (weight: 0.20) — fees earned / capital deployed / time.

    Annualized fee yield as percentage, capped at 100.
    """
    if total_capital_usd <= 0 or total_days <= 0:
        return 0.0
    daily_yield = total_fees_usd / total_capital_usd / total_days
    annualized = daily_yield * 365 * 100  # as percentage
    # Cap at 100 (>100% annualized fee yield is exceptional)
    return min(100.0, annualized)


def capital_efficiency(
    avg_range_width_bins: float, avg_fee_per_unit_liquidity: float
) -> float:
    """Factor 3 (weight: 0.15) — how tight ranges are vs how much they earn.

    Tighter ranges that earn more fees = more capital efficient.
    Score favors narrow ranges with high fee capture.
    """
    if avg_range_width_bins <= 0:
        return 0.0
    # Efficiency = fee per unit / range width
    # Narrower range + more fees = higher efficiency
    efficiency = avg_fee_per_unit_liquidity / avg_range_width_bins
    # Normalize: typical good efficiency ~0.01, excellent ~0.05+
    return min(100.0, efficiency * 2000)


def activity_pattern_quality(
    rebalance_intervals_hours: list[float],
) -> float:
    """Factor 4 (weight: 0.15) — regular rebalancing vs panic moves.

    Measures coefficient of variation of rebalance intervals.
    Regular = good, erratic = bad.
    """
    if len(rebalance_intervals_hours) < 2:
        return 0.0
    arr = np.array(rebalance_intervals_hours)
    mean = arr.mean()
    if mean <= 0:
        return 0.0
    cv = arr.std() / mean  # coefficient of variation
    # cv of 0 = perfectly regular (score 100)
    # cv of 2+ = very erratic (score ~0)
    return max(0.0, min(100.0, 100 * (1 - cv / 2)))


def drawdown_control(drawdown_pcts: list[float]) -> float:
    """Factor 5 (weight: 0.10) — worst IL periods vs recovery.

    Lower max drawdown = better score.
    """
    if not drawdown_pcts:
        return 50.0  # neutral if no data
    max_dd = max(abs(d) for d in drawdown_pcts) if drawdown_pcts else 0
    # 0% drawdown = 100, 50%+ drawdown = 0
    return max(0.0, min(100.0, 100 * (1 - max_dd / 50)))


def track_record_length(total_days: float) -> float:
    """Factor 6 (weight: 0.10) — longer = more reliable signal.

    Scales from 0 at 7 days to 100 at 180+ days.
    """
    if total_days < 7:
        return 0.0
    return min(100.0, (total_days - 7) / (180 - 7) * 100)


def pool_diversity(unique_pools: int) -> float:
    """Factor 7 (weight: 0.10) — spreads across pool types vs single-pool.

    1 pool = 20, 5+ pools = 100.
    """
    if unique_pools <= 0:
        return 0.0
    if unique_pools == 1:
        return 20.0
    return min(100.0, 20 + (unique_pools - 1) * 20)


# Factor weights — must sum to 1.0
FACTOR_WEIGHTS = {
    "win_rate_consistency": 0.20,
    "fee_yield_efficiency": 0.20,
    "capital_efficiency": 0.15,
    "activity_pattern_quality": 0.15,
    "drawdown_control": 0.10,
    "track_record_length": 0.10,
    "pool_diversity": 0.10,
}


def compute_weighted_score(factor_scores: dict[str, float]) -> float:
    """Compute the weighted sum of all 7 factors."""
    total = 0.0
    for name, weight in FACTOR_WEIGHTS.items():
        total += factor_scores.get(name, 0.0) * weight
    return total
