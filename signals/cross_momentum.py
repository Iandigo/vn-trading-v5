"""
signals/cross_momentum.py — Signal 2: Cross-Sectional Momentum Rotation
=========================================================================
Logic:
  - Rank all stocks in universe by their 3-month (63 trading day) return
  - Stocks in the top 40% of the universe → positive forecast
  - Stocks in the bottom 40% → negative forecast (reduce/avoid)
  - Middle 20% → neutral (0 forecast, hold if already in position)
  - Rebalance signal monthly (every 21 trading days) to keep costs low

Why 63 days (3 months)?
  - Academic consensus: momentum works best at 3–12 months
  - Shorter → mean reversion dominates; longer → too slow to react
  - 63 = 3 × 21 trading days. Round, economic logic, not optimised.

Why skip last 5 days?
  - Short-term reversal: stocks that surged this week often dip next week
  - Measurement period: day -68 to day -5 (skip the most recent 5 days)

VN adaptation:
  - Only long signals (no shorting on HOSE)
  - Negative forecast = "reduce position / don't enter" not "go short"
  - In BEAR regime: ALL forecasts are set to 0 (no new entries of any kind)
  - Min 5 stocks required to produce a meaningful cross-sectional ranking
"""

import numpy as np
import pandas as pd

from config import CROSS_MOMENTUM, FORECAST_CAP, FORECAST_SCALAR_CROSS_MOM


def get_cross_momentum_forecasts(
    close_matrix: pd.DataFrame,
    as_of_date=None,
    regime: str = "BULL",
) -> pd.Series:
    """
    Compute cross-sectional momentum forecasts for all stocks in the universe.

    Parameters
    ----------
    close_matrix : pd.DataFrame
        Columns = tickers, Index = DatetimeIndex (daily closes).
    as_of_date : datetime-like, optional
        Compute as of this date. Defaults to latest available.
    regime : str
        'BULL' or 'BEAR'. Returns all zeros in BEAR regime.

    Returns
    -------
    pd.Series
        Forecast values in [-20, +20] for each ticker.
        Tickers with insufficient data get forecast = 0.
    """
    lookback = CROSS_MOMENTUM["lookback_days"]     # 63 days
    skip = CROSS_MOMENTUM["skip_recent_days"]       # 5 days
    min_stocks = CROSS_MOMENTUM["min_stocks_for_signal"]  # 5

    prices = close_matrix.sort_index()
    if as_of_date is not None:
        prices = prices[prices.index <= pd.Timestamp(as_of_date)]

    # In BEAR regime: keep top-group rankings (so existing positions aren't all
    # force-exited) but zero out the bottom group entirely. The tau_multiplier
    # (0.5 in BEAR) already halves position sizes — we don't need to also zero
    # all forecasts, which caused 2 full portfolio turnovers per regime flip.
    bear_mode = (regime == "BEAR")

    if len(prices) < lookback + skip + 5:
        return pd.Series(0.0, index=close_matrix.columns)

    # Measurement window: [-(lookback + skip), -skip]
    # e.g., day -68 to day -5 for lookback=63, skip=5
    end_idx = -skip if skip > 0 else len(prices)
    start_idx = end_idx - lookback

    if end_idx == 0:
        end_prices = prices.iloc[-skip]
    else:
        end_prices = prices.iloc[end_idx - 1]

    start_prices = prices.iloc[start_idx - 1]

    # Compute raw return for each stock over the measurement window
    raw_returns = (end_prices - start_prices) / start_prices.replace(0, np.nan)

    # Drop stocks with missing data
    raw_returns = raw_returns.dropna()

    if len(raw_returns) < min_stocks:
        return pd.Series(0.0, index=close_matrix.columns)

    # Rank into percentiles (0 = worst, 1 = best)
    # Use scipy-free percentile rank
    ranks = raw_returns.rank(pct=True)  # 0..1

    # Convert percentile rank to forecast:
    #   top_pct (top 40%)  → positive forecast, scaled up to FORECAST_CAP
    #   bottom_pct (bot 40%) → negative forecast (capped at 0 for VN — no shorting)
    #   middle 20% → 0
    top_threshold = 1.0 - CROSS_MOMENTUM["top_pct"]      # 0.60
    bottom_threshold = CROSS_MOMENTUM["bottom_pct"]        # 0.40

    forecasts = pd.Series(0.0, index=raw_returns.index)

    # Top group: linearly scale from 0 at threshold to FORECAST_CAP at rank=1.0
    top_mask = ranks >= top_threshold
    if top_mask.any():
        top_ranks = ranks[top_mask]
        # Normalise within top group: 0..1
        top_norm = (top_ranks - top_threshold) / (1.0 - top_threshold)
        forecasts[top_mask] = top_norm * FORECAST_CAP

    # Bottom group: penalise weak stocks with negative forecast (reduce/exit)
    # In BEAR regime: zero out bottom group entirely (avoid forced sells that
    # generate cost drag — let positions decay naturally via tau reduction)
    bottom_mask = ranks <= bottom_threshold
    if bottom_mask.any() and not bear_mode:
        bottom_ranks = ranks[bottom_mask]
        bottom_norm = (bottom_threshold - bottom_ranks) / bottom_threshold
        # For VN long-only: clamp negative forecasts at -10 (reduce but not reverse)
        forecasts[bottom_mask] = -bottom_norm * (FORECAST_CAP * 0.5)
    elif bottom_mask.any() and bear_mode:
        forecasts[bottom_mask] = 0.0  # Neutral, not negative — avoids forced exits

    # Align back to full universe — tickers with no data get 0
    full_forecasts = pd.Series(0.0, index=close_matrix.columns)
    full_forecasts.update(forecasts)

    return full_forecasts.clip(-FORECAST_CAP, FORECAST_CAP)


