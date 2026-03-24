"""Dune Analytics queries for discovering hot pools and active wallets."""

from __future__ import annotations

import httpx

from src.common.config import settings
from src.common.logger import get_logger

log = get_logger(__name__)

DUNE_API_BASE = "https://api.dune.com/api/v1"


async def execute_query(
    client: httpx.AsyncClient, query_id: int, params: dict | None = None
) -> list[dict]:
    """Execute a Dune query and return the results rows."""
    if not settings.dune_api_key:
        log.warning("No DUNE_API_KEY set — skipping Dune query %d", query_id)
        return []

    headers = {"X-Dune-API-Key": settings.dune_api_key}

    # Start execution
    body: dict = {}
    if params:
        body["query_parameters"] = params
    resp = await client.post(
        f"{DUNE_API_BASE}/query/{query_id}/execute",
        json=body,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    execution_id = resp.json()["execution_id"]

    # Poll for results
    import asyncio

    for _ in range(60):
        await asyncio.sleep(5)
        resp = await client.get(
            f"{DUNE_API_BASE}/execution/{execution_id}/results",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data.get("state", "")
        if state == "QUERY_STATE_COMPLETED":
            return data.get("result", {}).get("rows", [])
        if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
            log.error("Dune query %d failed: %s", query_id, state)
            return []

    log.error("Dune query %d timed out", query_id)
    return []


async def find_hot_pools(client: httpx.AsyncClient) -> list[dict]:
    """Find high-volume Meteora DLMM pools via Dune.

    Uses a pre-built Dune query. Replace query_id with your own saved query.
    """
    # Placeholder query ID — user should create their own Dune query
    # that finds Meteora DLMM pools with highest volume/fees in last 24h
    QUERY_ID = 0  # Replace with your Dune query ID
    if QUERY_ID == 0:
        log.info("No Dune query configured for hot pools — using Meteora API only")
        return []
    return await execute_query(client, QUERY_ID)


async def find_active_wallets(client: httpx.AsyncClient) -> list[dict]:
    """Find wallets actively LPing on Meteora DLMM via Dune."""
    QUERY_ID = 0  # Replace with your Dune query ID
    if QUERY_ID == 0:
        log.info("No Dune query configured for wallets — using Meteora API only")
        return []
    return await execute_query(client, QUERY_ID)
