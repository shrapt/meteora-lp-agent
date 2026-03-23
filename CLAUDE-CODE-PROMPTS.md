# What to Say to Claude Code Cloud

## Key Insights from the Ecosystem (READ FIRST)

Someone already built a similar system and shared their learnings publicly.
Here's what they learned the hard way — so you don't have to:

### Wallet Scoring is THE Hard Problem
- v1 scoring was useless: "a wallet with 1 winning trade scored 100"
- v2 uses gate multipliers: track_record × recency × sample_size
- Minimum 7+ days of consistent LPing to even qualify
- 88 wallets passed v1 filters. Only 33 survived v2. Filtering > finding.
- 7 weighted scoring factors (still being improved)

### Their Data Pipeline (runs every 4 hours):
1. **Dune Analytics** → finds hot pools and fresh wallets
2. **LP Agent (lpagent.io)** → scans top LPers and their strategies  
3. **Scoring engine** → ranks wallets on 7 weighted factors
4. **Claude agent** → reviews data, decides which strategies to follow

### Tools in the Ecosystem:
- **TrackLP (tracklp.com)** — find top LPers per pool, ranked by performance, 7-day history
- **LP Agent (lpagent.io)** — AI LP automation, Smart LP copy, position suggestions
- **Dune Analytics** — SQL queries for on-chain Meteora data
- **GeekLad Profit Analysis** (geeklad.github.io/meteora-profit-analysis) — P&L per wallet
- **Hummingbot lp-agent skill** — open source LP rebalancer with Meteora integration
- **Cleopetra** (github.com/umang-veerma/cleopetra) — open source Telegram LP bot
- **Helius** — premium Solana RPC with enhanced tx parsing
- **Birdeye API** — token prices and pool analytics

### Their Key Lesson:
"The wallets it chose are way too conservative for the balance I gave it"
→ Scoring must match RISK APPETITE, not just raw performance

---

## Your Initial Prompt (Copy-paste this EXACTLY)

---

**PROMPT 1 — Project Setup (say this first):**

