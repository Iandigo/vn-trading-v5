# CONTEXT.md — VN Trading v5

> Last updated: 2026-03-24
> Purpose: Resume work seamlessly in a new Claude Code session on any machine.

---

## 1. Project Overview

### What This Is
A **quantitative trading framework for Vietnamese stocks (HOSE/VN30)** with two independent strategy engines:

1. **Carver Engine** — Robert Carver's systematic methodology: continuous forecasts, vol-based position sizing, buffer zones, 3-signal combination (MA regime + cross-momentum + IBS)
2. **Martin Luk Engine** — Swing breakout strategy: binary entry/exit, EMA alignment scanner, fixed-risk sizing, R-multiple partial exits, market health breadth filter

Both share data infrastructure, metrics, and the React+FastAPI dashboard.

### Tech Stack
- **Backend**: Python 3.14, FastAPI (port 8000), pandas, numpy, yfinance, vnstock
- **Frontend**: React 18, TypeScript, Vite (port 5173), Recharts, Tailwind CSS, TanStack Query
- **Data**: yfinance (primary) + vnstock v3 (fallback), disk cache at `data/cache/`

### Architecture
```
React Dashboard (Vite :5173) ←→ FastAPI (:8000) ←→ Python Engines
                                    ↕                   ↕
                              outputs/*.json/csv    data/cache/
```

The system is **single-user, single-backtest-at-a-time** (threading lock on global config module). Config overrides are saved to `outputs/config_override.json` and applied via dict mutation at runtime.

---

## 2. Strategy Engines

### Strategy 1: Carver (Systematic Forecasting)

**Signal Pipeline** (3 signals combined):
1. **MA200 Regime** (`signals/ma_regime.py`) — BULL/BEAR detection, weekly recalc, tau multiplier (1.0/0.5)
2. **Cross-Sectional Momentum** (`signals/cross_momentum.py`) — 63-day return ranking, top/bottom 40%, monthly rebalance
3. **IBS Mean Reversion** (`signals/ibs.py`) — (close-low)/(high-low), oversold<0.20/overbought>0.80, BULL-only, 5-day smoothed
4. **Combined** (`signals/combined.py`) — Weighted: 55% momentum + 15% IBS, FDM=1.20, clipped [-20, +20]

**Position Sizing** (Carver Formula):
```
OptimalShares = (Capital x IDM x weight x (forecast/10) x tau) / (price x annual_vol)
```
Buffer zone: trade-to-edge rule (nearest 40% buffer boundary, not to optimal). Lot size: 100 shares. Max position: 15%.

**Engine**: `backtesting/engine.py` | **Sizing**: `sizing/position.py`

### Strategy 2: Martin Luk (Swing Breakout)

**Entry Conditions** — All require stock classified as LEAD (EMA 9 > 21 > 50) + ADR > 2.5%:
1. **Prior High Breakout**: close > yesterday's high (most common)
2. **Inside Day Breakout**: yesterday was inside day, today breaks above
3. **EMA Convergence Breakout**: tight EMA spread (<1.5%) + close above all EMAs

**Stop Loss**: Low of breakout day, capped at half-ADR distance, absolute max 5% below entry. Min distance enforced at max(half-ADR, 1%) to prevent absurdly small R-values.

**Position Sizing** (Fixed Risk):
```
Shares = (Equity × 0.75% × risk_multiplier) / (entry_price - stop_price)
```
- Risk halved to 0.375% during drawdowns (>10% from peak)
- Max 10% of equity per stock, 80% total exposure
- Market health multiplier: STRONG=1.0x, CAUTIOUS=0.5x, WEAK=0x (no new entries)

**Exit Rules** (R-multiple partial exits):
1. Stop loss at initial stop → full position exit
2. At 3R profit → sell 25%, move stop to breakeven
3. At 5R profit → sell 25%, trail stop with EMA(9)
4. Remaining 50% → trail with EMA(9), full exit below EMA(21)
5. R-multiples capped at ±20R as safety net against bad data

**Market Health** (breadth indicator, not just MA200):
- STRONG: ≥50% of universe are LEAD → full risk
- CAUTIOUS: 27-49% LEAD → half risk
- WEAK: <27% LEAD → no new entries

