"""Extract patterns from top LP behavior for use as mentor data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from src.common.config import CACHE_DIR
from src.common.logger import get_logger

log = get_logger(__name__)


@dataclass
class LPPattern:
    """Extracted pattern from a top LP's behavior."""

    wallet: str = ""
    pool_address: str = ""
    pool_name: str = ""

    # Range characteristics
    avg_range_width_bins: float = 0.0
    range_width_std: float = 0.0
    uses_symmetric_ranges: bool = True

    # Rebalance behavior
    avg_rebalance_interval_hours: float = 24.0
    rebalance_count: int = 0

    # Capital deployment
    capital_deployed_ratio: float = 0.7

    # Performance
    total_fees_usd: float = 0.0
    estimated_apr: float = 0.0
    win_rate: float = 0.0

    # Bin distribution preference
    bin_distribution: str = "Spot"  # Spot, Curve, BidAsk


@dataclass
class AggregatedPatterns:
    """Aggregated patterns across all top LPs for a pool type."""

    pool_type: str = ""  # volatile, correlated, stable
    num_wallets: int = 0

    # Consensus ranges
    median_range_width: float = 0.0
    p25_range_width: float = 0.0
    p75_range_width: float = 0.0

    # Consensus rebalance frequency
    median_rebalance_hours: float = 0.0

    # Consensus bin distribution
    preferred_distribution: str = "Spot"

    # Consensus capital deployment
    median_capital_ratio: float = 0.7

    # Performance benchmarks
    median_apr: float = 0.0
    top_quartile_apr: float = 0.0


def extract_patterns(positions_data: list[dict]) -> list[LPPattern]:
    """Extract LP patterns from raw position data."""
    patterns = []
    for pos in positions_data:
        pattern = LPPattern(
            wallet=pos.get("owner", ""),
            pool_address=pos.get("pool_address", ""),
            pool_name=pos.get("pool_name", ""),
            avg_range_width_bins=pos.get("range_width", 0),
            avg_rebalance_interval_hours=pos.get("rebalance_interval_hours", 24),
            rebalance_count=pos.get("rebalance_count", 0),
            total_fees_usd=pos.get("fees_usd", 0),
            estimated_apr=pos.get("apr", 0),
        )
        patterns.append(pattern)
    return patterns


def aggregate_patterns(
    patterns: list[LPPattern], pool_type: str = "volatile"
) -> AggregatedPatterns:
    """Aggregate individual patterns into consensus for a pool type."""
    if not patterns:
        return AggregatedPatterns(pool_type=pool_type)

    widths = [p.avg_range_width_bins for p in patterns if p.avg_range_width_bins > 0]
    rebalance_hours = [
        p.avg_rebalance_interval_hours
        for p in patterns
        if p.avg_rebalance_interval_hours > 0
    ]
    capital_ratios = [p.capital_deployed_ratio for p in patterns]
    aprs = [p.estimated_apr for p in patterns if p.estimated_apr > 0]

    return AggregatedPatterns(
        pool_type=pool_type,
        num_wallets=len(patterns),
        median_range_width=float(np.median(widths)) if widths else 0,
        p25_range_width=float(np.percentile(widths, 25)) if widths else 0,
        p75_range_width=float(np.percentile(widths, 75)) if widths else 0,
        median_rebalance_hours=float(np.median(rebalance_hours)) if rebalance_hours else 0,
        preferred_distribution=_most_common_distribution(patterns),
        median_capital_ratio=float(np.median(capital_ratios)) if capital_ratios else 0.7,
        median_apr=float(np.median(aprs)) if aprs else 0,
        top_quartile_apr=float(np.percentile(aprs, 75)) if aprs else 0,
    )


def _most_common_distribution(patterns: list[LPPattern]) -> str:
    from collections import Counter

    dists = [p.bin_distribution for p in patterns if p.bin_distribution]
    if not dists:
        return "Spot"
    return Counter(dists).most_common(1)[0][0]


def save_patterns(patterns: list[LPPattern], filename: str = "latest") -> Path:
    """Save extracted patterns to cache/top_lps/ as JSON."""
    out_dir = CACHE_DIR / "top_lps"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{filename}.json"
    data = [asdict(p) for p in patterns]
    path.write_text(json.dumps(data, indent=2))
    log.info("Saved %d patterns to %s", len(data), path)
    return path


def load_patterns(filename: str = "latest") -> list[LPPattern]:
    """Load patterns from cache."""
    path = CACHE_DIR / "top_lps" / f"{filename}.json"
    if not path.exists():
        log.warning("No cached patterns at %s", path)
        return []
    data = json.loads(path.read_text())
    return [LPPattern(**item) for item in data]
