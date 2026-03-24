"""Meteora DLMM API client.

Base URL: https://dlmm-api.meteora.ag
Rate limit: 30 RPS (no auth needed)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.common.config import settings
from src.common.logger import get_logger
from src.meteora.types import (
    DepositRecord,
    FeeClaimRecord,
    PoolInfo,
    PositionInfo,
    WalletEarning,
    WithdrawRecord,
)

log = get_logger(__name__)

# Simple rate limiter: 30 RPS with margin
_MIN_INTERVAL = 1.0 / 28
_last_request: float = 0.0


async def _rate_limit() -> None:
    global _last_request
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_request)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request = time.monotonic()


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    """Make a rate-limited GET request to the Meteora API."""
    await _rate_limit()
    url = f"{settings.meteora_api_base}{path}"
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def fetch_all_pools(client: httpx.AsyncClient) -> list[PoolInfo]:
    """Fetch all DLMM pools from /pair/all."""
    data = await _get(client, "/pair/all")
    if not isinstance(data, list):
        log.warning("Unexpected response format from /pair/all: %s", type(data))
        return []
    pools = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            pools.append(PoolInfo(**item))
        except Exception as e:
            log.debug("Skipping pool parse error: %s", e)
            continue
    return pools


async def fetch_pool(client: httpx.AsyncClient, address: str) -> PoolInfo:
    """Fetch a specific pool from /pair/{address}."""
    data = await _get(client, f"/pair/{address}")
    if not isinstance(data, dict):
        data = {}
    return PoolInfo(address=data.get("address", address), **data)


async def fetch_pool_positions(
    client: httpx.AsyncClient, pool_address: str
) -> list[dict]:
    """Fetch all positions in a pool from /pair/{address}/positions_lock."""
    try:
        data = await _get(client, f"/pair/{pool_address}/positions_lock")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some responses wrap in a container
            return data.get("positions", data.get("data", []))
        return []
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("No positions found for pool %s", pool_address[:8])
            return []
        raise


async def fetch_position(
    client: httpx.AsyncClient, position_address: str
) -> PositionInfo:
    """Fetch position details from /position/{address}."""
    data = await _get(client, f"/position/{position_address}")
    if not isinstance(data, dict):
        data = {}
    return PositionInfo(address=position_address, **data)


async def fetch_position_fees(
    client: httpx.AsyncClient, position_address: str
) -> list[FeeClaimRecord]:
    """Fetch fee claim history from /position/{address}/claim_fees."""
    data = await _get(client, f"/position/{position_address}/claim_fees")
    if not isinstance(data, list):
        return []
    results = []
    for item in data:
        try:
            results.append(FeeClaimRecord(**item))
        except Exception:
            continue
    return results


async def fetch_position_deposits(
    client: httpx.AsyncClient, position_address: str
) -> list[DepositRecord]:
    """Fetch deposit history from /position/{address}/deposits."""
    data = await _get(client, f"/position/{position_address}/deposits")
    if not isinstance(data, list):
        return []
    results = []
    for item in data:
        try:
            results.append(DepositRecord(**item))
        except Exception:
            continue
    return results


async def fetch_position_withdrawals(
    client: httpx.AsyncClient, position_address: str
) -> list[WithdrawRecord]:
    """Fetch withdrawal history from /position/{address}/withdraws."""
    data = await _get(client, f"/position/{position_address}/withdraws")
    if not isinstance(data, list):
        return []
    results = []
    for item in data:
        try:
            results.append(WithdrawRecord(**item))
        except Exception:
            continue
    return results


async def fetch_wallet_earnings(
    client: httpx.AsyncClient, wallet: str, pool_address: str
) -> WalletEarning:
    """Fetch wallet earnings from /wallet/{wallet}/{pair}/earning."""
    try:
        data = await _get(client, f"/wallet/{wallet}/{pool_address}/earning")
        if not isinstance(data, dict):
            data = {}
        return WalletEarning(wallet=wallet, pool_address=pool_address, **data)
    except httpx.HTTPStatusError:
        return WalletEarning(wallet=wallet, pool_address=pool_address)