**Engine**: `strategies/martin_luk.py` | **Signals**: `signals/ema_scanner.py`, `signals/breakout_detector.py`, `signals/market_health.py` | **Sizing**: `sizing/fixed_risk.py`

---

## 3. Dashboard Pages (React Frontend)

9 pages, Scanner is default landing page:

| Page | Description |
|------|-------------|
| **Scanner** (default) | Live VN30 scan: EMA classification, breakout signals, market health banner, position allocation summary, quick-buy button |
| **Portfolio** | Holdings table with stop/R-value, allocation pie chart, trade recording form (BUY/SELL with strategy tag), trade log with delete |
| **Results** | Equity curve, drawdown chart, Carver scorecard + Sharpe, annual returns bar chart, run selector |
| **Trades** | Volume by ticker, trades/month chart, win/loss breakdown, full trade table with date range filter + pagination |
| **History** | Comparison table of all runs (with strategy column), delete runs, clear all |
| **Validation Suite** | 3-tab strategy validation: In-Sample Permutation, Walk-Forward Test (OOS equity + per-window table), WF Permutation Test |
| **Regime** | Live VNIndex vs MA200, signal weights, current regime status |
| **Config** | Editable config overrides (all dict params), anti-overfitting checklist |
| **Run Backtest** | Select stocks (1-30 VN30), years, capital, data source, strategy (Carver/Luk) from UI |

---

## 4. Current State

### What Is Working
- Full React dashboard with 9 pages (Scanner added as default landing)
- Two backtest engines: Carver (continuous forecasts) and Martin Luk (swing breakout)
- **4-step strategy validation system** (Timothy Masters methodology):
  - Step 1: In-Sample Excellence (regular backtest)
  - Step 2: In-Sample Monte Carlo Permutation Test
  - Step 3: Walk-Forward Test with rolling parameter re-optimisation
  - Step 4: Walk-Forward Permutation Test (WF OOS metric vs shuffled baselines)
- Strategy selector on backtest, permutation test, and history pages
- Live scanner with breakout detection, market health, position sizing, quick-buy
- Carver signals page with manual Load button for capital changes
- Portfolio page with trade recording, holdings management, position details for Luk trades
- Data pipeline with spike detection (>50% daily change = corruption from yfinance auto_adjust)
- VNINDEX scale auto-detection and rescaling (when values are 1000x too low)
- Permutation test with parallel execution (ProcessPoolExecutor, 8 workers) + config override propagation to workers
- 31 cached data files in `data/cache/` (30 VN30 stocks + VNINDEX)

### Walk-Forward Validation System
- **`run_walk_forward.py`**: Implements Steps 3 & 4. Grid-search parameter optimisation on training windows (≤27 combos), OOS testing, stitched OOS equity curve, walk-forward efficiency metric.
- **Parameter grids**: Carver: `target_vol × buffer_fraction × lookback_days`. Martin Luk: `ema_fast × risk_per_trade_pct × max_stop_pct`.
- **WF Permutation**: Conservative hybrid — real metric is WF OOS (penalised), compared against shuffled single backtests (in-sample). Keeps runtime practical (~same as regular permutation test).
- **API endpoints**: `GET/POST /api/walk-forward`, `GET/POST /api/wf-permutation`.
- **Frontend**: 3-tab Strategy Validation Suite in `PermutationTest.tsx` (In-Sample Perm, Walk-Forward, WF Permutation).

### Data Quality Fixes (Latest)
1. **Price spike detection** (`data/fetcher.py`): VN stocks have ±7% daily limit. Any >50% change flagged as yfinance auto_adjust corruption. Isolated spikes removed; level shifts truncate all subsequent data.
2. **VNINDEX scale fix** (`data/fetcher.py`): Auto-detects when index values are <100 (should be >1000) and rescales by 1000x. Corrected data saved back to cache.
3. **R-value minimum distance** (`signals/breakout_detector.py`): Stop must be at least max(half-ADR, 1% of entry) below entry price. Prevents tiny R-values on narrow-range breakout days that produced absurdly large position sizes.
4. **R-multiple cap** (`strategies/martin_luk.py`): Capped at ±20R per trade. Anything higher indicates remaining data corruption.
5. **Cost drag formula** (`strategies/martin_luk.py`): Uses average equity instead of initial capital, so cost drag stays meaningful as equity grows.

