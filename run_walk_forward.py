"""
run_walk_forward.py — Walk-Forward Validation System
=====================================================
Implements Steps 3 & 4 of the Timothy Masters methodology:

Step 3: Walk-Forward Test
  - Split data into rolling train/test windows
  - Grid-search parameters on each training window
  - Test with best params on OOS window
  - Stitch OOS equity curves → compute overall OOS metrics
  - Walk-forward efficiency = OOS metric / IS metric

Step 4: Walk-Forward Permutation Test
  - Run walk-forward → real OOS metric
  - Shuffle returns N times, run single backtest on each
  - Compare real OOS metric vs permuted distribution → p-value
  - If p < 0.05: edge survives out-of-sample AND is statistically significant

Reference: Timothy Masters, "Permutation and Randomization Tests for
Trading System Development"

Usage:
    python run_walk_forward.py                           # Walk-forward test
    python run_walk_forward.py --perm 100                # + permutation test
    python run_walk_forward.py --strategy martin_luk     # Martin Luk strategy
    python run_walk_forward.py --train 3 --test 6        # 3yr train, 6mo test
"""

import argparse
import copy
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from itertools import product
from multiprocessing import cpu_count
from pathlib import Path

import numpy as np
import pandas as pd

from config import UNIVERSE, VNINDEX_TICKER


# ── Parameter grids for optimisation ────────────────────────────────────────
# Keep grids small (≤27 combos) so each window completes in ~1 min.
# Only vary parameters with the highest expected impact on the target metric.
CARVER_PARAM_GRID = {
    "target_vol":       [0.20, 0.25, 0.30],
    "buffer_fraction":  [0.30, 0.35, 0.40],
    "lookback_days":    [42, 63, 84],
}

MARTIN_LUK_PARAM_GRID = {
    "ema_fast":             [7, 9, 12],
    "risk_per_trade_pct":   [0.005, 0.0075, 0.01],
    "max_stop_pct":         [0.04, 0.05, 0.06],
}


# ── Internal helpers ────────────────────────────────────────────────────────

def _get_param_combos(strategy, param_grid=None):
    """Generate all combinations from the parameter grid."""
    grid = param_grid or (
        CARVER_PARAM_GRID if strategy == "carver" else MARTIN_LUK_PARAM_GRID
    )
    keys = list(grid.keys())
    vals = list(grid.values())
    return keys, [dict(zip(keys, combo)) for combo in product(*vals)]


def _apply_params(params_dict, strategy):
    """Set config module parameters for one grid-search iteration."""
    import config as cfg
    if strategy == "carver":
        mapping = {
            "target_vol":            (cfg.SIZING, "target_vol"),
            "buffer_fraction":       (cfg.SIZING, "buffer_fraction"),
            "lookback_days":         (cfg.CROSS_MOMENTUM, "lookback_days"),
            "rebalance_every_days":  (cfg.CROSS_MOMENTUM, "rebalance_every_days"),
            "top_pct":               (cfg.CROSS_MOMENTUM, "top_pct"),
            "bottom_pct":            (cfg.CROSS_MOMENTUM, "bottom_pct"),
        }
    else:
        mapping = {k: (cfg.MARTIN_LUK, k) for k in params_dict}

    for key, val in params_dict.items():
        if key in mapping:
            target, field = mapping[key]
            target[field] = val


def _snapshot_config():
    """Deep-copy all mutable config dicts for safe restore."""
    import config as cfg
    return {
        "MA_REGIME":      copy.deepcopy(cfg.MA_REGIME),
        "CROSS_MOMENTUM": copy.deepcopy(cfg.CROSS_MOMENTUM),
        "IBS":            copy.deepcopy(cfg.IBS),
        "SIGNAL_WEIGHTS": copy.deepcopy(cfg.SIGNAL_WEIGHTS),
        "SIZING":         copy.deepcopy(cfg.SIZING),
        "COSTS":          copy.deepcopy(cfg.COSTS),
        "STOCK_FILTER":   copy.deepcopy(cfg.STOCK_FILTER),
        "MARTIN_LUK":     copy.deepcopy(cfg.MARTIN_LUK),
    }


