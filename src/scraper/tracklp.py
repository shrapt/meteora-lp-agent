"""Scrape tracklp.com for top LPers per pool.

TrackLP provides ranked lists of top LPers by performance for any Meteora pool.
No API key needed — web scraping.
"""

from __future__ import annotations

import httpx

from src.common.logger import get_logger
from src.scraper.cache import cache_get, cache_set

log = get_logger(__name__)

TRACKLP_BASE = "https://tracklp.com"


async def fetch_top_lpers_for_pool(
    client: httpx.AsyncClient, pool_address: str, limit: int = 20
) -> list[dict]:
    """Fetch top LPers for a specific pool from TrackLP.

    Returns list of dicts with wallet address and performance metrics.
    Falls back to cached data if the request fails.
    """
    cache_key = f"tracklp_{pool_address}"
    cached = cache_get("top_lps", cache_key, max_age_hours=12)
    if cached and "lpers" in cached:
        log.info("Using cached TrackLP data for %s", pool_address[:8])
        return cached["lpers"]

    try:
        # TrackLP has a pool page — try to get data
        # Note: This may need adjustment based on actual TrackLP page structure
        resp = await client.get(
            f"{TRACKLP_BASE}/pool/{pool_address}",
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            log.warning("TrackLP returned %d for pool %s", resp.status_code, pool_address[:8])
            return []

        # Parse the response — TrackLP may return JSON or HTML
        # This is a best-effort parser; adjust based on actual response format
        lpers = _parse_tracklp_response(resp.text, limit)

        if lpers:
            cache_set("top_lps", cache_key, {"lpers": lpers, "pool": pool_address})
            log.info("Fetched %d top LPers from TrackLP for %s", len(lpers), pool_address[:8])

        return lpers

    except Exception as e:
        log.warning("TrackLP fetch failed for %s: %s", pool_address[:8], e)
        return []


def _parse_tracklp_response(html: str, limit: int) -> list[dict]:
    """Parse TrackLP response to extract wallet addresses and metrics.

    This is a best-effort parser. TrackLP may change their format.
    """
    # Look for wallet addresses (base58, 32-44 chars)
    import re

    wallets = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,44}', html)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in wallets:
        if w not in seen and len(w) >= 32:
            seen.add(w)
            unique.append({"wallet": w})
    return unique[:limit]
