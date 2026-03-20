"""
sizing/position.py — Signal 4: Volatility-Scaled Position Sizing
==================================================================
Implements the Carver formula with VN-specific adjustments:

  Optimal Shares = (Capital × IDM × weight × forecast/10 × τ)
                   / (price × annual_vol)

VN adjustments vs standard Carver:
  1. τ = 0.25 (raised from 0.20 — VN high correlation causes undersizing)
  2. IDM table: lower values (VN correlation ~0.6 vs ~0.35 in developed mkts)
  3. Lot size: round to nearest 100 shares (HOSE minimum)
  4. Bear regime: multiply τ by 0.5 (regime filter output)
  5. Max position cap: 15% of capital per stock (concentration risk)
  6. Buffer zone: 20% band around optimal (reduces 69 trades/month → ~25)

Volatility estimation:
  - Use 20-day realised vol (captures recent regime)
  - Annualise with sqrt(252) — VN has ~250 trading days/year
  - Floor at 0.10 (10%) — prevents infinite position on low-vol days
  - Ceiling at 1.00 (100%) — prevents near-zero position on crisis days
"""

import numpy as np
import pandas as pd

from config import SIZING, COSTS


# IDM table (VN-calibrated, lower than Carver standard due to high correlation)
IDM_TABLE = SIZING["idm_table"]


def get_annual_vol(close_series: pd.Series, lookback: int = None) -> float:
    """
    Compute annualised volatility from daily close prices.

    Parameters
    ----------
    close_series : pd.Series   Daily close prices, most recent last
    lookback : int             Days of returns to use (20 = ~1 month)

    Returns
    -------
    float   Annualised vol (e.g., 0.30 for 30%)
    """
    if lookback is None:
        lookback = SIZING.get("vol_lookback", 60)

    if len(close_series) < lookback + 1:
        return 0.30  # Conservative default if insufficient data

    recent = close_series.tail(lookback + 1)
    daily_returns = recent.pct_change().dropna()

    if len(daily_returns) < 5:
        return 0.30

    daily_vol = float(daily_returns.std())
    annual_vol = daily_vol * np.sqrt(252)

    # Clamp: floor at 10%, ceiling at 100%
    return float(np.clip(annual_vol, 0.10, 1.00))


def get_idm(n_stocks: int) -> float:
    """
    Instrument Diversification Multiplier (VN-calibrated).
    Interpolates between table values for unlisted sizes.
    """
    if n_stocks <= 0:
        return 1.0

    keys = sorted(IDM_TABLE.keys())

    if n_stocks <= keys[0]:
        return IDM_TABLE[keys[0]]
    if n_stocks >= keys[-1]:
        return IDM_TABLE[keys[-1]]

    # Linear interpolation between nearest two table entries
    for i in range(len(keys) - 1):
        if keys[i] <= n_stocks <= keys[i + 1]:
            lo, hi = keys[i], keys[i + 1]
            t = (n_stocks - lo) / (hi - lo)
            return IDM_TABLE[lo] + t * (IDM_TABLE[hi] - IDM_TABLE[lo])

    return 1.40  # Safe fallback


def optimal_shares(
    capital: float,
    forecast: float,
    price: float,
    annual_vol: float,
    n_stocks: int,
    tau_multiplier: float = 1.0,
) -> int:
    """
    Compute optimal position size in shares (Carver formula, VN-adjusted).

    Parameters
    ----------
    capital       : float   Total trading capital in VND
    forecast      : float   Combined forecast [-20, +20]
    price         : float   Current stock price in VND
    annual_vol    : float   Annualised volatility (e.g., 0.30)
    n_stocks      : int     Number of stocks in current portfolio
    tau_multiplier: float   1.0 = BULL, 0.5 = BEAR (from regime filter)

    Returns
    -------
    int   Optimal number of shares (rounded to nearest lot of 100).
          Always >= 0 (no short positions).
    """
    tau = SIZING["target_vol"] * tau_multiplier   # e.g., 0.25 * 1.0 = 0.25
    idm = get_idm(n_stocks)
    weight = 1.0 / max(n_stocks, 1)

    # Guard against any NaN/inf inputs — return 0 (no position) rather than crash
    import math
    if any(
        v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
        for v in [capital, forecast, price, annual_vol]
    ):
        return 0
    if price <= 0 or annual_vol <= 0 or capital <= 0:
        return 0

    # Carver formula
    raw_shares = (capital * idm * weight * (forecast / 10.0) * tau) / (price * annual_vol)

    # Round to nearest lot (100 shares minimum on HOSE)
    lot = SIZING["lot_size"]  # 100
    # Guard again after calculation — division can still produce NaN if inputs are edge cases
    if math.isnan(raw_shares) or math.isinf(raw_shares):
        return 0
    raw_shares = max(raw_shares, 0)  # VN: no short positions
    rounded = int(round(raw_shares / lot) * lot)

    # Cap at max_position_pct of capital
    max_shares = int((capital * SIZING["max_position_pct"]) / price / lot) * lot
    rounded = min(rounded, max_shares)

    return rounded