def _restore_config(snapshot):
    """Restore config dicts from a snapshot."""
    import config as cfg
    for attr, saved in snapshot.items():
        target = getattr(cfg, attr)
        target.clear()
        target.update(saved)


def _make_engine(strategy, capital):
    """Create the appropriate backtest engine."""
    if strategy == "martin_luk":
        from strategies.martin_luk import MartinLukEngine
        return MartinLukEngine(capital=capital)
    else:
        from backtesting.engine import BacktestEngine
        return BacktestEngine(capital=capital)


def _generate_windows(data_start, data_end, train_years, test_months):
    """Generate non-overlapping rolling train/test windows."""
    windows = []
    train_delta = timedelta(days=int(train_years * 365.25))
    test_delta = timedelta(days=int(test_months * 30.44))

    test_start = data_start + train_delta
    while test_start < data_end:
        test_end = min(test_start + test_delta, data_end)
        train_start = test_start - train_delta

        # Need at least 30 calendar days of test data
        if (test_end - test_start).days < 30:
            break

        windows.append({
            "train_start": train_start,
            "train_end":   test_start,
            "test_start":  test_start,
            "test_end":    test_end,
        })

        test_start = test_end
        if test_end >= data_end:
            break

    return windows


def _slice_data(close_matrix, ohlcv_dict, index_prices, start, end):
    """Slice all data sources to [start, end]."""
    cm = close_matrix.loc[start:end]
    ohlcv = {}
    for t, df in ohlcv_dict.items():
        sliced = df.loc[start:end]
        if not sliced.empty:
            ohlcv[t] = sliced
    idx = index_prices.loc[start:end]
    return cm, ohlcv, idx


def _extract_oos_equity(result, test_start, test_end):
    """Extract the OOS equity segment from engine results."""
    eq_df = result["equity_curve"]
    dates = pd.to_datetime(eq_df["date"])
    mask = (dates >= pd.Timestamp(test_start)) & (dates <= pd.Timestamp(test_end))
    oos = eq_df.loc[mask]
    if oos.empty:
        return pd.Series(dtype=float)
    return pd.Series(
        oos["equity"].values.astype(float),
        index=pd.to_datetime(oos["date"].values),
    )


def _load_data(universe, start_date, end_date, use_real, verbose):
    """Load price data (shared by walk-forward and WF permutation)."""
    if not use_real:
        cache_dir = Path("data/cache")
        cached = [t for t in universe
                  if (cache_dir / f"{t.replace('.', '_')}.csv").exists()]
        if len(cached) >= len(universe) * 0.7:
            use_real = True
            if verbose:
                print(f"  Auto-detected cache ({len(cached)}/{len(universe)}) "
                      f"— using real data...")

    if use_real:
        from data.fetcher import fetch_close_matrix, fetch_multi, fetch_index_prices
        from config import VNINDEX_FALLBACK_TICKERS
        if verbose:
            print(f"  Fetching real data...")
        close_matrix = fetch_close_matrix(universe, start_date, end_date, verbose=False)
        ohlcv_dict = fetch_multi(universe, start_date, end_date, verbose=False)
        index_prices = fetch_index_prices(
            VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS,
            start_date, end_date, close_matrix,
        )
    else:
        from run_backtest import _generate_mock_data
        if verbose:
            print(f"  Using mock data...")
        close_matrix, ohlcv_dict, index_prices = _generate_mock_data(
            universe, start_date, end_date,
        )

    # Normalise indices & deduplicate
    close_matrix.index = close_matrix.index.normalize()
    close_matrix = close_matrix[~close_matrix.index.duplicated(keep="last")]
    index_prices.index = index_prices.index.normalize()
    index_prices = index_prices[~index_prices.index.duplicated(keep="last")]
    for t in list(ohlcv_dict):
        ohlcv_dict[t].index = ohlcv_dict[t].index.normalize()
        ohlcv_dict[t] = ohlcv_dict[t][~ohlcv_dict[t].index.duplicated(keep="last")]

    return close_matrix, ohlcv_dict, index_prices


