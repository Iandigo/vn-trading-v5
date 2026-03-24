"""
backtesting/engine.py — Walk-Forward Backtest Engine
=====================================================
Key design decisions (lessons from v4 regime bug):

  ✅ Regime recalculated WEEKLY (every 5 days) — not daily
  ✅ Cross-momentum ranks updated MONTHLY (every 21 days) — not daily
  ✅ IBS recomputed daily (it's a daily signal, cheap, no lookback)
  ✅ Buffer zone applied — only trade when outside 20% band
  ✅ Transaction costs deducted on every trade
  ✅ T+2.5 settlement respected (can't sell stock bought < 3 days ago)
  ✅ No short positions ever
  ✅ Lot size (100 shares) respected throughout

The regime is intentionally NOT recalculated inside the main bar loop.
This was the v4 critical bug: daily regime → τ changes daily → whipsaw
→ 7% cost drag → negative Sharpe.
"""

import numpy as np
import pandas as pd
from datetime import datetime

from config import SIZING, COSTS, BACKTEST, MA_REGIME, STOCK_FILTER


class BacktestEngine:
    """
    Event-driven backtest engine for the VN Trading Framework v5.

    Usage:
        engine = BacktestEngine(capital=500_000_000)
        results = engine.run(close_matrix, ohlcv_dict, index_prices)
    """

    def __init__(self, capital: float = 500_000_000):
        self.initial_capital = capital
        self.capital = capital
        self.holdings = {}          # {ticker: shares}
        self.entry_dates = {}       # {ticker: date} for T+3 settlement
        self.trade_log = []
        self.equity_curve = []
        self.cost_total = 0.0
        self.filtered_out = []      # Stocks removed by quality filter

    @staticmethod
    def _apply_stock_filter(
        close_matrix: pd.DataFrame,
        ohlcv_dict: dict,
        verbose: bool = True,
    ) -> tuple:
        """
        Pre-filter stocks by quality (volume + history length).
        Returns filtered close_matrix, ohlcv_dict, and list of removed tickers.
        """
        if not STOCK_FILTER.get("enabled", False):
            return close_matrix, ohlcv_dict, []

        min_vol = STOCK_FILTER.get("min_avg_volume", 500_000)
        vol_window = STOCK_FILTER.get("volume_lookback_days", 60)
        min_hist = STOCK_FILTER.get("min_history_days", 250)

        keep = []
        removed = []

        for ticker in close_matrix.columns:
            ohlcv = ohlcv_dict.get(ticker)

            # Check history length
            if ohlcv is None or len(ohlcv) < min_hist:
                removed.append((ticker, "insufficient_history"))
                continue

            # Check average volume
            if "volume" in ohlcv.columns:
                avg_vol = ohlcv["volume"].tail(vol_window).mean()
                if avg_vol < min_vol:
                    removed.append((ticker, f"low_volume_{avg_vol:.0f}"))
                    continue

            keep.append(ticker)

        if verbose and removed:
            print(f"  Stock filter: removed {len(removed)} stocks:")
            for t, reason in removed:
                print(f"    {t}: {reason}")
            print(f"  Remaining: {len(keep)} stocks")

        filtered_close = close_matrix[keep]
        filtered_ohlcv = {t: ohlcv_dict[t] for t in keep if t in ohlcv_dict}
        return filtered_close, filtered_ohlcv, [t for t, _ in removed]

    def run(
        self,
        close_matrix: pd.DataFrame,
        ohlcv_dict: dict,
        index_prices: pd.Series,
        verbose: bool = True,
    ) -> dict:
        """
        Run the full backtest.

        Parameters
        ----------
        close_matrix  : pd.DataFrame   Aligned daily close prices {ticker: prices}
        ohlcv_dict    : dict           {ticker: ohlcv_df} for IBS signal
        index_prices  : pd.Series      VNIndex daily closes for regime detection
        verbose       : bool           Print progress

        Returns
        -------
        dict with keys:
            equity_curve, trade_log, metrics, regime_history
        """
        from signals.ma_regime import get_regime_series, get_tau_multiplier_series
        from signals.cross_momentum import get_cross_momentum_series
        from signals.ibs import get_ibs_forecast_series
        from signals.combined import combine_forecasts
        from sizing.position import optimal_shares, check_buffer, get_annual_vol, get_trade_cost
        from backtesting.metrics import compute_metrics

        # ── Stock quality filter ─────────────────────────────────────────────
        close_matrix, ohlcv_dict, self.filtered_out = self._apply_stock_filter(
            close_matrix, ohlcv_dict, verbose=verbose,
        )

        prices = close_matrix.sort_index()
        dates = prices.index
        n_dates = len(dates)
        n_universe = len(prices.columns)  # Fixed universe size for weight calc

        if verbose:
            print(f"\n{'='*60}")
            print(f"  VN Trading Framework v5 — Backtest")
            print(f"  Capital: {self.initial_capital:,.0f} VND")
            print(f"  Period:  {dates[0].date()} → {dates[-1].date()}")
            print(f"  Stocks:  {n_universe}")
            print(f"{'='*60}\n")

        # ── Pre-compute regime series (WEEKLY updates) ────────────────────────
        if verbose:
            print("  Pre-computing regime series (weekly updates)...")
        regime_series = get_regime_series(
            index_prices,
            update_every=BACKTEST["regime_update_days"],   # 5 = weekly
        )
        tau_mult_series = get_tau_multiplier_series(
            index_prices,
            update_every=BACKTEST["regime_update_days"],
        )

        # ── Pre-compute cross-momentum forecast matrix (MONTHLY updates) ─────
        if verbose:
            print("  Pre-computing cross-momentum forecasts (monthly updates)...")
        cm_matrix = get_cross_momentum_series(
            close_matrix=prices,
            regime_series=regime_series,
            update_every=BACKTEST["cross_mom_update_days"],  # 21 = monthly
        )

        # ── Pre-compute IBS forecast series per stock (DAILY) ─────────────────
        if verbose:
            print("  Pre-computing IBS forecasts (daily)...")
        ibs_matrix = {}
        for ticker, ohlcv in ohlcv_dict.items():
            if ticker in prices.columns:
                ibs_matrix[ticker] = get_ibs_forecast_series(
                    ohlcv=ohlcv,
                    regime_series=regime_series,
                )

        regime_history = []

        # ── Main simulation loop ──────────────────────────────────────────────
        warmup = max(
            MA_REGIME["ma_period"],          # 200 bars
            SIZING.get("min_warmup", 210),
        )

        for i, date in enumerate(dates):
            if i < warmup:
                self.equity_curve.append({
                    "date": date,
                    "equity": self.initial_capital,
                    "cash": self.initial_capital,
                    "positions_value": 0,
                })
                continue

            # Current prices
            current_prices = prices.loc[date]
            regime = regime_series.get(date, "BULL")
            tau_mult = float(tau_mult_series.get(date, 1.0))

            regime_history.append({"date": date, "regime": regime, "tau_mult": tau_mult})

            # ── Mark-to-market ───────────────────────────────────────────────
            positions_value = sum(
                int(shares) * float(current_prices.get(ticker, 0))
                for ticker, shares in self.holdings.items()
            )
            total_equity = self.capital + positions_value

            self.equity_curve.append({
                "date": date,
                "equity": total_equity,
                "cash": self.capital,
                "positions_value": positions_value,
                "regime": regime,
            })

            # ── Get forecasts for today ───────────────────────────────────────
            # Bug fix: n_active was computed INSIDE the per-stock loop, which
            # caused weights to change as positions opened/closed within the
            # same day → inconsistent sizing. Now computed ONCE before the loop.
            # Use stocks with positive forecast as the target portfolio size.
            vol_lookback = SIZING.get("vol_lookback", 60)
            n_positive = 0
            for t in prices.columns:
                cm_f = float(cm_matrix.loc[date, t]) if t in cm_matrix.columns else 0.0
                ibs_f = float(ibs_matrix.get(t, pd.Series()).get(date, 0.0))
                c = combine_forecasts(cm_f, ibs_f, regime)
                if c["combined_forecast"] > 0:
                    n_positive += 1
            n_active = max(n_positive, max(sum(1 for s in self.holdings.values() if s > 0), 1))

            for ticker in prices.columns:
                price = float(current_prices.get(ticker, 0))
                if price <= 0:
                    continue

                cm_forecast = float(cm_matrix.loc[date, ticker]) if ticker in cm_matrix.columns else 0.0
                ibs_forecast = float(ibs_matrix.get(ticker, pd.Series()).get(date, 0.0))

                combined = combine_forecasts(
                    cross_momentum_forecast=cm_forecast,
                    ibs_forecast=ibs_forecast,
                    regime=regime,
                )
                forecast = combined["combined_forecast"]

                # No new entries in BEAR regime — unless top-N momentum stock
                current_shares = int(self.holdings.get(ticker, 0))
                if not combined["trading_allowed"] and current_shares == 0:
                    bear_top_n = MA_REGIME.get("bear_top_n_entries", 0)
                    if bear_top_n > 0 and ticker in cm_matrix.columns:
                        # Rank by momentum forecast (highest = rank 1)
                        today_cm = cm_matrix.loc[date].dropna().sort_values(ascending=False)
                        rank = list(today_cm.index).index(ticker) + 1 if ticker in today_cm.index else 999
                        if rank > bear_top_n:
                            continue
                        # Top-N: allow entry but combined forecast is already computed
                    else:
                        continue

                # Volatility estimate (configurable lookback, default 60d)
                ohlcv = ohlcv_dict.get(ticker)
                if ohlcv is not None and not ohlcv.empty:
                    close_hist = ohlcv["close"][ohlcv.index <= date]
                    ann_vol = get_annual_vol(close_hist, lookback=vol_lookback)
                else:
                    close_hist = prices[ticker][prices.index <= date]
                    ann_vol = get_annual_vol(close_hist, lookback=vol_lookback)

                # Optimal shares — n_active computed once before loop (no intra-day drift)
                opt = optimal_shares(
                    capital=total_equity,
                    forecast=forecast,
                    price=price,
                    annual_vol=ann_vol,
                    n_stocks=n_active,
                    tau_multiplier=tau_mult,
                )

                # Buffer check
                buf = check_buffer(current_shares, opt)
                if not buf["should_trade"]:
                    continue

                target = buf["target_shares"]
                delta = target - current_shares

                # Skip tiny trades — they cost disproportionately
                min_trade_val = COSTS.get("min_trade_value", 5_000_000)
                if abs(delta * price) < min_trade_val and delta != -current_shares:
                    continue

                # T+2.5 settlement: can't sell recently purchased shares
                entry_date = self.entry_dates.get(ticker)
                if delta < 0 and entry_date is not None:
                    days_held = (date - entry_date).days
                    if days_held < 3:
                        continue  # Can't sell yet — T+3 lock

                # Check sufficient cash for buys
                if delta > 0:
                    cost = delta * price
                    fee = get_trade_cost(delta, price)
                    if cost + fee > self.capital:
                        # Reduce to what we can afford
                        affordable = int((self.capital * 0.95) / price / 100) * 100
                        delta = max(0, affordable - current_shares)
                        target = current_shares + delta
                        if delta == 0:
                            continue

                # Execute trade
                fee = get_trade_cost(delta, price)
                trade_value = delta * price

                if delta > 0:
                    self.capital -= (trade_value + fee)
                    self.entry_dates[ticker] = date
                else:
                    self.capital += (-trade_value - fee)

                self.capital = max(self.capital, 0)
                self.cost_total += abs(fee)
                self.holdings[ticker] = target

                self.trade_log.append({
                    "date": date,
                    "ticker": ticker,
                    "action": "BUY" if delta > 0 else "SELL",
                    "shares": delta,
                    "price": price,
                    "value": abs(trade_value),
                    "fee": round(fee),
                    "regime": regime,
                    "forecast": round(forecast, 1),
                })

        # ── Compute final metrics ─────────────────────────────────────────────
        equity_df = pd.DataFrame(self.equity_curve).set_index("date")
        trade_df = pd.DataFrame(self.trade_log) if self.trade_log else pd.DataFrame()

        n_days = max((dates[-1] - dates[warmup]).days, 1)
        n_years = n_days / 365.25
        total_fees = self.cost_total
        final_equity = equity_df["equity"].iloc[-1] if not equity_df.empty else self.initial_capital
        # Use average equity over the period (geometric mean of start and end)
        # to avoid inflating drag when equity grows significantly over long periods
        avg_equity = (self.initial_capital * final_equity) ** 0.5
        cost_drag_annual = (total_fees / avg_equity) / max(n_years, 0.1)

        metrics = compute_metrics(equity_df["equity"])
        metrics["cost_drag_annual"] = round(cost_drag_annual, 4)
        metrics["total_fees_vnd"] = round(total_fees)
        metrics["n_trades"] = len(self.trade_log)
        metrics["trades_per_month"] = round(len(self.trade_log) / max(n_years * 12, 1), 1)
        metrics["n_years"] = round(n_years, 2)
        metrics["regime_pct_bull"] = round(
            sum(1 for r in regime_history if r["regime"] == "BULL") / max(len(regime_history), 1), 2
        )

        if verbose:
            self._print_summary(metrics)

        return {
            "equity_curve": equity_df,
            "trade_log": trade_df,
            "metrics": metrics,
            "regime_history": pd.DataFrame(regime_history),
        }

    def _print_summary(self, metrics: dict):
        print(f"\n{'='*60}")
        print(f"  BACKTEST RESULTS")
        print(f"{'='*60}")
        print(f"  CAGR:           {metrics.get('cagr', 0)*100:+.1f}%   (target: >4.5%)")
        print(f"  Sharpe:          {metrics.get('sharpe', 0):.2f}    (target: >0.40)")
        print(f"  Max Drawdown:   {metrics.get('max_drawdown', 0)*100:.1f}%   (target: < -30%)")
        print(f"  Trades/month:    {metrics.get('trades_per_month', 0):.0f}     (target: <30)")
        print(f"  Cost drag/yr:   {metrics.get('cost_drag_annual', 0)*100:.1f}%    (target: <1%)")
        print(f"  % Bull regime:   {metrics.get('regime_pct_bull', 0)*100:.0f}%")
        print(f"{'='*60}\n")
