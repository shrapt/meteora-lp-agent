"""
live_watcher.py — Real-time Meteora Pool & Top LP Watcher

Uses the NEW Meteora DLMM API (March 2026):
  Base URL: https://dlmm.datapi.meteora.ag
  Endpoints: /pools, /pools/{address}, /pools/{address}/ohlcv, /stats/protocol_metrics

Run: python live_watcher.py
     python live_watcher.py --once     (single fetch, no loop)
     python live_watcher.py --pools    (just show top pools)

No API key needed — 30 req/sec limit.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

import httpx

# ============================================================
# CONFIGURATION
# ============================================================

METEORA_API = "https://dlmm.datapi.meteora.ag"
CYCLE_INTERVAL = int(os.getenv("WATCHER_INTERVAL", "14400"))
MAX_POOLS = int(os.getenv("MAX_POOLS", "10"))
REQUEST_DELAY = 0.15

# Storage
LIVE_DIR = Path("cache/live")
POOLS_DIR = LIVE_DIR / "pools"
SNAPSHOTS_DIR = LIVE_DIR / "snapshots"
PATTERNS_FILE = LIVE_DIR / "latest_patterns.json"

for d in [LIVE_DIR, POOLS_DIR, SNAPSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class PoolInfo:
    address: str
    name: str
    token_x_symbol: str
    token_y_symbol: str
    token_x_price: float
    token_y_price: float
    bin_step: int
    base_fee_pct: float
    current_price: float
    tvl: float
    volume_24h: float
    fees_24h: float
    apr: float
    apy: float
    has_farm: bool = False


# ============================================================
# METEORA API CLIENT (New March 2026 API)
# ============================================================

class MeteoraClient:
    """Client for new Meteora DLMM API."""

    def __init__(self):
        self.client = httpx.Client(
            base_url=METEORA_API,
            timeout=30,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        self.request_count = 0

    def _get(self, path):
        self.request_count += 1
        time.sleep(REQUEST_DELAY)
        try:
            resp = self.client.get(path)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print("    API error on {}: {}".format(path, e))
            return None

    def get_pools(self, limit=100, page=1):
        data = self._get("/pools?limit={}&page={}".format(limit, page))
        return data if isinstance(data, dict) else {"data": []}

    def get_pool(self, address):
        return self._get("/pools/{}".format(address))

    def get_pool_ohlcv(self, address, resolution="1h", limit=168):
        data = self._get("/pools/{}/ohlcv?resolution={}&limit={}".format(address, resolution, limit))
        return data if isinstance(data, list) else []

    def get_protocol_metrics(self):
        return self._get("/stats/protocol_metrics")


# ============================================================
# TOP POOL DISCOVERY
# ============================================================

def discover_top_pools(client, max_pools=MAX_POOLS):
    print("  Fetching pools from Meteora...")

    all_raw = []
    for page in range(1, 4):
        result = client.get_pools(limit=100, page=page)
        page_data = result.get("data", [])
        if not page_data:
            break
        all_raw.extend(page_data)
        print("    Page {}: {} pools".format(page, len(page_data)))

    print("  Total pools fetched: {}".format(len(all_raw)))

    if not all_raw:
        print("  ERROR: No pools returned from API")
        return []

    pools = []
    for p in all_raw:
        try:
            if p.get("is_blacklisted", False):
                continue

            vol_data = p.get("volume", {})
            fee_data = p.get("fees", {})
            volume = float(vol_data.get("24h", 0) if isinstance(vol_data, dict) else 0)
            fees = float(fee_data.get("24h", 0) if isinstance(fee_data, dict) else 0)
            tvl = float(p.get("tvl", 0) or 0)

            if volume < 10000 or tvl < 50000:
                continue

            token_x = p.get("token_x", {})
            token_y = p.get("token_y", {})
            pool_config = p.get("pool_config", {})

            pool = PoolInfo(
                address=p.get("address", ""),
                name=p.get("name", "Unknown"),
                token_x_symbol=token_x.get("symbol", "?"),
                token_y_symbol=token_y.get("symbol", "?"),
                token_x_price=float(token_x.get("price", 0) or 0),
                token_y_price=float(token_y.get("price", 0) or 0),
                bin_step=int(pool_config.get("bin_step", 0) or 0),
                base_fee_pct=float(pool_config.get("base_fee_pct", 0) or 0),
                current_price=float(p.get("current_price", 0) or 0),
                tvl=tvl,
                volume_24h=volume,
                fees_24h=fees,
                apr=float(p.get("apr", 0) or 0),
                apy=float(p.get("apy", 0) or 0),
                has_farm=p.get("has_farm", False),
            )
            pools.append(pool)
        except (ValueError, TypeError, KeyError):
            continue

    pools.sort(key=lambda p: p.fees_24h, reverse=True)

    top = pools[:max_pools]
    print("")
    print("  Top {} pools by 24h fees:".format(len(top)))
    print("  {:<4} {:<20} {:>15} {:>12} {:>15} {:>8} {:>5}".format(
        "#", "Name", "Volume 24h", "Fees 24h", "TVL", "APR", "Bin"))
    print("  " + "-" * 80)
    for i, p in enumerate(top):
        print("  {:<4} {:<20} ${:>13,.0f} ${:>10,.0f} ${:>13,.0f} {:>7.1f}% {:>5}".format(
            i + 1, p.name, p.volume_24h, p.fees_24h, p.tvl, p.apr, p.bin_step))

    return top


# ============================================================
# OHLCV DATA (Real price history!)
# ============================================================

def fetch_pool_ohlcv(client, pool, hours=168):
    print("    Fetching OHLCV for {} ({}h)...".format(pool.name, hours))
    candles = client.get_pool_ohlcv(pool.address, resolution="1h", limit=hours)
    if candles:
        print("    Got {} candles".format(len(candles)))
    else:
        print("    No OHLCV data available")
    return candles


# ============================================================
# PATTERN EXTRACTION
# ============================================================

def extract_patterns(pools):
    timestamp = datetime.now(timezone.utc).isoformat()

    pool_patterns = []
    for p in pools[:10]:
        pool_patterns.append({
            "name": p.name,
            "address": p.address,
            "volume_24h": p.volume_24h,
            "fees_24h": p.fees_24h,
            "tvl": p.tvl,
            "apr": p.apr,
            "apy": p.apy,
            "bin_step": p.bin_step,
            "base_fee_pct": p.base_fee_pct,
            "current_price": p.current_price,
            "fee_to_tvl_ratio": p.fees_24h / p.tvl if p.tvl > 0 else 0,
            "volume_to_tvl_ratio": p.volume_24h / p.tvl if p.tvl > 0 else 0,
            "token_x": p.token_x_symbol,
            "token_y": p.token_y_symbol,
        })

    aprs = [p.apr for p in pools if p.apr > 0]
    bin_steps = [p.bin_step for p in pools if p.bin_step > 0]
    tvls = [p.tvl for p in pools]
    volumes = [p.volume_24h for p in pools]

    patterns = {
        "timestamp": timestamp,
        "pools_analyzed": len(pools),
        "top_pools": pool_patterns,
        "aggregate": {
            "avg_apr": sum(aprs) / len(aprs) if aprs else 0,
            "median_apr": sorted(aprs)[len(aprs) // 2] if aprs else 0,
            "total_tvl": sum(tvls),
            "total_volume_24h": sum(volumes),
            "common_bin_steps": sorted(set(bin_steps)),
            "avg_fee_to_tvl": sum(p.fees_24h for p in pools) / sum(tvls) if sum(tvls) > 0 else 0,
        },
        "insights": [],
    }

    if pool_patterns:
        best = pool_patterns[0]
        patterns["insights"].append(
            "Top pool: {} -- ${:,.0f} fees/24h, {:.1f}% APR, bin_step={}".format(
                best["name"], best["fees_24h"], best["apr"], best["bin_step"]))

    if aprs:
        patterns["insights"].append(
            "APR range: {:.1f}% to {:.1f}%, avg {:.1f}%".format(
                min(aprs), max(aprs), patterns["aggregate"]["avg_apr"]))

    if bin_steps:
        from collections import Counter
        common = Counter(bin_steps).most_common(3)
        patterns["insights"].append(
            "Most common bin steps: {}".format(
                ", ".join("{}({}x)".format(bs, cnt) for bs, cnt in common)))

    high_efficiency = [p for p in pool_patterns if p["fee_to_tvl_ratio"] > 0.01]
    if high_efficiency:
        patterns["insights"].append(
            "High fee efficiency pools (>1% fee/TVL daily): {}".format(
                ", ".join(p["name"] for p in high_efficiency[:3])))

    return patterns


# ============================================================
# SAVE DATA
# ============================================================

def save_snapshot(pools, patterns, ohlcv_data=None):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    pool_data = [asdict(p) for p in pools]
    pool_file = POOLS_DIR / "pools_{}.json".format(ts)
    pool_file.write_text(json.dumps(pool_data, indent=2), encoding="utf-8")

    snapshot = {
        "timestamp": ts,
        "pools": pool_data,
        "patterns": patterns,
    }
    if ohlcv_data:
        snapshot["ohlcv"] = ohlcv_data
    snap_file = SNAPSHOTS_DIR / "snapshot_{}.json".format(ts)
    snap_file.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    PATTERNS_FILE.write_text(json.dumps(patterns, indent=2), encoding="utf-8")

    top_lps_dir = Path("cache/top_lps")
    top_lps_dir.mkdir(parents=True, exist_ok=True)
    (top_lps_dir / "live_patterns.json").write_text(
        json.dumps(patterns, indent=2), encoding="utf-8"
    )

    print("  Saved snapshot: {}".format(snap_file.name))
    print("  Updated: cache/top_lps/live_patterns.json")

    for dir_path in [POOLS_DIR, SNAPSHOTS_DIR]:
        files = sorted(dir_path.glob("*.json"))
        if len(files) > 50:
            for f in files[:-50]:
                f.unlink()


# ============================================================
# MAIN
# ============================================================

def run_once(client, fetch_ohlcv=True):
    print("\n" + "=" * 60)
    print("LIVE WATCHER -- {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 60)

    print("\n[0/3] Protocol metrics...")
    metrics = client.get_protocol_metrics()
    if metrics:
        print("  Total TVL: ${:,.0f}".format(metrics.get("total_tvl", 0)))
        print("  24h Volume: ${:,.0f}".format(metrics.get("volume_24h", 0)))
        print("  24h Fees: ${:,.0f}".format(metrics.get("fee_24h", 0)))
        print("  Total Pools: {:,}".format(metrics.get("total_pools", 0)))

    print("\n[1/3] Discovering top pools...")
    pools = discover_top_pools(client)
    if not pools:
        print("  No pools found.")
        return

    ohlcv_data = {}
    if fetch_ohlcv:
        print("\n[2/3] Fetching price history for top 3 pools...")
        for pool in pools[:3]:
            candles = fetch_pool_ohlcv(client, pool, hours=168)
            if candles:
                ohlcv_data[pool.name] = {
                    "address": pool.address,
                    "candles_count": len(candles),
                    "candles": candles[:5],
                }
    else:
        print("\n[2/3] Skipping OHLCV")

    print("\n[3/3] Extracting patterns...")
    patterns = extract_patterns(pools)
    save_snapshot(pools, patterns, ohlcv_data if ohlcv_data else None)

    print("\n  Insights:")
    for insight in patterns.get("insights", []):
        print("    > {}".format(insight))

    print("\n  API requests this cycle: {}".format(client.request_count))
    client.request_count = 0


def main():
    parser = argparse.ArgumentParser(description="Meteora Live Data Watcher")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--pools", action="store_true", help="Just show top pools")
    parser.add_argument("--ohlcv", action="store_true", help="Also fetch OHLCV data")
    parser.add_argument("--interval", type=int, default=CYCLE_INTERVAL,
                        help="Seconds between cycles (default: {})".format(CYCLE_INTERVAL))
    args = parser.parse_args()

    client = MeteoraClient()

    if args.pools:
        discover_top_pools(client, max_pools=20)
        return

    if args.once:
        run_once(client, fetch_ohlcv=args.ohlcv)
        return

    print("=" * 60)
    print("METEORA LIVE WATCHER -- CONTINUOUS MODE")
    print("Interval: {}s ({:.1f} hours)".format(args.interval, args.interval / 3600))
    print("Press Ctrl+C to stop")
    print("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        try:
            run_once(client, fetch_ohlcv=True)
        except Exception as e:
            print("  ERROR in cycle {}: {}".format(cycle, e))

        print("\n  Next cycle in {:.1f} hours...".format(args.interval / 3600))

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\nStopped by user. Data saved.")
            break


if __name__ == "__main__":
    main()
