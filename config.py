"""
VN Trading Framework v5 — Configuration
========================================
All parameters in one place.

Design principle: Every number here uses ROUND values with economic logic.
No "optimised" magic numbers like MA(47) or lookback(189).
If you can't explain WHY a number is what it is, it shouldn't be here.
"""

# ─── Universe ────────────────────────────────────────────────────────────────
# Full VN30 blue-chips — all 30 constituents of the VN30 index (HOSE)
# Use n_stocks parameter at runtime to select the top N from this list
# Ordered roughly by market cap / liquidity for best n_stocks < 30 subsets
UNIVERSE = [
    # Banks (most liquid, highest market cap)
    "VCB.VN",   # Vietcombank
    "BID.VN",   # BIDV
    "CTG.VN",   # Vietinbank
    "TCB.VN",   # Techcombank
    "MBB.VN",   # MB Bank
    "VPB.VN",   # VPBank
    "ACB.VN",   # Asia Commercial Bank
    "HDB.VN",   # HDBank
    "STB.VN",   # Sacombank
    "TPB.VN",   # TPBank
    "SHB.VN",   # SHB
    # Industrials / Energy / Consumer
    "HPG.VN",   # Hoa Phat Group
    "GAS.VN",   # PetroVietnam Gas
    "PLX.VN",   # Petrolimex
    "POW.VN",   # PetroVietnam Power
    "REE.VN",   # REE Corp (electrical / real estate)
    # Real Estate / Conglomerate
    "VHM.VN",   # Vinhomes
    "VIC.VN",   # Vingroup
    "MSN.VN",   # Masan Group
    "BCM.VN",   # Becamex IDC
    "KDH.VN",   # Khang Dien House
    "NVL.VN",   # Novaland
    "PDR.VN",   # Phat Dat Real Estate
    # Technology / Retail / Consumer
    "FPT.VN",   # FPT Corp
    "MWG.VN",   # Mobile World
    "PNJ.VN",   # Phu Nhuan Jewelry
    "SAB.VN",   # Sabeco
    # Securities / Chemicals
    "SSI.VN",   # SSI Securities
    "VND.VN",   # VNDIRECT
    "DGC.VN",   # Duc Giang Chemicals
]

# Market index proxy — used for regime detection
# ^VNINDEX was removed from Yahoo Finance (~2025).
# Fallback order tried automatically: VNINDEX → E1VFVN30.VN (VN30 ETF) → universe mean proxy
VNINDEX_TICKER = "VNINDEX"
VNINDEX_FALLBACK_TICKERS = ["E1VFVN30.VN", "VN30F1M.VN"]

# ─── Signal Parameters ────────────────────────────────────────────────────────

# --- Signal 1: 200-day MA Regime Filter ---
# WHY 200? Standard in global markets. ~10 months of trading days.
# Widely watched by institutional VN funds → self-fulfilling + real edge.
# WHY confirm_days=3? Avoids single-day whipsaws from news spikes.
MA_REGIME = {
    "ma_period": 200,          # DO NOT optimise this. Use 200.
    "confirm_days": 3,         # Days index must be above/below MA before flipping
    "bull_tau_multiplier": 1.0,  # Full position sizing in bull market
    "bear_tau_multiplier": 0.5,  # Half sizing in bear market (regime = BEAR)
    "bear_new_entries": False,   # No new long entries when in BEAR regime
    "bear_top_n_entries": 3,     # Exception: allow top-N momentum stocks to enter in BEAR
}

# --- Signal 2: Cross-Sectional Momentum ---
# WHY 63 days? = ~3 calendar months of trading. Round number, widely used.
# Academic evidence: momentum works best at 3–12 month horizon.
# Monthly rebalance (21 days) to keep transaction costs low.
# WHY skip last 5 days? Avoids short-term reversal contaminating the signal.
CROSS_MOMENTUM = {
    "lookback_days": 63,       # ~3 months. DO NOT optimise. Round number.
    "skip_recent_days": 5,     # Skip most recent week (short-term reversal bias)
    "rebalance_every_days": 21, # Monthly — keeps cost drag low
    "min_stocks_for_signal": 5, # Need at least this many stocks to rank
    "top_pct": 0.3,           # Top 40% of universe gets positive forecast
    "bottom_pct": 0.3,        # Bottom 40% gets negative forecast
    # Middle 20% → 0 forecast (no signal, not penalised)
}

