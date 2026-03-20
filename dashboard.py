"""
dashboard.py — Streamlit Web Dashboard
========================================
Run with:  python -m streamlit run dashboard.py

Pages:
  📊  Backtest Results   — equity curve, drawdown, annual returns, Carver scorecard
  📋  Backtest Trades    — trade table, P&L by ticker/month
  🔬  Permutation Test   — distribution chart, p-value, edge confidence
  🌡️  Regime Status      — current regime, VNIndex vs MA200, signal weights
  💼  Live Portfolio     — holdings, allocation, unrealised P&L
  ⚙️  Config             — current parameters with explanations
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VN Trading v5",
    page_icon="🇻🇳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Sidebar navigation ───────────────────────────────────────────────────────
st.sidebar.title("🇻🇳 VN Trading v5")
st.sidebar.caption("Semi-automatic framework for HOSE")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    [
        "📊  Backtest Results",
        "📋  Backtest Trades",
        "📈  Backtest History",
        "🔬  Permutation Test",
        "🌡️  Regime Status",
        "💼  Live Portfolio",
        "⚙️  Config",
    ],
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def load_csv(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.exists():
        return pd.read_csv(p, parse_dates=["date"] if "equity" in path else True)
    return pd.DataFrame()


def metric_card(label, value, delta=None, good_direction="up"):
    """Display a metric in a styled container."""
    if delta is not None:
        color = "green" if (delta > 0 and good_direction == "up") or \
                           (delta < 0 and good_direction == "down") else "red"
        st.metric(label=label, value=value, delta=delta)
    else:
        st.metric(label=label, value=value)


def fmt_pct(v, decimals=1):
    if v is None:
        return "—"
    return f"{v*100:+.{decimals}f}%"


def fmt_vnd(v):
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"{v/1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.1f}M"
    return f"{v:,.0f}"


def scorecard_row(label, value_str, threshold_str, passed):
    pass  # replaced by scorecard_table() below


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Backtest Results
# ═════════════════════════════════════════════════════════════════════════════

if page == "📊  Backtest Results":
    st.title("📊 Backtest Results")

    # ── History dropdown ──────────────────────────────────────────────────────
    hist_path = Path("outputs/backtest_history.json")
    history   = []
    if hist_path.exists():
        try:
            history = json.load(open(hist_path))
        except Exception:
            history = []

    selected_run = None
    if history:
        run_options = {
            f"{r.get('timestamp','')}  —  {r.get('params',{}).get('n_stocks','?')} stocks  "
            f"{r.get('params',{}).get('years','?')}y  [{r.get('params',{}).get('data_source','?')}]": i
            for i, r in enumerate(history)
        }
        label_list = list(run_options.keys())
        chosen = st.selectbox("Select backtest run", label_list,
                              index=len(label_list) - 1,
                              help="Defaults to latest run. Pick any historical run to review it.")
        selected_run = history[run_options[chosen]]
        st.caption(f"Showing run from {selected_run.get('timestamp','?')}")
    else:
        selected_run = {"metrics": load_json("outputs/backtest_results.json"),
                        "equity_file": "outputs/equity_curve.csv",
                        "trades_file": "outputs/trade_log.csv"}

    metrics   = (selected_run or {}).get("metrics", {}) or {}
    eq_file   = (selected_run or {}).get("equity_file") or "outputs/equity_curve.csv"
    equity_df = load_csv(eq_file)

    if not metrics:
        st.info("No backtest results yet. Run `python run_backtest.py` first.")
        st.code("python run_backtest.py --n 15 --real --years 3")
        st.stop()

    st.markdown("---")

    # ── Top metrics row ───────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("CAGR", fmt_pct(metrics.get("cagr")),
                  help="Target > 4.5% (bank FD rate)")
    with col2:
        st.metric("Sharpe Ratio", f"{metrics.get('sharpe', 0):.2f}",
                  help="Target > 0.40")
    with col3:
        st.metric("Max Drawdown", fmt_pct(metrics.get("max_drawdown")),
                  help="Target > -30%")
    with col4:
        st.metric("Cost Drag / yr", fmt_pct(metrics.get("cost_drag_annual")),
                  help="Target < 1.5%")
    with col5:
        st.metric("Trades / month", f"{metrics.get('trades_per_month', 0):.0f}",
                  help="Target < 30")

    st.markdown("---")

    # ── Equity curve (latest run only) ────────────────────────────────────────
    if not equity_df.empty:
        st.subheader("Equity Curve")

        if "date" not in equity_df.columns and equity_df.index.name == "date":
            equity_df = equity_df.reset_index()

        if "equity" in equity_df.columns and "date" in equity_df.columns:
            equity_df["date"] = pd.to_datetime(equity_df["date"])
            equity_df = equity_df.sort_values("date")

            import plotly.graph_objects as go
            from plotly.subplots import make_subplots

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.7, 0.3],
                                subplot_titles=["Portfolio Value (VND)", "Drawdown (%)"])

            fig.add_trace(go.Scatter(
                x=equity_df["date"], y=equity_df["equity"],
                name="Equity", line=dict(color="#1B6CA8", width=2),
                fill="tozeroy", fillcolor="rgba(27,108,168,0.08)"
            ), row=1, col=1)

            rolling_max = equity_df["equity"].cummax()
            drawdown    = (equity_df["equity"] - rolling_max) / rolling_max * 100
            fig.add_trace(go.Scatter(
                x=equity_df["date"], y=drawdown,
                name="Drawdown", line=dict(color="#E85D24", width=1.5),
                fill="tozeroy", fillcolor="rgba(232,93,36,0.15)"
            ), row=2, col=1)

            fig.update_layout(height=500, showlegend=False,
                              plot_bgcolor="rgba(0,0,0,0)",
                              paper_bgcolor="rgba(0,0,0,0)")
            fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)")
            fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
            st.plotly_chart(fig, use_container_width=True)

    # ── Carver Scorecard ──────────────────────────────────────────────────────
    st.subheader("Carver Scorecard")

    cagr    = metrics.get("cagr", 0) or 0
    sharpe  = metrics.get("sharpe", 0) or 0
    sortino = metrics.get("sortino", 0) or 0
    dd      = metrics.get("max_drawdown", 0) or 0
    vol     = metrics.get("annual_vol", 0) or 0
    wr      = metrics.get("win_rate", 0) or 0
    cost    = metrics.get("cost_drag_annual", 0) or 0

    scorecard_data = [
        ("CAGR",         fmt_pct(cagr),        "> 4.5%",    cagr >= 0.045),
        ("Sharpe Ratio", f"{sharpe:.2f}",       "> 0.40",    sharpe >= 0.40),
        ("Sortino",      f"{sortino:.2f}",      "> 0.50",    sortino >= 0.50),
        ("Max Drawdown", fmt_pct(dd),           "> -30%",    dd > -0.30),
        ("Annual Vol",   fmt_pct(vol),          "10–25%",    0.10 <= vol <= 0.25),
        ("Win Rate",     fmt_pct(wr),           "> 45%",     wr >= 0.45),
        ("Cost Drag/yr", fmt_pct(cost),         "< 1.5%",    cost < 0.015),
    ]

    sc_df = pd.DataFrame(scorecard_data, columns=["Metric", "Value", "Target", "_pass"])
    sc_df.insert(0, "Status", sc_df["_pass"].map({True: "✅", False: "❌"}))
    sc_df = sc_df.drop(columns=["_pass"])

    st.dataframe(
        sc_df.style
            .apply(lambda col: [
                "color: #3BB57A; font-weight: 600" if v == "✅" else "color: #E85D24; font-weight: 600"
                for v in col
            ] if col.name == "Status" else [""] * len(col), axis=0)
            .set_properties(**{"text-align": "left"})
            .hide(axis="index"),
        use_container_width=True,
        height=280,
    )

    # ── Annual returns bar chart ───────────────────────────────────────────────
    if not equity_df.empty and "date" in equity_df.columns and "equity" in equity_df.columns:
        st.subheader("Annual Returns")
        equity_df["date"] = pd.to_datetime(equity_df["date"])
        annual = equity_df.set_index("date")["equity"].resample("YE").last().pct_change().dropna()
        if not annual.empty:
            import plotly.graph_objects as go
            colors = ["#1B6CA8" if r > 0 else "#E85D24" for r in annual.values]
            fig2 = go.Figure(go.Bar(
                x=[str(d.year) for d in annual.index],
                y=annual.values * 100,
                marker_color=colors,
                text=[f"{r*100:+.1f}%" for r in annual.values],
                textposition="outside",
            ))
            fig2.update_layout(
                yaxis_title="Return (%)", height=300,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            )
            fig2.update_xaxes(gridcolor="rgba(128,128,128,0.1)")
            fig2.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
            st.plotly_chart(fig2, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Backtest Trades
# ═════════════════════════════════════════════════════════════════════════════

elif page == "📋  Backtest Trades":
    st.title("📋 Backtest Trades")

    # ── History dropdown (same pattern as Backtest Results) ───────────────────
    hist_path_t = Path("outputs/backtest_history.json")
    history_t   = []
    if hist_path_t.exists():
        try:
            history_t = json.load(open(hist_path_t))
        except Exception:
            history_t = []

    selected_run_t = None
    if history_t:
        run_options_t = {
            f"{r.get('timestamp','')}  —  {r.get('params',{}).get('n_stocks','?')} stocks  "
            f"{r.get('params',{}).get('years','?')}y  [{r.get('params',{}).get('data_source','?')}]": i
            for i, r in enumerate(history_t)
        }
        label_list_t = list(run_options_t.keys())
        chosen_t = st.selectbox("Select backtest run", label_list_t,
                                index=len(label_list_t) - 1,
                                help="Defaults to latest run.")
        selected_run_t = history_t[run_options_t[chosen_t]]
        st.caption(f"Showing run from {selected_run_t.get('timestamp','?')}")

    trades_file_t = (selected_run_t or {}).get("trades_file") or "outputs/trade_log.csv"
    trades_df = load_csv(trades_file_t)

    if trades_df.empty:
        st.info("No trade log yet. Run `python run_backtest.py` first.")
        st.stop()

    trades_df["date"] = pd.to_datetime(trades_df["date"])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Trades", len(trades_df))
    with col2:
        buys  = (trades_df["action"] == "BUY").sum()
        sells = (trades_df["action"] == "SELL").sum()
        st.metric("Buys / Sells", f"{buys} / {sells}")
    with col3:
        if "fee" in trades_df.columns:
            st.metric("Total Fees", fmt_vnd(trades_df["fee"].sum()))

    st.markdown("---")

    # Trades by ticker
    if "ticker" in trades_df.columns and "value" in trades_df.columns:
        st.subheader("Volume by Ticker")
        by_ticker = trades_df.groupby("ticker")["value"].sum().sort_values(ascending=False)
        import plotly.express as px
        fig = px.bar(by_ticker.reset_index(), x="ticker", y="value",
                     labels={"value": "Total Value (VND)", "ticker": ""},
                     color_discrete_sequence=["#1B6CA8"])
        fig.update_layout(height=300, plot_bgcolor="rgba(0,0,0,0)",
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # Monthly trade count
    st.subheader("Trades per Month")
    trades_df["month"] = trades_df["date"].dt.to_period("M").astype(str)
    monthly = trades_df.groupby("month").size().reset_index(name="count")
    fig2 = px.bar(monthly, x="month", y="count",
                  labels={"count": "Trades", "month": ""},
                  color_discrete_sequence=["#1B6CA8"])
    fig2.update_layout(height=280, plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig2, use_container_width=True)

    # ── Win / Loss summary per ticker ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("Win / Loss by Stock")
    st.caption("Each completed round-trip (BUY → SELL) counted as one trade. Open positions excluded.")

    wl_rows = []
    for ticker, grp in trades_df.groupby("ticker"):
        grp = grp.sort_values("date")
        buy_queue = []
        wins = losses = 0
        total_pnl = total_fees = 0.0

        for _, row in grp.iterrows():
            if row["action"] == "BUY":
                buy_queue.append({
                    "shares": int(row.get("shares", 0)),
                    "price":  float(row.get("price", 0)),
                    "fee":    float(row.get("fee", 0)),
                })
            elif row["action"] == "SELL" and buy_queue:
                sell_shares = abs(int(row.get("shares", 0)))
                sell_price  = float(row.get("price", 0))
                sell_fee    = float(row.get("fee", 0))
                remaining   = sell_shares

                while remaining > 0 and buy_queue:
                    buy     = buy_queue[0]
                    matched = min(remaining, buy["shares"])
                    pnl     = (matched * (sell_price - buy["price"])
                               - sell_fee * (matched / sell_shares)
                               - buy["fee"] * (matched / buy["shares"]))
                    total_pnl  += pnl
                    total_fees += sell_fee * (matched / sell_shares) + buy["fee"] * (matched / buy["shares"])
                    wins   += 1 if pnl >= 0 else 0
                    losses += 0 if pnl >= 0 else 1
                    buy["shares"] -= matched
                    remaining     -= matched
                    if buy["shares"] == 0:
                        buy_queue.pop(0)

        total_trades = wins + losses
        if total_trades == 0:
            continue
        wl_rows.append({
            "Ticker":     ticker,
            "Wins":       wins,
            "Losses":     losses,
            "Total":      total_trades,
            "Win Rate":   f"{wins/total_trades*100:.0f}%",
            "Total P&L":  fmt_vnd(total_pnl),
            "Avg P&L":    fmt_vnd(total_pnl / total_trades),
            "Fees Paid":  fmt_vnd(total_fees),
            "_pnl":       total_pnl,
            "_wr":        wins / total_trades,
        })

    if wl_rows:
        total_w   = sum(r["Wins"] for r in wl_rows)
        total_l   = sum(r["Losses"] for r in wl_rows)
        overall_wr  = total_w / (total_w + total_l) if (total_w + total_l) > 0 else 0
        overall_pnl = sum(r["_pnl"] for r in wl_rows)

        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Overall Win Rate", f"{overall_wr*100:.0f}%")
        with c2: st.metric("Total Wins",   total_w)
        with c3: st.metric("Total Losses", total_l)
        with c4: st.metric("Total P&L",    fmt_vnd(overall_pnl))

        wl_df = pd.DataFrame(wl_rows).sort_values("_pnl", ascending=False)
        st.dataframe(
            wl_df[["Ticker","Wins","Losses","Total","Win Rate","Total P&L","Avg P&L","Fees Paid"]],
            use_container_width=True,
            hide_index=True,
        )

        import plotly.graph_objects as go
        fig_pnl = go.Figure(go.Bar(
            x=wl_df["Ticker"],
            y=wl_df["_pnl"],
            marker_color=["#3BB57A" if v >= 0 else "#E85D24" for v in wl_df["_pnl"]],
            text=[fmt_vnd(v) for v in wl_df["_pnl"]],
            textposition="outside",
        ))
        fig_pnl.update_layout(
            yaxis_title="Total P&L (VND)", height=300,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        fig_pnl.update_xaxes(gridcolor="rgba(128,128,128,0.1)")
        fig_pnl.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
        st.plotly_chart(fig_pnl, use_container_width=True)
    else:
        st.info("No completed round-trips yet (need at least one BUY followed by a SELL for the same stock).")

    # Full table
    st.markdown("---")
    st.subheader("All Trades")
    display_cols = [c for c in ["date","ticker","action","shares","price","value","fee","regime","forecast"]
                    if c in trades_df.columns]
    st.dataframe(trades_df[display_cols].sort_values("date", ascending=False), use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Permutation Test
# ═════════════════════════════════════════════════════════════════════════════

elif page == "🔬  Permutation Test":
    st.title("🔬 Permutation Test — Statistical Edge Validation")

    perm = load_json("outputs/permutation_results.json")

    if not perm:
        st.info("No permutation test results yet.")
        st.code("python run_permutation_test.py --n_perm 100")
        st.stop()

    # Verdict banner
    p_val   = perm.get("p_value", 1.0)
    verdict = perm.get("verdict", "")
    if p_val < 0.01:
        st.success(f"✅✅ {verdict} — p-value: {p_val:.4f}")
    elif p_val < 0.05:
        st.success(f"✅ {verdict} — p-value: {p_val:.4f}")
    elif p_val < 0.10:
        st.warning(f"⚠️ {verdict} — p-value: {p_val:.4f}")
    else:
        st.error(f"❌ {verdict} — p-value: {p_val:.4f}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Real Strategy",
                  f"{perm.get('real_value', 0):+.3f}",
                  help=perm.get("metric","").upper())
    with col2:
        st.metric("Perm. Mean",   f"{perm.get('perm_mean', 0):+.3f}")
    with col3:
        st.metric("p-value",      f"{p_val:.4f}")
    with col4:
        st.metric("# Beats Real", f"{perm.get('n_beats_real', 0)} / {perm.get('n_permutations', 0)}")

    st.markdown("---")

    # Distribution chart
    dist = perm.get("perm_distribution", [])
    if dist:
        st.subheader("Permutation Distribution")
        import plotly.graph_objects as go

        real_val = perm.get("real_value", 0)
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=dist, nbinsx=30, name="Random shuffles",
            marker_color="#9FE1CB", opacity=0.8,
        ))
        fig.add_vline(x=real_val, line_color="#E85D24", line_width=2.5,
                      annotation_text=f"Real: {real_val:+.3f}",
                      annotation_font_color="#E85D24")
        fig.update_layout(
            xaxis_title=perm.get("metric","").upper(),
            yaxis_title="Count",
            height=350,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)")
        fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
        st.plotly_chart(fig, use_container_width=True)

        ci_low  = perm.get("p_ci_low", 0)
        ci_high = perm.get("p_ci_high", 0)
        st.caption(f"p-value 95% CI: [{ci_low:.4f}, {ci_high:.4f}]  "
                   f"({perm.get('n_permutations', 0)} permutations, "
                   f"{perm.get('years', '?')} years, "
                   f"{perm.get('n_stocks', '?')} stocks)")

    st.subheader("Interpretation Guide")
    st.markdown("""
