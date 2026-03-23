"""Pydantic models for Meteora DLMM data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoolInfo(BaseModel):
    """Summary info for a DLMM pool from /pair/all or /pair/{address}."""

    address: str
    name: str = ""
    mint_x: str = ""
    mint_y: str = ""
    bin_step: int = 0
    base_fee_percentage: str = "0"
    current_price: float = 0.0
    liquidity: float = 0.0
    trade_volume_24h: float = Field(0.0, alias="trade_volume")
    fees_24h: float = Field(0.0, alias="fees")
    tvl: float = Field(0.0, alias="tvl")
    apr: float = 0.0

    model_config = {"populate_by_name": True}


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


class WalletEarning(BaseModel):
    """Earnings data for a wallet in a specific pool."""

    wallet: str
    pool_address: str
    total_fee_earned_usd: float = 0.0
    total_deposit_usd: float = 0.0
    total_withdraw_usd: float = 0.0
    pnl_usd: float = 0.0


class DepositRecord(BaseModel):
    """Single deposit event."""

    tx_id: str = ""
    timestamp: int = 0
    amount_x: float = 0.0
    amount_y: float = 0.0


class WithdrawRecord(BaseModel):
    """Single withdrawal event."""

    tx_id: str = ""
    timestamp: int = 0
    amount_x: float = 0.0
    amount_y: float = 0.0


class FeeClaimRecord(BaseModel):
    """Single fee claim event."""

    tx_id: str = ""
    timestamp: int = 0
    fee_x: float = 0.0
    fee_y: float = 0.0


class PoolSimData(BaseModel):
    """Data needed to simulate LP performance on a pool."""

    pool: PoolInfo
    price_series: list[float] = []
    volume_series: list[float] = []
    fee_rate: float = 0.0
    timestamps: list[int] = []
