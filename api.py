"""
api.py — FastAPI backend for the VN Trading v5 React Dashboard
==============================================================
Run:  uvicorn api:app --reload --port 8000

In development, the Vite frontend (port 5173) proxies /api/* here.
In production, serve the built frontend from frontend/dist/ as static files.
"""

import copy
import json
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="VN Trading v5 API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)
CONFIG_OVERRIDE_PATH = OUTPUTS_DIR / "config_override.json"

# ─── Full VN30 — authoritative list used by the API ───────────────────────────
# config.py UNIVERSE is patched to this list before every backtest run
VN30_FULL: List[str] = [
    "VCB.VN", "BID.VN", "CTG.VN", "TCB.VN", "MBB.VN",
    "VPB.VN", "ACB.VN", "HDB.VN", "STB.VN", "TPB.VN",
    "SHB.VN", "HPG.VN", "GAS.VN", "PLX.VN", "POW.VN",
    "REE.VN", "VHM.VN", "VIC.VN", "MSN.VN", "BCM.VN",
    "KDH.VN", "NVL.VN", "PDR.VN", "FPT.VN", "MWG.VN",
    "PNJ.VN", "SAB.VN", "SSI.VN", "VND.VN", "DGC.VN",
]

# ─── Job registry ─────────────────────────────────────────────────────────────
_jobs: Dict[str, Dict[str, Any]] = {}
_backtest_lock = threading.Lock()  # Only one backtest at a time (config is global)

# ─── Pydantic models ──────────────────────────────────────────────────────────
class BacktestParams(BaseModel):
    n_stocks: int = 15
    years: int = 3
    capital: float = 500_000_000
    use_real: bool = False
    config_overrides: Optional[Dict[str, Any]] = None


class PermutationParams(BaseModel):
    n_perm: int = 100
    years: int = 3
    n_stocks: int = 10
    use_real: bool = False
    metric: str = "sharpe"


