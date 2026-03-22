"""
run_backtest.py — Backtest Runner
===================================
Usage:
    python run_backtest.py                  # Mock data, fast test
    python run_backtest.py --real           # Real yfinance data
    python run_backtest.py --real --years 3 # 3 years of real data
    python run_backtest.py --n 10           # 10 stocks from universe
    python run_backtest.py --capital 500000000

Outputs:
    - Performance scorecard printed to console
    - outputs/backtest_results.json (for dashboard)
    - outputs/equity_curve.csv
    - outputs/trade_log.csv
"""

import argparse
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config import UNIVERSE, VNINDEX_TICKER, DATA


def run_backtest(
    n_stocks: int = 15,
    years: int = 3,
    capital: float = 500_000_000,
    use_real: bool = False,
    verbose: bool = True,
    strategy: str = "carver",
):
    universe = UNIVERSE[:n_stocks]
    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=int(years * 365.25) + 60)

    # ── Load data ─────────────────────────────────────────────────────────────
    # Auto-detect: if cache exists for these tickers, use real data from cache.
    # This avoids re-fetching and gives instant results on subsequent runs.
    if not use_real:
        from pathlib import Path
        cache_dir = Path("data/cache")
        cached_tickers = [t for t in universe
                          if (cache_dir / f"{t.replace('.', '_')}.csv").exists()]
        if len(cached_tickers) >= len(universe) * 0.7:  # 70%+ cached → use real
            use_real = True
            if verbose:
                print(f"\n  Auto-detected cache ({len(cached_tickers)}/{len(universe)} stocks) — using real data...")

    if use_real:
        from data.fetcher import fetch_close_matrix, fetch_multi, fetch_index_prices
        from config import VNINDEX_FALLBACK_TICKERS
        if verbose:
            print(f"\n  Loading {years} years of data for {n_stocks} stocks (cache + fetch)...")
        close_matrix = fetch_close_matrix(universe, start_date, end_date, verbose=verbose)
        ohlcv_dict = fetch_multi(universe, start_date, end_date, verbose=False)
        index_prices = fetch_index_prices(
            VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS, start_date, end_date, close_matrix
        )
    else:
        if verbose:
            print(f"\n  Using mock data ({years} years, {n_stocks} stocks)...")
        close_matrix, ohlcv_dict, index_prices = _generate_mock_data(universe, start_date, end_date)

    if close_matrix.empty:
        print("  ❌ No data available.")
        return None

    # ── Run backtest ──────────────────────────────────────────────────────────
    if strategy == "martin_luk":
        from strategies.martin_luk import MartinLukEngine
        engine = MartinLukEngine(capital=capital)
        results = engine.run(
            close_matrix=close_matrix,
            ohlcv_dict=ohlcv_dict,
            index_prices=index_prices,
            verbose=verbose,
        )
    else:
        from backtesting.engine import BacktestEngine
        engine = BacktestEngine(capital=capital)
        results = engine.run(
            close_matrix=close_matrix,
            ohlcv_dict=ohlcv_dict,
            index_prices=index_prices,
            verbose=verbose,
        )

    from backtesting.metrics import print_scorecard
    if verbose:
        title = f"Martin Luk Swing — {years}y" if strategy == "martin_luk" else f"VN Trading v5 — {years}y Backtest"
        print_scorecard(results["metrics"], title=title)

    # ── Save outputs ──────────────────────────────────────────────────────────
    os.makedirs("outputs", exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Per-run files (so dashboard can load any historical run)
    eq = results["equity_curve"]
    eq_file     = f"outputs/equity_{run_id}.csv"
    trades_file = f"outputs/trades_{run_id}.csv"

    if not eq.empty:
        eq.to_csv(eq_file)
        eq.to_csv("outputs/equity_curve.csv")   # latest alias

    trades = results["trade_log"]
    if not trades.empty:
        trades.to_csv(trades_file, index=False)
        trades.to_csv("outputs/trade_log.csv", index=False)  # latest alias

    # Metrics JSON (latest run — always overwritten)
    metrics = results["metrics"]
    metrics_serialisable = {
        k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
        for k, v in metrics.items()
    }
    with open("outputs/backtest_results.json", "w") as f:
        json.dump(metrics_serialisable, f, indent=2)

    # ── Append to history log ─────────────────────────────────────────────────
    history_path = "outputs/backtest_history.json"
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                history = json.load(f)
        except Exception:
            history = []

    run_record = {
        "run_id":    run_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "params": {
            "n_stocks":    n_stocks,
            "years":       years,
            "capital":     capital,
            "data_source": "real" if use_real else "mock",
            "strategy":    strategy,
        },
        "metrics":    metrics_serialisable,
        "equity_file": eq_file     if not eq.empty     else None,
        "trades_file": trades_file if not trades.empty else None,
    }
    history.append(run_record)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    if verbose:
        print(f"  Outputs saved to outputs/  (run #{len(history)} in history)")

    return results


def _generate_mock_data(universe, start_date, end_date):
    """
    Realistic synthetic OHLCV data representing VN market characteristics:
    - Moderate bull trend (~14% annual VNIndex, matching VN historical avg)
    - Two periodic corrections (typical 3-year VN cycle)
    - High inter-stock correlation (~0.6, characteristic of VN frontier market)
    - VN daily vol ~1.2% index, ~1.8% individual stocks
    Uses deterministic trend + noise to avoid seed-dependent bear markets.
    """
    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    rng = np.random.default_rng(seed=4)  # seed 4: +21% VNIndex over 3yr, realistic

    # ── VNIndex: deterministic trend + stochastic noise ─────────────────────
    # Annual return target: ~14% → daily log drift = ln(1.14)/252 ≈ 0.00052
    deterministic_trend = 0.00052 * np.ones(n)  # steady daily drift

    # Add two corrections: -12% and -10% drawdowns over ~25-30 days
    # Daily return needed: ln(0.88)/25 ≈ -0.0051/day for -12% total
    import math
    corr1_daily = math.log(0.88) / 25   # -12% correction
    corr2_daily = math.log(0.90) / 20   # -10% correction
    for c_start_pct, c_daily, c_len in [(0.38, corr1_daily, 25), (0.72, corr2_daily, 20)]:
        c_start = int(n * c_start_pct)
        c_end   = min(c_start + c_len, n)
        deterministic_trend[c_start:c_end] = c_daily

    noise = rng.normal(0, 0.008, n)  # tighter noise: still realistic but won't dominate trend
    market_returns = deterministic_trend + noise
    vnindex = pd.Series(1200.0 * np.exp(np.cumsum(market_returns)), index=dates)

    close_matrix = {}
    ohlcv_dict   = {}

    for ticker in universe:
        beta     = rng.uniform(0.80, 1.20)
        alpha    = rng.uniform(-0.0001, 0.0002)   # modest stock-specific alpha
        idio_vol = rng.uniform(0.010, 0.018)
        idio     = rng.normal(alpha, idio_vol, n)
        returns  = beta * market_returns + idio

        start_price = rng.uniform(15_000, 80_000)
        prices = start_price * np.exp(np.cumsum(returns))

        range_pct = np.abs(rng.normal(0, 0.012, n)) + 0.005
        highs = prices * (1 + range_pct)
        lows  = prices * (1 - range_pct)
        # Beta(2,2) close position: naturally mean-reverting (IBS varies 0–1)
        close_pos = rng.beta(2, 2, n)
        closes = lows + (highs - lows) * close_pos
        volume = rng.integers(300_000, 3_000_000, n)

        close_matrix[ticker] = pd.Series(closes, index=dates)
        ohlcv_dict[ticker] = pd.DataFrame({
            "open":   lows + (highs - lows) * rng.uniform(0.2, 0.8, n),
            "high":   highs, "low": lows, "close": closes, "volume": volume,
        }, index=dates)

    return pd.DataFrame(close_matrix), ohlcv_dict, vnindex


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VN Trading Framework v5 — Backtest")
    parser.add_argument("--real", action="store_true", help="Use real yfinance data")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--capital", type=float, default=500_000_000)
    parser.add_argument("--strategy", type=str, default="carver",
                        choices=["carver", "martin_luk"],
                        help="Trading strategy: carver or martin_luk")
    args = parser.parse_args()

    run_backtest(
        n_stocks=args.n,
        years=args.years,
        capital=args.capital,
        use_real=args.real,
        strategy=args.strategy,
    )