"""
main.py — Daily Workflow (run every morning before 9am)
=========================================================
Usage:
    python main.py                        # Live mode, fetch real data
    python main.py --n 10                 # Use 10 stocks from universe
    python main.py --capital 500000000    # Set capital in VND
    python main.py --test                 # Mock data, no internet needed
    python main.py --regime BEAR          # Force regime override

Output:
    1. Current regime banner (BULL/BEAR + VNIndex vs MA200)
    2. Cross-momentum ranking table (all universe stocks)
    3. IBS signals (stocks near daily low = buy candidates)
    4. Position sizing recommendations (what to buy/sell/hold)
    5. Estimated transaction costs for today's trades
"""

import argparse
import sys
from datetime import datetime, timedelta

import pandas as pd

from config import UNIVERSE, VNINDEX_TICKER, DATA, SIZING


def run_daily(
    n_stocks: int = 15,
    capital: float = 500_000_000,
    regime_override: str = None,
    use_mock: bool = False,
):
    print("\n" + "=" * 60)
    print("  VN Trading Framework v5 — Daily Report")
    print(f"  {datetime.now().strftime('%A, %d %B %Y %H:%M')}")
    print("=" * 60)

    universe = UNIVERSE[:n_stocks]
    end_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=DATA["min_history_days"] + 50)

    # ── Fetch data ────────────────────────────────────────────────────────────
    if use_mock:
        close_matrix, ohlcv_dict, index_prices = _generate_mock_data(universe, start_date, end_date)
    else:
        from data.fetcher import fetch_close_matrix, fetch_multi
        print("\n  Fetching market data...")
        close_matrix = fetch_close_matrix(universe, start_date, end_date)

        if close_matrix.empty:
            print("  ❌ No market data available. Check internet connection.")
            sys.exit(1)

        ohlcv_dict = fetch_multi(universe, start_date, end_date, verbose=False)

        # Fetch VNIndex
        from data.fetcher import fetch_index_prices
        from config import VNINDEX_FALLBACK_TICKERS
        index_prices = fetch_index_prices(
            VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS, start_date, end_date, close_matrix
        )

    print(f"  ✅ Data loaded: {len(close_matrix.columns)} stocks, {len(close_matrix)} days\n")

    # ── Signal 1: Regime ──────────────────────────────────────────────────────
    from signals.ma_regime import get_regime

    if regime_override:
        regime_result = {
            "regime": regime_override.upper(),
            "ma200": None,
            "index_close": None,
            "pct_vs_ma200": None,
            "days_in_regime": 0,
            "tau_multiplier": 0.5 if regime_override.upper() == "BEAR" else 1.0,
            "allow_new_entries": regime_override.upper() == "BULL",
        }
        print(f"  ⚠️  REGIME OVERRIDE: {regime_override.upper()}")
    else:
        regime_result = get_regime(index_prices)

    regime = regime_result["regime"]
    tau_mult = regime_result["tau_multiplier"]
    effective_tau = SIZING["target_vol"] * tau_mult

    regime_icon = "🟢" if regime == "BULL" else "🔴"
    print(f"  {regime_icon} MARKET REGIME: {regime}")
    if regime_result["ma200"]:
        pct = regime_result['pct_vs_ma200'] * 100
        sign = "+" if pct >= 0 else ""
        print(f"     VNIndex: {regime_result['index_close']:.0f}  |  MA200: {regime_result['ma200']:.0f}  |  Diff: {sign}{pct:.1f}%")
        print(f"     In this regime for {regime_result['days_in_regime']} trading days")
    print(f"     Effective τ: {effective_tau*100:.0f}%  (base {SIZING['target_vol']*100:.0f}% × {tau_mult})")
    if not regime_result["allow_new_entries"]:
        print(f"     ⛔  BEAR REGIME: No new long entries today")

    # ── Signal 2: Cross-sectional momentum ────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  📊 CROSS-SECTIONAL MOMENTUM RANKING")
    print(f"  (3-month return ranking, skip last 5 days)")
    print(f"{'─'*60}")

    from signals.cross_momentum import get_universe_momentum_summary
    mom_summary = get_universe_momentum_summary(close_matrix)

    if not mom_summary.empty:
        print(f"  {'Ticker':<10} {'3M Return':<12} {'Rank':<6} {'Forecast':<10} {'Signal'}")
        print(f"  {'─'*8} {'─'*10} {'─'*4} {'─'*8} {'─'*8}")
        for ticker, row in mom_summary.iterrows():
            icon = "🟢" if row["signal"] == "BUY" else ("🔴" if row["signal"] == "REDUCE" else "⚪")
            print(f"  {ticker:<10} {row['return_3m']:<12} {row['rank']:<6} {row['forecast']:<10} {icon} {row['signal']}")

    # ── Signal 3: IBS ─────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  📉 IBS MEAN REVERSION SIGNALS")
    print(f"  (Today's oversold / overbought readings)")
    print(f"{'─'*60}")

    from signals.ibs import get_ibs_forecasts_multi, get_ibs_series

    ibs_forecasts = get_ibs_forecasts_multi(ohlcv_dict, regime=regime)
    active_ibs = [(t, f) for t, f in ibs_forecasts.items() if abs(f) > 0.5]

    if active_ibs:
        for ticker, forecast in sorted(active_ibs, key=lambda x: -abs(x[1])):
            ohlcv = ohlcv_dict.get(ticker)
            if ohlcv is not None and not ohlcv.empty:
                ibs_val = get_ibs_series(ohlcv).iloc[-1]
                direction = "🟢 OVERSOLD" if forecast > 0 else "🟡 OVERBOUGHT"
                print(f"  {ticker:<10} IBS={ibs_val:.2f}   Forecast={forecast:+.1f}   {direction}")
    else:
        print("  No IBS signals active today (all stocks in neutral zone)")

    # ── Combined forecasts + Position sizing ──────────────────────────────────
    print(f"\n{'─'*60}")
    print("  💼 POSITION RECOMMENDATIONS")
    print(f"  (Buffer zone: ±{SIZING['buffer_fraction']*100:.0f}% — only trade if outside)")
    print(f"{'─'*60}")

    from signals.combined import get_all_forecasts_universe
    from sizing.position import get_position_summary

    combined_df = get_all_forecasts_universe(
        close_matrix=close_matrix,
        ohlcv_dict=ohlcv_dict,
        regime=regime,
    )

    latest_prices = close_matrix.iloc[-1]
    holdings = {}  # Load from portfolio/tracker in full version

    pos_df = get_position_summary(
        capital=capital,
        holdings=holdings,
        forecasts=combined_df["forecast"],
        prices=latest_prices,
        ohlcv_dict=ohlcv_dict,
        regime=regime,
        tau_multiplier=tau_mult,
    )

    if not pos_df.empty:
        trades_today = pos_df[pos_df["should_trade"]]
        holds = pos_df[~pos_df["should_trade"]]

        if not trades_today.empty:
            print(f"\n  TRADES TO EXECUTE ({len(trades_today)} stocks):")
            for _, row in trades_today.iterrows():
                action_icon = "🟢 BUY " if row["action"] == "BUY" else "🔴 SELL"
                print(f"  {action_icon}  {row['ticker']:<10} "
                      f"{abs(row['trade_shares']):>6} shares @ {row['price']:,.0f}  "
                      f"(forecast: {row['forecast']:+.1f}  vol: {row['annual_vol']})")
        else:
            print("  ✅ No trades today — all positions within buffer zone")

        total_cost = pos_df["trade_cost_vnd"].sum()
        if total_cost > 0:
            print(f"\n  Estimated fees today: {total_cost:,.0f} VND")

    print(f"\n{'='*60}")
    print("  End of daily report. Execute trades manually on TCBS.")
    print(f"{'='*60}\n")