# ── Step 3: Walk-Forward Test ───────────────────────────────────────────────

def run_walk_forward(
    years: int = 10,
    train_years: int = 3,
    test_months: int = 6,
    n_stocks: int = 10,
    strategy: str = "carver",
    param_grid: dict = None,
    metric: str = "sharpe",
    use_real: bool = True,
    capital: float = 500_000_000,
    verbose: bool = True,
    progress_callback=None,
) -> dict:
    """
    Walk-Forward Test with rolling parameter re-optimisation.

    For each window:
    1. Grid-search parameters on training period → best combo
    2. Run backtest with best params through test period
    3. Extract OOS equity segment

    Then stitch all OOS segments → compute overall OOS metrics.
    """
    from backtesting.metrics import compute_metrics

    universe = UNIVERSE[:n_stocks]
    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=int(years * 365.25) + 60)

    # ── Load data ──────────────────────────────────────────────────────────
    close_matrix, ohlcv_dict, index_prices = _load_data(
        universe, start_date, end_date, use_real, verbose,
    )
    if close_matrix.empty:
        if verbose:
            print("  No data. Aborting.")
        return {}

    data_start = close_matrix.index[0]
    data_end = close_matrix.index[-1]

    # ── Generate windows ───────────────────────────────────────────────────
    windows = _generate_windows(data_start, data_end, train_years, test_months)
    if not windows:
        if verbose:
            print("  Not enough data for walk-forward windows. "
                  "Try fewer training years or a longer data period.")
        return {}

    param_keys, combos = _get_param_combos(strategy, param_grid)
    n_combos = len(combos)
    total_steps = len(windows) * (n_combos + 1)
    completed_steps = 0

    if verbose:
        print(f"  Windows: {len(windows)}, Param combos: {n_combos}, "
              f"Total training runs: {len(windows) * n_combos}")

    # ── Config snapshot ────────────────────────────────────────────────────
    snapshot = _snapshot_config()

    window_results = []
    oos_equity_segments = []

    try:
        for w_idx, w in enumerate(windows):
            if verbose:
                print(f"\n  Window {w_idx + 1}/{len(windows)}: "
                      f"Train {w['train_start'].strftime('%Y-%m')} → "
                      f"{w['train_end'].strftime('%Y-%m')} | "
                      f"Test → {w['test_end'].strftime('%Y-%m')}")

            # Warmup: 300 calendar days before train_start for MA200 etc.
            warmup_start = w["train_start"] - timedelta(days=300)
            if warmup_start < data_start:
                warmup_start = data_start

            # ── Grid search on training period ─────────────────────────────
            best_metric_val = -999.0
            best_params = combos[0]

            train_cm, train_ohlcv, train_idx = _slice_data(
                close_matrix, ohlcv_dict, index_prices,
                warmup_start, w["train_end"],
            )

            if train_cm.empty or len(train_cm) < 210:
                if verbose:
                    print(f"    Skipping — insufficient training data "
                          f"({len(train_cm)} rows, need 210)")
                completed_steps += n_combos + 1
                if progress_callback:
                    progress_callback(completed_steps, total_steps)
                continue

            for combo in combos:
                _apply_params(combo, strategy)
                try:
                    engine = _make_engine(strategy, capital)
                    result = engine.run(
                        train_cm, train_ohlcv, train_idx, verbose=False,
                    )
                    m_val = result["metrics"].get(metric, -999.0)
                except Exception:
                    m_val = -999.0

                if m_val > best_metric_val:
                    best_metric_val = m_val
                    best_params = combo.copy()

                completed_steps += 1
                if progress_callback:
                    progress_callback(completed_steps, total_steps)

            if verbose:
                print(f"    Best train {metric}: {best_metric_val:.3f}  "
                      f"params: {best_params}")

            # ── Test best params on full period → extract OOS ──────────────
            _apply_params(best_params, strategy)

            test_cm, test_ohlcv, test_idx = _slice_data(
                close_matrix, ohlcv_dict, index_prices,
                warmup_start, w["test_end"],
            )

            try:
                engine = _make_engine(strategy, capital)
                test_result = engine.run(
                    test_cm, test_ohlcv, test_idx, verbose=False,
                )
                oos_eq = _extract_oos_equity(
                    test_result, w["test_start"], w["test_end"],
                )

                if len(oos_eq) < 10:
                    if verbose:
                        print(f"    OOS too short ({len(oos_eq)} points), "
                              f"skipping")
                    test_metric_val = 0.0
                else:
                    oos_metrics = compute_metrics(oos_eq)
                    test_metric_val = oos_metrics.get(metric, 0.0)
                    oos_equity_segments.append(oos_eq)

            except Exception as e:
                if verbose:
                    print(f"    OOS test failed: {e}")
                test_metric_val = 0.0

            completed_steps += 1
            if progress_callback:
                progress_callback(completed_steps, total_steps)

            efficiency = (test_metric_val / best_metric_val
                          if best_metric_val > 0 else 0.0)

            window_results.append({
                "window_id":   w_idx + 1,
                "train_start": str(w["train_start"].date()),
                "train_end":   str(w["train_end"].date()),
                "test_start":  str(w["test_start"].date()),
                "test_end":    str(w["test_end"].date()),
                "best_params": {
                    k: round(v, 6) if isinstance(v, float) else v
                    for k, v in best_params.items()
                },
                "train_metric": round(best_metric_val, 4),
                "test_metric":  round(test_metric_val, 4),
                "efficiency":   round(efficiency, 4),
            })

            if verbose:
                print(f"    OOS {metric}: {test_metric_val:.3f}  "
                      f"efficiency: {efficiency:.1%}")

    finally:
        _restore_config(snapshot)

    # ── Stitch OOS equity curves ───────────────────────────────────────────
    if not oos_equity_segments:
        if verbose:
            print("\n  No valid OOS segments. Walk-forward failed.")
        return {}

    stitched_parts = []
    last_val = float(capital)
    for seg in oos_equity_segments:
        if seg.empty:
            continue
        scale = last_val / float(seg.iloc[0])
        scaled = seg * scale
        stitched_parts.append(scaled)
        last_val = float(scaled.iloc[-1])

    full_oos_equity = pd.concat(stitched_parts)
    full_oos_equity = full_oos_equity[
        ~full_oos_equity.index.duplicated(keep="last")
    ]

    overall_oos_metrics = compute_metrics(full_oos_equity)

    # Walk-forward efficiency
    train_metrics = [w["train_metric"] for w in window_results
                     if w["train_metric"] > -900]
    is_avg = float(np.mean(train_metrics)) if train_metrics else 0.0
    oos_metric_val = overall_oos_metrics.get(metric, 0.0)
    wf_efficiency = oos_metric_val / is_avg if is_avg > 0 else 0.0

    # Verdict
    if oos_metric_val > 0 and wf_efficiency > 0.5:
        wf_verdict = "PASS"
    elif oos_metric_val > 0:
        wf_verdict = "MARGINAL"
    else:
        wf_verdict = "FAIL"

    # OOS equity curve for frontend chart
    oos_curve_data = [
        {"date": str(d.date()), "equity": round(float(v), 0)}
        for d, v in full_oos_equity.items()
    ]

    results = {
        "available":       True,
        "strategy":        strategy,
        "metric":          metric,
        "years":           years,
        "train_years":     train_years,
        "test_months":     test_months,
        "n_stocks":        n_stocks,
        "n_windows":       len(window_results),
        "n_combos":        n_combos,
        "param_keys":      param_keys,
        "windows":         window_results,
        "oos_metrics": {
            k: (round(float(v), 4) if isinstance(v, (int, float, np.floating))
                else v)
            for k, v in overall_oos_metrics.items()
        },
        "is_avg_metric":   round(float(is_avg), 4),
        "oos_metric":      round(float(oos_metric_val), 4),
        "wf_efficiency":   round(float(wf_efficiency), 4),
        "verdict":         wf_verdict,
        "oos_equity_curve": oos_curve_data,
    }

    if verbose:
        _print_wf_results(results)

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/walk_forward_results.json", "w") as f:
        json.dump(results, f, indent=2)
    if verbose:
        print(f"  Saved to outputs/walk_forward_results.json")

    return results


