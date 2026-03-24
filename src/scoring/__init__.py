"""Wallet scoring engine with gate multipliers and risk profile matching."""

from src.scoring.scorer import WalletData, WalletScore, score_wallet, score_and_rank_wallets
from src.scoring.gates import compute_gate_multiplier
from src.scoring.factors import compute_weighted_score, FACTOR_WEIGHTS
from src.scoring.risk_profile import RiskProfile, classify_wallet_risk, matches_risk_appetite

__all__ = [
    "WalletData",
    "WalletScore",
    "score_wallet",
    "score_and_rank_wallets",
    "compute_gate_multiplier",
    "compute_weighted_score",
    "FACTOR_WEIGHTS",
    "RiskProfile",
    "classify_wallet_risk",
    "matches_risk_appetite",
]