# ─── Mock data generator ──────────────────────────────────────────────────────

def _generate_mock_data(universe, start_date, end_date):
    """Realistic synthetic OHLCV data for testing (no internet needed)."""
    import numpy as np

    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    rng = np.random.default_rng(seed=42)

    daily_drift = 0.00046
    daily_vol   = 0.012
    market_returns = rng.normal(daily_drift, daily_vol, n)
    vnindex = pd.Series(1200.0 * np.exp(np.cumsum(market_returns)), index=dates)

    close_matrix = {}
    ohlcv_dict = {}

    for ticker in universe:
        beta     = rng.uniform(0.8, 1.2)
        alpha    = rng.uniform(-0.0001, 0.0003)
        idio_vol = rng.uniform(0.010, 0.018)
        idio     = rng.normal(alpha, idio_vol, n)
        returns  = beta * market_returns + idio

        start_price = rng.uniform(15_000, 80_000)
        prices = start_price * np.exp(np.cumsum(returns))

        range_pct = np.abs(rng.normal(0, 0.012, n)) + 0.005
        highs = prices * (1 + range_pct)
        lows  = prices * (1 - range_pct)
        close_pos = rng.beta(2, 2, n)
        closes = lows + (highs - lows) * close_pos
        volume = rng.integers(300_000, 3_000_000, n)

        close_matrix[ticker] = pd.Series(closes, index=dates)
        ohlcv_dict[ticker] = pd.DataFrame({
            "open":   lows + (highs - lows) * rng.uniform(0.2, 0.8, n),
            "high":   highs, "low": lows, "close": closes, "volume": volume,
        }, index=dates)

    return pd.DataFrame(close_matrix), ohlcv_dict, vnindex


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VN Trading Framework v5 — Daily Workflow")
    parser.add_argument("--n", type=int, default=15, help="Number of stocks from universe")
    parser.add_argument("--capital", type=float, default=500_000_000, help="Capital in VND")
    parser.add_argument("--regime", type=str, default=None, help="Force regime: BULL or BEAR")
    parser.add_argument("--test", action="store_true", help="Use mock data (no internet)")
    args = parser.parse_args()

    run_daily(
        n_stocks=args.n,
        capital=args.capital,
        regime_override=args.regime,
        use_mock=args.test,
    )
