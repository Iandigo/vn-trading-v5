"""
sizing/fixed_risk.py — Fixed Percentage Risk Position Sizing
=============================================================
Martin Luk's position sizing: risk a fixed % of equity per trade.

Formula:
    shares = (equity * risk_pct * risk_mult) / (entry_price - stop_price)

VN Adaptation:
  - Base risk: 0.75% per trade (vs Luk's 0.5% — wider VN daily bars)
  - Drawdown scaling: halve risk when equity drops > 10% from peak
  - Lot size: round DOWN to nearest 100 shares (HOSE)
  - Max position: 10% of equity per stock
  - Max total exposure: 80%
"""

import math


def compute_position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = 0.0075,
    risk_multiplier: float = 1.0,
    peak_equity: float = None,
    drawdown_threshold: float = 0.10,
    risk_drawdown_pct: float = 0.00375,
    lot_size: int = 100,
    max_position_pct: float = 0.10,
) -> dict:
    """
    Compute position size based on fixed risk per trade.

    Parameters
    ----------
    equity : float, current portfolio equity in VND
    entry_price : float, planned entry price
    stop_price : float, initial stop loss price
    risk_pct : float, base risk per trade as decimal (0.0075 = 0.75%)
    risk_multiplier : float, from market health (1.0, 0.5, 0.0)
    peak_equity : float, highest equity seen (for drawdown scaling)
    drawdown_threshold : float, drawdown level to start reducing risk
    risk_drawdown_pct : float, reduced risk during drawdowns
    lot_size : int, HOSE minimum lot size (100)
    max_position_pct : float, max single position as % of equity

    Returns
    -------
    dict with keys:
        shares : int (rounded to lot_size, always >= 0)
        risk_amount : float (VND risked on this trade)
        r_value : float (risk per share = entry - stop)
        position_value : float (shares * entry_price)
        position_pct : float (position_value / equity)
    """
    # Guard against bad inputs
    if (equity <= 0 or entry_price <= 0 or stop_price <= 0 or
            stop_price >= entry_price or risk_multiplier <= 0):
        return _zero_result()

    r_value = entry_price - stop_price
    if r_value <= 0 or math.isnan(r_value) or math.isinf(r_value):
        return _zero_result()

    # Determine effective risk percentage
    effective_risk_pct = risk_pct
    if peak_equity is not None and peak_equity > 0:
        drawdown = (peak_equity - equity) / peak_equity
        if drawdown > drawdown_threshold:
            effective_risk_pct = risk_drawdown_pct

    # Apply market health multiplier
    effective_risk_pct *= risk_multiplier

    # Calculate shares
    risk_amount = equity * effective_risk_pct
    raw_shares = risk_amount / r_value

    # Round DOWN to lot size (conservative)
    shares = int(raw_shares / lot_size) * lot_size

    # Cap at max position size
    max_shares_by_pct = int((equity * max_position_pct) / entry_price / lot_size) * lot_size
    shares = min(shares, max_shares_by_pct)

    # Must be at least 0
    shares = max(shares, 0)

    position_value = shares * entry_price
    position_pct = position_value / equity if equity > 0 else 0.0

    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 0),
        "r_value": round(r_value, 2),
        "position_value": round(position_value, 0),
        "position_pct": round(position_pct, 4),
    }


def check_exposure_limit(current_exposure_value: float, new_position_value: float,
                          equity: float, max_total_exposure: float = 0.80) -> bool:
    """
    Check if adding a new position would exceed the total exposure limit.

    Returns True if the trade is allowed, False if it would breach the limit.
    """
    if equity <= 0:
        return False
    new_total = current_exposure_value + new_position_value
    return (new_total / equity) <= max_total_exposure


def _zero_result() -> dict:
    return {
        "shares": 0,
        "risk_amount": 0.0,
        "r_value": 0.0,
        "position_value": 0.0,
        "position_pct": 0.0,
    }
