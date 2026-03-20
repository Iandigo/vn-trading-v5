"""
signals/ma_regime.py — Signal 1: 200-day MA Market Regime Filter
==================================================================
Logic:
  - Compute 200-day simple moving average of VNIndex
  - If index has been BELOW MA200 for >= confirm_days → BEAR regime
  - If index has been ABOVE MA200 for >= confirm_days → BULL regime
  - In BEAR regime: halve position sizing (tau * 0.5) + no new long entries

Why this works for VN:
  - VN institutional funds (mutual funds, insurance) widely watch MA200
  - Creates self-fulfilling support/resistance level
  - US-Iran war (Feb 2026): VNIndex -5.7% → already in BEAR regime
  - Simple filters outperform complex ones in illiquid markets (less overfitting)

What this is NOT:
  - Not a timing signal for individual stocks
  - Not a day-trading signal
  - Not optimised for VN specifically (MA200 = global standard = less curve-fitting)
"""

import numpy as np
import pandas as pd

from config import MA_REGIME


def get_regime(index_prices: pd.Series, as_of_date=None) -> dict:
    """
    Compute the current market regime based on VNIndex vs MA200.

    Parameters
    ----------
    index_prices : pd.Series
        Daily close prices of VNIndex. Index = DatetimeIndex.
    as_of_date : datetime-like, optional
        Compute regime as of this date. Defaults to last available date.

    Returns
    -------
    dict with keys:
        regime        : 'BULL' or 'BEAR'
        ma200         : current MA200 value
        index_close   : current index close
        pct_vs_ma200  : (close - ma200) / ma200
        days_in_regime: consecutive days current regime has been active
        tau_multiplier: multiplier to apply to target_vol
        allow_new_entries: bool — whether to open new positions today
    """
    ma_period = MA_REGIME["ma_period"]           # 200
    confirm_days = MA_REGIME["confirm_days"]      # 3

    if len(index_prices) < ma_period:
        return _default_regime("BULL")

    prices = index_prices.copy().sort_index()
    if as_of_date is not None:
        prices = prices[prices.index <= pd.Timestamp(as_of_date)]

    if len(prices) < ma_period:
        return _default_regime("BULL")

    ma200 = prices.rolling(window=ma_period, min_periods=ma_period).mean()
    ma200 = ma200.dropna()

    if ma200.empty:
        return _default_regime("BULL")

    current_close = float(prices.iloc[-1])
    current_ma200 = float(ma200.iloc[-1])
    pct_vs_ma200 = (current_close - current_ma200) / current_ma200

    # Count consecutive days above/below MA200
    # Align on common index before comparing
    common_idx = prices.index.intersection(ma200.index)
    prices_aligned = prices.loc[common_idx]
    ma200_aligned = ma200.loc[common_idx]
    above_ma = (prices_aligned[-confirm_days * 3:] > ma200_aligned[-confirm_days * 3:])
    above_ma = above_ma.dropna()

    # Check last `confirm_days` are all above or all below
    if len(above_ma) >= confirm_days:
        last_n = above_ma.iloc[-confirm_days:]
        if last_n.all():
            regime = "BULL"
        elif (~last_n).all():
            regime = "BEAR"
        else:
            # Mixed signal — keep previous regime (whipsaw protection)
            # Look back further to determine direction
            prev_above = above_ma.iloc[:-confirm_days]
            if prev_above.empty or prev_above.iloc[-1]:
                regime = "BULL"
            else:
                regime = "BEAR"
    else:
        regime = "BULL"

    # Count consecutive days in current regime
    days_in_regime = _count_consecutive_regime(prices, ma200, regime)

    return {
        "regime": regime,
        "ma200": round(current_ma200, 2),
        "index_close": round(current_close, 2),
        "pct_vs_ma200": round(pct_vs_ma200, 4),
        "days_in_regime": days_in_regime,
        "tau_multiplier": MA_REGIME["bull_tau_multiplier"] if regime == "BULL"
                          else MA_REGIME["bear_tau_multiplier"],
        "allow_new_entries": True if regime == "BULL"
                             else MA_REGIME["bear_new_entries"],
    }


def get_regime_series(index_prices: pd.Series, update_every: int = 5) -> pd.Series:
    """
    Compute regime for every date in index_prices.
    Used by backtest engine.

    Parameters
    ----------
    update_every : int
        Recalculate only every N days (default: 5 = weekly).
        Prevents whipsaw and matches real-world weekly review cadence.
        This is the fix for the v4 engine.py bug (regime was recalculated daily).

    Returns
    -------
    pd.Series with values 'BULL' / 'BEAR', same index as input.
    """
    prices = index_prices.sort_index()
    ma_period = MA_REGIME["ma_period"]

    if len(prices) < ma_period:
        return pd.Series("BULL", index=prices.index)

    regimes = {}
    dates = prices.index[ma_period:]   # Skip warmup period
    last_regime = "BULL"

    for i, date in enumerate(dates):
        if i % update_every == 0:  # Only recalculate weekly
            result = get_regime(prices[:date])
            last_regime = result["regime"]
        regimes[date] = last_regime

    regime_series = pd.Series(regimes)
    # Backfill warmup period with BULL (default)
    full_series = pd.Series("BULL", index=prices.index)
    full_series.update(regime_series)
    return full_series


def get_tau_multiplier_series(index_prices: pd.Series, update_every: int = 5) -> pd.Series:
    """
    Returns a series of tau multipliers (1.0 for BULL, 0.5 for BEAR).
    Convenience wrapper for position sizing in the backtest engine.
    """
    regime_series = get_regime_series(index_prices, update_every=update_every)
    return regime_series.map({
        "BULL": MA_REGIME["bull_tau_multiplier"],
        "BEAR": MA_REGIME["bear_tau_multiplier"],
    })


# ─── Private helpers ──────────────────────────────────────────────────────────

def _count_consecutive_regime(prices: pd.Series, ma200: pd.Series, regime: str) -> int:
    """Count how many consecutive trading days we've been in the current regime."""
    aligned = pd.DataFrame({"price": prices, "ma200": ma200}).dropna()
    if aligned.empty:
        return 0
    above = aligned["price"] > aligned["ma200"]
    target = True if regime == "BULL" else False
    count = 0
    for val in reversed(above.values):
        if val == target:
            count += 1
        else:
            break
    return count


def _default_regime(regime: str) -> dict:
    """Return a default regime dict when insufficient data."""
    return {
        "regime": regime,
        "ma200": None,
        "index_close": None,
        "pct_vs_ma200": None,
        "days_in_regime": 0,
        "tau_multiplier": MA_REGIME["bull_tau_multiplier"],
        "allow_new_entries": True,
    }