def check_buffer(
    current_shares: int,
    optimal_shares_val: int,
) -> dict:
    """
    Determine whether a trade is needed based on the buffer zone.

    Buffer = 20% around optimal. Only trade if current is OUTSIDE the zone.
    This is the key mechanism that reduces ~69 trades/month → ~25.

    Parameters
    ----------
    current_shares   : int   Current holding
    optimal_shares_val : int   Target position from Carver formula

    Returns
    -------
    dict with keys:
        should_trade : bool
        target_shares : int    (what to trade TO if should_trade)
        current_shares : int
        optimal_shares : int
        lower_bound : int
        upper_bound : int
        reason : str
    """
    buf = SIZING["buffer_fraction"]  # 0.20

    if optimal_shares_val == 0:
        if current_shares > 0:
            return {
                "should_trade": True,
                "target_shares": 0,
                "current_shares": current_shares,
                "optimal_shares": 0,
                "lower_bound": 0,
                "upper_bound": 0,
                "reason": "forecast_zero_exit",
            }
        return _no_trade(current_shares, 0)

    lower = int(optimal_shares_val * (1 - buf))
    upper = int(optimal_shares_val * (1 + buf))

    # Round bounds to lot size too
    lot = SIZING["lot_size"]
    lower = int(lower / lot) * lot
    upper = int((upper + lot - 1) / lot) * lot

    if lower <= current_shares <= upper:
        return _no_trade(current_shares, optimal_shares_val, lower, upper)

    # Carver "trade to edge" rule: instead of trading all the way to optimal,
    # trade to the NEAREST buffer edge. This minimises trade size and keeps
    # the position inside the band longer → far fewer follow-up trades.
    # Before: current=800, optimal=1200, buffer=[900,1500] → trade to 1200 (delta 400)
    # After:  current=800 → trade to 900 (delta 100). Much smaller, stays in band.
    if current_shares < lower:
        target = lower  # Under-weight: trade up to lower edge
    elif current_shares > upper:
        target = upper  # Over-weight: trade down to upper edge
    else:
        target = optimal_shares_val  # Shouldn't reach here, but safe fallback

    # Round target to lot size
    target = int(round(target / lot) * lot)

    # Skip if rounding eliminated the trade
    if target == current_shares:
        return _no_trade(current_shares, optimal_shares_val, lower, upper)

    return {
        "should_trade": True,
        "target_shares": target,
        "current_shares": current_shares,
        "optimal_shares": optimal_shares_val,
        "lower_bound": lower,
        "upper_bound": upper,
        "reason": "outside_buffer",
    }


def get_trade_cost(shares_delta: int, price: float) -> float:
    """
    Estimate transaction cost for a trade.
    TCBS: ~0.25% per side (brokerage 0.15% + stamp/tax).
    """
    trade_value = abs(shares_delta) * price
    return trade_value * COSTS["cost_per_trade_pct"]


def get_position_summary(
    capital: float,
    holdings: dict,
    forecasts: pd.Series,
    prices: pd.Series,
    ohlcv_dict: dict,
    regime: str = "BULL",
    tau_multiplier: float = 1.0,
) -> pd.DataFrame:
    """
    Full position sizing report for the daily workflow.
    Shows current vs optimal for each stock, and whether to trade.

    Parameters
    ----------
    capital   : float   Total capital
    holdings  : dict    {ticker: current_shares}
    forecasts : pd.Series  {ticker: combined_forecast}
    prices    : pd.Series  {ticker: latest_close}
    ohlcv_dict: dict    {ticker: ohlcv_df}
    regime    : str
    tau_multiplier: float

    Returns
    -------
    pd.DataFrame with one row per stock
    """
    n_stocks = len([t for t, f in forecasts.items() if f > 0])
    n_stocks = max(n_stocks, 1)

    rows = []
    for ticker in forecasts.index:
        forecast = float(forecasts.get(ticker, 0.0))
        price = float(prices.get(ticker, 0.0))
        current = int(holdings.get(ticker, 0))

        if price <= 0:
            continue

        ohlcv = ohlcv_dict.get(ticker, pd.DataFrame())
        ann_vol = get_annual_vol(ohlcv["close"]) if not ohlcv.empty else 0.30

        optimal = optimal_shares(
            capital=capital,
            forecast=forecast,
            price=price,
            annual_vol=ann_vol,
            n_stocks=n_stocks,
            tau_multiplier=tau_multiplier,
        )

        buffer_check = check_buffer(current, optimal)
        trade_shares = (buffer_check["target_shares"] - current) if buffer_check["should_trade"] else 0
        trade_cost = get_trade_cost(trade_shares, price) if trade_shares != 0 else 0.0

        rows.append({
            "ticker": ticker,
            "forecast": round(forecast, 1),
            "current_shares": current,
            "optimal_shares": optimal,
            "trade_shares": trade_shares,
            "action": "BUY" if trade_shares > 0 else ("SELL" if trade_shares < 0 else "HOLD"),
            "price": price,
            "annual_vol": f"{ann_vol*100:.0f}%",
            "trade_cost_vnd": round(trade_cost),
            "should_trade": buffer_check["should_trade"],
            "reason": buffer_check.get("reason", ""),
        })

    return pd.DataFrame(rows)


# ─── Private helpers ──────────────────────────────────────────────────────────

def _no_trade(current, optimal, lower=None, upper=None):
    return {
        "should_trade": False,
        "target_shares": current,
        "current_shares": current,
        "optimal_shares": optimal,
        "lower_bound": lower,
        "upper_bound": upper,
        "reason": "within_buffer",
    }
