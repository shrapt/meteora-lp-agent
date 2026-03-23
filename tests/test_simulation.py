"""Tests for the simulation pipeline."""

import numpy as np

from prepare import (
    evaluate_strategy,
    generate_price_series,
    generate_volume_series,
    prepare_pool,
    TARGET_POOLS,
)
from strategy import strategy


class TestPriceGeneration:
    def test_generates_correct_length(self):
        prices = generate_price_series(100.0, 0.04, days=10, steps_per_day=24, seed=42)
        assert len(prices) == 10 * 24 + 1

    def test_starts_at_initial_price(self):
        prices = generate_price_series(150.0, 0.04, seed=42)
        assert prices[0] == 150.0

    def test_all_positive(self):
        prices = generate_price_series(100.0, 0.10, seed=42)
        assert np.all(prices > 0)


class TestSimulation:
    def test_evaluate_baseline_runs(self):
        pool = prepare_pool(TARGET_POOLS[0], seed=42)
        result = evaluate_strategy(strategy, pool)
        assert result.pool_name == "SOL-USDC"
        assert result.num_rebalances >= 1
        assert 0 <= result.time_in_range <= 1.0

    def test_evaluate_all_pools(self):
        for i, cfg in enumerate(TARGET_POOLS):
            pool = prepare_pool(cfg, seed=42 + i * 100)
            result = evaluate_strategy(strategy, pool)
            assert result.pool_name == cfg["name"]
            # Should not crash
            assert isinstance(result.net_yield, float)
