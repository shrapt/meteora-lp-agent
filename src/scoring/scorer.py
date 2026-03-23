"""Main wallet scoring engine (v2+ with gate multipliers).

Combines gate multipliers × weighted factor scores to produce a final
wallet quality score. Only wallets passing all gates get a non-zero score.

Key insight from prior art:
- v1 was useless: a wallet with 1 winning trade scored 100
- v2 uses gate multipliers: track_record × recency × sample_size
- 88 wallets passed v1 filters, only 33 survived v2. Filtering > finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.scoring.factors import (
    activity_pattern_quality,
    capital_efficiency,
    compute_weighted_score,
    drawdown_control,
    fee_yield_efficiency,
    pool_diversity,
    track_record_length,
    win_rate_consistency,
)
from src.scoring.gates import compute_gate_multiplier
from src.scoring.risk_profile import RiskProfile, classify_wallet_risk


@dataclass
class WalletData:
    """All data needed to score a wallet."""

    wallet: str
    first_activity_ts: int = 0
    last_activity_ts: int = 0
    num_completed_positions: int = 0
    position_pnls: list[float] | None = None
    total_fees_usd: float = 0.0
    total_capital_usd: float = 0.0
    total_days: float = 0.0
    avg_range_width_bins: float = 0.0
    avg_fee_per_unit_liquidity: float = 0.0
    rebalance_intervals_hours: list[float] | None = None
    drawdown_pcts: list[float] | None = None
    unique_pools: int = 0
    volatile_pair_ratio: float = 0.5
    avg_rebalance_freq_hours: float = 24.0
    capital_at_risk_ratio: float = 0.7

    def __post_init__(self):
        if self.position_pnls is None:
            self.position_pnls = []
        if self.rebalance_intervals_hours is None:
            self.rebalance_intervals_hours = []
        if self.drawdown_pcts is None:
            self.drawdown_pcts = []


@dataclass
class WalletScore:
    """Result of scoring a wallet."""

    wallet: str
    final_score: float
    gate_multiplier: float
    weighted_factor_score: float
    factor_scores: dict[str, float]
    risk_profile: RiskProfile

    @property
    def passes_minimum(self) -> bool:
        return self.final_score > 0 and self.gate_multiplier > 0


def score_wallet(data: WalletData) -> WalletScore:
    """Score a wallet using gate multipliers × weighted factors.

    final_score = weighted_sum_of_7_factors × track_record_gate × recency_gate × sample_size_gate
    """
    # Compute gate multiplier (0 if any gate fails)
    gate = compute_gate_multiplier(
        first_activity_ts=data.first_activity_ts,
        last_activity_ts=data.last_activity_ts,
        num_completed_positions=data.num_completed_positions,
    )

    # Compute individual factor scores
    factor_scores = {
        "win_rate_consistency": win_rate_consistency(data.position_pnls),
        "fee_yield_efficiency": fee_yield_efficiency(
            data.total_fees_usd, data.total_capital_usd, data.total_days
        ),
        "capital_efficiency": capital_efficiency(
            data.avg_range_width_bins, data.avg_fee_per_unit_liquidity
        ),
        "activity_pattern_quality": activity_pattern_quality(
            data.rebalance_intervals_hours
        ),
        "drawdown_control": drawdown_control(data.drawdown_pcts),
        "track_record_length": track_record_length(data.total_days),
        "pool_diversity": pool_diversity(data.unique_pools),
    }

    weighted = compute_weighted_score(factor_scores)

    # Final score = weighted factors × gate multiplier
    final = weighted * gate

    # Classify risk profile
    risk = classify_wallet_risk(
        avg_range_width_bins=data.avg_range_width_bins,
        volatile_pair_ratio=data.volatile_pair_ratio,
        avg_rebalance_freq_hours=data.avg_rebalance_freq_hours,
        capital_at_risk_ratio=data.capital_at_risk_ratio,
    )

    return WalletScore(
        wallet=data.wallet,
        final_score=final,
        gate_multiplier=gate,
        weighted_factor_score=weighted,
        factor_scores=factor_scores,
        risk_profile=risk,
    )


def score_and_rank_wallets(
    wallets: list[WalletData], min_score: float = 0.0
) -> list[WalletScore]:
    """Score all wallets and return ranked list (highest first)."""
    scores = [score_wallet(w) for w in wallets]
    passing = [s for s in scores if s.final_score >= min_score and s.passes_minimum]
    return sorted(passing, key=lambda s: s.final_score, reverse=True)
