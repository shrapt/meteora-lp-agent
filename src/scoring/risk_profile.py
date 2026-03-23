"""Risk appetite matching — classify wallets into risk profiles.

Key lesson from someone who built this:
"The wallets it chose are way too conservative for the balance I gave it"
→ Scoring must match RISK APPETITE, not just raw performance.
"""

from __future__ import annotations

from enum import Enum


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


def classify_wallet_risk(
    avg_range_width_bins: float,
    volatile_pair_ratio: float,
    avg_rebalance_freq_hours: float,
    capital_at_risk_ratio: float,
) -> RiskProfile:
    """Classify a wallet into a risk profile based on its LP behavior.

    Args:
        avg_range_width_bins: Average number of bins in positions
        volatile_pair_ratio: Fraction of positions in volatile (non-stable) pairs
        avg_rebalance_freq_hours: Average hours between rebalances
        capital_at_risk_ratio: Fraction of capital actively deployed vs reserved
    """
    aggressive_signals = 0
    conservative_signals = 0

    # Range width: tight (<10 bins) = conservative, wide (>30) = aggressive
    if avg_range_width_bins < 10:
        conservative_signals += 1
    elif avg_range_width_bins > 30:
        aggressive_signals += 1

    # Pair volatility: mostly stable pairs = conservative
    if volatile_pair_ratio < 0.3:
        conservative_signals += 1
    elif volatile_pair_ratio > 0.7:
        aggressive_signals += 1

    # Rebalance frequency: infrequent (>48h) = conservative, frequent (<6h) = aggressive
    if avg_rebalance_freq_hours > 48:
        conservative_signals += 1
    elif avg_rebalance_freq_hours < 6:
        aggressive_signals += 1

    # Capital at risk: low (<0.5) = conservative, high (>0.8) = aggressive
    if capital_at_risk_ratio < 0.5:
        conservative_signals += 1
    elif capital_at_risk_ratio > 0.8:
        aggressive_signals += 1

    if aggressive_signals >= 3:
        return RiskProfile.AGGRESSIVE
    if conservative_signals >= 3:
        return RiskProfile.CONSERVATIVE
    return RiskProfile.MODERATE


def matches_risk_appetite(
    wallet_profile: RiskProfile, target_profile: str
) -> bool:
    """Check if a wallet's risk profile matches the agent's target."""
    target = RiskProfile(target_profile.lower())
    if target == RiskProfile.MODERATE:
        return True  # moderate accepts learning from any wallet
    return wallet_profile == target