```
I'm building an autonomous Meteora DLMM LP agent that learns to optimize 
liquidity provision strategies, inspired by karpathy/autoresearch. 

The agent has two learning sources:
1. Self-experimentation: modify strategy → simulate → keep/discard (autoresearch loop)
2. Learning from top LPs: scrape what the best Meteora LPs are doing and learn from their patterns

IMPORTANT CONTEXT from someone who already built this:
- Wallet scoring is THE hardest part. v1 was useless (1-trade wallets scored 100)
- Need gate multipliers: track_record × recency × sample_size 
- Minimum 7+ days consistent LPing to qualify
- 88 wallets passed basic filter, only 33 survived proper scoring
- Must score on: consistency, activity patterns, capital efficiency, win rate stability, fee yield
- Their data pipeline: Dune → LP Agent/TrackLP → Scoring → Agent decides
- Key lesson: scored wallets were too conservative — need risk appetite matching

Here's the architecture:

## Project Structure
meteora-lp-agent/
├── CLAUDE.md                    
├── program.md                   # Autoresearch-style autonomous loop instructions
├── pyproject.toml              
├── .env.example                
├── prepare.py                   # READ-ONLY: data prep, eval harness, top LP scraper
├── strategy.py                  # THE FILE YOU MODIFY: LP strategy logic
├── simulate.py                  # Run evaluation
├── results.tsv                  # Experiment log
├── src/
│   ├── scraper/
│   │   ├── top_lps.py           # Fetch top LP positions from Meteora API + Shyft
│   │   ├── patterns.py          # Extract patterns from top LP behavior
│   │   ├── tracklp.py           # Scrape tracklp.com for top LPers per pool
│   │   └── cache.py             # Cache scraped data locally
│   ├── scoring/                 # THE HARDEST PART — wallet quality scoring
│   │   ├── scorer.py            # Main wallet scoring engine (v2+ with gate multipliers)
│   │   ├── factors.py           # Individual scoring factors (7 factors)
│   │   ├── gates.py             # Gate multipliers: track_record × recency × sample_size
│   │   └── risk_profile.py      # Risk appetite matching (conservative vs aggressive)
│   ├── meteora/
│   │   ├── client.py            # Meteora DLMM on-chain interaction (for live mode)
│   │   └── types.py             # Pydantic models
│   ├── data/
│   │   ├── feeds.py             # Price feeds (Birdeye, Jupiter, Pyth)
│   │   ├── dune.py              # Dune Analytics queries for hot pools & wallets
│   │   └── store.py             # SQLite storage
│   └── common/
│       ├── config.py           
│       └── logger.py           
├── cache/                       
│   ├── pools/                   
│   ├── prices/                  
│   ├── top_lps/                 # Cached top LP data
│   └── wallet_scores/           # Cached wallet scoring results
└── tests/

## APIs available for top LP data:

1. Meteora DLMM API (no auth needed, 30 RPS limit):
   - GET https://dlmm-api.meteora.ag/pair/all — all pools with volume, TVL, fees
   - GET https://dlmm-api.meteora.ag/pair/{pair_address} — specific pool details
   - GET https://dlmm-api.meteora.ag/pair/{pair_address}/positions_lock — positions in pool
   - GET https://dlmm-api.meteora.ag/position/{position_address} — position details (bins, ranges)
   - GET https://dlmm-api.meteora.ag/position/{position_address}/claim_fees — fee claims
   - GET https://dlmm-api.meteora.ag/position/{position_address}/deposits — deposit history
   - GET https://dlmm-api.meteora.ag/position/{position_address}/withdraws — withdrawal history
   - GET https://dlmm-api.meteora.ag/wallet/{wallet_address}/{pair_address}/earning — wallet earnings per pool

2. Shyft GraphQL (needs API key) for on-chain position data:
   - meteora_dlmm_PositionV2: owner, upperBinId, lowerBinId, totalClaimedFeeXAmount, totalClaimedFeeYAmount, lbPair
   - meteora_dlmm_LbPair: activeId, tokenXMint, tokenYMint, binStep, reserveX, reserveY
   
3. Solana RPC: direct on-chain reads of position accounts

## The "Learn from Top LPs" flow:

1. Fetch top pools by volume/fees from Meteora API
2. For each top pool, get all positions 
3. SCORE WALLETS (this is the hardest part — see scoring system below)
4. Extract patterns from TOP SCORED wallets only
5. Feed patterns into prepare.py as "mentor data" for strategy.py

## Wallet Scoring System (CRITICAL — build this carefully):

The scoring engine must filter out noise. Key learnings from someone who built this:
- v1 was useless: a wallet with 1 winning trade scored 100
- Must use GATE MULTIPLIERS to prevent thin-data wallets from ranking high

### Gate Multipliers (all must pass minimum threshold):
- track_record_gate: wallet must have 7+ days of LP activity (0 if < 7 days)
- recency_gate: must have activity in last 14 days (decays to 0 over 30 days)  
- sample_size_gate: must have 5+ completed positions (0 if < 5)

### 7 Scoring Factors (weighted, normalized 0-100):
1. Win rate consistency (weight: 0.20) — % of positions that were profitable, smoothed
2. Fee yield efficiency (weight: 0.20) — fees earned / capital deployed / time
3. Capital efficiency (weight: 0.15) — how tight ranges are vs how much they earn
4. Activity pattern quality (weight: 0.15) — regular rebalancing vs panic moves
5. Drawdown control (weight: 0.10) — worst IL periods vs recovery  
6. Track record length (weight: 0.10) — longer = more reliable signal
7. Pool diversity (weight: 0.10) — spreads across pool types vs single-pool

### Final Score:
wallet_score = (weighted_sum_of_7_factors) × track_record_gate × recency_gate × sample_size_gate

### Risk Appetite Matching:
After scoring, classify wallets into risk profiles:
- Conservative: tight ranges, stable pairs, low rebalance freq
- Moderate: mixed ranges, both volatile and stable pairs  
- Aggressive: wide ranges on volatile pairs, frequent rebalancing, higher capital at risk
Match the agent's risk profile to the right wallet group.

## Additional Data Sources for Wallet Discovery:
- TrackLP (tracklp.com): search any pool, get top LPers ranked by performance
- Dune Analytics: SQL queries to find hot pools and active wallets
- GeekLad tool (geeklad.github.io/meteora-profit-analysis): profit analysis per wallet
- Meteora API /wallet/{address}/{pair}/earning: earnings data per wallet

## Key design principle: 
EXECUTION QUALITY FIRST (learned from failed Polymarket bot with liquidity issues)

Please start by:
1. Creating the full project scaffold
2. Building the wallet scoring system FIRST (src/scoring/) — this is the hardest part
3. Building prepare.py with simulation AND top LP data fetching
4. Building the top LP scraper with wallet scoring integration
5. Building baseline strategy.py
6. Building simulate.py
7. Writing CLAUDE.md and program.md for the autonomous loop
8. Setting up pyproject.toml

Reference tools to study: 
- hummingbot lp-agent skill (open source, has Meteora pool scripts)
- cleopetra (github.com/umang-veerma/cleopetra, open source LP bot)
- GeekLad profit analysis (github.com/GeekLad/meteora-profit-analysis)

Use Python 3.12+, numpy, httpx, pydantic. No heavy frameworks.
Start building now — create all files.
```

