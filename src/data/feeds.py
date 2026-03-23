"""Price feeds from Birdeye, Jupiter, and Pyth."""

from __future__ import annotations

import httpx

from src.common.config import settings
from src.common.logger import get_logger

log = get_logger(__name__)

# Well-known Solana token mints
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# Jupiter price API (free, no auth)
JUPITER_PRICE_URL = "https://price.jup.ag/v6/price"


async def fetch_price_jupiter(
    client: httpx.AsyncClient, token_mint: str
) -> float | None:
    """Fetch current USD price from Jupiter."""
    try:
        resp = await client.get(
            JUPITER_PRICE_URL,
            params={"ids": token_mint},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        price_data = data.get("data", {}).get(token_mint)
        if price_data:
            return float(price_data["price"])
    except Exception as e:
        log.warning("Jupiter price fetch failed for %s: %s", token_mint, e)
    return None


async def fetch_price_birdeye(
    client: httpx.AsyncClient, token_mint: str
) -> float | None:
    """Fetch current USD price from Birdeye API."""
    if not settings.birdeye_api_key:
        return None
    try:
        resp = await client.get(
            "https://public-api.birdeye.so/defi/price",
            params={"address": token_mint},
            headers={
                "X-API-KEY": settings.birdeye_api_key,
                "x-chain": "solana",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("data", {}).get("value", 0))
    except Exception as e:
        log.warning("Birdeye price fetch failed for %s: %s", token_mint, e)
    return None


async def fetch_price(
    client: httpx.AsyncClient, token_mint: str
) -> float:
    """Fetch price with fallback: Jupiter → Birdeye."""
    price = await fetch_price_jupiter(client, token_mint)
    if price is not None:
        return price
    price = await fetch_price_birdeye(client, token_mint)
    if price is not None:
        return price
    log.error("Could not fetch price for %s from any source", token_mint)
    return 0.0


async def fetch_historical_prices_birdeye(
    client: httpx.AsyncClient,
    token_mint: str,
    time_from: int,
    time_to: int,
    interval: str = "1H",
) -> list[dict]:
    """Fetch historical OHLCV from Birdeye. Returns list of {timestamp, open, high, low, close, volume}."""
    if not settings.birdeye_api_key:
        log.warning("No BIRDEYE_API_KEY set — cannot fetch historical prices")
        return []
    try:
        resp = await client.get(
            "https://public-api.birdeye.so/defi/ohlcv",
            params={
                "address": token_mint,
                "type": interval,
                "time_from": time_from,
                "time_to": time_to,
            },
            headers={
                "X-API-KEY": settings.birdeye_api_key,
                "x-chain": "solana",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("items", [])
    except Exception as e:
        log.warning("Birdeye OHLCV fetch failed: %s", e)
    return []