# ── Step 4: Walk-Forward Permutation Test ───────────────────────────────────

def run_wf_permutation(
    n_perm: int = 100,
    years: int = 10,
    train_years: int = 3,
    test_months: int = 6,
    n_stocks: int = 10,
    strategy: str = "carver",
    param_grid: dict = None,
    metric: str = "sharpe",
    use_real: bool = True,
    capital: float = 500_000_000,
    verbose: bool = True,
    progress_callback=None,
) -> dict:
    """
    Walk-Forward Permutation Test.

    1. Run walk-forward → real OOS metric
    2. Shuffle returns N times, run single backtest on each
    3. Compare real WF OOS metric vs permuted distribution → p-value

    Why single backtests for the permuted runs (not full walk-forward)?
    - Running walk-forward for each of 100+ perms would take hours.
    - Using single backtests is actually MORE CONSERVATIVE: the real metric
      (WF OOS) is already penalised by being out-of-sample, while the
      permuted metrics are in-sample.  If WF OOS still beats them, the edge
      is very strong.
    """
    # ── Step 1: Walk-forward ───────────────────────────────────────────────
    if verbose:
        print("=" * 60)
        print("  STEP 1 / 2 — Walk-Forward Test")
        print("=" * 60)

    def _wf_progress(done, total):
        if progress_callback:
            # Scale 0–50% for walk-forward portion
            progress_callback(done, total + n_perm)

    wf_results = run_walk_forward(
        years=years, train_years=train_years, test_months=test_months,
        n_stocks=n_stocks, strategy=strategy, param_grid=param_grid,
        metric=metric, use_real=use_real, capital=capital,
        verbose=verbose, progress_callback=_wf_progress,
    )

    if not wf_results:
        if verbose:
            print("  Walk-forward failed. Cannot run permutation test.")
        return {}

    real_oos_metric = wf_results["oos_metric"]

    # ── Step 2: Permutation test ───────────────────────────────────────────
    if verbose:
        print(f"\n{'=' * 60}")
        print(f"  STEP 2 / 2 — Permutation Test "
              f"(WF OOS {metric} = {real_oos_metric:.3f})")
        print(f"{'=' * 60}")

    universe = UNIVERSE[:n_stocks]
    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=int(years * 365.25) + 60)

    close_matrix, ohlcv_dict, index_prices = _load_data(
        universe, start_date, end_date, use_real, verbose=False,
    )

    # Pre-compute returns
    close_matrix = close_matrix.dropna(axis=1, how="all")
    cm_returns = close_matrix.pct_change().dropna()
    idx_returns = index_prices.pct_change().dropna()
    common_idx = cm_returns.index.intersection(idx_returns.index)

    if len(common_idx) < 50:
        if verbose:
            print(f"  Insufficient overlapping data ({len(common_idx)}). Aborting.")
        return {}

    cm_ret_aligned = cm_returns.loc[common_idx]
    idx_ret_aligned = idx_returns.loc[common_idx]

    valid_cols = cm_ret_aligned.columns[cm_ret_aligned.notna().all()]
    cm_ret_aligned = cm_ret_aligned[valid_cols]
    close_matrix = close_matrix[valid_cols]

    first_close = close_matrix.bfill().iloc[0]
    first_index = float(index_prices.bfill().iloc[0])

    # Pre-compute OHLCV alignment
    ohlcv_aligned = {}
    for ticker in valid_cols:
        if ticker not in ohlcv_dict:
            continue
        orig = ohlcv_dict[ticker].copy()
        orig.index = orig.index.normalize()
        orig = orig[~orig.index.duplicated(keep="last")]
        aligned = orig.reindex(common_idx).ffill().bfill()
        if aligned.empty or aligned["close"].isna().any():
            continue
        ohlcv_aligned[ticker] = {
            "open":   aligned["open"].values,
            "high":   aligned["high"].values,
            "low":    aligned["low"].values,
            "close":  aligned["close"].values,
            "volume": aligned["volume"].values,
        }

    cm_ret_np = cm_ret_aligned.values
    idx_ret_np = idx_ret_aligned.values
    columns = cm_ret_aligned.columns
    first_close_np = first_close.reindex(columns).values

    # Generate shuffled indices
    rng = np.random.default_rng(seed=42)
    n_days = len(common_idx)
    all_shuffle_indices = [rng.permutation(n_days) for _ in range(n_perm)]

    from run_permutation_test import _run_single_permutation, _snapshot_config_for_workers

    # Snapshot current config (including overrides) so workers use same settings
    config_snap = _snapshot_config_for_workers()

    worker_args = [
        (
            all_shuffle_indices[i],
            cm_ret_np, idx_ret_np,
            common_idx, columns,
            first_close_np, first_index,
            ohlcv_aligned, capital, metric, strategy,
            config_snap,
        )
        for i in range(n_perm)
    ]

    n_workers = max(1, min(cpu_count() - 1, n_perm, 8))
    if verbose:
        print(f"  Running {n_perm} permutations with {n_workers} workers...\n")

    perm_metrics = [None] * n_perm
    completed = 0
    wf_total = wf_results.get("n_windows", 0) * (
        wf_results.get("n_combos", 0) + 1
    )

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
                progress_callback(wf_total + completed, wf_total + n_perm)
            if verbose and completed % 10 == 0:
                done = [m for m in perm_metrics if m is not None]
                beats = sum(1 for m in done if m >= real_oos_metric)
                print(f"  Perm {completed:>4}/{n_perm}  |  "
                      f"beats WF OOS: {beats}/{len(done)}")

    # ── p-value ────────────────────────────────────────────────────────────
    perm_arr = np.array(perm_metrics, dtype=float)
    p_value = float(np.mean(perm_arr >= real_oos_metric))

    # Bootstrap 95% CI
    boot_p = []
    for _ in range(1000):
        sample = rng.choice(perm_arr, size=len(perm_arr), replace=True)
        boot_p.append(float(np.mean(sample >= real_oos_metric)))
    p_ci_low = float(np.percentile(boot_p, 2.5))
    p_ci_high = float(np.percentile(boot_p, 97.5))

    # Verdict
    if p_value < 0.01:
        verdict = "STRONG EDGE"
    elif p_value < 0.05:
        verdict = "EDGE DETECTED"
    elif p_value < 0.10:
        verdict = "WEAK / MARGINAL"
    else:
        verdict = "NO EDGE DETECTED"

    results = {
        "available":          True,
        "test_type":          "wf_permutation",
        "metric":             metric,
        "strategy":           strategy,
        "real_wf_oos_value":  round(real_oos_metric, 4),
        "wf_efficiency":      wf_results.get("wf_efficiency", 0.0),
        "p_value":            round(p_value, 4),
        "p_ci_low":           round(p_ci_low, 4),
        "p_ci_high":          round(p_ci_high, 4),
        "n_permutations":     n_perm,
        "perm_mean":          round(float(np.mean(perm_arr)), 4),
        "perm_median":        round(float(np.median(perm_arr)), 4),
        "perm_std":           round(float(np.std(perm_arr)), 4),
        "perm_p5":            round(float(np.percentile(perm_arr, 5)), 4),
        "perm_p95":           round(float(np.percentile(perm_arr, 95)), 4),
        "n_beats_real":       int(np.sum(perm_arr >= real_oos_metric)),
        "verdict":            verdict,
        "years":              years,
        "n_stocks":           n_stocks,
        "train_years":        train_years,
        "test_months":        test_months,
        "n_windows":          wf_results.get("n_windows", 0),
        "perm_distribution":  [round(float(x), 4) for x in sorted(perm_arr)],
    }

    if verbose:
        _print_wfp_results(results)

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/wf_permutation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    if verbose:
        print(f"  Saved to outputs/wf_permutation_results.json")

    return results


