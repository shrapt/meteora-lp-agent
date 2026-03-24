"""
agent_loop.py — Autonomous LP Strategy Researcher

This script IS the autoresearch loop. It replaces Claude Code by calling
an LLM API (OpenRouter, Anthropic, or OpenAI-compatible) to:
1. Read current strategy.py and results history
2. Ask the LLM to propose a modification
3. Apply the edit to strategy.py
4. Run simulate.py and capture results
5. Keep or discard based on avg_net_yield
6. Repeat forever

Run: python agent_loop.py
Stop: Ctrl+C (it saves state cleanly)

Cost estimate per night (~100 experiments):
- Haiku via OpenRouter: ~$0.30-0.80
- Sonnet via OpenRouter: ~$2-5
- Gemini Flash: ~$0.20-0.50
- Llama 3.1 70B: ~$0.40-1.00
"""

import os
import sys
import json
import time
import subprocess
import shutil
import hashlib
from pathlib import Path
from datetime import datetime

import httpx

# ============================================================
# CONFIGURATION
# ============================================================

# LLM Provider settings
# Supports: OpenRouter, Anthropic, OpenAI, or any OpenAI-compatible API
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")  # Your OpenRouter or other API key
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-3.5-haiku")  # Cheap & good

# Alternative models (uncomment to use):
# LLM_MODEL = "anthropic/claude-sonnet-4"      # Better but ~10x cost
# LLM_MODEL = "google/gemini-flash-1.5"        # Very cheap
# LLM_MODEL = "meta-llama/llama-3.1-70b-instruct"  # Good & cheap
# LLM_MODEL = "deepseek/deepseek-chat"         # Very cheap, good at code

# Agent settings
MAX_EXPERIMENTS = int(os.getenv("MAX_EXPERIMENTS", "200"))  # Max per session
EXPERIMENT_TIMEOUT = int(os.getenv("EXPERIMENT_TIMEOUT", "120"))  # Seconds per simulation
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
SLEEP_BETWEEN_EXPERIMENTS = int(os.getenv("SLEEP_BETWEEN_EXPERIMENTS", "2"))  # Seconds

# File paths
STRATEGY_FILE = Path("strategy.py")
RESULTS_FILE = Path("results.tsv")
PREPARE_FILE = Path("prepare.py")
SIMULATE_CMD = ["python", "simulate.py"]  # or ["python", "simulate.py"]
TOP_LP_DATA = Path("cache/top_lps")
BACKUP_DIR = Path("backups")

# ============================================================
# LLM CLIENT
# ============================================================

class LLMClient:
    """Unified client for OpenRouter / Anthropic / OpenAI-compatible APIs."""

    def __init__(self):
        self.base_url = LLM_BASE_URL.rstrip("/")
        self.api_key = LLM_API_KEY
        self.model = LLM_MODEL
        self.client = httpx.Client(timeout=120)

        if not self.api_key:
            print("ERROR: Set LLM_API_KEY environment variable")
            print("  For OpenRouter: https://openrouter.ai/keys")
            print("  For Anthropic:  https://console.anthropic.com/")
            sys.exit(1)

        # Detect if using Anthropic native API
        self.is_anthropic = "anthropic.com" in self.base_url

    def chat(self, system_prompt: str, user_message: str) -> str:
        """Send a message and get a response."""
        if self.is_anthropic:
            return self._chat_anthropic(system_prompt, user_message)
        else:
            return self._chat_openai_compat(system_prompt, user_message)

    def _chat_openai_compat(self, system_prompt: str, user_message: str) -> str:
        """OpenRouter / OpenAI / compatible API."""
        resp = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 4096,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _chat_anthropic(self, system_prompt: str, user_message: str) -> str:
        """Native Anthropic API."""
        resp = self.client.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
                "max_tokens": 4096,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


# ============================================================
# SYSTEM PROMPT (the "program.md" for the LLM)
# ============================================================

SYSTEM_PROMPT = """You are an autonomous LP strategy researcher for Meteora DLMM pools.

Your job: modify strategy.py to maximize avg_net_yield across simulated Meteora pools.

## Rules:
1. You ONLY modify strategy.py — nothing else
2. You respond with the COMPLETE new strategy.py file content
3. Wrap the code in ```python ... ``` markers
4. Keep changes focused — one hypothesis per experiment
5. Simpler is better. Don't add complexity unless it clearly helps.
6. Track what you've tried from the results history — don't repeat failed ideas

## Strategy file interface:
The lp_strategy() function receives:
- snapshots_history: list of PoolSnapshot (timestamp, price, volume_24h, tvl, fee_rate, bin_step, active_bin_id)
- current_position: None or dict with entry_price, range_lower, range_upper, amount, deployed_at
- capital_available: float (USDC not deployed)
- fees_earned_so_far: float

It must return a dict with:
- type: "deploy" | "rebalance" | "withdraw" | "hold"
- range_lower, range_upper: floats (for deploy/rebalance)
- amount: float (for deploy/rebalance)

## Research directions:
- Volatility-adaptive range widths
- Volume-weighted rebalancing decisions
- Asymmetric ranges (wider in trend direction)
- Fee-rate-aware capital sizing
- Mean reversion detection for tighter ranges
- Gas-cost-aware rebalancing (only if improvement > tx cost)
- Multi-timeframe analysis
- Different strategies per pool type (stable vs volatile)

## Response format:
First write 1-2 sentences explaining your hypothesis.
Then output the COMPLETE strategy.py wrapped in ```python markers.
Nothing else.
"""


