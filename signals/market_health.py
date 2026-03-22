"""
signals/market_health.py — Market Breadth / Leader Count Indicator
===================================================================
Martin Luk tracks how many stocks qualify as "Leaders" (EMA aligned).
When leaders expand → market is strong → take full risk.
When leaders contract → reduce exposure or stop entering.

VN Adaptation:
  - STRONG:   >= 50% of universe are LEAD → full risk (1.0x)
  - CAUTIOUS: 27-49% are LEAD → half risk (0.5x)
  - WEAK:     < 27% are LEAD → no new entries (0.0x)

This supplements the existing MA200 regime filter with a breadth measure.
MA200 is a macro indicator (index-level); leader count is a micro breadth
indicator (stock-level EMA alignment across the universe).
"""

import pandas as pd


def compute_market_health(ema_scans: dict, date, config: dict) -> dict:
    """
    Compute market health based on leader count across the universe.

    Parameters
    ----------
    ema_scans : dict {ticker: DataFrame} from ema_scanner.scan_universe()
    date : datetime-like, the date to check
    config : dict, MARTIN_LUK config

    Returns
    -------
    dict with keys:
        leader_count : int
        total_stocks : int
        leader_pct : float
        health : str ("STRONG", "CAUTIOUS", "WEAK")
        risk_multiplier : float (1.0, 0.5, 0.0)
    """
    strong_pct = config.get("health_strong_pct", 0.50)
    cautious_pct = config.get("health_cautious_pct", 0.27)

    leader_count = 0
    total_stocks = 0

    for ticker, scan_df in ema_scans.items():
        if scan_df is None or scan_df.empty:
            continue
        if date not in scan_df.index:
            continue

        total_stocks += 1
        classification = scan_df.loc[date, "classification"]
        if classification == "LEAD":
            leader_count += 1

    if total_stocks == 0:
        return {
            "leader_count": 0,
            "total_stocks": 0,
            "leader_pct": 0.0,
            "health": "WEAK",
            "risk_multiplier": 0.0,
        }

    leader_pct = leader_count / total_stocks

    if leader_pct >= strong_pct:
        health = "STRONG"
        risk_multiplier = 1.0
    elif leader_pct >= cautious_pct:
        health = "CAUTIOUS"
        risk_multiplier = 0.5
    else:
        health = "WEAK"
        risk_multiplier = 0.0

    return {
        "leader_count": leader_count,
        "total_stocks": total_stocks,
        "leader_pct": round(leader_pct, 3),
        "health": health,
        "risk_multiplier": risk_multiplier,
    }


def compute_market_health_series(ema_scans: dict, dates: pd.DatetimeIndex,
                                  config: dict) -> pd.DataFrame:
    """
    Compute market health for every date in the backtest.

    Returns
    -------
    pd.DataFrame with columns: leader_count, total_stocks, leader_pct,
                               health, risk_multiplier
    """
    records = []
    for date in dates:
        h = compute_market_health(ema_scans, date, config)
        h["date"] = date
        records.append(h)

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.set_index("date")
    return df
