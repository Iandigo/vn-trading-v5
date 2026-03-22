"""
signals/breakout_detector.py — Daily Breakout Detection
========================================================
Martin Luk's entry patterns adapted for VN30 daily bars.

Three breakout patterns:
  1. Prior High Breakout: close > yesterday's high (most common)
  2. Inside Day Breakout: yesterday was inside day, today breaks above
  3. EMA Convergence Breakout: tight EMA spread + price breaks above all EMAs

All patterns require:
  - Stock classified as LEAD (EMA 9 > 21 > 50)
  - Confirmation via CLOSE above level (not just intraday high)
  - ADR above minimum threshold

Stop price calculation:
  - Default: low of breakout day
  - If distance > half ADR in price terms: use entry - (ADR_price / 2)
  - Absolute cap: 5% below entry price
"""

import numpy as np
import pandas as pd


def detect_prior_high_breakout(ohlcv: pd.DataFrame, idx: int) -> dict:
    """
    Check if today's close breaks above yesterday's high.

    Parameters
    ----------
    ohlcv : pd.DataFrame with columns: open, high, low, close
    idx : int, index position for today (must be >= 1)

    Returns
    -------
    dict with triggered, pattern, entry_price, day_low
    """
    if idx < 1:
        return {"triggered": False}

    today_close = float(ohlcv.iloc[idx]["close"])
    yesterday_high = float(ohlcv.iloc[idx - 1]["high"])
    today_low = float(ohlcv.iloc[idx]["low"])

    if today_close > yesterday_high:
        return {
            "triggered": True,
            "pattern": "prior_high",
            "entry_price": today_close,
            "day_low": today_low,
        }
    return {"triggered": False}


def detect_inside_day_breakout(ohlcv: pd.DataFrame, idx: int) -> dict:
    """
    Check for inside day breakout pattern.
    Yesterday's range is contained within the day before's range,
    and today closes above yesterday's high.

    Parameters
    ----------
    ohlcv : pd.DataFrame
    idx : int, index position for today (must be >= 2)

    Returns
    -------
    dict with triggered, pattern, entry_price, day_low
    """
    if idx < 2:
        return {"triggered": False}

    today = ohlcv.iloc[idx]
    yesterday = ohlcv.iloc[idx - 1]
    day_before = ohlcv.iloc[idx - 2]

    # Check if yesterday was an inside day
    yesterday_inside = (
        float(yesterday["high"]) <= float(day_before["high"]) and
        float(yesterday["low"]) >= float(day_before["low"])
    )

    if not yesterday_inside:
        return {"triggered": False}

    # Today must close above yesterday's high
    if float(today["close"]) > float(yesterday["high"]):
        return {
            "triggered": True,
            "pattern": "inside_day",
            "entry_price": float(today["close"]),
            "day_low": float(today["low"]),
        }
    return {"triggered": False}


def detect_ema_convergence_breakout(ohlcv: pd.DataFrame, idx: int,
                                     ema_scan: pd.DataFrame,
                                     convergence_pct: float = 0.015) -> dict:
    """
    Check for EMA convergence breakout.
    EMAs must be within convergence_pct of each other, and today's close
    must break above all three EMAs.

    Parameters
    ----------
    ohlcv : pd.DataFrame
    idx : int, index position for today
    ema_scan : pd.DataFrame from ema_scanner.scan_single_stock()
    convergence_pct : float, max EMA spread for convergence (default 1.5%)

    Returns
    -------
    dict with triggered, pattern, entry_price, day_low
    """
    if idx < 1 or ema_scan is None or ema_scan.empty:
        return {"triggered": False}

    date = ohlcv.index[idx]
    if date not in ema_scan.index:
        return {"triggered": False}

    scan_row = ema_scan.loc[date]
    ema_spread = float(scan_row.get("ema_spread", 1.0))
    ema_9 = float(scan_row.get("ema_9", 0))
    ema_21 = float(scan_row.get("ema_21", 0))
    ema_50 = float(scan_row.get("ema_50", 0))

    if np.isnan(ema_spread) or np.isnan(ema_9):
        return {"triggered": False}

    today_close = float(ohlcv.iloc[idx]["close"])
    today_low = float(ohlcv.iloc[idx]["low"])

    # EMAs must be converged (tight spread)
    if ema_spread > convergence_pct:
        return {"triggered": False}

    # Close must be above all three EMAs
    max_ema = max(ema_9, ema_21, ema_50)
    if today_close > max_ema:
        return {
            "triggered": True,
            "pattern": "ema_convergence",
            "entry_price": today_close,
            "day_low": today_low,
        }
    return {"triggered": False}


