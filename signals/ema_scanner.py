"""
signals/ema_scanner.py — EMA Alignment Scanner + ADR Calculation
=================================================================
Martin Luk's stock classification system adapted for VN30 daily bars.

EMA Classification:
  - LEAD:      EMA(9) > EMA(21) > EMA(50) — strong uptrend, eligible for entry
  - WEAKENING: EMA(9) < EMA(21), both > EMA(50) — momentum fading, hold only
  - LAGGARD:   EMA(50) above either shorter EMA — downtrend, avoid/exit

ADR (Average Daily Range):
  - 20-day rolling average of (high - low) / close
  - Luk uses >5% for US stocks; VN30 blue chips need >2.5% threshold
  - Stocks with very low ADR produce oversized positions with fixed-risk sizing

EMA Spread:
  - (max(EMAs) - min(EMAs)) / close
  - Used to detect EMA convergence — tight spread = potential breakout setup
"""

import numpy as np
import pandas as pd


def compute_emas(close_series: pd.Series, periods: tuple = (9, 21, 50)) -> pd.DataFrame:
    """
    Compute multiple EMAs for a single stock's close prices.

    Returns DataFrame with columns: ema_9, ema_21, ema_50
    """
    result = pd.DataFrame(index=close_series.index)
    for p in periods:
        result[f"ema_{p}"] = close_series.ewm(span=p, adjust=False).mean()
    return result


def classify_ema_alignment(ema_9: float, ema_21: float, ema_50: float) -> str:
    """
    Classify a stock's trend based on EMA alignment.

    LEAD:      9 > 21 > 50 (strong uptrend)
    WEAKENING: 9 < 21 but both > 50 (losing momentum)
    LAGGARD:   anything else (downtrend or no trend)
    """
    if ema_9 > ema_21 > ema_50:
        return "LEAD"
    elif ema_9 < ema_21 and ema_21 > ema_50 and ema_9 > ema_50:
        return "WEAKENING"
    else:
        return "LAGGARD"


def compute_adr(ohlcv: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Compute Average Daily Range as a percentage of close price.

    ADR% = rolling_mean((high - low) / close, period)

    Parameters
    ----------
    ohlcv : pd.DataFrame with columns high, low, close
    period : int, rolling window (default 20 days)

    Returns
    -------
    pd.Series of ADR percentages (e.g., 0.03 = 3%)
    """
    daily_range_pct = (ohlcv["high"] - ohlcv["low"]) / ohlcv["close"].replace(0, np.nan)
    return daily_range_pct.rolling(period, min_periods=max(period // 2, 1)).mean()


def compute_ema_spread(ema_9: pd.Series, ema_21: pd.Series, ema_50: pd.Series,
                       close: pd.Series) -> pd.Series:
    """
    Compute EMA spread as percentage of close price.
    Tight spread indicates convergence — potential breakout setup.
    """
    ema_max = pd.concat([ema_9, ema_21, ema_50], axis=1).max(axis=1)
    ema_min = pd.concat([ema_9, ema_21, ema_50], axis=1).min(axis=1)
    return (ema_max - ema_min) / close.replace(0, np.nan)


def scan_single_stock(ohlcv: pd.DataFrame, ema_periods: tuple = (9, 21, 50),
                      adr_period: int = 20) -> pd.DataFrame:
    """
    Compute full EMA alignment scan for a single stock.

    Parameters
    ----------
    ohlcv : pd.DataFrame with columns: open, high, low, close, volume
    ema_periods : tuple of EMA periods (default: 9, 21, 50)
    adr_period : int, ADR rolling window

    Returns
    -------
    pd.DataFrame with columns:
        ema_9, ema_21, ema_50, classification, ema_spread, adr
    """
    close = ohlcv["close"]
    emas = compute_emas(close, ema_periods)

    # Classification per day
    classifications = []
    for idx in emas.index:
        e9 = float(emas.loc[idx, f"ema_{ema_periods[0]}"])
        e21 = float(emas.loc[idx, f"ema_{ema_periods[1]}"])
        e50 = float(emas.loc[idx, f"ema_{ema_periods[2]}"])
        if np.isnan(e9) or np.isnan(e21) or np.isnan(e50):
            classifications.append("LAGGARD")
        else:
            classifications.append(classify_ema_alignment(e9, e21, e50))

    emas["classification"] = classifications
    emas["ema_spread"] = compute_ema_spread(
        emas[f"ema_{ema_periods[0]}"],
        emas[f"ema_{ema_periods[1]}"],
        emas[f"ema_{ema_periods[2]}"],
        close,
    )
    emas["adr"] = compute_adr(ohlcv, period=adr_period)

    return emas


def scan_universe(ohlcv_dict: dict, ema_periods: tuple = (9, 21, 50),
                  adr_period: int = 20) -> dict:
    """
    Compute EMA alignment scan for all stocks in the universe.

    Parameters
    ----------
    ohlcv_dict : dict {ticker: ohlcv_df}
    ema_periods : tuple of EMA periods
    adr_period : int, ADR rolling window

    Returns
    -------
    dict {ticker: DataFrame} where each DataFrame has columns:
        ema_9, ema_21, ema_50, classification, ema_spread, adr
    """
    results = {}
    for ticker, ohlcv in ohlcv_dict.items():
        if ohlcv is None or ohlcv.empty:
            continue
        results[ticker] = scan_single_stock(ohlcv, ema_periods, adr_period)
    return results
