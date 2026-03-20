"""
signals/combined.py — Combine All Signals Into Final Forecast
==============================================================
Combines:
  - Signal 1 (MA Regime): FILTER only — modifies tau, blocks new entries
  - Signal 2 (Cross Momentum): 55% weight
  - Signal 3 (IBS): 15% weight

Note: Signal weights sum to 0.70, not 1.0.
The remaining 0.30 represents "no signal" — cash/flat exposure.
FDM (1.20) compensates for the correlation structure between signals.

FDM derivation (simplified Carver method):
  Cross Momentum vs IBS correlation ≈ -0.3 (counter-trend vs trend)
  With 2 signals, weights [0.55, 0.15]:
  Portfolio variance ≈ 0.55² + 0.15² + 2×0.55×0.15×(-0.3) = 0.294
  FDM = 1 / sqrt(0.294) ≈ 1.84  (theoretical)
  Conservative VN estimate: 1.20 (less diversification in illiquid market)

All forecasts are clipped to [-20, +20] — Carver standard.
"""

import numpy as np
import pandas as pd

from config import SIGNAL_WEIGHTS, FDM, FORECAST_CAP


def combine_forecasts(
    cross_momentum_forecast: float,
    ibs_forecast: float,
    regime: str = "BULL",
) -> dict:
    """
    Combine individual signal forecasts into a single trading forecast.

    Parameters
    ----------
    cross_momentum_forecast : float   [-20, +20]
    ibs_forecast : float              [-20, +20]
    regime : str                      'BULL' or 'BEAR'

    Returns
    -------
    dict with keys:
        combined_forecast : float in [-20, +20]
        cross_mom_contrib : contribution from cross momentum
        ibs_contrib       : contribution from IBS
        regime            : current regime
        trading_allowed   : whether regime permits new entries
    """
    w_cm = SIGNAL_WEIGHTS["cross_momentum"]   # 0.55
    w_ibs = SIGNAL_WEIGHTS["ibs"]              # 0.15

    cross_mom_contrib = w_cm * cross_momentum_forecast
    ibs_contrib = w_ibs * ibs_forecast

    raw_combined = cross_mom_contrib + ibs_contrib
    combined = raw_combined * FDM

    combined = float(np.clip(combined, -FORECAST_CAP, FORECAST_CAP))

    # In BEAR regime: keep existing positions but no new longs
    # (sizing module will respect this — new entries get 0 forecast)
    from config import MA_REGIME
    trading_allowed = True if regime == "BULL" else MA_REGIME["bear_new_entries"]

    return {
        "combined_forecast": combined,
        "cross_mom_contrib": round(cross_mom_contrib, 2),
        "ibs_contrib": round(ibs_contrib, 2),
        "fdm_applied": FDM,
        "regime": regime,
        "trading_allowed": trading_allowed,
    }


def get_all_forecasts(
    ticker: str,
    close_matrix: pd.DataFrame,
    ohlcv_dict: dict,
    regime: str = "BULL",
    as_of_date=None,
) -> dict:
    """
    High-level: compute all signals and combine for a single stock.
    Used by main.py for the daily report.

    Parameters
    ----------
    ticker : str
    close_matrix : pd.DataFrame   All stocks' close prices
    ohlcv_dict : dict             {ticker: ohlcv_df}
    regime : str
    as_of_date : datetime-like, optional

    Returns
    -------
    dict with full signal breakdown + combined forecast
    """
    from signals.cross_momentum import get_cross_momentum_forecasts
    from signals.ibs import get_ibs_forecast

    # Get cross-sectional momentum for the whole universe, then extract this ticker
    cm_forecasts = get_cross_momentum_forecasts(
        close_matrix=close_matrix,
        as_of_date=as_of_date,
        regime=regime,
    )
    cm_forecast = float(cm_forecasts.get(ticker, 0.0))

    # IBS for this specific stock
    ohlcv = ohlcv_dict.get(ticker, pd.DataFrame())
    ibs_forecast = get_ibs_forecast(ohlcv, as_of_date=as_of_date, regime=regime)

    result = combine_forecasts(
        cross_momentum_forecast=cm_forecast,
        ibs_forecast=ibs_forecast,
        regime=regime,
    )
    result["ticker"] = ticker
    result["cross_mom_raw"] = round(cm_forecast, 2)
    result["ibs_raw"] = round(ibs_forecast, 2)

    return result


def get_all_forecasts_universe(
    close_matrix: pd.DataFrame,
    ohlcv_dict: dict,
    regime: str = "BULL",
    as_of_date=None,
) -> pd.DataFrame:
    """
    Compute combined forecasts for the entire universe.
    Returns DataFrame with one row per ticker.
    """
    from signals.cross_momentum import get_cross_momentum_forecasts
    from signals.ibs import get_ibs_forecasts_multi

    cm_forecasts = get_cross_momentum_forecasts(
        close_matrix=close_matrix,
        as_of_date=as_of_date,
        regime=regime,
    )

    ibs_forecasts = get_ibs_forecasts_multi(
        ohlcv_dict=ohlcv_dict,
        as_of_date=as_of_date,
        regime=regime,
    )

    rows = []
    for ticker in close_matrix.columns:
        cm_f = float(cm_forecasts.get(ticker, 0.0))
        ibs_f = float(ibs_forecasts.get(ticker, 0.0))
        result = combine_forecasts(cm_f, ibs_f, regime)
        rows.append({
            "ticker": ticker,
            "forecast": result["combined_forecast"],
            "cross_mom": cm_f,
            "ibs": ibs_f,
            "regime": regime,
        })

    return pd.DataFrame(rows).set_index("ticker")
