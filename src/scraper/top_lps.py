"""Fetch top LP positions from Meteora API + Shyft and score them.

This is the main entry point for the "learn from top LPs" pipeline:
1. Fetch top pools by volume/fees from Meteora API
2. For each top pool, get positions
3. Score wallets using the scoring engine
4. Extract patterns from top-scored wallets
5. Save patterns to cache/top_lps/ for the autoresearch loop

Run with: uv run python -m src.scraper.top_lps
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from src.common.config import CACHE_DIR, settings
from src.common.logger import get_logger
from src.meteora.client import (
    fetch_all_pools,
    fetch_pool_positions,
    fetch_wallet_earnings,
)
from src.meteora.types import PoolInfo
from src.scoring.scorer import WalletData, WalletScore, score_and_rank_wallets
from src.scraper.cache import cache_get, cache_set
from src.scraper.patterns import (
    AggregatedPatterns,
    LPPattern,
    aggregate_patterns,
    save_patterns,
)
from src.scraper.tracklp import fetch_top_lpers_for_pool

log = get_logger(__name__)

# Top pools to analyze (by volume) — take top N
TOP_POOL_COUNT = 10
# Max positions to analyze per pool
MAX_POSITIONS_PER_POOL = 50


async def fetch_top_pools(client: httpx.AsyncClient) -> list[PoolInfo]:
    """Get the top DLMM pools by 24h trading volume."""
    cached = cache_get("pools", "top_pools", max_age_hours=4)
    if cached and "pools" in cached:
        log.info("Using cached top pools (%d pools)", len(cached["pools"]))
        return [PoolInfo(**p) for p in cached["pools"]]

    log.info("Fetching all DLMM pools from Meteora API...")
    all_pools = await fetch_all_pools(client)
    log.info("Fetched %d total pools", len(all_pools))

    # Sort by volume, take top N
    all_pools.sort(key=lambda p: p.trade_volume_24h, reverse=True)
    top = all_pools[:TOP_POOL_COUNT]

    # Cache the result
    cache_set("pools", "top_pools", {"pools": [p.model_dump() for p in top]})
    log.info("Top %d pools by volume cached", len(top))

    for p in top:
        log.info(
            "  %s | vol=$%.0f | tvl=$%.0f | fees=$%.0f",
            p.name or p.address[:8],
            p.trade_volume_24h,
            p.tvl,
            p.fees_24h,
        )

    return top


async def analyze_pool_positions(
    client: httpx.AsyncClient, pool: PoolInfo
) -> list[dict]:
    """Fetch and analyze positions in a pool."""
    pool_addr = pool.address
    cache_key = f"positions_{pool_addr}"
    cached = cache_get("pools", cache_key, max_age_hours=4)
    if cached and "positions" in cached:
        return cached["positions"]

    log.info("Fetching positions for %s...", pool.name or pool_addr[:8])
    try:
        raw_positions = await fetch_pool_positions(client, pool_addr)
    except Exception as e:
        log.warning("Failed to fetch positions for %s: %s", pool_addr[:8], e)
        return []

    if not isinstance(raw_positions, list):
        raw_positions = []

    # Extract position summaries
    positions = []
    for pos in raw_positions[:MAX_POSITIONS_PER_POOL]:
        if isinstance(pos, dict):
            positions.append(
                {
                    "address": pos.get("address", ""),
                    "owner": pos.get("owner", ""),
                    "pool_address": pool_addr,
                    "pool_name": pool.name,
                    "lower_bin_id": pos.get("lowerBinId", pos.get("lower_bin_id", 0)),
                    "upper_bin_id": pos.get("upperBinId", pos.get("upper_bin_id", 0)),
                    "range_width": abs(
                        pos.get("upperBinId", pos.get("upper_bin_id", 0))
                        - pos.get("lowerBinId", pos.get("lower_bin_id", 0))
                    ),
                }
            )

    cache_set("pools", cache_key, {"positions": positions})
    log.info("  Found %d positions in %s", len(positions), pool.name or pool_addr[:8])
    return positions


async def build_wallet_data(
    client: httpx.AsyncClient,
    wallet: str,
    pool_positions: list[dict],
) -> WalletData:
    """Build WalletData from positions and on-chain data for scoring."""
    now = int(time.time())

    # Aggregate position data for this wallet
    wallet_positions = [p for p in pool_positions if p.get("owner") == wallet]
    num_positions = len(wallet_positions)
    unique_pools = len(set(p.get("pool_address", "") for p in wallet_positions))

    range_widths = [p.get("range_width", 0) for p in wallet_positions]
    avg_range = sum(range_widths) / len(range_widths) if range_widths else 0

    # Try to fetch earnings data for the first pool
    fees_usd = 0.0
    capital_usd = 0.0
    if wallet_positions:
        pool_addr = wallet_positions[0].get("pool_address", "")
        try:
            earning = await fetch_wallet_earnings(client, wallet, pool_addr)
            fees_usd = earning.total_fee_earned_usd
            capital_usd = earning.total_deposit_usd or 1.0
        except Exception:
            pass

    # Estimate activity timespan (best-effort without full tx history)
    # Default to 30 days if we can't determine
    est_days = 30.0
    first_ts = now - int(est_days * 86400)

    return WalletData(
        wallet=wallet,
        first_activity_ts=first_ts,
        last_activity_ts=now,
        num_completed_positions=num_positions,
        position_pnls=[],  # Would need full deposit/withdraw history
        total_fees_usd=fees_usd,
        total_capital_usd=capital_usd,
        total_days=est_days,
        avg_range_width_bins=avg_range,
        avg_fee_per_unit_liquidity=fees_usd / capital_usd if capital_usd > 0 else 0,
        rebalance_intervals_hours=[],
        drawdown_pcts=[],
        unique_pools=unique_pools,
    )


async def run_pipeline() -> None:
    """Main pipeline: fetch pools → positions → score wallets → extract patterns."""
    log.info("=" * 60)
    log.info("Starting top LP analysis pipeline")
    log.info("=" * 60)

    async with httpx.AsyncClient() as client:
        # Step 1: Get top pools
        top_pools = await fetch_top_pools(client)
        if not top_pools:
            log.error("No pools found — check network/API")
            return

        # Step 2: Get positions from each pool
        all_positions: list[dict] = []
        for pool in top_pools:
            positions = await analyze_pool_positions(client, pool)
            all_positions.extend(positions)

        log.info("Total positions across all pools: %d", len(all_positions))

        # Step 3: Also check TrackLP for additional wallet discovery
        for pool in top_pools[:3]:  # Top 3 pools only (rate limiting)
            tracklp_wallets = await fetch_top_lpers_for_pool(client, pool.address)
            for tw in tracklp_wallets:
                # Add as positions if not already present
                if not any(
                    p.get("owner") == tw.get("wallet") for p in all_positions
                ):
                    all_positions.append(
                        {
                            "owner": tw.get("wallet", ""),
                            "pool_address": pool.address,
                            "pool_name": pool.name,
                            "range_width": 0,
                        }
                    )

        # Step 4: Build unique wallet list
        unique_wallets = list(
            set(p.get("owner", "") for p in all_positions if p.get("owner"))
        )
        log.info("Unique wallets found: %d", len(unique_wallets))

        # Step 5: Score wallets
        log.info("Scoring wallets...")
        wallet_data_list = []
        for wallet in unique_wallets[:100]:  # Cap at 100 for API rate limits
            try:
                wd = await build_wallet_data(client, wallet, all_positions)
                wallet_data_list.append(wd)
            except Exception as e:
                log.warning("Failed to build data for %s: %s", wallet[:8], e)

        ranked = score_and_rank_wallets(
            wallet_data_list, min_score=settings.min_wallet_score
        )
        log.info(
            "Wallets passing score threshold (%.0f): %d / %d",
            settings.min_wallet_score,
            len(ranked),
            len(wallet_data_list),
        )

        for ws in ranked[:10]:
            log.info(
                "  %s | score=%.1f | gate=%.2f | risk=%s",
                ws.wallet[:8],
                ws.final_score,
                ws.gate_multiplier,
                ws.risk_profile.value,
            )

        # Step 6: Extract patterns from top-scored wallets
        top_wallet_addrs = {ws.wallet for ws in ranked}
        top_positions = [
            p for p in all_positions if p.get("owner") in top_wallet_addrs
        ]

        patterns = []
        for pos in top_positions:
            patterns.append(
                LPPattern(
                    wallet=pos.get("owner", ""),
                    pool_address=pos.get("pool_address", ""),
                    pool_name=pos.get("pool_name", ""),
                    avg_range_width_bins=pos.get("range_width", 0),
                )
            )

        save_patterns(patterns, "latest")

        # Step 7: Aggregate patterns by pool type
        agg = aggregate_patterns(patterns, "volatile")
        log.info("Aggregated patterns for volatile pools:")
        log.info("  Median range width: %.1f bins", agg.median_range_width)
        log.info("  Median rebalance: %.1f hours", agg.median_rebalance_hours)
        log.info("  Preferred distribution: %s", agg.preferred_distribution)

        # Save aggregated patterns
        agg_path = CACHE_DIR / "top_lps" / "aggregated.json"
        agg_path.parent.mkdir(parents=True, exist_ok=True)
        agg_path.write_text(
            json.dumps(
                {
                    "pool_type": agg.pool_type,
                    "num_wallets": agg.num_wallets,
                    "median_range_width": agg.median_range_width,
                    "p25_range_width": agg.p25_range_width,
                    "p75_range_width": agg.p75_range_width,
                    "median_rebalance_hours": agg.median_rebalance_hours,
                    "preferred_distribution": agg.preferred_distribution,
                    "median_capital_ratio": agg.median_capital_ratio,
                },
                indent=2,
            )
        )

        # Save wallet scores
        scores_path = CACHE_DIR / "wallet_scores" / "latest.json"
        scores_path.parent.mkdir(parents=True, exist_ok=True)
        scores_data = [
            {
                "wallet": ws.wallet,
                "score": ws.final_score,
                "gate": ws.gate_multiplier,
                "risk": ws.risk_profile.value,
                "factors": ws.factor_scores,
            }
            for ws in ranked
        ]
        scores_path.write_text(json.dumps(scores_data, indent=2))

    log.info("=" * 60)
    log.info("Pipeline complete. Patterns saved to cache/top_lps/")
    log.info("=" * 60)


def main() -> None:
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
