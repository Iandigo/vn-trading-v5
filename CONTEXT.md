# CONTEXT.md — VN Trading v5

> Last updated: 2026-03-20
> Purpose: Resume work seamlessly in a new Claude Code session on any machine.

---

## 1. Project Overview

### What This Is
A **quantitative trading framework for Vietnamese stocks (HOSE/VN30)** implementing Robert Carver's systematic trading methodology, adapted for Vietnam's market microstructure. It includes a full-stack dashboard (React + FastAPI) for running backtests, viewing results, tuning parameters, and validating statistical edge via permutation tests.

### Tech Stack
- **Backend**: Python 3.14, FastAPI (port 8000), pandas, numpy, yfinance, vnstock
- **Frontend**: React 18, TypeScript, Vite (port 5173), Recharts, Tailwind CSS, TanStack Query
- **Data**: yfinance (primary) + vnstock v3 (fallback), disk cache at `data/cache/`

### Architecture
```
React Dashboard (Vite :5173) ←→ FastAPI (:8000) ←→ Python Engine
                                    ↕
                              outputs/*.json/csv
```

The system is **single-user, single-backtest-at-a-time** (threading lock on global config module). Config overrides are saved to `outputs/config_override.json` and applied via dict mutation at runtime.

### Signal Pipeline (3 signals combined)
1. **MA200 Regime** (`signals/ma_regime.py`) — BULL/BEAR detection, weekly recalc, tau multiplier (1.0/0.5)
2. **Cross-Sectional Momentum** (`signals/cross_momentum.py`) — 63-day return ranking, top/bottom 40%, monthly rebalance
3. **IBS Mean Reversion** (`signals/ibs.py`) — (close-low)/(high-low), oversold<0.20/overbought>0.80, BULL-only, 5-day smoothed
4. **Combined** (`signals/combined.py`) — Weighted: 55% momentum + 15% IBS, FDM=1.20, clipped [-20, +20]

### Position Sizing (Carver Formula)
```
OptimalShares = (Capital x IDM x weight x (forecast/10) x tau) / (price x annual_vol)
```
With buffer zone: trade-to-edge rule (nearest 40% buffer boundary, not to optimal). Lot size: 100 shares (HOSE). Max position: 15%.

### VN Market Constraints
- **T+2.5 settlement**: Can't sell shares bought < 3 days ago
- **HOSE lot size**: 100 shares minimum
- **Transaction cost**: 0.25% per trade (brokerage + stamp duty)
- **High correlation**: ~0.6 between VN30 stocks (lower IDM values than global)
- **Daily limit**: 7% price movement cap (creates IBS mean-reversion edge)
- **Risk-free rate**: 5% (Vietnam fixed deposit rate, used in Sharpe calc)

---

## 2. Current State

### What Is Working
- Full React dashboard with 8 pages (Results, Trades, History, Permutation, Regime, Portfolio, Config, RunBacktest)
- Backtest engine with all signal generation, Carver sizing, buffer zones, T+3 settlement
- Stock quality filter (min volume 500K, min history 250 days)
- Config override system (dict-based params editable from UI, saved to disk)
- Data pipeline with yfinance + vnstock fallback + incremental disk cache
- Permutation test with parallel execution (ProcessPoolExecutor, 8 workers)
- Auto-cache detection (if 70%+ stocks cached, uses real data automatically)
- 31 cached data files in `data/cache/` (30 VN30 stocks + VNINDEX)

### Latest Backtest Results (on file)
Best run (30 stocks, 7 years, real data):
- CAGR 12.0%, Sharpe 0.323, Max DD -19.6%, Cost Drag 2.30%, 19.4 trades/month

Most recent run (15 stocks, 5 years):
- CAGR 3.2%, Sharpe -0.272, Trades/mo 7.8, Cost Drag 1.06%

### Latest Permutation Test (on file)
- 20 permutations, 3 years, 15 stocks
- Real Sharpe: 0.615, Perm Mean: -0.164, p-value: 0.05
- Verdict: WEAK / MARGINAL (need more permutations for significance)

### What Was Recently Fixed (This Session + Previous)
1. **Permutation test producing -1.16e17 Sharpe values** — Two root causes:
   - Date index mismatch: `index_prices` had timestamps (`07:00:00`), `close_matrix` had midnight → `.normalize()` fix
   - NaN first-row prices after shuffle: `cumprod() * NaN` → entire column NaN → flat equity → extreme Sharpe. Fixed with `bfill().iloc[0]`
