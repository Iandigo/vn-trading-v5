# VN Trading Framework v5

**Semi-automatic trading framework for HOSE (Vietnam), based on 4 proven signals.**

## 4 Signals

| # | Signal | Type | Weight | Update freq |
|---|--------|------|--------|-------------|
| 1 | **200-day MA Regime Filter** | Filter (not forecast) | τ × 0.5 in BEAR | Weekly |
| 2 | **Cross-Sectional Momentum** | Trend — rank vs peers | 55% | Monthly |
| 3 | **IBS Mean Reversion** | Counter-trend | 15% | Daily |
| 4 | **Volatility-Scaled Sizing** | Position sizing | τ = 25% | Per trade |

## Anti-Overfitting Rules Baked In

- MA period = **200** (global standard, not optimised for VN)
- Momentum lookback = **63 days** (3 months, round number)
- IBS thresholds = **0.20 / 0.80** (textbook values)
- Rebalance = **monthly** (not optimised frequency)
- Buffer zone = **20%** (from Carver theory, not backtested)
- τ = **25%** (raised from 20% to correct VN correlation bias)

## VN Market Adaptations

- **Long-only**: no short selling (HOSE does not allow it)
- **T+3 settlement**: can't sell within 3 days of purchase
- **Lot size**: all positions rounded to nearest 100 shares
- **Cost**: 0.25% per trade (TCBS rate)
- **IDM table**: lower than standard (VN correlation ~0.6 vs ~0.35)
- **Regime updates weekly**: prevents whipsaw (v4 bug lesson)
- **IBS disabled in BEAR**: no counter-trend when market in downtrend

## Quick Start

```bash
pip install -r requirements.txt
pip install vnstock  # optional fallback

# Test with mock data (no internet needed)
python main.py --test

# Daily workflow (real data)
python main.py --n 15 --capital 500000000

# Force BEAR regime (current: US-Iran war)
python main.py --regime BEAR

# Backtest (mock data, fast)
python run_backtest.py

# Backtest (real data, 3 years)
python run_backtest.py --real --years 3 --n 15

# Permutation test — validate statistical edge
python run_permutation_test.py --n_perm 100
python run_permutation_test.py --real --years 3 --n_perm 200

# Dashboard
python -m streamlit run dashboard.py

# Record a trade after executing on TCBS
python -c "
from portfolio.tracker import PortfolioTracker
t = PortfolioTracker()
t.record_trade('VCB.VN', 'BUY', shares=500, price=88500)
t.print_summary()
"
```

## Project Structure

```
vn_trading_v5/
├── config.py                  ← All parameters (read this first)
├── main.py                    ← Daily workflow
├── run_backtest.py            ← Backtest runner
├── run_permutation_test.py    ← Statistical edge validation
├── dashboard.py               ← Streamlit web dashboard (6 pages)
├── requirements.txt
│
├── signals/
│   ├── ma_regime.py           ← Signal 1: 200-day MA regime filter
│   ├── cross_momentum.py      ← Signal 2: Cross-sectional momentum
│   ├── ibs.py                 ← Signal 3: IBS mean reversion
│   └── combined.py            ← Combines signals 2 + 3 with FDM
│
├── sizing/
│   └── position.py            ← Signal 4: Volatility-scaled sizing
│
├── data/
│   └── fetcher.py             ← yfinance primary, vnstock fallback
│
├── backtesting/
│   ├── engine.py              ← Walk-forward backtest engine
│   └── metrics.py             ← Sharpe, CAGR, Drawdown, Sortino
│
├── portfolio/
│   └── tracker.py             ← Live holdings & P&L tracker
│
└── outputs/                   ← All results saved here
    ├── backtest_results.json
    ├── equity_curve.csv
    ├── trade_log.csv
    ├── permutation_results.json
    ├── holdings.json
    └── live_trade_log.json
```

## Target Metrics (after v4 bug fixes applied here)

| Metric | Target | Why |
|--------|--------|-----|
| CAGR | > 8% | Above VN bank FD rate (5%) with risk premium |
| Sharpe | > 0.40 | Minimum acceptable (Carver) |
| Max DD | < -20% | Conservative for retail trader |
| Trades/month | < 30 | Buffer 20% + monthly rebalance |
| Cost drag | < 1.5%/yr | From reduced trading frequency |

## Key Design Decisions

**Why cross-sectional momentum (not just EWMAC)?**  
Your v4 used time-series momentum only. Cross-sectional adds a genuinely different alpha source: "is this stock outperforming peers?" vs "is this stock trending up vs itself?". Correlation between the two is ~0.4 — real diversification.

**Why IBS instead of RSI?**  
RSI has a period parameter (usually 14) that is commonly over-optimised. IBS has zero parameters. Same mean-reversion logic, much less curve-fitting risk.

**Why 200-day MA as a filter (not a signal)?**  
In VN's current war-impact environment (Feb 2026, VNIndex -5.7%), a regime filter that halves position sizing is more valuable than any individual stock signal. It's the difference between -20% drawdown and -40%.

**Why monthly rebalance for momentum?**  
3-month momentum doesn't change meaningfully day-to-day. Monthly updates reduce transaction costs from ~69 trades/month to ~25 with no meaningful signal degradation.