# --- Signal 3: IBS (Internal Bar Strength) Mean Reversion ---
# WHY IBS? More mechanical than RSI. No period to optimise. Pure price formula.
# IBS = (close - low) / (high - low). Ranges 0-1 each day.
# WHY 0.2 / 0.8? Standard textbook thresholds. Round numbers.
# WHY only in BULL regime? Counter-trend in a bear market = catching falling knives.
IBS = {
    "oversold_threshold": 0.20,   # IBS < 0.2 = closed near daily low = oversold
    "overbought_threshold": 0.80, # IBS > 0.8 = closed near daily high = overbought
    "only_in_bull_regime": True,  # Do NOT trade IBS in BEAR regime
    "ma_filter_period": 200,      # Only trade IBS long when price > MA200
    # Note: same MA200 as regime filter. Consistent, no extra parameters.
}

# ─── Signal Combination ───────────────────────────────────────────────────────
# Weights sum to 0.70 (not 1.0) — the remaining 0.30 represents "no signal / cash".
# FDM (Forecast Diversification Multiplier): compensates for imperfect correlation
# between signals. Since IBS is counter-trend (corr ~ -0.3 with momentum),
# combined signal is diversified → FDM > 1.0 is justified.
SIGNAL_WEIGHTS = {
    "cross_momentum": 0.85,   # Primary driver — works well in VN frontier market
    "ibs": 0.1,              # Counter-trend, low weight, BULL regime only
    # Note: MA regime is a FILTER not a signal — it has no weight here.
    # It modifies tau and blocks new entries, it doesn't produce a forecast.
    # Total = 0.70. Remaining 0.30 = cash/no-signal exposure. FDM compensates.
}
FDM = 1.20  # Forecast Diversification Multiplier

# Forecast is clipped to [-20, +20] — Carver standard
FORECAST_CAP = 20.0
FORECAST_SCALAR_CROSS_MOM = 10.0  # Scale cross-momentum rank to ~10 average abs forecast
FORECAST_SCALAR_IBS = 8.0         # IBS produces smaller, less frequent signals

# ─── Position Sizing ─────────────────────────────────────────────────────────
SIZING = {
    # WHY 0.25? VN stocks have high correlation (~0.6 vs ~0.35 in developed mkts).
    # IDM overestimates diversification benefit, so realised vol < target.
    # Raising tau from 0.20 to 0.25 corrects this systematic undersizing.
    "target_vol": 0.3,

    # Buffer zone: only trade when position drifts OUTSIDE this band.
    # WHY 0.40? Combined with "trade to edge" rule (Carver method), this keeps
    # positions inside the band much longer. VN illiquid market needs wide buffer.
    # At 0.20 with trade-to-optimal: 64 trades/month. At 0.40 with trade-to-edge: ~15.
    "buffer_fraction": 0.45,

    # VN lot size: HOSE requires multiples of 100 shares
    "lot_size": 100,

    # Maximum position as % of capital — single stock concentration limit
    "max_position_pct": 0.15,  # No single stock > 15% of capital

    # IDM table calibrated for VN (high correlation environment)
    # Lower than Carver's standard table because VN correlation ~0.6
    "idm_table": {
        5: 1.25, 10: 1.35, 15: 1.40, 20: 1.45,
        25: 1.48, 30: 1.50, 40: 1.53, 50: 1.55,
    },
    # Volatility lookback for position sizing.
    # WHY 60? 20-day was too noisy → sizes changed daily → excess trading.
    # 60 days (~3 months) smooths out short-term spikes while still adapting.
    "vol_lookback": 90,

    # Warmup bars before simulation begins (must be >= MA period)
    "min_warmup": 210,
}

# ─── Stock Quality Filter ────────────────────────────────────────────────────
# Pre-filter: stocks that fail these checks are excluded BEFORE the backtest.
# WHY filter? VN30 includes names with sporadic liquidity (NVL debt crisis,
# PDR margin calls) — trading them adds cost drag with no signal benefit.
STOCK_FILTER = {
    "enabled": True,
    "min_avg_volume": 500_000,     # Minimum avg daily volume (shares), ~60-day window
    "volume_lookback_days": 60,    # Window to compute average volume
    "min_history_days": 250,       # Need at least 250 trading days (~1 year)
}

