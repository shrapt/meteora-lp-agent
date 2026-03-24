"""SQLite storage for persistent data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.common.config import ROOT_DIR
from src.common.logger import get_logger

log = get_logger(__name__)

DB_PATH = ROOT_DIR / "data.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pools (
                address TEXT PRIMARY KEY,
                name TEXT,
                data_json TEXT,
                updated_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS wallet_scores (
                wallet TEXT PRIMARY KEY,
                score REAL,
                risk_profile TEXT,
                factors_json TEXT,
                updated_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS positions (
                address TEXT PRIMARY KEY,
                owner TEXT,
                pool_address TEXT,
                data_json TEXT,
                updated_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_hash TEXT,
                avg_net_yield REAL,
                time_in_range REAL,
                max_drawdown REAL,
                status TEXT,
                description TEXT,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            );
            """
        )


def upsert_pool(address: str, name: str, data: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pools (address, name, data_json) VALUES (?, ?, ?)",
            (address, name, json.dumps(data)),
        )


def upsert_wallet_score(
    wallet: str, score: float, risk_profile: str, factors: dict
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wallet_scores (wallet, score, risk_profile, factors_json) VALUES (?, ?, ?, ?)",
            (wallet, score, risk_profile, json.dumps(factors)),
        )


def get_top_wallets(min_score: float = 60.0, limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT wallet, score, risk_profile, factors_json FROM wallet_scores WHERE score >= ? ORDER BY score DESC LIMIT ?",
            (min_score, limit),
        ).fetchall()
    return [
        {
            "wallet": r["wallet"],
            "score": r["score"],
            "risk_profile": r["risk_profile"],
            "factors": json.loads(r["factors_json"]),
        }
        for r in rows
    ]


def ensure_db() -> None:
    """Ensure DB is initialized (idempotent)."""
    if not DB_PATH.exists():
        init_db()