# ============================================================
# EXPERIMENT RUNNER
# ============================================================

def read_file(path: Path) -> str:
    """Read a file, return empty string if not found."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_file(path: Path, content: str):
    """Write content to file."""
    path.write_text(content, encoding="utf-8")


def backup_strategy():
    """Backup current strategy.py before modification."""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy(STRATEGY_FILE, BACKUP_DIR / f"strategy_{ts}.py")


def run_simulation() -> dict | None:
    """Run simulate.py and parse the results. Returns dict or None on failure."""
    try:
        result = subprocess.run(
            SIMULATE_CMD,
            capture_output=True,
            text=True,
            timeout=EXPERIMENT_TIMEOUT,
        )

        output = result.stdout + result.stderr

        if result.returncode != 0:
            print(f"  Simulation CRASHED: {result.stderr[-200:]}")
            return None

        # Parse grep-able metrics
        metrics = {}
        for line in output.split("\n"):
            line = line.strip()
            for key in ["avg_net_yield", "avg_time_in_range", "avg_max_drawdown",
                        "eval_seconds", "pools_evaluated"]:
                if line.startswith(f"{key}:"):
                    try:
                        metrics[key] = float(line.split(":")[1].strip())
                    except (ValueError, IndexError):
                        pass

        if "avg_net_yield" not in metrics:
            print(f"  Could not parse avg_net_yield from output")
            print(f"  Last 300 chars: {output[-300:]}")
            return None

        return metrics

    except subprocess.TimeoutExpired:
        print(f"  Simulation TIMEOUT (>{EXPERIMENT_TIMEOUT}s)")
        return None
    except Exception as e:
        print(f"  Simulation ERROR: {e}")
        return None


def get_results_history() -> str:
    """Read results.tsv and return as string."""
    if RESULTS_FILE.exists():
        return RESULTS_FILE.read_text()
    # Create with header
    header = "experiment\tavg_net_yield\ttime_in_range\tstatus\tdescription\n"
    write_file(RESULTS_FILE, header)
    return header


def append_result(experiment_num: int, metrics: dict | None, status: str, description: str):
    """Append a result to results.tsv."""
    if metrics:
        yield_val = f"{metrics.get('avg_net_yield', 0):.6f}"
        tir_val = f"{metrics.get('avg_time_in_range', 0):.4f}"
    else:
        yield_val = "0.000000"
        tir_val = "0.0000"

    line = f"{experiment_num}\t{yield_val}\t{tir_val}\t{status}\t{description}\n"

    with open(RESULTS_FILE, "a") as f:
        f.write(line)


def get_top_lp_context() -> str:
    """Load top LP pattern data if available."""
    if not TOP_LP_DATA.exists():
        return "No top LP data available yet."

    context_parts = []
    for f in sorted(TOP_LP_DATA.glob("*.json"))[:5]:  # Limit to 5 files
        try:
            data = json.loads(f.read_text())
            context_parts.append(f"## {f.stem}\n{json.dumps(data, indent=2)[:1000]}")
        except Exception:
            pass

    if not context_parts:
        return "No top LP data available yet."

    return "## Top LP Patterns (learn from these):\n\n" + "\n\n".join(context_parts)


def extract_code(response: str) -> str | None:
    """Extract Python code from LLM response."""
    try:
        if "```python" in response:
            start = response.index("```python") + len("```python")
            end = response.index("```", start) if "```" in response[start:] else len(response)
            return response[start:end].strip()

        if "```" in response:
            start = response.index("```") + 3
            newline = response.index("\n", start) if "\n" in response[start:] else start
            start = newline + 1
            end = response.index("```", start) if "```" in response[start:] else len(response)
            return response[start:end].strip()
    except (ValueError, IndexError):
        pass

    return None

def get_best_yield() -> float:
    """Get the best avg_net_yield from results history."""
    best = float("-inf")
    if RESULTS_FILE.exists():
        for line in RESULTS_FILE.read_text().strip().split("\n")[1:]:  # Skip header
            parts = line.split("\t")
            if len(parts) >= 4 and parts[3] == "keep":
                try:
                    val = float(parts[1])
                    best = max(best, val)
                except ValueError:
                    pass
    return best if best > float("-inf") else 0.0


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("=" * 60)
    print("METEORA LP AUTORESEARCH — AUTONOMOUS AGENT LOOP")
    print("=" * 60)
    print(f"Model:     {LLM_MODEL}")
    print(f"Provider:  {LLM_BASE_URL}")
    print(f"Max runs:  {MAX_EXPERIMENTS}")
    print(f"Strategy:  {STRATEGY_FILE}")
    print()

    # Verify files exist
    if not STRATEGY_FILE.exists():
        print(f"ERROR: {STRATEGY_FILE} not found. Run project setup first.")
        sys.exit(1)

    llm = LLMClient()

    # Run baseline first
    print("=" * 60)
    print("EXPERIMENT 0: BASELINE")
    print("=" * 60)

    baseline_metrics = run_simulation()
    if baseline_metrics is None:
        print("ERROR: Baseline simulation failed. Fix simulate.py first.")
        sys.exit(1)

    print(f"  avg_net_yield:     {baseline_metrics['avg_net_yield']:.6f}")
    print(f"  avg_time_in_range: {baseline_metrics.get('avg_time_in_range', 0):.4f}")
    append_result(0, baseline_metrics, "keep", "baseline")

    best_yield = baseline_metrics["avg_net_yield"]
    best_strategy = read_file(STRATEGY_FILE)
    consecutive_failures = 0

    # Main experiment loop
    for exp_num in range(1, MAX_EXPERIMENTS + 1):
        print()
        print("=" * 60)
        print(f"EXPERIMENT {exp_num}/{MAX_EXPERIMENTS}")
        print(f"Best yield so far: {best_yield:.6f}")
        print("=" * 60)

        # Build context for LLM
        current_strategy = read_file(STRATEGY_FILE)
        results_history = get_results_history()
        top_lp_context = get_top_lp_context()

        user_message = f"""Here is the current state:

