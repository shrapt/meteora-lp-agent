"""
lp_intelligence.py — Learn from Top LPs via LP Agent API

Scans the most profitable LP wallets on Meteora, analyzes exactly how they:
- Open positions (what ranges, what strategy types, what capital)
- Maintain positions (rebalance frequency, fee collection patterns)
- Close positions (when they exit, PnL triggers)

Feeds everything into cache/top_lps/ for the agent_loop to learn from.

Run: python lp_intelligence.py                  (full scan, save patterns)
     python lp_intelligence.py --pools          (just discover pools)
     python lp_intelligence.py --wallet ADDR    (scan specific wallet)
     python lp_intelligence.py --loop           (continuous every 4 hours)

Requires: LPAGENT_API_KEY environment variable
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

import httpx

# ============================================================
# CONFIGURATION
# ============================================================

LPAGENT_API = "https://api.lpagent.io/open-api/v1"
LPAGENT_API_KEY = os.getenv("LPAGENT_API_KEY", "")
METEORA_API = "https://dlmm.datapi.meteora.ag"

MAX_POOLS_TO_SCAN = int(os.getenv("MAX_POOLS_SCAN", "5"))
MAX_TOP_LPERS = int(os.getenv("MAX_TOP_LPERS", "10"))
MAX_WALLETS_DEEP_SCAN = int(os.getenv("MAX_WALLETS_DEEP", "5"))
REQUEST_DELAY = 0.2
CYCLE_INTERVAL = int(os.getenv("INTEL_INTERVAL", "14400"))

# Storage
CACHE_DIR = Path("cache/top_lps")
WALLETS_DIR = CACHE_DIR / "wallets"
POSITIONS_DIR = CACHE_DIR / "positions"
INTEL_FILE = CACHE_DIR / "intelligence.json"

for d in [CACHE_DIR, WALLETS_DIR, POSITIONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# API CLIENTS
# ============================================================

class LPAgentClient:
    """LP Agent API client."""

    def __init__(self):
        if not LPAGENT_API_KEY:
            print("ERROR: Set LPAGENT_API_KEY environment variable")
            print("  Get your key from https://app.lpagent.io/")
            sys.exit(1)

        self.client = httpx.Client(
            base_url=LPAGENT_API,
            timeout=30,
            headers={
                "x-api-key": LPAGENT_API_KEY,
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }
        )
        self.request_count = 0

    def _get(self, path, params=None):
        self.request_count += 1
        time.sleep(REQUEST_DELAY)
        try:
            resp = self.client.get(path, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code == 400:
                return None
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data) if isinstance(data, dict) else data
        except Exception as e:
            print("    LP Agent API error on {}: {}".format(path, e))
            return None

    def discover_pools(self):
        """GET /pools/discover — find active pools."""
        return self._get("/pools/discover")

    def get_pool_info(self, pool_address):
        """GET /pools/{address} — pool details."""
        return self._get("/pools/{}".format(pool_address))

    def get_pool_positions(self, pool_address):
        """GET /pools/{address}/positions — positions in pool."""
        return self._get("/pools/{}/positions".format(pool_address))

    def get_top_lpers(self, pool_address):
        """GET /pools/{address}/top-lpers — top LPers for a pool."""
        return self._get("/pools/{}/top-lpers".format(pool_address))

    def get_pool_stats(self, pool_address):
        """GET /pools/{address}/onchain-stats — on-chain statistics."""
        return self._get("/pools/{}/onchain-stats".format(pool_address))

    def get_open_positions(self, owner):
        """GET /lp-positions/opening — current open positions."""
        return self._get("/lp-positions/opening", params={"owner": owner})

    def get_position_history(self, owner):
        """GET /lp-positions/history — closed positions."""
        return self._get("/lp-positions/history", params={"owner": owner})

    def get_position_overview(self, owner):
        """GET /lp-positions/overview — performance metrics."""
        return self._get("/lp-positions/overview", params={"owner": owner})

    def get_position_detail(self, position_id):
        """GET /lp-positions/{id} — specific position details."""
        return self._get("/lp-positions/{}".format(position_id))

    def get_position_logs(self, owner=None):
        """GET /lp-positions/logs — activity logs."""
        params = {}
        if owner:
            params["owner"] = owner
        return self._get("/lp-positions/logs", params=params)

    def get_wallet_balances(self, wallet):
        """GET /wallets/{address}/balances — token balances."""
        return self._get("/wallets/{}/balances".format(wallet))


class MeteoraClient:
    """Meteora API for pool data."""

    def __init__(self):
        self.client = httpx.Client(
            base_url=METEORA_API,
            timeout=30,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        )

    def get_pools(self, limit=100):
        try:
            resp = self.client.get("/pools?limit={}".format(limit))
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", []) if isinstance(data, dict) else []
        except Exception as e:
            print("    Meteora API error: {}".format(e))
            return []


# ============================================================
# STEP 1: FIND TOP POOLS
# ============================================================

def find_top_pools(lp_client, meteora_client):
    """Get top pools from both Meteora and LP Agent."""
    print("\n[1/5] Discovering top pools...")

    # Get pools from Meteora (sorted by fees)
    meteora_pools = meteora_client.get_pools(limit=50)
    top_pool_addresses = []

    for p in meteora_pools:
        vol_data = p.get("volume", {})
        fee_data = p.get("fees", {})
        volume = float(vol_data.get("24h", 0) if isinstance(vol_data, dict) else 0)
        fees = float(fee_data.get("24h", 0) if isinstance(fee_data, dict) else 0)
        tvl = float(p.get("tvl", 0) or 0)

        if volume > 100000 and tvl > 50000 and fees > 1000:
            top_pool_addresses.append({
                "address": p.get("address", ""),
                "name": p.get("name", "Unknown"),
                "volume_24h": volume,
                "fees_24h": fees,
                "tvl": tvl,
                "apr": float(p.get("apr", 0) or 0),
                "bin_step": p.get("pool_config", {}).get("bin_step", 0),
            })

    # Sort by fees
    top_pool_addresses.sort(key=lambda x: x["fees_24h"], reverse=True)
    top_pools = top_pool_addresses[:MAX_POOLS_TO_SCAN]

    print("  Found {} high-activity pools".format(len(top_pool_addresses)))
    print("  Scanning top {}:".format(len(top_pools)))
    for i, p in enumerate(top_pools):
        print("    {}. {} | Fees: ${:,.0f} | TVL: ${:,.0f} | APR: {:.1f}%".format(
            i + 1, p["name"], p["fees_24h"], p["tvl"], p["apr"]))

    return top_pools


# ============================================================
# STEP 2: GET TOP LPERS PER POOL
# ============================================================

def scan_top_lpers(lp_client, pools):
    """Get top LPers for each pool via LP Agent API."""
    print("\n[2/5] Scanning top LPers per pool...")

    all_top_lpers = []
    wallet_pool_map = defaultdict(list)

    for pool in pools:
        print("  Scanning {} ({})...".format(pool["name"], pool["address"][:12]))
        lpers = lp_client.get_top_lpers(pool["address"])

        if not lpers or not isinstance(lpers, list):
            print("    No top LPers data")
            continue

        print("    Found {} LPers".format(len(lpers)))

        for lper in lpers[:MAX_TOP_LPERS]:
            owner = lper.get("owner", "")
            if not owner:
                continue

            total_fee = float(lper.get("total_fee", 0) or 0)
            total_pnl = float(lper.get("total_pnl", 0) or 0)
            total_inflow = float(lper.get("total_inflow", 0) or 0)
            total_outflow = float(lper.get("total_outflow", 0) or 0)
            avg_inflow = float(lper.get("avg_inflow", 0) or 0)

            lper_data = {
                "wallet": owner,
                "pool": pool["address"],
                "pool_name": pool["name"],
                "total_fee": total_fee,
                "total_pnl": total_pnl,
                "total_inflow": total_inflow,
                "total_outflow": total_outflow,
                "avg_inflow": avg_inflow,
                "fee_efficiency": total_fee / total_inflow if total_inflow > 0 else 0,
                "pnl_percent": total_pnl / total_inflow * 100 if total_inflow > 0 else 0,
            }

            all_top_lpers.append(lper_data)
            wallet_pool_map[owner].append(pool["name"])

    # Rank by fee efficiency
    all_top_lpers.sort(key=lambda x: x["fee_efficiency"], reverse=True)

    print("\n  Top LPers by fee efficiency:")
    for i, lp in enumerate(all_top_lpers[:10]):
        print("    {}. {}... | Fee eff: {:.4f} | PnL: {:.1f}% | Pools: {}".format(
            i + 1,
            lp["wallet"][:12],
            lp["fee_efficiency"],
            lp["pnl_percent"],
            ", ".join(wallet_pool_map[lp["wallet"]])))

    return all_top_lpers, wallet_pool_map


# ============================================================
# STEP 3: DEEP SCAN TOP WALLETS
# ============================================================

def deep_scan_wallets(lp_client, top_lpers, wallet_pool_map):
    """Deep scan the best wallets: open positions, history, overview."""
    print("\n[3/5] Deep scanning top {} wallets...".format(MAX_WALLETS_DEEP_SCAN))

    # Get unique wallets sorted by fee efficiency
    seen = set()
    unique_wallets = []
    for lp in top_lpers:
        if lp["wallet"] not in seen:
            seen.add(lp["wallet"])
            unique_wallets.append(lp)

    wallet_profiles = []

    for lp in unique_wallets[:MAX_WALLETS_DEEP_SCAN]:
        wallet = lp["wallet"]
        print("\n  Scanning wallet: {}...".format(wallet[:16]))

        profile = {
            "wallet": wallet,
            "pools_active": wallet_pool_map.get(wallet, []),
            "fee_efficiency": lp["fee_efficiency"],
            "total_fee": lp["total_fee"],
            "total_pnl": lp["total_pnl"],
            "open_positions": [],
            "closed_positions": [],
            "overview": None,
            "patterns": {},
        }

        # Get open positions
        open_pos = lp_client.get_open_positions(wallet)
        if open_pos and isinstance(open_pos, list):
            print("    Open positions: {}".format(len(open_pos)))
            for pos in open_pos:
                profile["open_positions"].append({
                    "pool": pos.get("pool", ""),
                    "pair_name": pos.get("pairName", ""),
                    "strategy_type": pos.get("strategyType", "unknown"),
                    "status": pos.get("status", ""),
                    "tick_lower": pos.get("tickLower", 0),
                    "tick_upper": pos.get("tickUpper", 0),
                    "range_width": abs(pos.get("tickUpper", 0) - pos.get("tickLower", 0)),
                    "input_value": float(pos.get("inputValue", 0) or 0),
                    "current_value": float(pos.get("currentValue", 0) or 0),
                    "collected_fee": float(pos.get("collectedFee", 0) or 0),
                    "uncollected_fee": float(pos.get("uncollectedFee", 0) or 0),
                    "in_range": pos.get("inRange", False),
                    "created_at": pos.get("createdAt", ""),
                    "updated_at": pos.get("updatedAt", ""),
                    "pnl": pos.get("pnl", {}),
                })
        else:
            print("    No open positions")

        # Get historical positions
        history = lp_client.get_position_history(wallet)
        if history and isinstance(history, list):
            print("    Historical positions: {}".format(len(history)))
            for pos in history[:20]:
                profile["closed_positions"].append({
                    "pool": pos.get("pool", ""),
                    "pair_name": pos.get("pairName", ""),
                    "strategy_type": pos.get("strategyType", "unknown"),
                    "tick_lower": pos.get("tickLower", 0),
                    "tick_upper": pos.get("tickUpper", 0),
                    "range_width": abs(pos.get("tickUpper", 0) - pos.get("tickLower", 0)),
                    "input_value": float(pos.get("inputValue", 0) or 0),
                    "output_value": float(pos.get("outputValue", 0) or 0),
                    "collected_fee": float(pos.get("collectedFee", 0) or 0),
                    "created_at": pos.get("createdAt", ""),
                    "updated_at": pos.get("updatedAt", ""),
                    "pnl": pos.get("pnl", {}),
                    "hold_duration_hours": 0,
                })

                # Calculate hold duration
                try:
                    created = pos.get("createdAt", "")
                    updated = pos.get("updatedAt", "")
                    if created and updated:
                        from datetime import datetime as dt
                        c = dt.fromisoformat(created.replace("Z", "+00:00"))
                        u = dt.fromisoformat(updated.replace("Z", "+00:00"))
                        hours = (u - c).total_seconds() / 3600
                        profile["closed_positions"][-1]["hold_duration_hours"] = round(hours, 1)
                except Exception:
                    pass
        else:
            print("    No historical positions")

        # Get overview
        overview = lp_client.get_position_overview(wallet)
        if overview:
            print("    Overview: total fee ${:,.0f}, PnL ${:,.0f}".format(
                float(overview.get("total_fee", {}).get("ALL", 0) or 0) if isinstance(overview.get("total_fee"), dict) else float(overview.get("total_fee", 0) or 0),
                float(overview.get("total_pnl", {}).get("ALL", 0) or 0) if isinstance(overview.get("total_pnl"), dict) else float(overview.get("total_pnl", 0) or 0),
            ))
            profile["overview"] = overview

        # Extract patterns from this wallet
        profile["patterns"] = extract_wallet_patterns(profile)
        wallet_profiles.append(profile)

    return wallet_profiles


# ============================================================
# STEP 4: EXTRACT PATTERNS
# ============================================================

def extract_wallet_patterns(profile):
    """Extract actionable patterns from a single wallet's behavior."""
    patterns = {
        "strategy_types_used": [],
        "avg_range_width": 0,
        "avg_hold_duration_hours": 0,
        "win_rate": 0,
        "avg_capital_per_position": 0,
        "fee_collection_style": "unknown",
        "position_sizing": "unknown",
        "rebalance_frequency": "unknown",
    }

    # Analyze open positions
    open_pos = profile.get("open_positions", [])
    closed_pos = profile.get("closed_positions", [])
    all_pos = open_pos + closed_pos

    if not all_pos:
        return patterns

    # Strategy types
    strat_types = [p.get("strategy_type", "unknown") for p in all_pos]
    patterns["strategy_types_used"] = list(set(strat_types))

    # Range widths
    range_widths = [p.get("range_width", 0) for p in all_pos if p.get("range_width", 0) > 0]
    if range_widths:
        patterns["avg_range_width"] = sum(range_widths) / len(range_widths)

    # Hold durations (from closed positions)
    durations = [p.get("hold_duration_hours", 0) for p in closed_pos if p.get("hold_duration_hours", 0) > 0]
    if durations:
        patterns["avg_hold_duration_hours"] = sum(durations) / len(durations)

    # Win rate (from closed positions with PnL data)
    wins = 0
    total_with_pnl = 0
    for p in closed_pos:
        pnl = p.get("pnl", {})
        if isinstance(pnl, dict):
            pnl_value = float(pnl.get("value", 0) or pnl.get("percent", 0) or 0)
        else:
            pnl_value = float(pnl or 0)
        if pnl_value != 0:
            total_with_pnl += 1
            if pnl_value > 0:
                wins += 1
    if total_with_pnl > 0:
        patterns["win_rate"] = wins / total_with_pnl

    # Average capital per position
    capitals = [p.get("input_value", 0) for p in all_pos if p.get("input_value", 0) > 0]
    if capitals:
        patterns["avg_capital_per_position"] = sum(capitals) / len(capitals)

    # Fee collection style
    uncollected = sum(float(p.get("uncollected_fee", 0) or 0) for p in open_pos)
    collected = sum(float(p.get("collected_fee", 0) or 0) for p in all_pos)
    if collected > 0:
        if uncollected / (collected + uncollected + 0.001) < 0.1:
            patterns["fee_collection_style"] = "aggressive (claims frequently)"
        elif uncollected / (collected + uncollected + 0.001) < 0.3:
            patterns["fee_collection_style"] = "moderate"
        else:
            patterns["fee_collection_style"] = "passive (lets fees accumulate)"

    # Position sizing
    if capitals:
        max_cap = max(capitals)
        min_cap = min(capitals)
        if max_cap > 0 and min_cap / max_cap > 0.5:
            patterns["position_sizing"] = "uniform (similar sizes)"
        else:
            patterns["position_sizing"] = "varied (different sizes per pool)"

    # Rebalance frequency estimate
    if durations:
        avg_dur = patterns["avg_hold_duration_hours"]
        if avg_dur < 6:
            patterns["rebalance_frequency"] = "very frequent (<6h)"
        elif avg_dur < 24:
            patterns["rebalance_frequency"] = "frequent (6-24h)"
        elif avg_dur < 72:
            patterns["rebalance_frequency"] = "moderate (1-3 days)"
        elif avg_dur < 168:
            patterns["rebalance_frequency"] = "infrequent (3-7 days)"
        else:
            patterns["rebalance_frequency"] = "rare (>7 days)"

    return patterns


