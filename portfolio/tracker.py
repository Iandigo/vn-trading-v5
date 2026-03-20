"""
portfolio/tracker.py — Live Portfolio Tracker
===============================================
Persists your actual holdings to outputs/holdings.json.
main.py reads from here so position sizing knows what you currently hold.

Usage:
    from portfolio.tracker import PortfolioTracker
    tracker = PortfolioTracker()

    # After manually executing a BUY on TCBS:
    tracker.record_trade("VCB.VN", action="BUY", shares=500, price=88500)

    # Get current holdings for main.py
    holdings = tracker.get_holdings()      # {"VCB.VN": 500, ...}

    # Mark-to-market P&L
    tracker.print_summary(latest_prices)
"""

import json
import os
from datetime import datetime
from pathlib import Path

HOLDINGS_FILE = Path("outputs/holdings.json")
TRADE_LOG_FILE = Path("outputs/live_trade_log.json")


class PortfolioTracker:
    """
    Lightweight file-backed portfolio tracker.
    No database required — persists to JSON files in outputs/.
    """

    def __init__(self):
        os.makedirs("outputs", exist_ok=True)
        self.holdings   = self._load_holdings()
        self.trade_log  = self._load_trade_log()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(
        self,
        ticker: str,
        action: str,          # "BUY" or "SELL"
        shares: int,
        price: float,
        note: str = "",
    ) -> dict:
        """
        Record a trade you executed manually on TCBS.
        Updates holdings and appends to trade log.

        Parameters
        ----------
        ticker  : str    e.g. "VCB.VN"
        action  : str    "BUY" or "SELL"
        shares  : int    Number of shares traded (positive)
        price   : float  Execution price in VND
        note    : str    Optional note (e.g. "TCBS fill at 09:15")

        Returns
        -------
        dict  Trade record with cost and updated holding
        """
        shares = abs(int(shares))
        price  = float(price)

        from config import COSTS
        cost_pct = COSTS["cost_per_trade_pct"]
        fee = round(shares * price * cost_pct)
        value = shares * price

        current = int(self.holdings.get(ticker, 0))

        if action.upper() == "BUY":
            new_holding = current + shares
            net_cash    = -(value + fee)
        elif action.upper() == "SELL":
            if shares > current:
                print(f"  ⚠️  Warning: selling {shares} but only hold {current} of {ticker}. Capped.")
                shares = current
            new_holding = current - shares
            net_cash    = value - fee
        else:
            raise ValueError(f"action must be BUY or SELL, got {action!r}")

        # Update holdings
        if new_holding > 0:
            self.holdings[ticker] = new_holding
        elif ticker in self.holdings:
            del self.holdings[ticker]

        trade = {
            "date":        datetime.now().strftime("%Y-%m-%d %H:%M"),
            "ticker":      ticker,
            "action":      action.upper(),
            "shares":      shares,
            "price":       price,
            "value":       round(value),
            "fee":         fee,
            "net_cash":    round(net_cash),
            "new_holding": new_holding,
            "note":        note,
        }

        self.trade_log.append(trade)
        self._save()

        print(f"  ✅ Recorded: {action.upper()} {shares:,} {ticker} @ {price:,.0f}  "
              f"(fee: {fee:,.0f} VND)  →  holding: {new_holding:,}")
        return trade

    def get_holdings(self) -> dict:
        """Return current holdings as {ticker: shares}."""
        return dict(self.holdings)

    def get_total_invested(self, latest_prices: dict) -> float:
        """Market value of all open positions."""
        return sum(
            shares * float(latest_prices.get(ticker, 0))
            for ticker, shares in self.holdings.items()
        )

    def override_holding(self, ticker: str, shares: int):
        """Manually correct a holding (e.g. after a corporate action)."""
        if shares > 0:
            self.holdings[ticker] = shares
        elif ticker in self.holdings:
            del self.holdings[ticker]
        self._save()
        print(f"  ✏️  Overridden: {ticker} → {shares:,} shares")

    def print_summary(self, latest_prices: dict = None, capital: float = None):
        """Print a formatted portfolio summary to console."""
        print(f"\n{'='*60}")
        print(f"  LIVE PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")

        if not self.holdings:
            print("  (No open positions)\n")
            return

        total_value = 0.0
        rows = []

        for ticker, shares in sorted(self.holdings.items()):
            price = float(latest_prices.get(ticker, 0)) if latest_prices else 0
            market_val = shares * price

            # Find avg entry price from trade log
            avg_entry = self._calc_avg_entry(ticker)
            cost_basis = shares * avg_entry if avg_entry else None
            unrealised = (market_val - cost_basis) if cost_basis and price > 0 else None
            unrealised_pct = (unrealised / cost_basis) if cost_basis and cost_basis > 0 else None

            total_value += market_val
            rows.append((ticker, shares, price, market_val, avg_entry, unrealised, unrealised_pct))

        print(f"  {'Ticker':<10} {'Shares':>8} {'Price':>10} {'Value':>14} {'Entry':>10} {'Unreal.':>10} {'%':>6}")
        print(f"  {'─'*8} {'─'*8} {'─'*9} {'─'*13} {'─'*9} {'─'*9} {'─'*5}")

        for ticker, shares, price, val, entry, unreal, unreal_pct in rows:
            entry_s  = f"{entry:,.0f}" if entry else "n/a"
            unreal_s = f"{unreal/1e6:+.2f}M" if unreal is not None else "n/a"
            pct_s    = f"{unreal_pct*100:+.1f}%" if unreal_pct is not None else ""
            pct_icon = "📈" if (unreal_pct or 0) > 0 else ("📉" if (unreal_pct or 0) < 0 else "")
            print(f"  {ticker:<10} {shares:>8,} {price:>10,.0f} {val/1e6:>12.2f}M "
                  f"{entry_s:>10} {unreal_s:>10} {pct_s:>5} {pct_icon}")

        print(f"  {'─'*72}")
        print(f"  {'TOTAL':<10} {'':>8} {'':>10} {total_value/1e6:>12.2f}M")

        if capital:
            cash = capital - total_value
            print(f"  {'Cash':<10} {'':>8} {'':>10} {cash/1e6:>12.2f}M")
            print(f"  {'Portfolio':<10} {'':>8} {'':>10} {capital/1e6:>12.2f}M")

        print(f"\n  {len(self.holdings)} open positions  ·  "
              f"{len(self.trade_log)} total trades logged")
        print(f"{'='*60}\n")

    def print_trade_log(self, last_n: int = 20):
        """Print the last N trades."""
        print(f"\n  LAST {last_n} TRADES")
        print(f"  {'Date':<18} {'Ticker':<10} {'Action':<6} {'Shares':>8} {'Price':>10} {'Fee':>8}")
        print(f"  {'─'*16} {'─'*8} {'─'*5} {'─'*8} {'─'*9} {'─'*7}")
        for t in self.trade_log[-last_n:]:
            print(f"  {t['date']:<18} {t['ticker']:<10} {t['action']:<6} "
                  f"{t['shares']:>8,} {t['price']:>10,.0f} {t['fee']:>8,}")

    # ── Private ───────────────────────────────────────────────────────────────

    def _calc_avg_entry(self, ticker: str) -> float:
        """Compute average entry price from trade log using FIFO."""
        buys = [t for t in self.trade_log if t["ticker"] == ticker and t["action"] == "BUY"]
        if not buys:
            return 0.0
        total_shares = sum(b["shares"] for b in buys)
        total_cost   = sum(b["shares"] * b["price"] for b in buys)
        return total_cost / total_shares if total_shares > 0 else 0.0

    def _load_holdings(self) -> dict:
        if HOLDINGS_FILE.exists():
            try:
                with open(HOLDINGS_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _load_trade_log(self) -> list:
        if TRADE_LOG_FILE.exists():
            try:
                with open(TRADE_LOG_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save(self):
        with open(HOLDINGS_FILE, "w") as f:
            json.dump(self.holdings, f, indent=2)
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump(self.trade_log, f, indent=2, ensure_ascii=False)