| p-value | Meaning |
|---|---|
| < 0.01 | **Strong edge** — only 1% of random strategies do this well. Trade with confidence. |
| 0.01 – 0.05 | **Edge detected** — 95% confidence. Acceptable for live trading. |
| 0.05 – 0.10 | **Marginal** — More data needed. Paper-trade only. |
| > 0.10 | **No edge detected** — Do not trade this. Review signals. |

Run with more years of data for a more reliable result:
```bash
python run_permutation_test.py --real --years 5 --n_perm 200
```
""")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 4 — Regime Status
# ═════════════════════════════════════════════════════════════════════════════

elif page == "🌡️  Regime Status":
    st.title("🌡️ Current Market Regime")

    # Live regime detection
    with st.spinner("Fetching VNIndex data..."):
        try:
            from data.fetcher import fetch_ohlcv
            from signals.ma_regime import get_regime
            from config import VNINDEX_TICKER, SIZING

            end   = datetime.today()
            start = end - timedelta(days=300)
            df    = fetch_ohlcv(VNINDEX_TICKER, start, end)
            index_prices = df["close"] if not df.empty else pd.Series(dtype=float)

            if not index_prices.empty:
                result = get_regime(index_prices)
                fetched = True
            else:
                fetched = False
        except Exception as e:
            st.warning(f"Could not fetch live data: {e}")
            fetched = False

    if fetched:
        regime = result["regime"]
        col1, col2, col3 = st.columns(3)
        with col1:
            icon = "🟢" if regime == "BULL" else "🔴"
            st.metric("Regime", f"{icon} {regime}")
        with col2:
            pct = result.get("pct_vs_ma200", 0) or 0
            st.metric("VNIndex vs MA200", fmt_pct(pct),
                      delta=f"{pct*100:+.1f}%")
        with col3:
            tau_eff = SIZING["target_vol"] * result["tau_multiplier"]
            st.metric("Effective τ", fmt_pct(tau_eff))

        if not result["allow_new_entries"]:
            st.error("⛔ BEAR REGIME — No new long entries. Existing positions managed with half sizing.")
        else:
            st.success("✅ BULL REGIME — Full position sizing active.")

        st.markdown("---")

        # VNIndex vs MA200 chart
        st.subheader("VNIndex vs 200-day MA")
        if not index_prices.empty:
            ma200 = index_prices.rolling(200).mean()
            import plotly.graph_objects as go

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=index_prices.index, y=index_prices,
                                     name="VNIndex", line=dict(color="#1B6CA8", width=2)))
            fig.add_trace(go.Scatter(x=ma200.index, y=ma200,
                                     name="MA200", line=dict(color="#E85D24", width=1.5, dash="dash")))
            fig.update_layout(height=350, plot_bgcolor="rgba(0,0,0,0)",
                               paper_bgcolor="rgba(0,0,0,0)",
                               legend=dict(orientation="h", yanchor="bottom", y=1.02))
            fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)")
            fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
            st.plotly_chart(fig, use_container_width=True)

        # Signal weight table for current regime
        st.subheader("Signal Weights — Current Regime")
        from config import SIGNAL_WEIGHTS, MA_REGIME

        tau_mult = result["tau_multiplier"]
        st.markdown(f"""