def compute_stop_price(entry_price: float, day_low: float,
                       adr_pct: float, max_stop_pct: float = 0.05) -> float:
    """
    Compute stop price for a breakout entry.

    Logic:
      1. Default stop = low of breakout day
      2. If (entry - low) > half of ADR in price: use entry - (ADR/2 in price)
      3. Cap at max_stop_pct below entry (default 5%)

    Parameters
    ----------
    entry_price : float
    day_low : float, low of the breakout day
    adr_pct : float, ADR as decimal (e.g., 0.03 for 3%)
    max_stop_pct : float, absolute max distance from entry (default 0.05 = 5%)

    Returns
    -------
    float, stop price
    """
    if entry_price <= 0 or np.isnan(entry_price):
        return entry_price * 0.95

    adr_price = entry_price * max(adr_pct, 0.005)  # floor ADR at 0.5%
    half_adr_price = adr_price / 2.0

    # Default stop = day low
    stop = day_low

    # If distance is too wide (> half ADR), tighten
    distance = entry_price - stop
    if distance > half_adr_price:
        stop = entry_price - half_adr_price

    # If distance is too tight (< 1% of entry), widen to half ADR
    # Prevents absurdly small R-values on narrow-range breakout days
    min_distance = max(half_adr_price, entry_price * 0.01)
    if (entry_price - stop) < min_distance:
        stop = entry_price - min_distance

    # Absolute cap (stop can't be more than max_stop_pct below entry)
    min_stop = entry_price * (1 - max_stop_pct)
    stop = max(stop, min_stop)

    # Stop must be below entry
    if stop >= entry_price:
        stop = entry_price * (1 - max_stop_pct)

    return stop


def detect_breakouts(ohlcv: pd.DataFrame, idx: int,
                     ema_scan: pd.DataFrame,
                     classification: str,
                     adr: float,
                     config: dict) -> dict:
    """
    Run all breakout detection patterns for a single stock on a single day.

    Parameters
    ----------
    ohlcv : pd.DataFrame
    idx : int, today's index position
    ema_scan : pd.DataFrame from ema_scanner
    classification : str, EMA classification ("LEAD", "WEAKENING", "LAGGARD")
    adr : float, current ADR percentage
    config : dict, MARTIN_LUK config dict

    Returns
    -------
    dict with keys:
        triggered : bool
        pattern : str (which pattern fired)
        entry_price : float
        stop_price : float
        r_value : float (entry - stop, risk per share)
    """
    # Only trade LEAD stocks
    if classification != "LEAD":
        return {"triggered": False}

    # ADR filter
    adr_min = config.get("adr_min_pct", 0.025)
    if np.isnan(adr) or adr < adr_min:
        return {"triggered": False}

    max_stop_pct = config.get("max_stop_pct", 0.05)
    convergence_pct = config.get("ema_convergence_pct", 0.015)

    # Try each pattern in priority order
    # 1. Inside day breakout (highest quality)
    if config.get("inside_day_enabled", True):
        result = detect_inside_day_breakout(ohlcv, idx)
        if result["triggered"]:
            stop = compute_stop_price(result["entry_price"], result["day_low"],
                                       adr, max_stop_pct)
            r_value = result["entry_price"] - stop
            return {
                "triggered": True,
                "pattern": result["pattern"],
                "entry_price": result["entry_price"],
                "stop_price": stop,
                "r_value": r_value,
            }

    # 2. EMA convergence breakout
    result = detect_ema_convergence_breakout(ohlcv, idx, ema_scan, convergence_pct)
    if result["triggered"]:
        stop = compute_stop_price(result["entry_price"], result["day_low"],
                                   adr, max_stop_pct)
        r_value = result["entry_price"] - stop
        return {
            "triggered": True,
            "pattern": result["pattern"],
            "entry_price": result["entry_price"],
            "stop_price": stop,
            "r_value": r_value,
        }

    # 3. Prior high breakout (most common, lowest priority)
    if config.get("breakout_confirm_close", True):
        result = detect_prior_high_breakout(ohlcv, idx)
        if result["triggered"]:
            stop = compute_stop_price(result["entry_price"], result["day_low"],
                                       adr, max_stop_pct)
            r_value = result["entry_price"] - stop
            return {
                "triggered": True,
                "pattern": result["pattern"],
                "entry_price": result["entry_price"],
                "stop_price": stop,
                "r_value": r_value,
            }

    return {"triggered": False}
