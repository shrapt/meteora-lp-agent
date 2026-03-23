# Meteora LP Agent — Autoresearch

## What this is
An autonomous Meteora DLMM LP strategy optimizer. Uses karpathy/autoresearch pattern:
modify strategy → evaluate → keep/discard → repeat forever.

Unique addition: the agent also LEARNS FROM TOP LPs by scraping their on-chain
positions, range settings, rebalance patterns, and fee performance.

## How it works
- `prepare.py` is READ-ONLY. Contains evaluation harness and pool data.
- `strategy.py` is the ONLY file the agent modifies. Contains LP strategy.
- `simulate.py` runs the evaluation. Key metric: avg_net_yield (higher = better).
- `src/scraper/top_lps.py` fetches and analyzes top LP positions from Meteora API.
- `cache/top_lps/` contains extracted patterns from top LPs.
- `program.md` has the full autonomous experiment loop instructions.

## Quick commands
- `uv run prepare.py` — prepare simulation data
- `uv run python -m src.scraper.top_lps` — refresh top LP data
- `uv run simulate.py` — run strategy evaluation
- `uv run simulate.py > run.log 2>&1` — run and capture output for experiment loop

## Tech stack
- Python 3.12+, numpy, httpx, pydantic
- Meteora DLMM API: https://dlmm-api.meteora.ag/ (30 RPS, no auth)
- Shyft GraphQL: for on-chain position data (needs SHYFT_API_KEY)
- Solana RPC: for direct reads (needs SOLANA_RPC_URL)

## API endpoints we use

### Meteora DLMM API (base: https://dlmm-api.meteora.ag)
- GET /pair/all — all pools
- GET /pair/{address} — pool details
- GET /pair/{address}/positions_lock — positions in pool
- GET /position/{address} — position details (bin range, etc)
- GET /position/{address}/claim_fees — fee history
- GET /position/{address}/deposits — deposit history
- GET /position/{address}/withdraws — withdrawal history
- GET /wallet/{wallet}/{pair}/earning — earnings per wallet per pool

### Shyft GraphQL (base: https://programs.shyft.to/v0/graphql)
- meteora_dlmm_PositionV2: owner, bins, fees claimed
- meteora_dlmm_LbPair: pool config, active bin, reserves

## Key design principle
EXECUTION QUALITY FIRST. Born from a failed Polymarket bot with liquidity issues.
Every strategy decision considers: tx costs, rebalance frequency limits, slippage.

## Testing
- pytest tests/
- All strategy changes must pass simulation without crashing

## Project origin
Inspired by karpathy/autoresearch applied to DeFi LP optimization instead of
LLM training research. See program.md for the full autonomous loop.
