"""
strategies/martin_luk.py — Martin Luk Swing Trading Engine
===========================================================
Self-contained backtest engine implementing Martin Luk's USIC strategy
adapted for VN30 daily bars.

Key differences from the Carver engine:
  - Binary entry/exit (breakout + hard stops), not continuous forecasts
  - Fixed % risk per trade (0.75%), not vol-based Carver sizing
  - Per-position tracking with R-multiple targets and partial exits
  - Market health breadth indicator (leader count), not just MA200 regime
  - Trailing stops (EMA-based), not buffer zones

Shares infrastructure with Carver engine:
  - Data fetching (data/fetcher.py)
  - Performance metrics (backtesting/metrics.py)
  - Stock quality filter (same logic)
  - Output format (equity_curve, trade_log, metrics dicts)
  - T+2.5 settlement, lot size, transaction costs
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime

from config import MARTIN_LUK, STOCK_FILTER, COSTS


@dataclass
class OpenPosition:
    """Track per-position state for R-multiple exits and partial sells."""
    ticker: str
    entry_date: object          # pd.Timestamp
    entry_price: float
    initial_stop: float
    r_value: float              # entry_price - initial_stop
    shares_remaining: int
    shares_initial: int
    partial_count: int = 0      # 0, 1, 2
    trailing_stop: float = 0.0  # ratchets up over time
    pattern: str = ""           # breakout pattern that triggered entry

    def current_r_multiple(self, current_price: float) -> float:
        """Current unrealised profit in R-multiples."""
        if self.r_value <= 0:
            return 0.0
        return (current_price - self.entry_price) / self.r_value


class MartinLukEngine:
    """
    Backtest engine for Martin Luk's swing breakout strategy.

    Usage:
        engine = MartinLukEngine(capital=500_000_000)
        results = engine.run(close_matrix, ohlcv_dict, index_prices)
    """

    def __init__(self, capital: float = 500_000_000):
        self.initial_capital = capital
        self.capital = capital
        self.positions = {}         # {ticker: OpenPosition}
        self.trade_log = []
        self.equity_curve = []
        self.cost_total = 0.0
        self.peak_equity = capital
        self.filtered_out = []
        self.config = dict(MARTIN_LUK)

    def run(
        self,
        close_matrix: pd.DataFrame,
        ohlcv_dict: dict,
        index_prices: pd.Series,
        verbose: bool = True,
    ) -> dict:
        """
        Run the full Martin Luk backtest.

        Returns same format as BacktestEngine.run():
            {equity_curve, trade_log, metrics, regime_history}
        """
        from signals.ema_scanner import scan_universe
        from signals.breakout_detector import detect_breakouts
        from signals.market_health import compute_market_health
        from sizing.fixed_risk import compute_position_size, check_exposure_limit
        from backtesting.metrics import compute_metrics

        cfg = self.config
        lot_size = cfg["lot_size"]
        cost_pct = cfg["cost_per_trade_pct"]
        settlement_days = cfg["settlement_days"]

        # ── Stock quality filter (shared logic) ─────────────────────────────
        close_matrix, ohlcv_dict, self.filtered_out = self._apply_stock_filter(
            close_matrix, ohlcv_dict, verbose=verbose,
        )

        prices = close_matrix.sort_index()
        dates = prices.index
        n_universe = len(prices.columns)

        if verbose:
            print(f"\n{'='*60}")
            print(f"  Martin Luk Swing Strategy — Backtest")
            print(f"  Capital: {self.initial_capital:,.0f} VND")
            print(f"  Period:  {dates[0].date()} -> {dates[-1].date()}")
            print(f"  Stocks:  {n_universe}")
            print(f"  Risk/trade: {cfg['risk_per_trade_pct']*100:.2f}%")
            print(f"{'='*60}\n")

        # ── Pre-compute EMA alignment + ADR for all stocks ──────────────────
        if verbose:
            print("  Pre-computing EMA alignment + ADR...")
        ema_scans = scan_universe(
            ohlcv_dict,
            ema_periods=(cfg["ema_fast"], cfg["ema_mid"], cfg["ema_slow"]),
            adr_period=cfg["adr_period"],
        )

        # Build index-position lookup for each ticker's OHLCV
        ohlcv_date_idx = {}
        for ticker, ohlcv in ohlcv_dict.items():
            ohlcv_date_idx[ticker] = {d: i for i, d in enumerate(ohlcv.index)}

        warmup = cfg.get("warmup_bars", 60)
        health_history = []
        pending_sells = []  # Queued sells waiting for T+2.5 to clear

        # ── Main simulation loop ────────────────────────────────────────────
        if verbose:
            print("  Running simulation...")

        for bar_i, date in enumerate(dates):
            if bar_i < warmup:
                self.equity_curve.append({
                    "date": date,
                    "equity": self.initial_capital,
                    "cash": self.initial_capital,
                    "positions_value": 0,
                })
                continue

            current_prices = prices.loc[date]

            # ── Mark-to-market ──────────────────────────────────────────────
            positions_value = sum(
                pos.shares_remaining * float(current_prices.get(pos.ticker, 0))
                for pos in self.positions.values()
            )
            total_equity = self.capital + positions_value
            self.peak_equity = max(self.peak_equity, total_equity)

            # ── Market health ───────────────────────────────────────────────
            health = compute_market_health(ema_scans, date, cfg)
            health_history.append({"date": date, **health})
            risk_mult = health["risk_multiplier"]

            # ── Process pending sells (T+2.5 queue) ─────────────────────────
            still_pending = []
            for ps in pending_sells:
                days_held = (date - ps["entry_date"]).days
                if days_held >= settlement_days:
                    self._execute_sell(
                        ps["ticker"], ps["shares"], current_prices,
                        date, ps["reason"], cost_pct,
                    )
                else:
                    still_pending.append(ps)
            pending_sells = still_pending

            # ── CHECK EXITS (before entries) ────────────────────────────────
            tickers_to_remove = []
            for ticker, pos in list(self.positions.items()):
                price = float(current_prices.get(ticker, 0))
                if price <= 0:
                    continue

                days_held = (date - pos.entry_date).days
                can_sell = days_held >= settlement_days

                # Get EMA values for trailing stop
                scan = ema_scans.get(ticker)
                ema_9_val = None
                ema_21_val = None
                if scan is not None and date in scan.index:
                    ema_9_val = float(scan.loc[date, f"ema_{cfg['ema_fast']}"])
                    ema_21_val = float(scan.loc[date, f"ema_{cfg['exit_ema']}"])

                current_r = pos.current_r_multiple(price)

                # --- Partial exit at 3R ---
                if pos.partial_count == 0 and current_r >= cfg["partial_1_r"]:
                    sell_shares = int(pos.shares_remaining * cfg["partial_1_pct"])
                    sell_shares = (sell_shares // lot_size) * lot_size
                    if sell_shares >= lot_size:
                        if can_sell:
                            self._execute_sell(
                                ticker, sell_shares, current_prices,
                                date, "partial_3R", cost_pct,
                            )
                            pos.shares_remaining -= sell_shares
                            pos.partial_count = 1
                            pos.trailing_stop = pos.entry_price  # Move to breakeven
                        else:
                            pending_sells.append({
                                "ticker": ticker, "shares": sell_shares,
                                "entry_date": pos.entry_date, "reason": "partial_3R",
                            })
                            pos.partial_count = 1
                            pos.trailing_stop = pos.entry_price

                # --- Partial exit at 5R ---
                elif pos.partial_count == 1 and current_r >= cfg["partial_2_r"]:
                    sell_shares = int(pos.shares_remaining * cfg["partial_2_pct"])
                    sell_shares = (sell_shares // lot_size) * lot_size
                    if sell_shares >= lot_size:
                        if can_sell:
                            self._execute_sell(
                                ticker, sell_shares, current_prices,
                                date, "partial_5R", cost_pct,
                            )
                            pos.shares_remaining -= sell_shares
                            pos.partial_count = 2
                            if ema_9_val is not None and not np.isnan(ema_9_val):
                                pos.trailing_stop = ema_9_val
                        else:
                            pending_sells.append({
                                "ticker": ticker, "shares": sell_shares,
                                "entry_date": pos.entry_date, "reason": "partial_5R",
                            })
                            pos.partial_count = 2

                # --- Update trailing stop ---
                if pos.partial_count >= 2 and ema_9_val is not None and not np.isnan(ema_9_val):
                    pos.trailing_stop = max(pos.trailing_stop, ema_9_val)

                # --- Hard stop / trailing stop exit ---
                if price < pos.trailing_stop:
                    reason = "stop_loss" if pos.partial_count == 0 else "trail_exit"
                    if can_sell:
                        self._execute_sell(
                            ticker, pos.shares_remaining, current_prices,
                            date, reason, cost_pct,
                        )
                        tickers_to_remove.append(ticker)
                    else:
                        pending_sells.append({
                            "ticker": ticker, "shares": pos.shares_remaining,
                            "entry_date": pos.entry_date, "reason": reason,
                        })
                        tickers_to_remove.append(ticker)
                    continue

                # --- EMA(21) full exit (after partials taken) ---
                if pos.partial_count >= 2 and ema_21_val is not None and not np.isnan(ema_21_val):
                    if price < ema_21_val:
                        if can_sell:
                            self._execute_sell(
                                ticker, pos.shares_remaining, current_prices,
                                date, "ema_exit", cost_pct,
                            )
                            tickers_to_remove.append(ticker)
                        else:
                            pending_sells.append({
                                "ticker": ticker, "shares": pos.shares_remaining,
                                "entry_date": pos.entry_date, "reason": "ema_exit",
                            })
                            tickers_to_remove.append(ticker)
                        continue

                # --- Clean up fully sold positions ---
                if pos.shares_remaining <= 0:
                    tickers_to_remove.append(ticker)

            for t in tickers_to_remove:
                self.positions.pop(t, None)

            # ── CHECK ENTRIES ───────────────────────────────────────────────
            if risk_mult > 0:  # Not WEAK market
                for ticker in prices.columns:
                    # Skip if already holding
                    if ticker in self.positions:
                        continue

                    price = float(current_prices.get(ticker, 0))
                    if price <= 0:
                        continue

                    # Get OHLCV index for this ticker
                    ohlcv = ohlcv_dict.get(ticker)
                    if ohlcv is None or ohlcv.empty:
                        continue
                    idx_map = ohlcv_date_idx.get(ticker, {})
                    idx = idx_map.get(date)
                    if idx is None or idx < 2:
                        continue

                    # Get scan data
                    scan = ema_scans.get(ticker)
                    if scan is None or date not in scan.index:
                        continue

                    classification = scan.loc[date, "classification"]
                    adr = float(scan.loc[date, "adr"]) if "adr" in scan.columns else 0.0

                    # Detect breakout
                    breakout = detect_breakouts(
                        ohlcv, idx, scan, classification, adr, cfg,
                    )

                    if not breakout["triggered"]:
                        continue

                    # Check total exposure limit
                    if not check_exposure_limit(
                        positions_value,
                        breakout["entry_price"] * lot_size,  # estimate
                        total_equity,
                        cfg["max_total_exposure"],
                    ):
                        continue

                    # Compute position size
                    sizing = compute_position_size(
                        equity=total_equity,
                        entry_price=breakout["entry_price"],
                        stop_price=breakout["stop_price"],
                        risk_pct=cfg["risk_per_trade_pct"],
                        risk_multiplier=risk_mult,
                        peak_equity=self.peak_equity,
                        drawdown_threshold=cfg["drawdown_threshold"],
                        risk_drawdown_pct=cfg["risk_drawdown_pct"],
                        lot_size=lot_size,
                        max_position_pct=cfg["max_position_pct"],
                    )

                    shares = sizing["shares"]
                    if shares < lot_size:
                        continue

                    # Check cash
                    trade_value = shares * breakout["entry_price"]
                    fee = trade_value * cost_pct
                    if trade_value + fee > self.capital:
                        # Reduce to what we can afford
                        affordable = int((self.capital * 0.95) / breakout["entry_price"] / lot_size) * lot_size
                        if affordable < lot_size:
                            continue
                        shares = affordable
                        trade_value = shares * breakout["entry_price"]
                        fee = trade_value * cost_pct

                    # Execute buy
                    self.capital -= (trade_value + fee)
                    self.capital = max(self.capital, 0)
                    self.cost_total += fee

                    self.positions[ticker] = OpenPosition(
                        ticker=ticker,
                        entry_date=date,
                        entry_price=breakout["entry_price"],
                        initial_stop=breakout["stop_price"],
                        r_value=breakout["r_value"],
                        shares_remaining=shares,
                        shares_initial=shares,
                        trailing_stop=breakout["stop_price"],
                        pattern=breakout["pattern"],
                    )

                    self.trade_log.append({
                        "date": date,
                        "ticker": ticker,
                        "action": "BUY",
                        "shares": shares,
                        "price": breakout["entry_price"],
                        "value": round(trade_value),
                        "fee": round(fee),
                        "reason": f"breakout_{breakout['pattern']}",
                        "stop_price": round(breakout["stop_price"], 2),
                        "r_value": round(breakout["r_value"], 2),
                        "r_multiple": 0.0,
                        "health": health["health"],
                    })

                    # Update positions value for exposure check
                    positions_value += trade_value

            # ── Record equity ───────────────────────────────────────────────
            # Recompute after trades
            positions_value = sum(
                pos.shares_remaining * float(current_prices.get(pos.ticker, 0))
                for pos in self.positions.values()
            )
            total_equity = self.capital + positions_value

            self.equity_curve.append({
                "date": date,
                "equity": total_equity,
                "cash": self.capital,
                "positions_value": positions_value,
                "health": health["health"],
            })

        # ── Compute final metrics ───────────────────────────────────────────
        equity_df = pd.DataFrame(self.equity_curve).set_index("date")
        trade_df = pd.DataFrame(self.trade_log) if self.trade_log else pd.DataFrame()

        n_days = max((dates[-1] - dates[warmup]).days, 1)
        n_years = n_days / 365.25
        total_fees = self.cost_total
        # Use average equity (not initial) so cost drag stays meaningful when equity grows
        avg_equity = equity_df["equity"].mean() if not equity_df.empty else self.initial_capital
        cost_drag_annual = (total_fees / max(avg_equity, 1)) / max(n_years, 0.1)

        metrics = compute_metrics(equity_df["equity"])
        metrics["cost_drag_annual"] = round(cost_drag_annual, 4)
        metrics["total_fees_vnd"] = round(total_fees)
        metrics["n_trades"] = len(self.trade_log)
        metrics["trades_per_month"] = round(len(self.trade_log) / max(n_years * 12, 1), 1)
        metrics["n_years"] = round(n_years, 2)
        metrics["strategy"] = "martin_luk"

        # Swing-specific metrics
        swing_metrics = self._compute_swing_metrics(trade_df)
        metrics.update(swing_metrics)

        # Health stats
        if health_history:
            health_df = pd.DataFrame(health_history)
            strong_pct = (health_df["health"] == "STRONG").mean()
            metrics["health_pct_strong"] = round(strong_pct, 2)

        if verbose:
            self._print_summary(metrics)

        return {
            "equity_curve": equity_df,
            "trade_log": trade_df,
            "metrics": metrics,
            "regime_history": pd.DataFrame(health_history) if health_history else pd.DataFrame(),
        }

    def _execute_sell(self, ticker: str, shares: int, current_prices: pd.Series,
                      date, reason: str, cost_pct: float):
        """Execute a sell order and log it."""
        price = float(current_prices.get(ticker, 0))
        if price <= 0 or shares <= 0:
            return

        trade_value = shares * price
        fee = trade_value * cost_pct

        self.capital += (trade_value - fee)
        self.cost_total += fee

        # Compute R-multiple for the trade
        pos = self.positions.get(ticker)
        r_multiple = 0.0
        if pos is not None and pos.r_value > 0:
            r_multiple = (price - pos.entry_price) / pos.r_value
            # Sanity cap: VN stocks have ±7% daily limit, so >20R in a single
            # trade is extremely unlikely — flag as corrupted data
            if abs(r_multiple) > 20:
                r_multiple = max(min(r_multiple, 20.0), -20.0)

        self.trade_log.append({
            "date": date,
            "ticker": ticker,
            "action": "SELL",
            "shares": -shares,
            "price": price,
            "value": round(trade_value),
            "fee": round(fee),
            "reason": reason,
            "stop_price": round(pos.trailing_stop, 2) if pos else 0,
            "r_value": round(pos.r_value, 2) if pos else 0,
            "r_multiple": round(r_multiple, 2),
            "health": "",
        })

    def _compute_swing_metrics(self, trade_df: pd.DataFrame) -> dict:
        """Compute Martin Luk specific metrics: expectancy, avg R, streaks."""
        result = {
            "avg_winner_r": 0.0,
            "avg_loser_r": 0.0,
            "expectancy": 0.0,
            "max_consecutive_losses": 0,
            "avg_holding_days": 0.0,
            "partial_exit_count": 0,
        }

        if trade_df.empty or "r_multiple" not in trade_df.columns:
            return result

        # Only look at SELL trades for R-multiple analysis
        sells = trade_df[trade_df["action"] == "SELL"].copy()
        if sells.empty:
            return result

        r_multiples = sells["r_multiple"].dropna()
        if r_multiples.empty:
            return result

        winners = r_multiples[r_multiples > 0]
        losers = r_multiples[r_multiples <= 0]

        if len(winners) > 0:
            result["avg_winner_r"] = round(float(winners.mean()), 2)
        if len(losers) > 0:
            result["avg_loser_r"] = round(float(losers.mean()), 2)

        # Expectancy = (win% * avg_win_R) + (loss% * avg_loss_R)
        n_total = len(r_multiples)
        win_rate = len(winners) / n_total if n_total > 0 else 0
        loss_rate = len(losers) / n_total if n_total > 0 else 0
        result["expectancy"] = round(
            win_rate * result["avg_winner_r"] + loss_rate * result["avg_loser_r"], 2
        )

        # Max consecutive losses
        max_streak = 0
        current_streak = 0
        for r in r_multiples:
            if r <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        result["max_consecutive_losses"] = max_streak

        # Average holding days
        buys = trade_df[trade_df["action"] == "BUY"]
        if not buys.empty and not sells.empty and "date" in buys.columns:
            holding_days = []
            for ticker in sells["ticker"].unique():
                t_buys = buys[buys["ticker"] == ticker]["date"]
                t_sells = sells[sells["ticker"] == ticker]["date"]
                for s_date in t_sells:
                    matching_buys = t_buys[t_buys < s_date]
                    if not matching_buys.empty:
                        b_date = matching_buys.iloc[-1]
                        days = (pd.Timestamp(s_date) - pd.Timestamp(b_date)).days
                        holding_days.append(days)
            if holding_days:
                result["avg_holding_days"] = round(np.mean(holding_days), 1)

        # Partial exit count
        partials = sells[sells["reason"].str.contains("partial", case=False, na=False)]
        result["partial_exit_count"] = len(partials)

        return result

    @staticmethod
    def _apply_stock_filter(close_matrix, ohlcv_dict, verbose=True):
        """Same stock quality filter as Carver engine."""
        if not STOCK_FILTER.get("enabled", False):
            return close_matrix, ohlcv_dict, []

        min_vol = STOCK_FILTER.get("min_avg_volume", 500_000)
        vol_window = STOCK_FILTER.get("volume_lookback_days", 60)
        min_hist = STOCK_FILTER.get("min_history_days", 250)

        keep = []
        removed = []

        for ticker in close_matrix.columns:
            ohlcv = ohlcv_dict.get(ticker)
            if ohlcv is None or len(ohlcv) < min_hist:
                removed.append((ticker, "insufficient_history"))
                continue
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

    def _print_summary(self, metrics: dict):
        print(f"\n{'='*60}")
        print(f"  MARTIN LUK SWING STRATEGY — RESULTS")
        print(f"{'='*60}")
        print(f"  CAGR:              {metrics.get('cagr', 0)*100:+.1f}%")
        print(f"  Sharpe:             {metrics.get('sharpe', 0):.2f}")
        print(f"  Max Drawdown:      {metrics.get('max_drawdown', 0)*100:.1f}%")
        print(f"  Win Rate:          {metrics.get('win_rate', 0)*100:.0f}%")
        print(f"  Expectancy:         {metrics.get('expectancy', 0):.2f}R")
        print(f"  Avg Winner:         {metrics.get('avg_winner_r', 0):.2f}R")
        print(f"  Avg Loser:          {metrics.get('avg_loser_r', 0):.2f}R")
        print(f"  Max Consec Losses:  {metrics.get('max_consecutive_losses', 0)}")
        print(f"  Avg Hold Days:      {metrics.get('avg_holding_days', 0):.0f}")
        print(f"  Trades/month:       {metrics.get('trades_per_month', 0):.1f}")
        print(f"  Cost drag/yr:      {metrics.get('cost_drag_annual', 0)*100:.1f}%")
        print(f"  % Strong market:   {metrics.get('health_pct_strong', 0)*100:.0f}%")
        print(f"{'='*60}\n")