# ─── Config helpers ───────────────────────────────────────────────────────────
def _load_config_overrides() -> Dict:
    if CONFIG_OVERRIDE_PATH.exists():
        try:
            return json.loads(CONFIG_OVERRIDE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_config_overrides(overrides: Dict):
    OUTPUTS_DIR.mkdir(exist_ok=True)
    CONFIG_OVERRIDE_PATH.write_text(json.dumps(overrides, indent=2))


# Maps flat override key → (config dict name, field name inside dict)
# Only dict-based configs work at runtime; scalars (FDM, FORECAST_CAP) need restart.
_OVERRIDE_MAP = {
    "ma_period":             ("MA_REGIME",       "ma_period"),
    "confirm_days":          ("MA_REGIME",       "confirm_days"),
    "bear_tau_multiplier":   ("MA_REGIME",       "bear_tau_multiplier"),
    "bear_new_entries":      ("MA_REGIME",       "bear_new_entries"),
    "lookback_days":         ("CROSS_MOMENTUM",  "lookback_days"),
    "skip_recent_days":      ("CROSS_MOMENTUM",  "skip_recent_days"),
    "rebalance_every_days":  ("CROSS_MOMENTUM",  "rebalance_every_days"),
    "top_pct":               ("CROSS_MOMENTUM",  "top_pct"),
    "bottom_pct":            ("CROSS_MOMENTUM",  "bottom_pct"),
    "oversold_threshold":    ("IBS",             "oversold_threshold"),
    "overbought_threshold":  ("IBS",             "overbought_threshold"),
    "only_in_bull_regime":   ("IBS",             "only_in_bull_regime"),
    "target_vol":            ("SIZING",          "target_vol"),
    "buffer_fraction":       ("SIZING",          "buffer_fraction"),
    "max_position_pct":      ("SIZING",          "max_position_pct"),
    "cost_per_trade_pct":    ("COSTS",           "cost_per_trade_pct"),
    "weight_cross_momentum": ("SIGNAL_WEIGHTS",  "cross_momentum"),
    "weight_ibs":            ("SIGNAL_WEIGHTS",  "ibs"),
    "vol_lookback":          ("SIZING",          "vol_lookback"),
    "filter_enabled":        ("STOCK_FILTER",    "enabled"),
    "min_avg_volume":        ("STOCK_FILTER",    "min_avg_volume"),
    "volume_lookback_days":  ("STOCK_FILTER",    "volume_lookback_days"),
    "min_history_days":      ("STOCK_FILTER",    "min_history_days"),
}


def _apply_overrides(overrides: Dict) -> Dict:
    """
    Mutate config module dicts in-place with override values.
    Returns a deep-copy snapshot of the originals for later restore.
    """
    import config as cfg
    snapshot = {
        "MA_REGIME":      copy.deepcopy(cfg.MA_REGIME),
        "CROSS_MOMENTUM": copy.deepcopy(cfg.CROSS_MOMENTUM),
        "IBS":            copy.deepcopy(cfg.IBS),
        "SIGNAL_WEIGHTS": copy.deepcopy(cfg.SIGNAL_WEIGHTS),
        "SIZING":         copy.deepcopy(cfg.SIZING),
        "COSTS":          copy.deepcopy(cfg.COSTS),
        "STOCK_FILTER":   copy.deepcopy(cfg.STOCK_FILTER),
        "UNIVERSE":       list(cfg.UNIVERSE),
    }
    for key, value in overrides.items():
        if key in _OVERRIDE_MAP:
            dict_name, field = _OVERRIDE_MAP[key]
            target = getattr(cfg, dict_name)
            target[field] = value
    return snapshot


def _restore_config(snapshot: Dict):
    """Restore config module dicts to the snapshot taken before the run."""
    import config as cfg
    for attr in ("MA_REGIME", "CROSS_MOMENTUM", "IBS", "SIGNAL_WEIGHTS", "SIZING", "COSTS", "STOCK_FILTER"):
        target = getattr(cfg, attr)
        target.clear()
        target.update(snapshot[attr])
    cfg.UNIVERSE[:] = snapshot["UNIVERSE"]


# ─── Backtest job executor (runs in a thread) ─────────────────────────────────
def _execute_backtest(job_id: str, params: BacktestParams):
    with _backtest_lock:
        snapshot = {}
        try:
            import config as cfg
            from run_backtest import run_backtest

            # Merge saved + per-request overrides (per-request takes precedence)
            saved_overrides = _load_config_overrides()
            merged = {**saved_overrides, **(params.config_overrides or {})}
            snapshot = _apply_overrides(merged)

            # Always use the full VN30 list; n_stocks slices it
            cfg.UNIVERSE[:] = VN30_FULL

            _jobs[job_id]["stage"] = "fetching_data" if params.use_real else "generating_data"
            _jobs[job_id]["progress"] = 10

            result = run_backtest(
                n_stocks=min(params.n_stocks, len(VN30_FULL)),
                years=params.years,
                capital=params.capital,
                use_real=params.use_real,
                verbose=False,
            )

            _jobs[job_id]["progress"] = 95
            _jobs[job_id]["stage"] = "saving_results"

            if result is None:
                _jobs[job_id].update({
                    "status": "failed",
                    "stage": "done",
                    "progress": 100,
                    "error": "No data returned. Check internet connection or use mock data.",
                })
            else:
                m = result["metrics"]
                # Make sure all values are JSON-serialisable
                clean_metrics = {
                    k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                    for k, v in m.items()
                }
                _jobs[job_id].update({
                    "status": "completed",
                    "stage": "done",
                    "progress": 100,
                    "result": {"metrics": clean_metrics},
                    "error": None,
                })

        except Exception as e:
            _jobs[job_id].update({
                "status": "failed",
                "stage": "error",
                "progress": 0,
                "error": str(e),
            })
            traceback.print_exc()
        finally:
            if snapshot:
                try:
                    _restore_config(snapshot)
                except Exception:
                    pass


def _execute_permutation(job_id: str, params: PermutationParams):
    with _backtest_lock:
        snapshot = {}
        try:
            import config as cfg
            from run_permutation_test import run_permutation_test

            saved_overrides = _load_config_overrides()
            snapshot = _apply_overrides(saved_overrides)
            cfg.UNIVERSE[:] = VN30_FULL

            _jobs[job_id]["stage"] = "running_permutations"
            _jobs[job_id]["progress"] = 10

            def _progress_cb(completed, total):
                # Scale progress 10-95 during permutations
                pct = 10 + int(85 * completed / max(total, 1))
                _jobs[job_id]["progress"] = min(pct, 95)
                _jobs[job_id]["stage"] = f"permutation {completed}/{total}"

            result = run_permutation_test(
                n_perm=params.n_perm,
                n_stocks=min(params.n_stocks, len(VN30_FULL)),
                years=params.years,
                capital=500_000_000,
                use_real=params.use_real,
                metric=params.metric,
                verbose=False,
                progress_callback=_progress_cb,
            )

            _jobs[job_id].update({
                "status": "completed",
                "stage": "done",
                "progress": 100,
                "result": result,
                "error": None,
            })

        except Exception as e:
            _jobs[job_id].update({
                "status": "failed",
                "stage": "error",
                "progress": 0,
                "error": str(e),
            })
            traceback.print_exc()
        finally:
            if snapshot:
                try:
                    _restore_config(snapshot)
                except Exception:
                    pass


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _load_history() -> List[Dict]:
    path = OUTPUTS_DIR / "backtest_history.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _find_run(run_id: str) -> Optional[Dict]:
    history = _load_history()
    return next((r for r in history if r.get("run_id") == run_id), None)


def _read_equity_csv(path: Path) -> List[Dict]:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = df["date"].astype(str)
    eq = df["equity"].astype(float)
    rolling_max = eq.cummax()
    df["drawdown"] = ((eq - rolling_max) / rolling_max * 100).round(2)
    # Replace NaN with None for JSON serialisation
    return df.where(pd.notna(df), None).to_dict(orient="records")


def _read_trades_csv(path: Path) -> List[Dict]:
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).astype(str)
    for col in ("price", "value", "fee", "forecast"):
        if col in df.columns:
            df[col] = df[col].round(2)
    return df.where(pd.notna(df), None).to_dict(orient="records")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/universe")