2. **`compute_metrics` degenerate guard** — Near-zero std (1e-16 float noise) passed `> 0` check → Sharpe = -1e17. Threshold raised to `> 1e-8`, values clamped [-10, 10]
3. **Histogram chart not rendering** — XAxis was categorical (default for BarChart) but ReferenceLine used numeric x. Fixed with `type="number"` on XAxis
4. **Corrupted data warning** — Frontend now detects invalid permutation results and shows re-run prompt
5. **Progress bar** — Permutation page now shows real-time progress instead of just "Running..."

### Previously Fixed (Earlier Sessions)
6. **BEAR regime forced exits** — `cross_momentum.py` returned ALL zeros in BEAR → 2 full portfolio turnovers → 5%+ cost drag. Now keeps top-group rankings in BEAR.
7. **n_active bug** — Was computed inside per-stock loop → weights changed intra-day. Now computed once before loop.
8. **Vol lookback** — Hardcoded 20d → too noisy → excess trades. Now configurable, default 60d.
9. **Buffer zone** — 0.20 → 0.40 + trade-to-edge rule (biggest impact on reducing trades).
10. **IBS smoothing** — 5-day rolling mean on raw IBS prevents daily flip-flopping.
11. **Minimum trade value** — 5M VND threshold skips tiny trades.

---

## 3. Active Task

### Last Task Completed
**Fixing the permutation test page**: The histogram wasn't rendering and metrics showed extreme values (-1.16e17). Root causes were date index normalization and NaN handling in the shuffle logic. Both backend (`run_permutation_test.py`, `backtesting/metrics.py`) and frontend (`PermutationTest.tsx`) were fixed.

### Where We Left Off
All permutation fixes are complete and tested (10-perm and 20-perm runs both produce reasonable values). The user's original question was about **making permutations faster** — that hasn't been addressed yet beyond what's already in place (8-worker parallelism).

### Performance Optimization Opportunities Not Yet Implemented
- Current: `ProcessPoolExecutor` with 8 workers, but each permutation runs a **full backtest** (~365-line engine loop)
- The bottleneck is the per-permutation backtest, not the shuffle
- Possible speedups:
  - **Vectorized backtest** for permutations (numpy-only, skip logging/details)
  - **Reduce warmup** for permutation runs (currently 210 days skipped per run)
  - **Subsample dates** (e.g., weekly not daily) for permutation backtests
  - **C extension or numba JIT** for the inner loop
  - **Fewer permutations** (100 is standard; 1000 is overkill for initial validation)

---

## 4. Next Steps

### Immediate (If User Asks to Continue)
1. **Optimize permutation speed** — The user asked about this but we got sidetracked fixing bugs. Main approach: create a lightweight vectorized backtest path for permutations that skips trade logging, lot rounding, and settlement checks.

### Potential Follow-ups
2. **Improve Sharpe ratio** — Currently 0.323, target is 0.40+. Options: increase target_vol from 0.25 to 0.30, reduce to 15-20 stocks for higher conviction.
3. **Reduce cost drag** — Currently 2.30% (30-stock run), target <1%. Options: widen buffer further, reduce stock count.
4. **Run definitive permutation test** — Need 100+ permutations on real data to get tight p-value CI. Current 20-perm test has CI [0.00, 0.15] which is too wide.
5. **Production deployment** — `npm run build` in frontend/ then serve `dist/` from FastAPI. Not yet done.

### Open Questions
- Does the user want to optimize for the 30-stock or 15-stock universe going forward?
- Should permutation test use the same config as the latest backtest, or independent params?

---

## 5. Important Context & Gotchas

### Non-Obvious Things
- **Config module is global mutable state**. The backtest mutates `config.py` dicts in-place via overrides. A threading lock prevents concurrent backtests, and `_restore_config` cleans up after each run. If the server crashes mid-backtest, config may be left in a modified state (restart fixes this).
- **Scalar config values (FDM, FORECAST_CAP) cannot be changed from the UI** — they're module-level constants, not dict entries. Changing them requires editing `config.py` and restarting the server.
- **`api.py::VN30_FULL` is the authoritative stock list**, not `config.py::UNIVERSE`. The API patches `config.UNIVERSE` before each run based on user selection from VN30_FULL.
- **Regime updates weekly (every 5 days), not daily** — this was a critical v4 bug that caused 5%+ cost drag from regime whipsaw. Do not change to daily.
- **Cross-momentum rebalances monthly (every 21 days)** — reducing this increases cost drag substantially.
- **Windows console encoding**: Use `PYTHONIOENCODING=utf-8` when running Python scripts that print Unicode characters (like `→`), or they'll crash with `UnicodeEncodeError` on cp1252.
- **yfinance rate limits**: Fetching all 30 stocks + index can trigger throttling. The fetcher uses 365-day chunks with vnstock fallback per chunk.
- **vnstock v3 API**: Uses `vnstock.explorer.kbs.quote.Quote` class, not the older v2 API. Check import path if vnstock is updated.