# ── Pretty-print helpers ────────────────────────────────────────────────────

def _print_wf_results(r):
    print(f"\n{'=' * 60}")
    print(f"  WALK-FORWARD TEST — {r['verdict']}")
    print(f"{'=' * 60}")
    print(f"  Strategy:       {r['strategy']}")
    print(f"  Metric:         {r['metric'].upper()}")
    print(f"  Windows:        {r['n_windows']} "
          f"({r['train_years']}yr train / {r['test_months']}mo test)")
    print(f"  Param combos:   {r['n_combos']}")
    print(f"  Optimised:      {', '.join(r['param_keys'])}")
    print(f"\n  IS avg {r['metric']}:   {r['is_avg_metric']:+.3f}")
    print(f"  OOS {r['metric']}:       {r['oos_metric']:+.3f}")
    print(f"  WF Efficiency:  {r['wf_efficiency']:.1%}")

    oos = r["oos_metrics"]
    print(f"\n  OOS Performance:")
    for key in ("cagr", "sharpe", "sortino", "max_drawdown", "annual_vol"):
        val = oos.get(key, 0)
        if key in ("cagr", "max_drawdown", "annual_vol"):
            print(f"    {key:<14} {val * 100:+.1f}%")
        else:
            print(f"    {key:<14} {val:.3f}")

    print(f"\n  Per-Window:")
    for w in r["windows"]:
        print(f"    W{w['window_id']:>2}: "
              f"{w['train_start'][:7]}→{w['train_end'][:7]} "
              f"test→{w['test_end'][:7]}  "
              f"IS={w['train_metric']:+.3f}  "
              f"OOS={w['test_metric']:+.3f}  "
              f"eff={w['efficiency']:.0%}")
    print(f"{'=' * 60}\n")