def get_universe():
    return {"tickers": VN30_FULL, "count": len(VN30_FULL)}


@app.get("/api/history")
def get_history():
    runs = _load_history()
    return {"runs": runs, "count": len(runs)}


@app.delete("/api/history/{run_id}")
def delete_history_run(run_id: str):
    path = OUTPUTS_DIR / "backtest_history.json"
    if not path.exists():
        raise HTTPException(404, "No history file")
    runs = _load_history()
    original_count = len(runs)
    runs = [r for r in runs if r.get("run_id") != run_id]
    if len(runs) == original_count:
        raise HTTPException(404, f"Run '{run_id}' not found")
    path.write_text(json.dumps(runs, indent=2))
    return {"deleted": run_id, "remaining": len(runs)}


@app.delete("/api/history")
def clear_all_history():
    (OUTPUTS_DIR / "backtest_history.json").write_text("[]")
    return {"cleared": True}


@app.get("/api/equity/{run_id}")
def get_equity(run_id: str):
    if run_id == "latest":
        path = OUTPUTS_DIR / "equity_curve.csv"
    else:
        path = OUTPUTS_DIR / f"equity_{run_id}.csv"

    if not path.exists():
        raise HTTPException(404, f"Equity file not found for run '{run_id}'")
    try:
        return _read_equity_csv(path)
    except Exception as e:
        raise HTTPException(500, f"Failed to read equity: {e}")


@app.get("/api/trades/{run_id}")
def get_trades(run_id: str):
    if run_id == "latest":
        path = OUTPUTS_DIR / "trade_log.csv"
    else:
        path = OUTPUTS_DIR / f"trades_{run_id}.csv"

    if not path.exists():
        raise HTTPException(404, f"Trades file not found for run '{run_id}'")
    try:
        return _read_trades_csv(path)
    except Exception as e:
        raise HTTPException(500, f"Failed to read trades: {e}")


@app.get("/api/metrics/{run_id}")
def get_metrics(run_id: str):
    if run_id == "latest":
        path = OUTPUTS_DIR / "backtest_results.json"
        if not path.exists():
            raise HTTPException(404, "No results yet")
        return json.loads(path.read_text())
    run = _find_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return run.get("metrics", {})


@app.get("/api/permutation")
def get_permutation():
    path = OUTPUTS_DIR / "permutation_results.json"
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text())
        data["available"] = True
        return data
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/run-backtest")
async def start_backtest(params: BacktestParams):
    import asyncio
    job_id = str(uuid4())
    _jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "result": None,
        "error": None,
    }
    asyncio.create_task(asyncio.to_thread(_execute_backtest, job_id, params))
    return {"job_id": job_id}


