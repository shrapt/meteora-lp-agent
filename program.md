# Meteora LP Autoresearch

You are an autonomous LP strategy researcher. Your job: find the LP strategy
that maximizes net_yield on Meteora DLMM pools by BOTH self-experimentation
AND learning from what top LPs actually do on-chain.

## Setup

To set up a new experiment run:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar24`).
   The branch `autoresearch/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from master.
3. **Read the files**:
   - `CLAUDE.md` — project context
   - `prepare.py` — READ ONLY. Pool data, evaluation harness, constants.
   - `strategy.py` — THE file you modify. LP strategy logic.
   - `simulate.py` — How to run evaluations.
   - `src/scraper/top_lps.py` — How top LP data is fetched.
   - `cache/top_lps/` — Cached data from top LPs (ranges, rebalance patterns, fees)
4. **Refresh top LP data**: Run `uv run python -m src.scraper.top_lps` to fetch latest
   top LP positions and patterns. Review the output — this is your "mentor data".
5. **Verify simulation data**: Run `uv run prepare.py` to ensure pool data is cached.
6. **Initialize results.tsv**: Header row only.
7. **Confirm and go**.

## Two Learning Sources

### Source 1: Top LP Patterns (the mentor)
Before starting experiments, ALWAYS review the top LP data in cache/top_lps/.
This data tells you:
- What range widths top LPs use for each pool type
- How frequently they rebalance
- What bin distribution patterns they prefer (Spot, Curve, BidAsk)
- What percentage of capital they deploy vs keep in reserve
- Which pools they concentrate in and why (volume/fee ratio)

Use this as your STARTING HYPOTHESIS. Don't blindly copy — understand WHY they
do what they do, then try to improve on it.

### Source 2: Self-Experimentation (the autoresearch loop)
Modify strategy.py → run simulation → check if yield improved → keep/discard.

The combination is powerful: top LP data gives you a strong starting point,
and the autoresearch loop lets you iterate beyond what humans figured out.

## Experimentation

You run evaluations with: `uv run simulate.py > run.log 2>&1`

**What you CAN do:**
- Modify `strategy.py` — this is the ONLY file you edit during experiments.
- Change anything in strategy.py: range calculation, rebalance triggers,
  entry/exit logic, capital sizing, volatility adaptation, pool-specific
  behavior, bin distribution, any math.
- Reference data from cache/top_lps/ to inform your hypotheses.

**What you CANNOT do:**
- Modify `prepare.py` or `simulate.py`. They are read-only.
- Modify anything in `src/`. That's infrastructure.
- Install new packages beyond what's in pyproject.toml.
- Modify the evaluation harness.

**The goal: maximize avg_net_yield.**

The metric is averaged across all target pools. A good strategy should
work across different pool types (volatile, correlated, stable).

**Secondary goals (tiebreakers):**
1. Higher time_in_range (earning fees more often)
2. Lower max_drawdown (capital preservation)
3. Simpler code (fewer lines, less complexity)

**Simplicity criterion**: A small improvement that adds ugly complexity is
not worth it. Removing code for equal results = win. A 0.0001 yield
improvement from 30 lines of hacky code? Probably not worth it.

## Output format

After running `uv run simulate.py > run.log 2>&1`, extract metrics:
```
grep "^avg_net_yield:\|^avg_time_in_range:\|^avg_max_drawdown:" run.log
```

If grep is empty, the run crashed. Run `tail -n 50 run.log` to debug.

## Logging results

Log to `results.tsv` (tab-separated, NOT comma-separated):

```
commit	avg_net_yield	time_in_range	status	description
```

Status is one of: `keep`, `discard`, `crash`

Example:
```
commit	avg_net_yield	time_in_range	status	description
a1b2c3d	0.003200	0.7500	keep	baseline
b2c3d4e	0.004500	0.8200	keep	matched top LP range widths for SOL-USDC
c3d4e5f	0.005100	0.8400	keep	adaptive rebalance from top LP frequency patterns
d4e5f6g	0.004800	0.7900	discard	BidAsk distribution (top LPs prefer Spot for volatile)
```

## The experiment loop

LOOP FOREVER:

1. Check git state and results.tsv history
2. Review top LP patterns data if you haven't recently
3. Form a hypothesis — either from:
   a. Something you observed in top LP data
   b. A variation on what's working in results.tsv
   c. A new idea combining both
4. Modify `strategy.py` with the experiment
5. git commit with descriptive message
6. Run: `uv run simulate.py > run.log 2>&1`
7. Read results: `grep "^avg_net_yield:\|^avg_time_in_range:" run.log`
8. If grep empty → crash. `tail -n 50 run.log` to debug. Fix if simple, skip if fundamental.
9. Record in results.tsv
10. If avg_net_yield improved → keep (advance branch)
11. If equal or worse → discard (`git reset --hard HEAD~1`)
12. Go to step 1

## Research directions to explore

### From top LP analysis:
- Match the range widths that top LPs use for each pool type
- Replicate their rebalance frequency patterns
- Try their preferred bin distribution (Spot vs Curve vs BidAsk per pair type)
- Adopt their capital deployment ratios
- Identify what top LPs do differently during high vs low volatility periods

### Self-experimentation:
- Volatility-adaptive range widths (wider in high vol, tighter in low vol)
- Volume-weighted rebalancing (rebalance more when volume is high)
- Asymmetric ranges (wider above in uptrend, wider below in downtrend)
- Fee-rate-aware sizing (more capital to higher fee pools)
- IL prediction model (withdraw before large moves)
- Multi-timeframe analysis (short for rebalance, long for range)
- Mean reversion detection (tighter ranges in mean-reverting markets)
- Gas-cost-aware rebalancing (only if expected improvement > tx cost)

### Combining both:
- Start with top LP patterns as baseline, then optimize specific parameters
- Find where top LPs are suboptimal and beat them
- Adapt top LP patterns to different market conditions they didn't face

## Refreshing top LP data

Every ~50 experiments (or when you feel stuck), refresh the top LP data:
```
uv run python -m src.scraper.top_lps
```
Top LP strategies evolve over time — staying current matters.

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human.
Do NOT ask "should I keep going?" or "is this a good stopping point?".
The human might be asleep, or away from their computer and expects you
to continue working *indefinitely* until you are manually stopped.

If you run out of ideas:
1. Re-read the top LP data for new patterns you missed
2. Look at your results.tsv for near-misses worth revisiting
3. Try combining two previous improvements
4. Try more radical changes (different strategy type, completely new range logic)
5. Try simplifying — remove complexity for equal or better results

The loop runs until the human interrupts you, period.

Each simulation takes ~10 seconds. You can run ~500 experiments overnight.
That's your unfair advantage over every human LP.
