"""Tests for the strategy module."""

import numpy as np

from strategy import strategy


class TestStrategy:
    def test_first_step_rebalances(self):
        result = strategy(
            step=0,
            price=100.0,
            prices_so_far=np.array([100.0]),
            volumes_so_far=np.array([1000.0]),
            pool_context={"pair_type": "volatile", "volatility": 0.04, "bin_step": 10},
            state={},
        )
        assert result["rebalance"] is True
        assert result["lower_price"] < 100.0
        assert result["upper_price"] > 100.0
        assert 0 < result["capital_fraction"] <= 1.0

    def test_stable_pair_tight_range(self):
        result = strategy(
            step=0,
            price=1.0,
            prices_so_far=np.array([1.0]),
            volumes_so_far=np.array([1000.0]),
            pool_context={"pair_type": "stable", "volatility": 0.001, "bin_step": 1},
            state={},
        )
        range_width = result["upper_price"] - result["lower_price"]
        assert range_width < 0.01  # Tight range for stables

    def test_no_rebalance_too_soon(self):
        state = {}
        # First step rebalances
        strategy(
            step=0, price=100.0,
            prices_so_far=np.array([100.0]),
            volumes_so_far=np.array([1000.0]),
            pool_context={"pair_type": "volatile", "volatility": 0.04, "bin_step": 10},
            state=state,
        )
        # Step 1 — should NOT rebalance (too soon)
        result = strategy(
            step=1, price=100.5,
            prices_so_far=np.array([100.0, 100.5]),
            volumes_so_far=np.array([1000.0, 1100.0]),
            pool_context={"pair_type": "volatile", "volatility": 0.04, "bin_step": 10},
            state=state,
        )
        assert result["rebalance"] is False

    def test_returns_required_keys(self):
        result = strategy(
            step=0, price=50.0,
            prices_so_far=np.array([50.0]),
            volumes_so_far=np.array([500.0]),
            pool_context={"pair_type": "volatile", "volatility": 0.05, "bin_step": 20},
            state={},
        )
        assert "lower_price" in result
        assert "upper_price" in result
        assert "rebalance" in result
        assert "capital_fraction" in result