def _print_wfp_results(r):
    print(f"\n{'=' * 60}")
    print(f"  WF PERMUTATION TEST — {r['verdict']}")
    print(f"{'=' * 60}")
    print(f"  WF OOS {r['metric'].upper()}:  {r['real_wf_oos_value']:+.3f}")
    print(f"  Perm mean:       {r['perm_mean']:+.3f}")
    print(f"  p-value:         {r['p_value']:.4f}  "
          f"(CI: [{r['p_ci_low']:.4f}, {r['p_ci_high']:.4f}])")
    print(f"  Beats WF OOS:    {r['n_beats_real']} / {r['n_permutations']}")
    print()
    print(f"  This test compares your walk-forward OUT-OF-SAMPLE metric")
    print(f"  against randomly shuffled single backtests.  Since the WF OOS")
    print(f"  metric is already penalised by being out-of-sample, this is a")
    print(f"  CONSERVATIVE test.  Passing = strong evidence of real edge.")
    print(f"{'=' * 60}\n")


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VN Trading v5 — Walk-Forward Validation",
    )
    parser.add_argument("--years",    type=int, default=10)
    parser.add_argument("--train",    type=int, default=3,
                        help="Training years per window")
    parser.add_argument("--test",     type=int, default=6,
                        help="Test months per window")
    parser.add_argument("--n",        type=int, default=10, help="Stocks")
    parser.add_argument("--strategy", type=str, default="carver",
                        choices=["carver", "martin_luk"])
    parser.add_argument("--metric",   type=str, default="sharpe",
                        choices=["sharpe", "cagr"])
    parser.add_argument("--real",     action="store_true")
    parser.add_argument("--perm",     type=int, default=0,
                        help="If > 0, also run WF permutation test")
    args = parser.parse_args()

    results = run_walk_forward(
        years=args.years,
        train_years=args.train,
        test_months=args.test,
        n_stocks=args.n,
        strategy=args.strategy,
        metric=args.metric,
        use_real=args.real,
    )

    if args.perm > 0 and results:
        run_wf_permutation(
            n_perm=args.perm,
            years=args.years,
            train_years=args.train,
            test_months=args.test,
            n_stocks=args.n,
            strategy=args.strategy,
            metric=args.metric,
            use_real=args.real,
        )