### Data Pipeline Fixes (v5.1)
11. **Timestamp normalization** (`data/fetcher.py`): `_clean_ohlcv()` now normalizes all timestamps to midnight and deduplicates. Different data sources return 00:00 vs 07:00 for the same trading day, causing close_matrix misalignment and all-NEUTRAL Carver signals.
12. **Duplicate index in permutation test** (`run_permutation_test.py`): Added deduplication after index normalization to prevent `ValueError: cannot reindex on axis with duplicate labels`.
13. **Config propagation to permutation workers** (`run_permutation_test.py`): `ProcessPoolExecutor` workers now receive a config snapshot. Previously workers used default config.py values, making the permutation comparison invalid (real strategy used overrides, shuffled runs used defaults).

### Previously Fixed (Carver Engine)
6. **BEAR regime forced exits** — `cross_momentum.py` returned ALL zeros in BEAR → 2 full portfolio turnovers → 5%+ cost drag. Now keeps top-group rankings in BEAR.
7. **n_active bug** — Was computed inside per-stock loop → weights changed intra-day. Now computed once before loop.
8. **Vol lookback** — Hardcoded 20d → too noisy. Now configurable, default 60d.
9. **Buffer zone** — 0.20 → 0.25 (configurable via UI).
10. **Permutation test NaN/histogram bugs** — Date index normalization, NaN handling in shuffle, histogram XAxis type fix.

---

## 5. Important Context & Gotchas

### Non-Obvious Things
- **Config module is global mutable state**. The backtest mutates `config.py` dicts in-place via overrides. A threading lock prevents concurrent backtests, and `_restore_config` cleans up after each run. If the server crashes mid-backtest, config may be left in a modified state (restart fixes this). **Permutation/WF workers** (subprocess) receive a config snapshot via args since `ProcessPoolExecutor` spawns fresh processes with default config.
- **Scalar config values (FDM, FORECAST_CAP) cannot be changed from the UI** — they're module-level constants, not dict entries. Changing them requires editing `config.py` and restarting the server.
- **`api.py::VN30_FULL` is the authoritative stock list**, not `config.py::UNIVERSE`. The API patches `config.UNIVERSE` before each run based on user selection from VN30_FULL.
- **Regime updates weekly (every 5 days), not daily** — this was a critical v4 bug that caused 5%+ cost drag from regime whipsaw. Do not change to daily.
- **Cross-momentum rebalances monthly (every 21 days)** — reducing this increases cost drag substantially.
- **Windows console encoding**: Use `PYTHONIOENCODING=utf-8` when running Python scripts that print Unicode characters, or they'll crash with `UnicodeEncodeError` on cp1252.
- **yfinance rate limits**: Fetching all 30 stocks + index can trigger throttling. The fetcher uses 365-day chunks with vnstock fallback per chunk.
- **vnstock v3 API**: Uses `vnstock.explorer.kbs.quote.Quote` class, not the older v2 API.
- **Portfolio data is stored in `outputs/portfolio.json`** — holdings track shares, avg_price, stop_price, r_value, pattern, strategy, entry_date. Trades are appended to a log array.
- **Scanner uses cached data** — fetches from the same `data/cache/` as backtests. If cache is stale, scanner shows stale signals. Refresh forces a re-fetch.

### Data Cache
- 31 CSV files in `data/cache/` (30 VN30 stocks + VNINDEX)
- Cache is incremental — fetcher only downloads missing date ranges
- If cache exists for 70%+ of universe, `run_backtest.py` auto-detects and uses real data
- Cache files use `TICKER.replace('.', '_')` naming: e.g., `ACB_VN.csv` for `ACB.VN`
- Corrupted prices (>50% daily change) are now auto-detected and removed on fetch

### Known Pre-existing Issues
- **Sidebar TypeScript errors**: `lucide-react` icon types don't perfectly match the `FC<{size?, className?}>` type in `Sidebar.tsx`. Cosmetic only — build succeeds, runtime is fine.
- **dashboard.py (Streamlit)**: The original 34K-line Streamlit dashboard is still in the project root. It's superseded by the React frontend but not deleted. Can be ignored.