def get_cross_momentum_series(
    close_matrix: pd.DataFrame,
    regime_series: pd.Series,
    update_every: int = 21,
) -> pd.DataFrame:
    """
    Compute cross-sectional momentum forecasts for every date in the matrix.
    Used by the backtest engine.

    Parameters
    ----------
    update_every : int
        Recalculate only every N days (default: 21 = monthly).
        Cross-sectional momentum is a slow signal — monthly rebalance
        keeps transaction costs low and avoids over-trading.

    Returns
    -------
    pd.DataFrame
        Same shape as close_matrix. Values = forecasts in [-20, +20].
    """
    update_every = CROSS_MOMENTUM["rebalance_every_days"]  # 21

    prices = close_matrix.sort_index()
    dates = prices.index
    result = pd.DataFrame(0.0, index=dates, columns=prices.columns)

    last_forecasts = pd.Series(0.0, index=prices.columns)

    for i, date in enumerate(dates):
        regime = regime_series.get(date, "BULL")

        if i % update_every == 0:  # Monthly recalculation
            last_forecasts = get_cross_momentum_forecasts(
                close_matrix=prices[:i + 1],
                regime=regime,
            )

        result.loc[date] = last_forecasts

    return result


def get_universe_momentum_summary(
    close_matrix: pd.DataFrame,
    as_of_date=None,
) -> pd.DataFrame:
    """
    Return a human-readable summary of momentum rankings.
    Used by main.py to print the daily report.
    """
    lookback = CROSS_MOMENTUM["lookback_days"]
    skip = CROSS_MOMENTUM["skip_recent_days"]

    prices = close_matrix.sort_index()
    if as_of_date is not None:
        prices = prices[prices.index <= pd.Timestamp(as_of_date)]

    if len(prices) < lookback + skip + 5:
        return pd.DataFrame()

    end_idx = -skip if skip > 0 else len(prices)
    start_idx = end_idx - lookback

    end_prices = prices.iloc[end_idx - 1]
    start_prices = prices.iloc[start_idx - 1]
    raw_returns = ((end_prices - start_prices) / start_prices).dropna()

    forecasts = get_cross_momentum_forecasts(close_matrix, as_of_date)
    ranks = raw_returns.rank(ascending=False)

    summary = pd.DataFrame({
        "return_3m": raw_returns.map(lambda x: f"{x*100:.1f}%"),
        "rank": ranks.astype(int),
        "forecast": forecasts.map(lambda x: round(x, 1)),
        "signal": forecasts.map(lambda x: "BUY" if x > 5 else ("REDUCE" if x < -3 else "HOLD")),
    }).sort_values("rank")

    return summary
