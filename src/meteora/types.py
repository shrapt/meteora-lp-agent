"""Pydantic models for Meteora DLMM data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class PoolInfo(BaseModel):
    """Summary info for a DLMM pool from /pair/all or /pair/{address}.

    The Meteora API returns inconsistent field names across endpoints,
    so we normalize them here.
    """

    address: str
    name: str = ""
    mint_x: str = ""
    mint_y: str = ""
    bin_step: int = 0
    base_fee_percentage: str = "0"
    current_price: float = 0.0
    liquidity: float = 0.0
    trade_volume_24h: float = 0.0
    fees_24h: float = 0.0
    tvl: float = 0.0
    apr: float = 0.0

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Meteora API returns various field name conventions
            if "trade_volume" in data and "trade_volume_24h" not in data:
                data["trade_volume_24h"] = data["trade_volume"]
            if "fees" in data and "fees_24h" not in data:
                data["fees_24h"] = data["fees"]
            if "tradeVolume24h" in data and "trade_volume_24h" not in data:
                data["trade_volume_24h"] = data["tradeVolume24h"]
            if "fees24h" in data and "fees_24h" not in data:
                data["fees_24h"] = data["fees24h"]
            if "currentPrice" in data and "current_price" not in data:
                data["current_price"] = data["currentPrice"]
            if "mintX" in data and "mint_x" not in data:
                data["mint_x"] = data["mintX"]
            if "mintY" in data and "mint_y" not in data:
                data["mint_y"] = data["mintY"]
            if "binStep" in data and "bin_step" not in data:
                data["bin_step"] = data["binStep"]
            # Ensure numeric types
            for field in ("trade_volume_24h", "fees_24h", "tvl", "apr", "current_price", "liquidity"):
                if field in data and data[field] is not None:
                    try:
                        data[field] = float(data[field])
                    except (ValueError, TypeError):
                        data[field] = 0.0
        return data


class BinPosition(BaseModel):
    """A single bin within a position."""

    bin_id: int
    price: float = 0.0
    liquidity: float = 0.0


class PositionInfo(BaseModel):
    """LP position details."""

    address: str
    owner: str = ""
    pool_address: str = ""
    lower_bin_id: int = 0
    upper_bin_id: int = 0
    total_fee_x_claimed: float = 0.0
    total_fee_y_claimed: float = 0.0
    bins: list[BinPosition] = []

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "lowerBinId" in data and "lower_bin_id" not in data:
                data["lower_bin_id"] = data["lowerBinId"]
            if "upperBinId" in data and "upper_bin_id" not in data:
                data["upper_bin_id"] = data["upperBinId"]
            if "totalFeeXClaimed" in data and "total_fee_x_claimed" not in data:
                data["total_fee_x_claimed"] = data["totalFeeXClaimed"]
            if "totalFeeYClaimed" in data and "total_fee_y_claimed" not in data:
                data["total_fee_y_claimed"] = data["totalFeeYClaimed"]
        return data


class WalletEarning(BaseModel):
    """Earnings data for a wallet in a specific pool."""

    wallet: str
    pool_address: str
    total_fee_earned_usd: float = 0.0
    total_deposit_usd: float = 0.0
    total_withdraw_usd: float = 0.0
    pnl_usd: float = 0.0

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Handle camelCase variants
            mappings = {
                "totalFeeEarnedUsd": "total_fee_earned_usd",
                "totalDepositUsd": "total_deposit_usd",
                "totalWithdrawUsd": "total_withdraw_usd",
                "pnlUsd": "pnl_usd",
                "fee": "total_fee_earned_usd",
            }
            for src, dst in mappings.items():
                if src in data and dst not in data:
                    data[dst] = data[src]
        return data


class DepositRecord(BaseModel):
    """Single deposit event."""

    tx_id: str = ""
    timestamp: int = 0
    amount_x: float = 0.0
    amount_y: float = 0.0

    model_config = {"extra": "ignore"}


class WithdrawRecord(BaseModel):
    """Single withdrawal event."""

    tx_id: str = ""
    timestamp: int = 0
    amount_x: float = 0.0
    amount_y: float = 0.0

    model_config = {"extra": "ignore"}


class FeeClaimRecord(BaseModel):
    """Single fee claim event."""

    tx_id: str = ""
    timestamp: int = 0
    fee_x: float = 0.0
    fee_y: float = 0.0

    model_config = {"extra": "ignore"}


class PoolSimData(BaseModel):
    """Data needed to simulate LP performance on a pool."""

    pool: PoolInfo
    price_series: list[float] = []
    volume_series: list[float] = []
    fee_rate: float = 0.0
    timestamps: list[int] = []