def extract_aggregate_intelligence(wallet_profiles, top_lpers, pools):
    """Combine all wallet data into aggregate intelligence."""
    print("\n[4/5] Extracting aggregate intelligence...")

    timestamp = datetime.now(timezone.utc).isoformat()

    # Aggregate patterns across all wallets
    all_strat_types = []
    all_range_widths = []
    all_hold_durations = []
    all_win_rates = []
    all_capitals = []
    all_fee_styles = []
    all_rebalance_freqs = []

    wallet_summaries = []

    for wp in wallet_profiles:
        p = wp["patterns"]
        all_strat_types.extend(p.get("strategy_types_used", []))
        if p.get("avg_range_width", 0) > 0:
            all_range_widths.append(p["avg_range_width"])
        if p.get("avg_hold_duration_hours", 0) > 0:
            all_hold_durations.append(p["avg_hold_duration_hours"])
        if p.get("win_rate", 0) > 0:
            all_win_rates.append(p["win_rate"])
        if p.get("avg_capital_per_position", 0) > 0:
            all_capitals.append(p["avg_capital_per_position"])
        all_fee_styles.append(p.get("fee_collection_style", "unknown"))
        all_rebalance_freqs.append(p.get("rebalance_frequency", "unknown"))

        wallet_summaries.append({
            "wallet": wp["wallet"][:16] + "...",
            "pools": wp["pools_active"],
            "open_positions": len(wp["open_positions"]),
            "closed_positions": len(wp["closed_positions"]),
            "fee_efficiency": wp["fee_efficiency"],
            "patterns": p,
        })

    # Count strategy types
    strat_counts = defaultdict(int)
    for s in all_strat_types:
        strat_counts[s] += 1

    # Count rebalance frequencies
    rebalance_counts = defaultdict(int)
    for r in all_rebalance_freqs:
        rebalance_counts[r] += 1

    intelligence = {
        "timestamp": timestamp,
        "source": "LP Agent API",
        "pools_scanned": len(pools),
        "wallets_deep_scanned": len(wallet_profiles),
        "total_top_lpers_found": len(top_lpers),

        "top_pools": [{
            "name": p["name"],
            "address": p["address"],
            "fees_24h": p["fees_24h"],
            "tvl": p["tvl"],
            "apr": p["apr"],
            "bin_step": p["bin_step"],
        } for p in pools],

        "wallet_summaries": wallet_summaries,

        "aggregate_patterns": {
            "most_used_strategies": dict(sorted(strat_counts.items(), key=lambda x: -x[1])),
            "avg_range_width_bins": sum(all_range_widths) / len(all_range_widths) if all_range_widths else 0,
            "avg_hold_duration_hours": sum(all_hold_durations) / len(all_hold_durations) if all_hold_durations else 0,
            "avg_win_rate": sum(all_win_rates) / len(all_win_rates) if all_win_rates else 0,
            "avg_capital_per_position_usd": sum(all_capitals) / len(all_capitals) if all_capitals else 0,
            "rebalance_frequency_distribution": dict(rebalance_counts),
            "fee_collection_styles": list(set(all_fee_styles)),
        },

        "actionable_insights": [],
    }

    # Generate insights
    insights = intelligence["actionable_insights"]

    if strat_counts:
        top_strat = max(strat_counts, key=strat_counts.get)
        insights.append("Most used strategy type: {} ({}x)".format(top_strat, strat_counts[top_strat]))

    if all_range_widths:
        insights.append("Average range width: {:.0f} bins (min: {:.0f}, max: {:.0f})".format(
            sum(all_range_widths) / len(all_range_widths),
            min(all_range_widths), max(all_range_widths)))

    if all_hold_durations:
        avg_dur = sum(all_hold_durations) / len(all_hold_durations)
        insights.append("Average hold duration: {:.1f} hours ({:.1f} days)".format(avg_dur, avg_dur / 24))

    if all_win_rates:
        avg_wr = sum(all_win_rates) / len(all_win_rates)
        insights.append("Average win rate: {:.1f}%".format(avg_wr * 100))

    if all_capitals:
        insights.append("Average position size: ${:,.0f}".format(
            sum(all_capitals) / len(all_capitals)))

    if rebalance_counts:
        most_common = max(rebalance_counts, key=rebalance_counts.get)
        insights.append("Most common rebalance frequency: {}".format(most_common))

    # Specific LP behavior insights
    for wp in wallet_profiles[:3]:
        p = wp["patterns"]
        if p.get("win_rate", 0) > 0.7:
            insights.append("High win rate wallet {}...: {:.0f}% win rate, {} strategy, avg hold {:.1f}h".format(
                wp["wallet"][:8], p["win_rate"] * 100,
                "/".join(p.get("strategy_types_used", ["?"])),
                p.get("avg_hold_duration_hours", 0)))

    return intelligence