### Data Cache
- 31 CSV files in `data/cache/` (30 VN30 stocks + VNINDEX)
- Cache is incremental — fetcher only downloads missing date ranges
- If cache exists for 70%+ of universe, `run_backtest.py` auto-detects and uses real data
- Cache files use `TICKER.replace('.', '_')` naming: e.g., `ACB_VN.csv` for `ACB.VN`

### Known Pre-existing Issues
- **Sidebar TypeScript errors**: `lucide-react` icon types don't perfectly match the `FC<{size?, className?}>` type in `Sidebar.tsx`. Cosmetic only — build succeeds, runtime is fine.
- **dashboard.py (Streamlit)**: The original 34K-line Streamlit dashboard is still in the project root. It's superseded by the React frontend but not deleted. Can be ignored.
- **Sharpe below target**: Best result is 0.323 vs 0.40 target. Annual vol is 8.3% vs 15-20% target — the strategy is under-invested. Raising target_vol or reducing stock count would help.

### File Locations Quick Reference
| What | Where |
|------|-------|
| All strategy parameters | `config.py` |
| FastAPI backend (all endpoints) | `api.py` |
| Backtest engine | `backtesting/engine.py` |
| Performance metrics | `backtesting/metrics.py` |
| Signal: regime | `signals/ma_regime.py` |
| Signal: momentum | `signals/cross_momentum.py` |
| Signal: IBS | `signals/ibs.py` |
| Signal: combiner | `signals/combined.py` |
| Position sizing | `sizing/position.py` |
| Data fetcher + cache | `data/fetcher.py` |
| Backtest runner | `run_backtest.py` |
| Permutation runner | `run_permutation_test.py` |
| Frontend API client | `frontend/src/api/client.ts` |
| Frontend pages | `frontend/src/pages/*.tsx` |
| Results/outputs | `outputs/` |
| Cached market data | `data/cache/` |

---

## 6. How to Resume

### Environment Setup
```bash
# Python backend
cd c:\Users\nguye\Downloads\vn_trading_v5\vn_trading_v5
pip install -r requirements.txt
pip install vnstock

# Start API server
PYTHONIOENCODING=utf-8 uvicorn api:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```
Dashboard at http://localhost:5173, API at http://localhost:8000/docs

### Version Info
- Python 3.14.3, Node 24.14.0
- FastAPI 0.135.1, pandas 2.3.3, numpy 2.4.3, yfinance 1.2.0, vnstock 3.5.0
- React 18.3.1, Vite 5.4.8, TypeScript 5.5.3, Recharts 2.12.7

### Quick Test (Verify Everything Works)
```bash
# Run a fast backtest with cached data (auto-detected)
PYTHONIOENCODING=utf-8 python run_backtest.py --years 3 --n 15

# Run a small permutation test
PYTHONIOENCODING=utf-8 python run_permutation_test.py --n_perm 10 --years 3 --n_stocks 10
```

### First Message to Continue
> "I'm resuming work on VN Trading v5. Read CONTEXT.md for full project state. The last session fixed permutation test bugs (NaN shuffle data, histogram not rendering). The user originally asked about making permutations faster — that optimization hasn't been done yet. The strategy's Sharpe (0.323) and cost drag (2.30%) are still below targets (0.40 and 1% respectively)."

---

## 7. Git Status

**This is NOT a git repository.** There is no `.git` directory — all files are unversioned. Changes are tracked only via this document and the Claude Code memory system at `~/.claude/projects/`.

### File Inventory (not exhaustive)
```
Core Python:     config.py, api.py, main.py, run_backtest.py, run_permutation_test.py, dashboard.py
Modules:         backtesting/{engine,metrics}.py, signals/{ma_regime,cross_momentum,ibs,combined}.py
                 sizing/position.py, data/fetcher.py, portfolio/tracker.py
Frontend:        frontend/src/ (8 pages, 2 components, 1 API client, types, App, main)
Outputs:         16 equity CSVs, trade logs, backtest_history.json, permutation_results.json
Cache:           31 CSV files in data/cache/ (30 VN30 + VNINDEX, ~7 years of daily OHLCV)
```

### Uncommitted Changes (N/A — no git)
All files are in their current working state. No staged/unstaged distinction.

### Recommendation
Consider initializing git for this project:
```bash
cd c:\Users\nguye\Downloads\vn_trading_v5\vn_trading_v5
git init
echo -e "data/cache/\noutputs/\nfrontend/node_modules/\nfrontend/dist/\n__pycache__/\n*.pyc\n.env" > .gitignore
git add -A
git commit -m "Initial commit: VN Trading v5 with React dashboard"
```
