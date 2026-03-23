"""Gate multipliers — all must pass minimum threshold or score is zeroed out.

Lesson learned: v1 scoring was useless because a wallet with 1 winning trade
scored 100. Gates prevent thin-data wallets from ranking high.
"""

from __future__ import annotations

import time


def track_record_gate(first_activity_ts: int, min_days: int = 7) -> float:
    """Wallet must have 7+ days of LP activity.

    Returns 0.0 if under minimum, otherwise scales 0.5→1.0 for 7→90 days.
    """
    if first_activity_ts <= 0:
        return 0.0
    days_active = (time.time() - first_activity_ts) / 86400
    if days_active < min_days:
        return 0.0
    # Scale: 7 days → 0.5, 90+ days → 1.0
    return min(1.0, 0.5 + 0.5 * (days_active - min_days) / (90 - min_days))


def recency_gate(last_activity_ts: int, fresh_days: int = 14, decay_days: int = 30) -> float:
    """Must have activity in last 14 days. Decays to 0 over 30 days.

    Returns 1.0 if within fresh_days, linearly decays to 0.0 at decay_days.
    """
    if last_activity_ts <= 0:
        return 0.0
    days_since = (time.time() - last_activity_ts) / 86400
    if days_since <= fresh_days:
        return 1.0
    if days_since >= decay_days:
        return 0.0
    return 1.0 - (days_since - fresh_days) / (decay_days - fresh_days)


def sample_size_gate(num_completed_positions: int, min_positions: int = 5) -> float:
    """Must have 5+ completed positions.

    Returns 0.0 if under minimum, otherwise scales 0.5→1.0 for 5→30 positions.
    """
    if num_completed_positions < min_positions:
        return 0.0
    return min(1.0, 0.5 + 0.5 * (num_completed_positions - min_positions) / 25)


def compute_gate_multiplier(
    first_activity_ts: int,
    last_activity_ts: int,
    num_completed_positions: int,
) -> float:
    """Combined gate multiplier: product of all three gates.

    If ANY gate returns 0, the entire score is 0.
    """
    tr = track_record_gate(first_activity_ts)
    rc = recency_gate(last_activity_ts)
    ss = sample_size_gate(num_completed_positions)
    return tr * rc * ss