# ============================================================
# STEP 5: SAVE INTELLIGENCE
# ============================================================

def save_intelligence(intelligence):
    """Save intelligence data for the agent to use."""
    print("\n[5/5] Saving intelligence...")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Save full intelligence report
    INTEL_FILE.write_text(json.dumps(intelligence, indent=2), encoding="utf-8")
    print("  Saved: {}".format(INTEL_FILE))

    # Save timestamped copy
    timestamped = CACHE_DIR / "intel_{}.json".format(ts)
    timestamped.write_text(json.dumps(intelligence, indent=2), encoding="utf-8")

    # Save wallet profiles separately
    for ws in intelligence.get("wallet_summaries", []):
        wallet_short = ws["wallet"].replace("...", "")
        wallet_file = WALLETS_DIR / "wallet_{}.json".format(wallet_short)
        wallet_file.write_text(json.dumps(ws, indent=2), encoding="utf-8")

    # Update live_patterns.json with LP intelligence
    live_patterns_file = CACHE_DIR / "live_patterns.json"
    existing = {}
    if live_patterns_file.exists():
        try:
            existing = json.loads(live_patterns_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Merge LP intelligence into existing patterns
    existing["lp_intelligence"] = {
        "timestamp": intelligence["timestamp"],
        "wallets_scanned": intelligence["wallets_deep_scanned"],
        "aggregate_patterns": intelligence["aggregate_patterns"],
        "actionable_insights": intelligence["actionable_insights"],
        "top_wallet_strategies": [
            {
                "wallet": ws["wallet"],
                "patterns": ws["patterns"],
            }
            for ws in intelligence.get("wallet_summaries", [])[:5]
        ],
    }
    live_patterns_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print("  Updated: cache/top_lps/live_patterns.json with LP intelligence")

    # Print insights
    print("\n  Intelligence insights:")
    for insight in intelligence.get("actionable_insights", []):
        print("    > {}".format(insight))

    # Cleanup old files (keep last 20)
    intel_files = sorted(CACHE_DIR.glob("intel_*.json"))
    if len(intel_files) > 20:
        for f in intel_files[:-20]:
            f.unlink()


# ============================================================
# MAIN
# ============================================================

def run_full_scan():
    """Run the complete intelligence gathering pipeline."""
    print("=" * 60)
    print("LP INTELLIGENCE — {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)

    lp_client = LPAgentClient()
    meteora_client = MeteoraClient()

    # Step 1: Find top pools
    pools = find_top_pools(lp_client, meteora_client)
    if not pools:
        print("No pools found. Aborting.")
        return

    # Step 2: Get top LPers per pool
    top_lpers, wallet_pool_map = scan_top_lpers(lp_client, pools)
    if not top_lpers:
        print("No top LPers found. Aborting.")
        return

    # Step 3: Deep scan top wallets
    wallet_profiles = deep_scan_wallets(lp_client, top_lpers, wallet_pool_map)

    # Step 4: Extract aggregate intelligence
    intelligence = extract_aggregate_intelligence(wallet_profiles, top_lpers, pools)

    # Step 5: Save
    save_intelligence(intelligence)

    print("\n  Total API requests: {}".format(lp_client.request_count))
    print("  Done!")


def scan_wallet(wallet_address):
    """Scan a specific wallet."""
    print("Scanning wallet: {}".format(wallet_address))
    lp_client = LPAgentClient()

    profile = {
        "wallet": wallet_address,
        "pools_active": [],
        "fee_efficiency": 0,
        "total_fee": 0,
        "total_pnl": 0,
        "open_positions": [],
        "closed_positions": [],
        "overview": None,
        "patterns": {},
    }

    # Get open positions
    open_pos = lp_client.get_open_positions(wallet_address)
    if open_pos and isinstance(open_pos, list):
        print("  Open positions: {}".format(len(open_pos)))
        for pos in open_pos:
            print("    {} | {} | range: {}-{} | fee: ${:,.2f} | in_range: {}".format(
                pos.get("pairName", "?"),
                pos.get("strategyType", "?"),
                pos.get("tickLower", 0),
                pos.get("tickUpper", 0),
                float(pos.get("collectedFee", 0) or 0),
                pos.get("inRange", "?"),
            ))

    # Get overview
    overview = lp_client.get_position_overview(wallet_address)
    if overview:
        total_fee = overview.get("total_fee", {})
        total_pnl = overview.get("total_pnl", {})
        if isinstance(total_fee, dict):
            print("  Total fees: ${:,.2f}".format(float(total_fee.get("ALL", 0) or 0)))
        if isinstance(total_pnl, dict):
            print("  Total PnL: ${:,.2f}".format(float(total_pnl.get("ALL", 0) or 0)))

    # Get history
    history = lp_client.get_position_history(wallet_address)
    if history and isinstance(history, list):
        print("  Closed positions: {}".format(len(history)))


def main():
    parser = argparse.ArgumentParser(description="LP Intelligence — Learn from Top LPs")
    parser.add_argument("--pools", action="store_true", help="Just discover pools")
    parser.add_argument("--wallet", type=str, help="Scan specific wallet address")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=CYCLE_INTERVAL,
                        help="Seconds between cycles (default: {})".format(CYCLE_INTERVAL))
    args = parser.parse_args()

    if args.wallet:
        scan_wallet(args.wallet)
        return

    if args.pools:
        lp_client = LPAgentClient()
        meteora_client = MeteoraClient()
        find_top_pools(lp_client, meteora_client)
        return

    if args.loop:
        print("LP INTELLIGENCE — CONTINUOUS MODE")
        print("Interval: {}s ({:.1f} hours)".format(args.interval, args.interval / 3600))
        cycle = 0
        while True:
            cycle += 1
            try:
                run_full_scan()
            except Exception as e:
                print("  ERROR in cycle {}: {}".format(cycle, e))
            print("\n  Next scan in {:.1f} hours...".format(args.interval / 3600))
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopped. Data saved.")
                break
        return

    # Default: single full scan
    run_full_scan()


if __name__ == "__main__":
    main()
