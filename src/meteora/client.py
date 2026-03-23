"""Meteora DLMM API client."""

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

# Simple rate limiter: 30 RPS
_MIN_INTERVAL = 1.0 / 28  # slight margin under 30 RPS
_last_request: float = 0.0


async def _rate_limit() -> None:
    global _last_request
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_request)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request = time.monotonic()


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    await _rate_limit()
    url = f"{settings.meteora_api_base}{path}"
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def fetch_all_pools(client: httpx.AsyncClient) -> list[PoolInfo]:
    """Fetch all DLMM pools."""
    data = await _get(client, "/pair/all")
    pools = []
    for item in data:
        try:
            pools.append(PoolInfo(address=item.get("address", ""), **item))
        except Exception:
            continue
    return pools


async def fetch_pool(client: httpx.AsyncClient, address: str) -> PoolInfo:
    """Fetch a specific pool."""
    data = await _get(client, f"/pair/{address}")
    return PoolInfo(address=data.get("address", address), **data)


async def fetch_pool_positions(
    client: httpx.AsyncClient, pool_address: str
) -> list[dict]:
    """Fetch all positions in a pool."""
    return await _get(client, f"/pair/{pool_address}/positions_lock")


async def fetch_position(
    client: httpx.AsyncClient, position_address: str
) -> PositionInfo:
    """Fetch position details."""
    data = await _get(client, f"/position/{position_address}")
    return PositionInfo(address=position_address, **data)


async def fetch_position_fees(
    client: httpx.AsyncClient, position_address: str
) -> list[FeeClaimRecord]:
    """Fetch fee claim history for a position."""
    data = await _get(client, f"/position/{position_address}/claim_fees")
    return [FeeClaimRecord(**item) for item in data]


async def fetch_position_deposits(
    client: httpx.AsyncClient, position_address: str
) -> list[DepositRecord]:
    """Fetch deposit history for a position."""
    data = await _get(client, f"/position/{position_address}/deposits")
    return [DepositRecord(**item) for item in data]


async def fetch_position_withdrawals(
    client: httpx.AsyncClient, position_address: str
) -> list[WithdrawRecord]:
    """Fetch withdrawal history for a position."""
    data = await _get(client, f"/position/{position_address}/withdraws")
    return [WithdrawRecord(**item) for item in data]


async def fetch_wallet_earnings(
    client: httpx.AsyncClient, wallet: str, pool_address: str
) -> WalletEarning:
    """Fetch wallet earnings for a specific pool."""
    data = await _get(client, f"/wallet/{wallet}/{pool_address}/earning")
    return WalletEarning(wallet=wallet, pool_address=pool_address, **data)
