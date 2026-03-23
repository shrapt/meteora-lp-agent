"""Tests for the wallet scoring system."""

import time

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
from src.scoring.gates import (
    compute_gate_multiplier,
    recency_gate,
    sample_size_gate,
    track_record_gate,
)
from src.scoring.risk_profile import RiskProfile, classify_wallet_risk
from src.scoring.scorer import WalletData, score_wallet


class TestGates:
    def test_track_record_gate_too_short(self):
        # 3 days ago — should fail (< 7 days)
        ts = int(time.time()) - 3 * 86400
        assert track_record_gate(ts) == 0.0

    def test_track_record_gate_passes(self):
        # 30 days ago — should pass
        ts = int(time.time()) - 30 * 86400
        assert track_record_gate(ts) > 0.0

    def test_recency_gate_fresh(self):
        # Active 1 day ago
        ts = int(time.time()) - 86400
        assert recency_gate(ts) == 1.0

    def test_recency_gate_stale(self):
        # Active 60 days ago — should be 0
        ts = int(time.time()) - 60 * 86400
        assert recency_gate(ts) == 0.0

    def test_sample_size_gate_too_few(self):
        assert sample_size_gate(3) == 0.0

    def test_sample_size_gate_enough(self):
        assert sample_size_gate(10) > 0.0

    def test_all_gates_zero_if_any_fails(self):
        now = int(time.time())
        # Enough track record and recency, but too few positions
        gate = compute_gate_multiplier(
            first_activity_ts=now - 30 * 86400,
            last_activity_ts=now - 86400,
            num_completed_positions=2,
        )
        assert gate == 0.0


class TestFactors:
    def test_win_rate_all_wins(self):
        score = win_rate_consistency([1.0, 2.0, 3.0, 4.0, 5.0])
        assert score > 70  # Should be high

    def test_win_rate_all_losses(self):
        score = win_rate_consistency([-1.0, -2.0, -3.0])
        assert score < 40  # Should be low

    def test_fee_yield(self):
        # $100 fees on $10k over 30 days ≈ 12.2% annualized
        score = fee_yield_efficiency(100, 10000, 30)
        assert 10 < score < 15

    def test_pool_diversity_single(self):
        assert pool_diversity(1) == 20.0

    def test_pool_diversity_many(self):
        assert pool_diversity(5) == 100.0

    def test_weighted_score_sums_correctly(self):
        factors = {
            "win_rate_consistency": 80,
            "fee_yield_efficiency": 60,
            "capital_efficiency": 50,
            "activity_pattern_quality": 70,
            "drawdown_control": 90,
            "track_record_length": 40,
            "pool_diversity": 60,
        }
        score = compute_weighted_score(factors)
        expected = 80 * 0.20 + 60 * 0.20 + 50 * 0.15 + 70 * 0.15 + 90 * 0.10 + 40 * 0.10 + 60 * 0.10
        assert abs(score - expected) < 0.01


class TestRiskProfile:
    def test_conservative(self):
        profile = classify_wallet_risk(
            avg_range_width_bins=5,
            volatile_pair_ratio=0.1,
            avg_rebalance_freq_hours=72,
            capital_at_risk_ratio=0.3,
        )
        assert profile == RiskProfile.CONSERVATIVE

    def test_aggressive(self):
        profile = classify_wallet_risk(
            avg_range_width_bins=50,
            volatile_pair_ratio=0.9,
            avg_rebalance_freq_hours=2,
            capital_at_risk_ratio=0.95,
        )
        assert profile == RiskProfile.AGGRESSIVE


class TestScorer:
    def test_score_wallet_gates_fail(self):
        """Wallet with insufficient data should score 0."""
        data = WalletData(
            wallet="test_wallet",
            first_activity_ts=int(time.time()) - 2 * 86400,  # 2 days — fails gate
            last_activity_ts=int(time.time()),
            num_completed_positions=2,  # fails gate
        )
        result = score_wallet(data)
        assert result.final_score == 0.0
        assert not result.passes_minimum

    def test_score_wallet_gates_pass(self):
        """Wallet with sufficient data should get a positive score."""
        now = int(time.time())
        data = WalletData(
            wallet="good_wallet",
            first_activity_ts=now - 60 * 86400,
            last_activity_ts=now - 86400,
            num_completed_positions=15,
            position_pnls=[10, 20, -5, 15, 8, -3, 12, 7, 25, -2],
            total_fees_usd=500,
            total_capital_usd=10000,
            total_days=60,
            avg_range_width_bins=15,
            avg_fee_per_unit_liquidity=0.05,
            rebalance_intervals_hours=[12, 14, 10, 16, 11, 13, 15, 12],
            drawdown_pcts=[5, 8, 3, 12, 6],
            unique_pools=4,
        )
        result = score_wallet(data)
        assert result.final_score > 0
        assert result.passes_minimum
        assert result.gate_multiplier > 0
