"""Run strategy evaluation across all target pools.

Usage: uv run simulate.py
       uv run simulate.py > run.log 2>&1

Outputs key metrics to stdout in parseable format:
    avg_net_yield: 0.0032
    avg_time_in_range: 0.7500
    avg_max_drawdown: 0.0120
"""

from __future__ import annotations

import sys

import numpy as np

from prepare import (
    INITIAL_CAPITAL_USD,
    TARGET_POOLS,
    evaluate_strategy,
    prepare_all,
)
from src.common.logger import get_logger
from strategy import strategy

log = get_logger(__name__)


def main() -> None:
    log.info("Preparing simulation data...")
    pools = prepare_all(seed=42)

    log.info("Running strategy on %d pools...", len(pools))
    results = []

    for pool in pools:
        result = evaluate_strategy(strategy, pool, capital=INITIAL_CAPITAL_USD)
        results.append(result)
        log.info(
            "  %s: net_yield=%.6f  time_in_range=%.4f  max_dd=%.4f  "
            "fees=$%.2f  rebalances=%d  tx_cost=$%.2f",
            result.pool_name,
            result.net_yield,
            result.time_in_range,
            result.max_drawdown,
            result.total_fees_earned,
            result.num_rebalances,
            result.tx_costs,
        )

    # Compute averages
    avg_yield = np.mean([r.net_yield for r in results])
    avg_tir = np.mean([r.time_in_range for r in results])
    avg_dd = np.mean([r.max_drawdown for r in results])

    log.info("=" * 50)
    log.info("SUMMARY")
    log.info("=" * 50)

    # Output in parseable format (grep-friendly)
    print(f"avg_net_yield: {avg_yield:.6f}")
    print(f"avg_time_in_range: {avg_tir:.6f}")
    print(f"avg_max_drawdown: {avg_dd:.6f}")

    # Per-pool breakdown
    for r in results:
        print(
            f"pool:{r.pool_name} net_yield:{r.net_yield:.6f} "
            f"time_in_range:{r.time_in_range:.4f} "
            f"max_drawdown:{r.max_drawdown:.4f} "
            f"fees:{r.total_fees_earned:.2f} "
            f"rebalances:{r.num_rebalances}"
        )


if __name__ == "__main__":
    main()