| Signal | Weight | Status |
|---|---|---|
| MA Regime Filter | — | {'🟢 BULL — full τ' if regime == 'BULL' else '🔴 BEAR — τ × 0.5'} |
| Cross-Sectional Momentum | {SIGNAL_WEIGHTS['cross_momentum']*100:.0f}% | {'🟢 Active' if regime == 'BULL' else '⚪ No new entries'} |
| IBS Mean Reversion | {SIGNAL_WEIGHTS['ibs']*100:.0f}% | {'🟢 Active' if regime == 'BULL' else '🔴 Disabled'} |
| Target Vol (τ) | {SIZING['target_vol']*100:.0f}% × {tau_mult} = {SIZING['target_vol']*tau_mult*100:.0f}% | {'Full' if tau_mult == 1.0 else 'Halved (BEAR)'} |
""")
    else:
        st.info("Could not load live data. Check internet connection or run `python main.py --test` to test offline.")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 5 — Live Portfolio
# ═════════════════════════════════════════════════════════════════════════════

elif page == "💼  Live Portfolio":
    st.title("💼 Live Portfolio")

    holdings_data = load_json("outputs/holdings.json")
    trade_log     = load_json("outputs/live_trade_log.json")

    if isinstance(trade_log, list):
        trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    else:
        trade_df = pd.DataFrame()

    if not holdings_data:
        st.info("No live holdings yet.")
        st.markdown("""
