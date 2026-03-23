"""Central configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT_DIR / "cache"


class Settings(BaseSettings):
    # Solana / RPC
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    helius_api_key: str = ""

    # Data providers
    shyft_api_key: str = ""
    birdeye_api_key: str = ""
    dune_api_key: str = ""

    # Meteora DLMM API (no auth, 30 RPS)
    meteora_api_base: str = "https://dlmm-api.meteora.ag"

    # Agent behaviour
    risk_profile: str = "moderate"  # conservative | moderate | aggressive
    min_wallet_score: float = 60.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
