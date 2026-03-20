"""
backtesting/metrics.py — Performance Metrics
=============================================
Standard Carver scorecard: CAGR, Sharpe, Sortino, Max Drawdown.
Risk-free rate set to Vietnam bank FD rate (~5% annual).
"""

import numpy as np
import pandas as pd


RISK_FREE_RATE = 0.05   # Vietnam 12-month FD rate ~5%


def compute_metrics(equity_curve: pd.Series) -> dict:
    """
    Compute full performance metrics from an equity curve.

    Parameters
    ----------
    equity_curve : pd.Series
        Daily portfolio value. Index = DatetimeIndex.

    Returns
    -------
    dict with all metrics.
    """
    eq = equity_curve.dropna()
    if len(eq) < 10:
        return {"error": "insufficient_data"}

    daily_returns = eq.pct_change().dropna()
    n_days = len(eq)

    # Date range
    start = eq.index[0]
    end = eq.index[-1]
    n_years = max((end - start).days / 365.25, 0.1)

    # CAGR
    total_return = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + total_return) ** (1 / n_years) - 1

    # Sharpe ratio (annualised, vs VN FD rate)
    excess_daily = daily_returns - RISK_FREE_RATE / 252
    std_daily = excess_daily.std()
    if std_daily > 1e-8:  # Guard against near-zero std producing extreme values
        sharpe = float(np.clip(
            (excess_daily.mean() / std_daily) * np.sqrt(252), -10, 10
        ))
    else:
        sharpe = 0.0

    # Sortino ratio (only penalise downside vol)
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 1 and downside.std() > 1e-8:
        sortino = float(np.clip(
            (excess_daily.mean() / downside.std()) * np.sqrt(252), -10, 10
        ))
    else:
        sortino = 0.0

    # Max Drawdown
    rolling_max = eq.cummax()
    drawdowns = (eq - rolling_max) / rolling_max
    max_drawdown = float(drawdowns.min())

    # Win rate (% of ACTIVE trading days with positive return)
    # Exclude flat days (equity unchanged = cash, no positions open)
    active_returns = daily_returns[daily_returns.abs() > 1e-6]
    win_rate = float((active_returns > 0).mean()) if len(active_returns) > 0 else 0.0

    # Annual vol
    annual_vol = float(daily_returns.std() * np.sqrt(252))

    # Calmar ratio (CAGR / |Max DD|)
    calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # Monthly returns
    monthly = eq.resample("ME").last().pct_change().dropna()
    avg_monthly = float(monthly.mean())

    return {
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "max_drawdown": round(max_drawdown, 4),
        "annual_vol": round(annual_vol, 4),
        "win_rate": round(win_rate, 4),
        "total_return": round(total_return, 4),
        "n_years": round(n_years, 2),
        "avg_monthly_return": round(avg_monthly, 4),
        "start_date": str(start.date()),
        "end_date": str(end.date()),
    }


def print_scorecard(metrics: dict, title: str = "Performance Scorecard"):
    """Print a Carver-style scorecard with pass/fail ratings."""
    thresholds = {
        "cagr":            (0.045, "CAGR",           "pct",    ">4.5% (bank FD rate)"),
        "sharpe":          (0.40,  "Sharpe Ratio",    "num",    ">0.40 acceptable"),
        "sortino":         (0.50,  "Sortino Ratio",   "num",    ">0.50 good"),
        "max_drawdown":    (-0.30, "Max Drawdown",    "pct",    "> -30% (Carver limit)"),
        "annual_vol":      (0.15,  "Annual Vol",      "pct",    "~15-20% target"),
        "win_rate":        (0.45,  "Win Rate",        "pct",    ">45% acceptable"),
    }

    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"  Period: {metrics.get('start_date', '?')} → {metrics.get('end_date', '?')}")
    print(f"  ({metrics.get('n_years', 0):.1f} years)")
    print(f"{'='*60}")

    for key, (threshold, label, fmt, note) in thresholds.items():
        val = metrics.get(key, 0)
        if key == "max_drawdown":
            passed = val > threshold
        elif key == "annual_vol":
            passed = 0.10 <= val <= 0.30
        else:
            passed = val >= threshold

        status = "✅" if passed else "❌"
        if fmt == "pct":
            val_str = f"{val*100:+.1f}%"
        else:
            val_str = f"{val:.2f}"

        print(f"  {status} {label:<18} {val_str:<10} {note}")

    print(f"\n  Additional:")
    print(f"     Trades/month:  {metrics.get('trades_per_month', '?')}")
    print(f"     Cost drag/yr:  {metrics.get('cost_drag_annual', 0)*100:.1f}%")
    print(f"     Total trades:  {metrics.get('n_trades', '?')}")
    print(f"{'='*60}\n")