## Current strategy.py:
```python
{current_strategy}
```

## Experiment history (results.tsv):
```
{results_history}
```

## Best avg_net_yield so far: {best_yield:.6f}

{top_lp_context}

Propose ONE modification to strategy.py that you think will improve avg_net_yield.
Look at what worked and what didn't in the history. Try something new.
Return the COMPLETE modified strategy.py file.
"""

        # Ask LLM for new strategy
        print("  Asking LLM for new strategy...")
        try:
            response = llm.chat(SYSTEM_PROMPT, user_message)
        except Exception as e:
            print(f"  LLM ERROR: {e}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"  {MAX_CONSECUTIVE_FAILURES} consecutive failures. Stopping.")
                break
            time.sleep(10)  # Wait before retry
            continue

        # Extract code from response
        new_code = extract_code(response)
        if new_code is None:
            print("  Could not extract code from LLM response. Skipping.")
            append_result(exp_num, None, "crash", "LLM returned no code")
            consecutive_failures += 1
            continue

        # Extract description (first line or two of the response before code)
        description = response.split("```")[0].strip()[:100].replace("\t", " ").replace("\n", " ")
        if not description:
            description = "no description"

        print(f"  Hypothesis: {description}")
        print(f"  Full response:\n{response[:1000]}")

        # Backup and apply new strategy
        backup_strategy()
        write_file(STRATEGY_FILE, new_code)

        # Run simulation
        print("  Running simulation...")
        metrics = run_simulation()

        if metrics is None:
            # Crash — revert
            print("  CRASH — reverting to best strategy")
            write_file(STRATEGY_FILE, best_strategy)
            append_result(exp_num, None, "crash", description)
            consecutive_failures += 1
        else:
            new_yield = metrics["avg_net_yield"]
            print(f"  avg_net_yield: {new_yield:.6f} (best: {best_yield:.6f})")

            if new_yield > best_yield:
                # KEEP — improvement!
                improvement = new_yield - best_yield
                print(f"  ✓ KEEP — improved by {improvement:.6f}")
                best_yield = new_yield
                best_strategy = new_code
                append_result(exp_num, metrics, "keep", description)
                consecutive_failures = 0
            else:
                # DISCARD — no improvement
                print(f"  ✗ DISCARD — reverting")
                write_file(STRATEGY_FILE, best_strategy)
                append_result(exp_num, metrics, "discard", description)
                consecutive_failures = 0  # Not a failure, just not better

        # Check consecutive failures
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            print(f"\n{MAX_CONSECUTIVE_FAILURES} consecutive failures. Stopping.")
            break

        time.sleep(SLEEP_BETWEEN_EXPERIMENTS)

    # Summary
    print()
    print("=" * 60)
    print("SESSION COMPLETE")
    print("=" * 60)
    print(f"Experiments run: {exp_num}")
    print(f"Best avg_net_yield: {best_yield:.6f}")
    print(f"Results saved to: {RESULTS_FILE}")
    print(f"Best strategy in: {STRATEGY_FILE}")
    print()
    print("To review: cat results.tsv")
    print("To continue: python agent_loop.py")


if __name__ == "__main__":
    main()