@app.post("/api/run-permutation")
async def start_permutation(params: PermutationParams):
    import asyncio
    job_id = str(uuid4())
    _jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "result": None,
        "error": None,
    }
    asyncio.create_task(asyncio.to_thread(_execute_permutation, job_id, params))
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return _jobs[job_id]


@app.get("/api/regime")
def get_regime():
    try:
        from data.fetcher import fetch_index_prices
        from signals.ma_regime import get_regime as _get_regime
        from config import VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS, SIZING, SIGNAL_WEIGHTS

        end = datetime.today()
        start = end - timedelta(days=310)   # Need > 200 days for MA200
        index_prices = fetch_index_prices(
            VNINDEX_TICKER, VNINDEX_FALLBACK_TICKERS, start, end
        )

        if index_prices.empty:
            return {"available": False, "error": "Could not fetch VNIndex data"}

        regime_data = _get_regime(index_prices)
        regime_data["available"] = True
        regime_data["effective_tau"] = round(
            SIZING["target_vol"] * regime_data.get("tau_multiplier", 1.0), 4
        )
        regime_data["signal_weights"] = dict(SIGNAL_WEIGHTS)
        regime_data["target_vol"] = SIZING["target_vol"]

        # Build chart data (last ~252 trading days)
        ma200 = index_prices.rolling(200).mean()
        chart_data = []
        for date, price in index_prices.items():
            ma_val = ma200.get(date)
            chart_data.append({
                "date": str(date.date()),
                "vnindex": round(float(price), 2),
                "ma200": (round(float(ma_val), 2) if ma_val is not None and not np.isnan(ma_val) else None),
            })
        regime_data["chart_data"] = chart_data[-252:]

        # Serialise numpy types
        clean = {}
        for k, v in regime_data.items():
            if isinstance(v, (np.floating, np.integer)):
                clean[k] = float(v)
            else:
                clean[k] = v
        return clean

    except Exception as e:
        traceback.print_exc()
        return {"available": False, "error": str(e)}


@app.get("/api/config")
def get_config():
    import config as cfg
    overrides = _load_config_overrides()
    return {
        "MA_REGIME":      dict(cfg.MA_REGIME),
        "CROSS_MOMENTUM": dict(cfg.CROSS_MOMENTUM),
        "IBS":            dict(cfg.IBS),
        "SIGNAL_WEIGHTS": dict(cfg.SIGNAL_WEIGHTS),
        "FDM":            cfg.FDM,
        "FORECAST_CAP":   cfg.FORECAST_CAP,
        "SIZING":         {k: v for k, v in cfg.SIZING.items() if k != "idm_table"},
        "COSTS":          dict(cfg.COSTS),
        "STOCK_FILTER":   dict(cfg.STOCK_FILTER),
        "BACKTEST":       dict(cfg.BACKTEST),
        "UNIVERSE":       list(cfg.UNIVERSE),
        "overrides":      overrides,
        "has_overrides":  bool(overrides),
    }


@app.post("/api/config")
def save_config(body: Dict[str, Any]):
    allowed = set(_OVERRIDE_MAP.keys())
    filtered = {k: v for k, v in body.items() if k in allowed}
    _save_config_overrides(filtered)
    return {"saved": True, "overrides": filtered}


@app.delete("/api/config/overrides")
def clear_config_overrides():
    if CONFIG_OVERRIDE_PATH.exists():
        CONFIG_OVERRIDE_PATH.unlink()
    return {"cleared": True}


@app.get("/api/portfolio")
def get_portfolio():
    holdings: Dict = {}
    trades: List = []

    holdings_path = OUTPUTS_DIR / "holdings.json"
    if holdings_path.exists():
        try:
            holdings = json.loads(holdings_path.read_text())
        except Exception:
            pass

    trade_log_path = OUTPUTS_DIR / "live_trade_log.json"
    if trade_log_path.exists():
        try:
            data = json.loads(trade_log_path.read_text())
            trades = data if isinstance(data, list) else []
        except Exception:
            pass

    return {
        "holdings": holdings,
        "open_positions": len(holdings),
        "trades": trades[-50:],
        "available": bool(holdings),
    }


# ─── Serve built frontend (production) ────────────────────────────────────────
_dist = Path("frontend/dist")
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