**To record a trade:**
```python
from portfolio.tracker import PortfolioTracker
tracker = PortfolioTracker()
tracker.record_trade("VCB.VN", action="BUY", shares=500, price=88500)
```
""")
        st.stop()

    st.metric("Open Positions", len(holdings_data))

    # Holdings table
    st.subheader("Current Holdings")
    holdings_df = pd.DataFrame([
        {"Ticker": t, "Shares": s}
        for t, s in holdings_data.items()
    ])

    # Fetch current prices
    try:
        from data.fetcher import fetch_close_matrix
        end   = datetime.today()
        start = end - timedelta(days=10)
        tickers = list(holdings_data.keys())
        price_matrix = fetch_close_matrix(tickers, start, end, verbose=False)
        if not price_matrix.empty:
            latest_prices = price_matrix.iloc[-1].to_dict()
            holdings_df["Price"] = holdings_df["Ticker"].map(lambda t: latest_prices.get(t, 0))
            holdings_df["Market Value"] = holdings_df["Shares"] * holdings_df["Price"]
    except Exception:
        latest_prices = {}

    st.dataframe(holdings_df, use_container_width=True)

    # Allocation pie chart
    if "Market Value" in holdings_df.columns and holdings_df["Market Value"].sum() > 0:
        st.subheader("Allocation")
        import plotly.express as px
        fig = px.pie(holdings_df, values="Market Value", names="Ticker",
                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3)
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    # Trade log
    if not trade_df.empty:
        st.subheader("Trade Log")
        st.dataframe(trade_df.sort_values("date", ascending=False) if "date" in trade_df.columns else trade_df,
                     use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 6 — Config
# ═════════════════════════════════════════════════════════════════════════════

elif page == "📈  Backtest History":
    st.title("📈 Backtest History")
    st.caption("Every run of run_backtest.py is logged here automatically.")

    hist_path = Path("outputs/backtest_history.json")
    if not hist_path.exists():
        st.info("No history yet. Run `python run_backtest.py` at least twice to compare results.")
        st.code("python run_backtest.py --n 10\npython run_backtest.py --n 15")
        st.stop()

    with open(hist_path) as f:
        history = json.load(f)

    if not history:
        st.info("History file is empty.")
        st.stop()

    st.metric("Total runs logged", len(history))

    # ── Build comparison table ────────────────────────────────────────────────
    rows = []
    for r in history:
        m = r.get("metrics", {})
        p = r.get("params", {})
        rows.append({
            "Run":        r.get("run_id", ""),
            "Time":       r.get("timestamp", ""),
            "Stocks":     p.get("n_stocks", ""),
            "Years":      p.get("years", ""),
            "Data":       p.get("data_source", ""),
            "CAGR":       fmt_pct(m.get("cagr")),
            "Sharpe":     f"{m.get('sharpe', 0):.2f}",
            "Max DD":     fmt_pct(m.get("max_drawdown")),
            "Ann Vol":    fmt_pct(m.get("annual_vol")),
            "Win Rate":   fmt_pct(m.get("win_rate")),
            "Cost/yr":    fmt_pct(m.get("cost_drag_annual")),
            "Trades/mo":  f"{m.get('trades_per_month', 0):.0f}",
        })

    df_hist = pd.DataFrame(rows)
    st.markdown("---")
    st.subheader("All Runs")
    st.dataframe(df_hist, use_container_width=True)

    # run_labels defined here so both the compare section and delete section can use it
    run_labels = [
        f"{r.get('run_id','')} — {r.get('timestamp','')} "
        f"({r.get('params',{}).get('n_stocks','?')}s, {r.get('params',{}).get('years','?')}y)"
        for r in history
    ]

    # ── Delete a run ──────────────────────────────────────────────────────────
    with st.expander("⚠️  Manage history"):
        st.caption("Remove a specific run from the history log.")
        del_idx = st.selectbox("Select run to delete", range(len(run_labels)),
                               format_func=lambda i: run_labels[i])
        if st.button("Delete this run"):
            history.pop(del_idx)
            with open(hist_path, "w") as f:
                json.dump(history, f, indent=2)
            st.success("Deleted. Refresh the page to see updated history.")

        if st.button("🗑️  Clear ALL history"):
            open(hist_path, "w").write("[]")
            st.warning("All history cleared.")


elif page == "⚙️  Config":
    st.title("⚙️ Current Configuration")
    st.caption("All parameters are in config.py. Edit that file to change behaviour.")

    from config import (UNIVERSE, MA_REGIME, CROSS_MOMENTUM, IBS,
                        SIGNAL_WEIGHTS, FDM, SIZING, COSTS, BACKTEST)

    st.subheader("Universe")
    st.write(f"{len(UNIVERSE)} stocks: {', '.join(UNIVERSE)}")

    st.subheader("Signal Parameters")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**MA Regime Filter (Signal 1)**")
        st.json(MA_REGIME)
        st.markdown("**IBS (Signal 3)**")
        st.json(IBS)
    with col2:
        st.markdown("**Cross-Sectional Momentum (Signal 2)**")
        st.json(CROSS_MOMENTUM)
        st.markdown("**Signal Weights & FDM**")
        st.json({**SIGNAL_WEIGHTS, "FDM": FDM})

    st.subheader("Position Sizing (Signal 4)")
    st.json(SIZING)

    st.subheader("Costs & Backtest")
    col3, col4 = st.columns(2)
    with col3:
        st.json(COSTS)
    with col4:
        st.json(BACKTEST)

    st.markdown("---")
    st.subheader("Anti-Overfitting Checklist")
    st.markdown("""
| Parameter | Value | Justification |
|---|---|---|
| MA period | **200** | Global standard. Not optimised for VN. |
| Momentum lookback | **63 days** | = 3 months. Round number, academic consensus. |
| Momentum skip | **5 days** | = 1 week. Avoids short-term reversal bias. |
| IBS oversold | **0.20** | Textbook value. |
| IBS overbought | **0.80** | Textbook value. |
| Rebalance freq | **21 days** | = Monthly. Cost-driven, not backtest-optimised. |
| Buffer zone | **20%** | From Carver theory (not backtested). |
| τ (target vol) | **25%** | Raised from 20% for VN correlation correction. |
| Regime update | **Weekly** | Prevents whipsaw. Not optimised frequency. |
""")