# ─── Transaction Costs ────────────────────────────────────────────────────────
COSTS = {
    # TCBS brokerage: 0.15% buy + 0.15% sell + stamp duty 0.1% on sell
    # Conservative estimate: 0.25% per round-trip side
    "cost_per_trade_pct": 0.0025,

    # Minimum trade value in VND. Trades below this are skipped —
    # tiny adjustments cost disproportionately and add no value.
    "min_trade_value": 5_000_000,

    # Minimum capital required before framework makes sense
    # Below 200M VND, lot-size rounding and costs eat too much
    "min_recommended_capital_vnd": 200_000_000,
}

# ─── Data ─────────────────────────────────────────────────────────────────────
DATA = {
    "primary_source": "yfinance",
    "fallback_source": "vnstock",
    "cache_days": 1,            # Re-fetch if cache older than this
    "min_history_days": 250,    # Need at least 250 days for MA200 + cross-mom
    "fetch_chunk_days": 365,    # Fetch in 1-year chunks to avoid timeouts
    "request_timeout": 30,
}

# ─── Martin Luk Swing Strategy ────────────────────────────────────────────────
# Adapted from Martin Luk's USIC 1358% return swing trading method.
# Modified for VN30 daily bars: wider stops, higher base risk, T+2.5 settlement.
MARTIN_LUK = {
    # EMA Alignment
    "ema_fast": 9,
    "ema_mid": 21,
    "ema_slow": 50,

    # ADR Filter
    "adr_period": 20,           # 20-day rolling ADR
    "adr_min_pct": 0.025,       # 2.5% minimum (lowered from 5% for VN blue chips)

    # Entry
    "breakout_confirm_close": True,   # Require close above level (not just intraday)
    "inside_day_enabled": True,       # Enable inside-day breakout pattern
    "ema_convergence_pct": 0.015,     # 1.5% spread threshold for EMA convergence

    # Stop Loss
    "max_stop_pct": 0.05,       # 5% max stop distance (wider than Luk's 3.5% for VN daily)
    "stop_method": "breakout_low",    # "breakout_low" = low of breakout day

    # Position Sizing
    "risk_per_trade_pct": 0.0075,     # 0.75% of equity per trade (moderate)
    "risk_drawdown_pct": 0.00375,     # Halved to 0.375% during drawdowns
    "drawdown_threshold": 0.10,       # Start reducing risk at 10% drawdown from peak
    "max_position_pct": 0.10,         # Max 10% of equity per stock
    "max_total_exposure": 0.80,       # Max 80% total portfolio exposure

    # Exit / Partials
    "partial_1_r": 3.0,         # First partial sell at 3R profit
    "partial_1_pct": 0.25,      # Sell 25% of position
    "partial_2_r": 5.0,         # Second partial at 5R profit
    "partial_2_pct": 0.25,      # Sell another 25%
    "trail_ema": 9,             # Trail stop with EMA(9) after partial 2
    "exit_ema": 21,             # Full exit when close < EMA(21) after partials

    # Market Health (leader count breadth)
    "health_strong_pct": 0.50,  # >= 50% leaders = STRONG → full risk
    "health_cautious_pct": 0.27, # 27-49% leaders = CAUTIOUS → half risk

    # Settlement (HOSE)
    "settlement_days": 3,       # T+2.5 — can't sell until day 3

    # Lot size (HOSE)
    "lot_size": 100,

    # Transaction costs (same as Carver)
    "cost_per_trade_pct": 0.0025,

    # Warmup bars for EMA(50)
    "warmup_bars": 60,
}

# ─── Backtest ─────────────────────────────────────────────────────────────────
BACKTEST = {
    # Regime recalculated WEEKLY (not daily — prevents whipsaw, v4 bug lesson)
    "regime_update_days": 5,

    # Cross-momentum ranks updated monthly (matches signal design)
    "cross_mom_update_days": 21,

    # Walk-forward: train on N years, test on 1 year, step forward 1 year
    "wf_train_years": 2,
    "wf_test_years": 1,
}