---

**PROMPT 2 — Start the Autonomous Loop (say this after project is built):**

```
Read program.md and let's kick off a new experiment! Let's do the setup first.
```

---

**PROMPT 3 — If you need to restart or continue:**

```
Read program.md. Check git log and results.tsv for where we left off. 
Continue the experiment loop from where we stopped. Never stop.
```

---

## program.md (Put this in the project root)

Below is the complete program.md that tells Claude Code how to run autonomously.
This is the "skill" file — the most important file for the autonomous loop.

---

```markdown
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
```

---

## CLAUDE.md (Put this in the project root)

```markdown
# Meteora LP Agent — Autoresearch

## What this is
An autonomous Meteora DLMM LP strategy optimizer. Uses karpathy/autoresearch pattern:
modify strategy → evaluate → keep/discard → repeat forever.

Unique addition: the agent also LEARNS FROM TOP LPs by scraping their on-chain
positions, range settings, rebalance patterns, and fee performance.

## How it works
- `prepare.py` is READ-ONLY. Contains evaluation harness and pool data.
- `strategy.py` is the ONLY file the agent modifies. Contains LP strategy.
- `simulate.py` runs the evaluation. Key metric: avg_net_yield (higher = better).
- `src/scraper/top_lps.py` fetches and analyzes top LP positions from Meteora API.
- `cache/top_lps/` contains extracted patterns from top LPs.
- `program.md` has the full autonomous experiment loop instructions.

## Quick commands
- `uv run prepare.py` — prepare simulation data
- `uv run python -m src.scraper.top_lps` — refresh top LP data
- `uv run simulate.py` — run strategy evaluation
- `uv run simulate.py > run.log 2>&1` — run and capture output for experiment loop

## Tech stack
- Python 3.12+, numpy, httpx, pydantic
- Meteora DLMM API: https://dlmm-api.meteora.ag/ (30 RPS, no auth)
- Shyft GraphQL: for on-chain position data (needs SHYFT_API_KEY)
- Solana RPC: for direct reads (needs SOLANA_RPC_URL)

## API endpoints we use

### Meteora DLMM API (base: https://dlmm-api.meteora.ag)
- GET /pair/all — all pools
- GET /pair/{address} — pool details
- GET /pair/{address}/positions_lock — positions in pool
- GET /position/{address} — position details (bin range, etc)
- GET /position/{address}/claim_fees — fee history
- GET /position/{address}/deposits — deposit history  
- GET /position/{address}/withdraws — withdrawal history
- GET /wallet/{wallet}/{pair}/earning — earnings per wallet per pool

### Shyft GraphQL (base: https://programs.shyft.to/v0/graphql)
- meteora_dlmm_PositionV2: owner, bins, fees claimed
- meteora_dlmm_LbPair: pool config, active bin, reserves

## Key design principle
EXECUTION QUALITY FIRST. Born from a failed Polymarket bot with liquidity issues.
Every strategy decision considers: tx costs, rebalance frequency limits, slippage.

## Testing
- pytest tests/
- All strategy changes must pass simulation without crashing

## Project origin
Inspired by karpathy/autoresearch applied to DeFi LP optimization instead of
LLM training research. See program.md for the full autonomous loop.
```