---

## 6. File Locations Quick Reference

| What | Where |
|------|-------|
| All strategy parameters | `config.py` |
| FastAPI backend (all endpoints) | `api.py` |
| **Carver engine** | `backtesting/engine.py` |
| **Martin Luk engine** | `strategies/martin_luk.py` |
| Performance metrics | `backtesting/metrics.py` |
| Signal: regime | `signals/ma_regime.py` |
| Signal: momentum | `signals/cross_momentum.py` |
| Signal: IBS | `signals/ibs.py` |
| Signal: combiner | `signals/combined.py` |
| Signal: EMA scanner (Luk) | `signals/ema_scanner.py` |
| Signal: breakout detector (Luk) | `signals/breakout_detector.py` |
| Signal: market health (Luk) | `signals/market_health.py` |
| Position sizing: Carver | `sizing/position.py` |
| Position sizing: fixed risk (Luk) | `sizing/fixed_risk.py` |
| Data fetcher + cache | `data/fetcher.py` |
| Backtest runner | `run_backtest.py` |
| Permutation runner | `run_permutation_test.py` |
| Walk-forward runner | `run_walk_forward.py` |
| Frontend API client | `frontend/src/api/client.ts` |
| Frontend types | `frontend/src/types.ts` |
| Frontend pages | `frontend/src/pages/*.tsx` (9 pages) |
| VND formatter | `frontend/src/utils/format.ts` |
| Results/outputs | `outputs/` |
| Cached market data | `data/cache/` |

---

## 7. How to Resume

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
# Run a fast Carver backtest with cached data
PYTHONIOENCODING=utf-8 python run_backtest.py --years 3 --n 15

# Run a Martin Luk backtest
PYTHONIOENCODING=utf-8 python run_backtest.py --years 3 --n 15 --strategy martin_luk

# Run a small permutation test
PYTHONIOENCODING=utf-8 python run_permutation_test.py --n_perm 10 --years 3 --n_stocks 10
```

---

## 8. Git Status

**This is a git repository** with remote at `https://github.com/Iandigo/vn-trading-v5`.

### Recent Commits
```
<pending>  Add walk-forward validation, fix data timestamp normalization, fix config propagation to workers
6d04f8c  Add Martin Luk swing strategy, live scanner, portfolio tracking, and fix data corruption
e864724  Initial commit: VN Trading v5 — Vietnamese stock trading framework
```

### File Inventory
```
Core Python:     config.py, api.py, main.py, run_backtest.py, run_permutation_test.py, run_walk_forward.py, dashboard.py
Carver:          backtesting/{engine,metrics}.py, signals/{ma_regime,cross_momentum,ibs,combined}.py
                 sizing/position.py
Martin Luk:      strategies/martin_luk.py, signals/{ema_scanner,breakout_detector,market_health}.py
                 sizing/fixed_risk.py
Data:            data/fetcher.py
Frontend:        frontend/src/ (9 pages, 2 components, 1 API client, types, utils, App, main)
Outputs:         equity CSVs, trade logs, backtest_history.json, permutation_results.json,
                 walk_forward_results.json, wf_permutation_results.json
Cache:           31 CSV files in data/cache/ (30 VN30 + VNINDEX, ~7 years of daily OHLCV)
```

---

## 9. VN Market Constraints

- **T+2.5 settlement**: Can't sell shares bought < 3 days ago
- **HOSE lot size**: 100 shares minimum
- **Transaction cost**: 0.25% per trade (brokerage + stamp duty)
- **High correlation**: ~0.6 between VN30 stocks (lower IDM values than global)
- **Daily limit**: ±7% price movement cap (creates IBS mean-reversion edge; anything >50% in data = corruption)
- **Risk-free rate**: 5% (Vietnam fixed deposit rate, used in Sharpe calc)

---

## 10. First Message to Continue

> "I'm resuming work on VN Trading v5. Read CONTEXT.md for full project state. The project has two strategy engines (Carver + Martin Luk) and a 4-step strategy validation system (Timothy Masters methodology: IS backtest → IS permutation → walk-forward → WF permutation). Latest changes added walk-forward validation, fixed data timestamp normalization bugs, and fixed config override propagation to permutation subprocess workers."
