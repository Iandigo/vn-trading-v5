"""
run_permutation_test.py — Statistical Edge Validation
=======================================================
Scrambles the return sequence N times and runs the full backtest each time.
Measures what fraction of random shuffles beat the real strategy.

  p-value < 0.01 → Strong edge (99% confidence)
  p-value < 0.05 → Edge detected (95% confidence)
  p-value > 0.10 → No evidence of edge yet

Why this matters more than a regular backtest:
  A backtest can look good just because you got lucky with the data.
  The permutation test asks: "could a random strategy have done this well?"
  If fewer than 5% of random shuffles beat your Sharpe, the edge is real.

Usage:
    python run_permutation_test.py                   # 100 permutations, mock data
    python run_permutation_test.py --n_perm 200      # 200 permutations
    python run_permutation_test.py --real --years 3  # Real data
    python run_permutation_test.py --metric cagr     # Test on CAGR instead of Sharpe
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from multiprocessing import cpu_count

import numpy as np
import pandas as pd

from config import UNIVERSE, VNINDEX_TICKER


def _snapshot_config_for_workers():
    """Snapshot mutable config dicts for passing to subprocess workers."""
    import config as cfg
    return {
        "MA_REGIME": dict(cfg.MA_REGIME),
        "CROSS_MOMENTUM": dict(cfg.CROSS_MOMENTUM),
        "IBS": dict(cfg.IBS),
        "SIGNAL_WEIGHTS": dict(cfg.SIGNAL_WEIGHTS),
        "SIZING": {k: (dict(v) if isinstance(v, dict) else v)
                   for k, v in cfg.SIZING.items()},
        "COSTS": dict(cfg.COSTS),
        "STOCK_FILTER": dict(cfg.STOCK_FILTER),
        "MARTIN_LUK": dict(cfg.MARTIN_LUK),
    }


def _apply_config_snapshot(snapshot):
    """Apply config snapshot in a worker process."""
    import config as cfg
    for attr, values in snapshot.items():
        target = getattr(cfg, attr)
        target.clear()
        target.update(values)


def run_permutation_test(
    n_perm: int = 100,
    n_stocks: int = 10,
    years: int = 3,
    capital: float = 500_000_000,
    use_real: bool = False,
    metric: str = "sharpe",
    strategy: str = "carver",
    verbose: bool = True,
    progress_callback=None,
) -> dict:
    """
    Run permutation test to validate statistical edge.

    Parameters
    ----------
    progress_callback : callable, optional
        Called with (completed_count, n_perm) after each batch completes.
        Useful for API progress reporting.
    """
    universe = UNIVERSE[:n_stocks]
    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=int(years * 365.25) + 60)

    # ── Load / generate data ──────────────────────────────────────────────────
    if not use_real:
        from pathlib import Path
        cache_dir = Path("data/cache")
        cached_tickers = [t for t in universe
                          if (cache_dir / f"{t.replace('.', '_')}.csv").exists()]
        if len(cached_tickers) >= len(universe) * 0.7:
            use_real = True
            if verbose:
                print(f"\n  Auto-detected cache ({len(cached_tickers)}/{len(universe)} stocks) — using real data...")

    if use_real:
        from data.fetcher import fetch_close_matrix, fetch_multi, fetch_index_prices
        from config import VNINDEX_FALLBACK_TICKERS
        if verbose:
            print(f"\n  Fetching {years} years of real data...")
        close_matrix = fetch_close_matrix(universe, start_date, end_date, verbose=False)
        ohlcv_dict = fetch_multi(universe, start_date, end_date, verbose=False)
        index_prices = fetch_index_prices(
            VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS, start_date, end_date, close_matrix
        )
    else:
        from run_backtest import _generate_mock_data
        if verbose:
            print(f"\n  Using mock data ({years} years, {n_stocks} stocks)...")
        close_matrix, ohlcv_dict, index_prices = _generate_mock_data(universe, start_date, end_date)

    if close_matrix.empty:
        print("  No data. Aborting.")
        return {}

    # ── Run real strategy ─────────────────────────────────────────────────────
    if verbose:
        print(f"\n  Running REAL strategy ({strategy})...")
    if strategy == "martin_luk":
        from strategies.martin_luk import MartinLukEngine
        engine = MartinLukEngine(capital=capital)
    else:
        from backtesting.engine import BacktestEngine
        engine = BacktestEngine(capital=capital)
    real_results = engine.run(close_matrix, ohlcv_dict, index_prices, verbose=False)
    real_metric = real_results["metrics"].get(metric, 0.0)

    if verbose:
        print(f"  Real {metric.upper()}: {real_metric:.3f}")
        print(f"\n  Running {n_perm} permutations...")

    # ── Pre-compute returns ONCE (avoid redundant pct_change per perm) ───────
    # Normalize date indices to date-only (drop time component) to avoid
    # mismatch between e.g. "2019-01-21 00:00" and "2019-01-21 07:00"
    close_matrix.index = close_matrix.index.normalize()
    close_matrix = close_matrix[~close_matrix.index.duplicated(keep="last")]
    index_prices.index = index_prices.index.normalize()
    index_prices = index_prices[~index_prices.index.duplicated(keep="last")]

    # Drop columns that are entirely NaN (stocks without data)
    close_matrix = close_matrix.dropna(axis=1, how='all')

    cm_returns = close_matrix.pct_change().dropna()
    idx_returns = index_prices.pct_change().dropna()
    common_idx = cm_returns.index.intersection(idx_returns.index)

    if len(common_idx) < 300:
        print(f"  WARNING: Only {len(common_idx)} common dates between stocks and index.")
        if len(common_idx) < 50:
            print("  Aborting — insufficient overlapping data.")
            return {}

    cm_ret_aligned = cm_returns.loc[common_idx]
    idx_ret_aligned = idx_returns.loc[common_idx]

    # Drop any columns with NaN returns (stocks that started later)
    valid_cols = cm_ret_aligned.columns[cm_ret_aligned.notna().all()]
    cm_ret_aligned = cm_ret_aligned[valid_cols]
    close_matrix = close_matrix[valid_cols]

    # Use first NON-NaN close for each column (not iloc[0] which may be NaN)
    first_close = close_matrix.bfill().iloc[0]
    first_index = float(index_prices.bfill().iloc[0])

    if verbose:
        print(f"  Common dates: {len(common_idx)}, Valid stocks: {len(valid_cols)}")

    # Pre-compute OHLCV alignment data for fast reconstruction
    ohlcv_aligned = {}
    for ticker in valid_cols:
        if ticker not in ohlcv_dict:
            continue
        orig = ohlcv_dict[ticker].copy()
        orig.index = orig.index.normalize()
        # Drop duplicate dates (keep last) to avoid reindex error
        orig = orig[~orig.index.duplicated(keep="last")]
        aligned = orig.reindex(common_idx).ffill().bfill()
        if aligned.empty or aligned["close"].isna().any():
            continue
        ohlcv_aligned[ticker] = {
            "open": aligned["open"].values,
            "high": aligned["high"].values,
            "low": aligned["low"].values,
            "close": aligned["close"].values,
            "volume": aligned["volume"].values,
        }

    # Convert to numpy for faster shuffling
    cm_ret_np = cm_ret_aligned.values  # (n_days, n_stocks)
    idx_ret_np = idx_ret_aligned.values  # (n_days,)
    columns = cm_ret_aligned.columns
    first_close_np = first_close.reindex(columns).values

    # ── Parallel permutation loop ────────────────────────────────────────────
    n_workers = max(1, min(cpu_count() - 1, n_perm, 8))  # cap at 8 workers

    if verbose:
        print(f"  Using {n_workers} parallel workers\n")

    # Pre-generate all shuffled indices (fast, tiny memory)
    rng = np.random.default_rng(seed=0)
    n_days = len(common_idx)
    all_shuffle_indices = [rng.permutation(n_days) for _ in range(n_perm)]

    # Snapshot current config (including overrides) so workers use same settings
    config_snap = _snapshot_config_for_workers()

    # Build args for workers — numpy arrays are efficiently shared
    worker_args = []
    for i in range(n_perm):
        worker_args.append((
            all_shuffle_indices[i],
            cm_ret_np,
            idx_ret_np,
            common_idx,
            columns,
            first_close_np,
            first_index,
            ohlcv_aligned,
            capital,
            metric,
            strategy,
            config_snap,
        ))

    perm_metrics = [None] * n_perm
    completed = 0

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        future_to_idx = {
            executor.submit(_run_single_permutation, args): i
            for i, args in enumerate(worker_args)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                perm_metrics[idx] = future.result()
            except Exception:
                perm_metrics[idx] = 0.0

            completed += 1

            if progress_callback:
                progress_callback(completed, n_perm)

            if verbose and completed % 10 == 0:
                done_metrics = [m for m in perm_metrics if m is not None]
                beats_so_far = sum(1 for m in done_metrics if m >= real_metric)
                p_so_far = beats_so_far / len(done_metrics)
                print(f"  Perm {completed:>4}/{n_perm}  |  "
                      f"Perm avg {metric}: {np.mean(done_metrics):+.3f}  |  "
                      f"p-value so far: {p_so_far:.3f}")

    # ── Compute p-value ───────────────────────────────────────────────────────
    perm_arr = np.array(perm_metrics, dtype=float)
    p_value = float(np.mean(perm_arr >= real_metric))

    # Bootstrap 95% CI for p-value
    boot_p = []
    for _ in range(1000):
        sample = rng.choice(perm_arr, size=len(perm_arr), replace=True)
        boot_p.append(float(np.mean(sample >= real_metric)))
    p_ci_low = float(np.percentile(boot_p, 2.5))
    p_ci_high = float(np.percentile(boot_p, 97.5))

    # ── Verdict ───────────────────────────────────────────────────────────────
    if p_value < 0.01:
        verdict = "STRONG EDGE"
        verdict_icon = "OK OK"
    elif p_value < 0.05:
        verdict = "EDGE DETECTED"
        verdict_icon = "OK"
    elif p_value < 0.10:
        verdict = "WEAK / MARGINAL"
        verdict_icon = "WARN"
    else:
        verdict = "NO EDGE DETECTED"
        verdict_icon = "FAIL"

    results = {
        "metric":          metric,
        "real_value":      round(real_metric, 4),
        "p_value":         round(p_value, 4),
        "p_ci_low":        round(p_ci_low, 4),
        "p_ci_high":       round(p_ci_high, 4),
        "n_permutations":  n_perm,
        "perm_mean":       round(float(np.mean(perm_arr)), 4),
        "perm_median":     round(float(np.median(perm_arr)), 4),
        "perm_std":        round(float(np.std(perm_arr)), 4),
        "perm_p5":         round(float(np.percentile(perm_arr, 5)), 4),
        "perm_p95":        round(float(np.percentile(perm_arr, 95)), 4),
        "n_beats_real":    int(np.sum(perm_arr >= real_metric)),
        "verdict":         verdict,
        "years":           years,
        "n_stocks":        n_stocks,
        "perm_distribution": [round(float(x), 4) for x in sorted(perm_arr)],
    }

    if verbose:
        _print_results(results, verdict_icon)

    # Save
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/permutation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    if verbose:
        print(f"  Results saved to outputs/permutation_results.json")

    return results


def _run_single_permutation(args) -> float:
    """
    Worker function for a single permutation. Runs in a subprocess.
    Takes pre-computed numpy arrays to avoid redundant pct_change() calls.
    """
    (
        shuffle_idx,
        cm_ret_np,
        idx_ret_np,
        common_idx,
        columns,
        first_close_np,
        first_index,
        ohlcv_aligned,
        capital,
        metric,
        strategy,
        config_snapshot,
    ) = args

    # Apply config overrides in this worker process (subprocess gets fresh defaults)
    if config_snapshot:
        _apply_config_snapshot(config_snapshot)

    # Shuffle returns using pre-computed index
    cm_shuffled = cm_ret_np[shuffle_idx]
    idx_shuffled = idx_ret_np[shuffle_idx]

    # Reconstruct prices from shuffled returns (vectorized numpy)
    new_close_np = np.cumprod(1 + cm_shuffled, axis=0) * first_close_np
    new_index_np = np.cumprod(1 + idx_shuffled) * first_index

    new_close = pd.DataFrame(new_close_np, index=common_idx, columns=columns)
    new_index = pd.Series(new_index_np, index=common_idx)

    # Reconstruct OHLCV using pre-aligned data (no reindex/ffill per perm)
    new_ohlcv = {}
    for ticker_idx, ticker in enumerate(columns):
        if ticker not in ohlcv_aligned:
            continue
        orig = ohlcv_aligned[ticker]
        new_close_col = new_close_np[:, ticker_idx]
        orig_close = orig["close"]

        # Ratio: avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = np.where(orig_close > 0, new_close_col / orig_close, 1.0)

        new_ohlcv[ticker] = pd.DataFrame({
            "open":   orig["open"] * ratio,
            "high":   orig["high"] * ratio,
            "low":    orig["low"] * ratio,
            "close":  new_close_col,
            "volume": orig["volume"],
        }, index=common_idx)

    # Run backtest
    if strategy == "martin_luk":
        from strategies.martin_luk import MartinLukEngine
        eng = MartinLukEngine(capital=capital)
    else:
        from backtesting.engine import BacktestEngine
        eng = BacktestEngine(capital=capital)
    res = eng.run(new_close, new_ohlcv, new_index, verbose=False)
    return res["metrics"].get(metric, 0.0)


def _print_results(results: dict, verdict_icon: str):
    metric = results["metric"].upper()
    print(f"\n{'='*60}")
    print(f"  PERMUTATION TEST RESULTS")
    print(f"  {verdict_icon}  {results['verdict']}")
    print(f"{'='*60}")
    print(f"  Test metric:     {metric}")
    print(f"  Permutations:    {results['n_permutations']}")
    print(f"  Period:          {results['years']} years, {results['n_stocks']} stocks")
    print(f"\n  Real strategy {metric}:    {results['real_value']:+.3f}")
    print(f"  Permutation mean:       {results['perm_mean']:+.3f}")
    print(f"  Permutation median:     {results['perm_median']:+.3f}")
    print(f"  Permutation 5th pctile: {results['perm_p5']:+.3f}")
    print(f"  Permutation 95th pctile:{results['perm_p95']:+.3f}")
    print(f"\n  # permutations that beat real:  {results['n_beats_real']} / {results['n_permutations']}")
    print(f"  p-value:  {results['p_value']:.4f}  "
          f"(95% CI: [{results['p_ci_low']:.4f}, {results['p_ci_high']:.4f}])")
    print(f"\n  Interpretation:")
    if results['p_value'] < 0.01:
        print(f"  Only {results['p_value']*100:.1f}% of random shuffles beat the strategy.")
        print(f"  Strong evidence of real predictive edge (99% confidence).")
    elif results['p_value'] < 0.05:
        print(f"  {results['p_value']*100:.1f}% of random shuffles beat the strategy.")
        print(f"  Edge detected at 95% confidence. Acceptable for live trading.")
    elif results['p_value'] < 0.10:
        print(f"  {results['p_value']*100:.1f}% of random shuffles beat the strategy.")
        print(f"  Marginal edge. Consider more data or review signal weights.")
    else:
        print(f"  {results['p_value']*100:.1f}% of random shuffles beat the strategy.")
        print(f"  No significant edge. Do NOT trade this — more data needed.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VN Trading v5 — Permutation Test")
    parser.add_argument("--n_perm",  type=int,   default=100)
    parser.add_argument("--n",       type=int,   default=10,          help="Stocks")
    parser.add_argument("--years",   type=int,   default=3)
    parser.add_argument("--capital", type=float, default=500_000_000)
    parser.add_argument("--real",    action="store_true")
    parser.add_argument("--metric",  type=str,   default="sharpe",    help="sharpe or cagr")
    parser.add_argument("--strategy", type=str,  default="carver",    choices=["carver", "martin_luk"])
    args = parser.parse_args()

    run_permutation_test(
        n_perm=args.n_perm,
        n_stocks=args.n,
        years=args.years,
        capital=args.capital,
        use_real=args.real,
        metric=args.metric,
        strategy=args.strategy,
    )