---

## Conversation Flow — What to Say at Each Stage

### Stage 1: Build
```
[Paste PROMPT 1 above]
```
Claude Code will build all the files. This takes 5-10 minutes.

### Stage 2: Review
After it builds, say:
```
Show me the key files: strategy.py, prepare.py, simulate.py, 
and src/scraper/top_lps.py. Let me review before we start the loop.
```

### Stage 3: Test
```
Run `uv run prepare.py` to check data prep works.
Then run `uv run simulate.py` and show me the baseline results.
```

### Stage 4: Fetch top LP data
```
Run `uv run python -m src.scraper.top_lps` to fetch current top LP data.
Show me what patterns you found — what ranges, rebalance frequency, 
and strategy types do the top LPs use?
```

### Stage 5: Start the autonomous loop
```
Read program.md and let's kick off a new experiment! Do the setup first.
```
Then Claude Code will run autonomously — **you can walk away and sleep.**

### Stage 6: Check results (next morning)
```
Show me results.tsv and summarize what you learned overnight.
What was the best avg_net_yield achieved? What strategy changes worked?
What patterns from top LPs proved most useful?
```

### Stage 7: Iterate (ongoing)
```
Refresh the top LP data with `uv run python -m src.scraper.top_lps`,
then continue the experiment loop. Keep going.
```

---

## Environment Variables You'll Need

```bash
# .env
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com   # or Helius/Quicknode
SHYFT_API_KEY=your_shyft_key_here                     # for GraphQL position data
HELIUS_API_KEY=your_helius_key_here                    # enhanced Solana RPC
BIRDEYE_API_KEY=your_birdeye_key_here                  # token prices & analytics
DUNE_API_KEY=your_dune_key_here                        # wallet/pool discovery queries
# METEORA_API needs no key — just rate limited to 30 RPS
# TRACKLP needs no key — web scraping

# Agent config
RISK_PROFILE=moderate                                  # conservative | moderate | aggressive
MIN_WALLET_SCORE=60                                    # minimum score to learn from a wallet
```

### Free tier API keys:
- **Shyft**: https://shyft.to (free tier works)
- **Helius**: https://www.helius.dev (free tier = 100K credits/month)
- **Birdeye**: https://birdeye.so (free tier for basic price data)
- **Dune**: https://dune.com (free tier = 2500 API credits/month)
- **Meteora DLMM API**: No key needed, 30 requests/second limit

---

## Tips for Running from China

1. **Claude Code Cloud** — if available, this is simplest. Just open it and paste the prompts.

2. **GitHub Codespaces** — create a Codespace, install Claude Code:
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude
   ```
   Then paste the prompts. Codespace is a full Linux VM in the cloud.

3. **Use a VPN + local Claude Code** as fallback.

4. **RPC considerations**: Some Solana RPCs may be slow from China. 
   Use Helius or Quicknode which have global CDN endpoints.
