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
    strategy: str = "carver"  # "carver" or "martin_luk"
    config_overrides: Optional[Dict[str, Any]] = None


class PermutationParams(BaseModel):
    n_perm: int = 100
    years: int = 3
    n_stocks: int = 10
    use_real: bool = False
    metric: str = "sharpe"
    strategy: str = "carver"


class WalkForwardParams(BaseModel):
    years: int = 10
    train_years: int = 3
    test_months: int = 6
    n_stocks: int = 10
    strategy: str = "carver"
    metric: str = "sharpe"
    use_real: bool = True


class WfPermutationParams(BaseModel):
    n_perm: int = 100
    years: int = 10
    train_years: int = 3
    test_months: int = 6
    n_stocks: int = 10
    strategy: str = "carver"
    metric: str = "sharpe"
    use_real: bool = True


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
    "bear_top_n_entries":    ("MA_REGIME",       "bear_top_n_entries"),
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
    # Martin Luk
    "ml_ema_fast":           ("MARTIN_LUK",     "ema_fast"),
    "ml_ema_mid":            ("MARTIN_LUK",     "ema_mid"),
    "ml_ema_slow":           ("MARTIN_LUK",     "ema_slow"),
    "ml_adr_period":         ("MARTIN_LUK",     "adr_period"),
    "ml_adr_min_pct":        ("MARTIN_LUK",     "adr_min_pct"),
    "ml_breakout_confirm":   ("MARTIN_LUK",     "breakout_confirm_close"),
    "ml_inside_day":         ("MARTIN_LUK",     "inside_day_enabled"),
    "ml_ema_convergence":    ("MARTIN_LUK",     "ema_convergence_pct"),
    "ml_max_stop_pct":       ("MARTIN_LUK",     "max_stop_pct"),
    "ml_risk_per_trade":     ("MARTIN_LUK",     "risk_per_trade_pct"),
    "ml_risk_drawdown":      ("MARTIN_LUK",     "risk_drawdown_pct"),
    "ml_drawdown_threshold": ("MARTIN_LUK",     "drawdown_threshold"),
    "ml_max_position_pct":   ("MARTIN_LUK",     "max_position_pct"),
    "ml_max_exposure":       ("MARTIN_LUK",     "max_total_exposure"),
    "ml_partial_1_r":        ("MARTIN_LUK",     "partial_1_r"),
    "ml_partial_1_pct":      ("MARTIN_LUK",     "partial_1_pct"),
    "ml_partial_2_r":        ("MARTIN_LUK",     "partial_2_r"),
    "ml_partial_2_pct":      ("MARTIN_LUK",     "partial_2_pct"),
    "ml_trail_ema":          ("MARTIN_LUK",     "trail_ema"),
    "ml_exit_ema":           ("MARTIN_LUK",     "exit_ema"),
    "ml_health_strong":      ("MARTIN_LUK",     "health_strong_pct"),
    "ml_health_cautious":    ("MARTIN_LUK",     "health_cautious_pct"),
    "ml_cost_per_trade":     ("MARTIN_LUK",     "cost_per_trade_pct"),
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
        "MARTIN_LUK":     copy.deepcopy(cfg.MARTIN_LUK),
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
    for attr in ("MA_REGIME", "CROSS_MOMENTUM", "IBS", "SIGNAL_WEIGHTS", "SIZING", "COSTS", "STOCK_FILTER", "MARTIN_LUK"):
        target = getattr(cfg, attr)
        target.clear()
        target.update(snapshot[attr])
    cfg.UNIVERSE[:] = snapshot["UNIVERSE"]


from contextlib import contextmanager

@contextmanager
def _with_overrides():
    """Context manager: apply saved config overrides, then restore on exit."""
    overrides = _load_config_overrides()
    if not overrides:
        yield
        return
    snapshot = _apply_overrides(overrides)
    try:
        yield
    finally:
        _restore_config(snapshot)


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
                strategy=params.strategy,
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
                strategy=params.strategy,
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


# ─── Walk-Forward executors ──────────────────────────────────────────────────

def _execute_walk_forward(job_id: str, params: WalkForwardParams):
    with _backtest_lock:
        snapshot = {}
        try:
            import config as cfg
            from run_walk_forward import run_walk_forward

            saved_overrides = _load_config_overrides()
            snapshot = _apply_overrides(saved_overrides)
            cfg.UNIVERSE[:] = VN30_FULL

            _jobs[job_id]["stage"] = "walk_forward"
            _jobs[job_id]["progress"] = 5

            def _progress_cb(completed, total):
                pct = 5 + int(90 * completed / max(total, 1))
                _jobs[job_id]["progress"] = min(pct, 95)
                _jobs[job_id]["stage"] = f"window {completed}/{total}"

            result = run_walk_forward(
                years=params.years,
                train_years=params.train_years,
                test_months=params.test_months,
                n_stocks=min(params.n_stocks, len(VN30_FULL)),
                strategy=params.strategy,
                metric=params.metric,
                use_real=params.use_real,
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


def _execute_wf_permutation(job_id: str, params: WfPermutationParams):
    with _backtest_lock:
        snapshot = {}
        try:
            import config as cfg
            from run_walk_forward import run_wf_permutation

            saved_overrides = _load_config_overrides()
            snapshot = _apply_overrides(saved_overrides)
            cfg.UNIVERSE[:] = VN30_FULL

            _jobs[job_id]["stage"] = "walk_forward + permutations"
            _jobs[job_id]["progress"] = 5

            def _progress_cb(completed, total):
                pct = 5 + int(90 * completed / max(total, 1))
                _jobs[job_id]["progress"] = min(pct, 95)
                _jobs[job_id]["stage"] = f"step {completed}/{total}"

            result = run_wf_permutation(
                n_perm=params.n_perm,
                years=params.years,
                train_years=params.train_years,
                test_months=params.test_months,
                n_stocks=min(params.n_stocks, len(VN30_FULL)),
                strategy=params.strategy,
                metric=params.metric,
                use_real=params.use_real,
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
    # Forward-fill NaN equity/positions_value (from missing price data on some dates)
    for col in ("equity", "positions_value"):
        if col in df.columns:
            df[col] = df[col].ffill().bfill()
    eq = df["equity"].astype(float)
    rolling_max = eq.cummax()
    df["drawdown"] = ((eq - rolling_max) / rolling_max * 100).round(2)
    # Replace NaN with None — must convert to object dtype first so None sticks
    records = df.to_dict(orient="records")
    import math
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
    return records


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


@app.delete("/api/cache")
def clear_data_cache():
    """Delete all cached market data CSV files."""
    from data.fetcher import CACHE_DIR
    if CACHE_DIR.exists():
        files = list(CACHE_DIR.glob("*.csv"))
        for f in files:
            f.unlink()
        return {"cleared": True, "files_deleted": len(files)}
    return {"cleared": True, "files_deleted": 0}


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


@app.get("/api/walk-forward")
def get_walk_forward():
    path = OUTPUTS_DIR / "walk_forward_results.json"
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text())
        data["available"] = True
        return data
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/run-walk-forward")
async def start_walk_forward(params: WalkForwardParams):
    import asyncio
    job_id = str(uuid4())
    _jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "result": None,
        "error": None,
    }
    asyncio.create_task(asyncio.to_thread(_execute_walk_forward, job_id, params))
    return {"job_id": job_id}


@app.get("/api/wf-permutation")
def get_wf_permutation():
    path = OUTPUTS_DIR / "wf_permutation_results.json"
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text())
        data["available"] = True
        return data
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/run-wf-permutation")
async def start_wf_permutation(params: WfPermutationParams):
    import asyncio
    job_id = str(uuid4())
    _jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "progress": 0,
        "result": None,
        "error": None,
    }
    asyncio.create_task(asyncio.to_thread(_execute_wf_permutation, job_id, params))
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return _jobs[job_id]


@app.get("/api/regime")
def get_regime():
    with _with_overrides():
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
        "MARTIN_LUK":    {k: v for k, v in cfg.MARTIN_LUK.items() if k != "stop_method"},
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


@app.post("/api/config/save-to-file")
def save_config_to_file():
    """
    Write current overrides permanently into config.py, then clear the overrides file.
    This makes the overrides the new defaults.
    """
    import config as cfg
    overrides = _load_config_overrides()
    if not overrides:
        return {"saved": False, "message": "No overrides to save."}

    config_path = Path("config.py")
    if not config_path.exists():
        raise HTTPException(404, "config.py not found")

    content = config_path.read_text(encoding="utf-8")
    import re

    changes = 0
    for key, value in overrides.items():
        if key not in _OVERRIDE_MAP:
            continue
        dict_name, field = _OVERRIDE_MAP[key]

        # Build regex to find and replace the value in the config dict
        # Matches: "field_name": value,  or  "field_name": value,  # comment
        if isinstance(value, bool):
            val_str = "True" if value else "False"
        elif isinstance(value, float):
            # Keep clean formatting
            val_str = f"{value:.6g}"
        else:
            val_str = str(value)

        # Pattern: "field": <old_value>  (possibly with trailing comma and comment)
        pattern = rf'("{field}"\s*:\s*)([^,\n#]+)(,?\s*(?:#.*)?)'
        replacement = rf'\g<1>{val_str}\3'

        new_content, n = re.subn(pattern, replacement, content, count=1)
        if n > 0:
            content = new_content
            changes += 1

    if changes > 0:
        config_path.write_text(content, encoding="utf-8")
        # Clear overrides file since they're now in config.py
        if CONFIG_OVERRIDE_PATH.exists():
            CONFIG_OVERRIDE_PATH.unlink()

    return {"saved": True, "changes": changes, "keys": list(overrides.keys())}


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
        "trades": trades[-100:],
        "available": bool(holdings) or bool(trades),
    }


# ─── Trade recording ────────────────────────────────────────────────────────

class TradeRecord(BaseModel):
    ticker: str
    action: str  # BUY or SELL
    shares: int
    price: float
    stop_price: Optional[float] = None
    r_value: Optional[float] = None
    pattern: Optional[str] = None
    strategy: str = "martin_luk"
    note: Optional[str] = None


@app.post("/api/portfolio/trade")
def record_trade(trade: TradeRecord):
    """Record a live trade and update holdings."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fee = round(trade.shares * trade.price * 0.0025, 0)

    entry = {
        "date": now,
        "ticker": trade.ticker,
        "action": trade.action.upper(),
        "shares": trade.shares,
        "price": trade.price,
        "value": round(trade.shares * trade.price, 0),
        "fee": fee,
        "strategy": trade.strategy,
    }
    if trade.stop_price is not None:
        entry["stop_price"] = trade.stop_price
    if trade.r_value is not None:
        entry["r_value"] = trade.r_value
    if trade.pattern:
        entry["pattern"] = trade.pattern
    if trade.note:
        entry["note"] = trade.note

    # Append to trade log
    log_path = OUTPUTS_DIR / "live_trade_log.json"
    trades: List = []
    if log_path.exists():
        try:
            trades = json.loads(log_path.read_text())
        except Exception:
            trades = []
    trades.append(entry)
    log_path.write_text(json.dumps(trades, indent=2))

    # Update holdings
    holdings_path = OUTPUTS_DIR / "holdings.json"
    holdings: Dict = {}
    if holdings_path.exists():
        try:
            holdings = json.loads(holdings_path.read_text())
        except Exception:
            holdings = {}

    ticker = trade.ticker
    if trade.action.upper() == "BUY":
        current = holdings.get(ticker, {"shares": 0, "avg_price": 0})
        if isinstance(current, (int, float)):
            current = {"shares": int(current), "avg_price": 0}
        old_shares = current.get("shares", 0)
        old_avg = current.get("avg_price", 0)
        new_shares = old_shares + trade.shares
        new_avg = ((old_avg * old_shares) + (trade.price * trade.shares)) / max(new_shares, 1)
        holdings[ticker] = {
            "shares": new_shares,
            "avg_price": round(new_avg, 0),
            "stop_price": trade.stop_price,
            "r_value": trade.r_value,
            "pattern": trade.pattern,
            "strategy": trade.strategy,
            "entry_date": now,
        }
    elif trade.action.upper() == "SELL":
        current = holdings.get(ticker, {"shares": 0})
        if isinstance(current, (int, float)):
            current = {"shares": int(current)}
        remaining = current.get("shares", 0) - trade.shares
        if remaining <= 0:
            holdings.pop(ticker, None)
        else:
            current["shares"] = remaining
            holdings[ticker] = current

    holdings_path.write_text(json.dumps(holdings, indent=2))

    return {"recorded": True, "trade": entry, "holdings_count": len(holdings)}


@app.delete("/api/portfolio/trade/{index}")
def delete_trade(index: int):
    """Delete a trade by index from the log."""
    log_path = OUTPUTS_DIR / "live_trade_log.json"
    if not log_path.exists():
        raise HTTPException(404, "No trade log")
    trades = json.loads(log_path.read_text())
    if index < 0 or index >= len(trades):
        raise HTTPException(404, "Trade index out of range")
    removed = trades.pop(index)
    log_path.write_text(json.dumps(trades, indent=2))
    return {"deleted": removed}


@app.delete("/api/portfolio/holding/{ticker}")
def delete_holding(ticker: str):
    """Delete a holding (position) by ticker."""
    holdings_path = OUTPUTS_DIR / "holdings.json"
    if not holdings_path.exists():
        raise HTTPException(404, "No holdings file")
    holdings = json.loads(holdings_path.read_text())
    # Try exact match first, then with .VN suffix
    key = ticker if ticker in holdings else f"{ticker}.VN" if f"{ticker}.VN" in holdings else None
    if key is None:
        raise HTTPException(404, f"Holding not found: {ticker}")
    removed = holdings.pop(key)
    holdings_path.write_text(json.dumps(holdings, indent=2))
    return {"deleted_ticker": key, "deleted": removed}


# ─── Carver Signals (live momentum + IBS signals) ────────────────────────────

_carver_lock = threading.Lock()


@app.get("/api/carver-signals")
def get_carver_signals(n_stocks: int = 30, capital: float = 500_000_000):
    """
    Compute live Carver strategy signals: momentum rankings, IBS, combined
    forecast, and recommended position sizes for the VN30 universe.
    """
    with _carver_lock, _with_overrides():
        try:
            from signals.ma_regime import get_regime
            from signals.cross_momentum import get_cross_momentum_forecasts
            from signals.ibs import get_ibs_forecast
            from signals.combined import combine_forecasts
            from sizing.position import optimal_shares, get_annual_vol, get_idm
            from config import MA_REGIME, SIZING
            from data.fetcher import fetch_multi, fetch_ohlcv

            universe = VN30_FULL[:n_stocks]
            end = datetime.today()
            start = end - timedelta(days=400)  # ~250+ trading days for MA200

            # Fetch OHLCV for all stocks
            ohlcv_dict = fetch_multi(universe, start, end, verbose=False)
            if not ohlcv_dict:
                return {"available": False, "error": "No data available."}

            # Build close matrix for cross-momentum
            close_frames = {}
            for t, df in ohlcv_dict.items():
                if not df.empty and "close" in df.columns:
                    close_frames[t] = df["close"]
            if not close_frames:
                return {"available": False, "error": "No price data."}
            close_matrix = pd.DataFrame(close_frames)

            # Get regime
            try:
                vnindex_data = fetch_ohlcv("VNINDEX", start, end)
                if vnindex_data is not None and not vnindex_data.empty:
                    regime_info = get_regime(vnindex_data["close"])
                else:
                    regime_info = {"regime": "BULL", "tau_multiplier": 1.0}
            except Exception:
                regime_info = {"regime": "BULL", "tau_multiplier": 1.0}

            regime = regime_info.get("regime", "BULL")
            tau_mult = regime_info.get("tau_multiplier", 1.0)

            # Cross-momentum forecasts (universe-wide ranking)
            cm_forecasts = get_cross_momentum_forecasts(
                close_matrix=close_matrix, regime=regime
            )

            # IBS + combined forecast per stock
            n_active = max(sum(1 for v in cm_forecasts if v > 0), 1)
            idm = get_idm(n_active)

            stock_rows = []
            for ticker in universe:
                ohlcv = ohlcv_dict.get(ticker)
                if ohlcv is None or ohlcv.empty:
                    stock_rows.append({
                        "ticker": ticker, "close": None,
                        "momentum_return": None, "momentum_rank": None,
                        "cm_forecast": 0, "ibs_forecast": 0,
                        "combined_forecast": 0, "signal": "NO_DATA",
                        "optimal_shares": 0, "position_value": 0,
                        "annual_vol": None,
                    })
                    continue

                close_price = float(ohlcv["close"].iloc[-1])
                cm_f = float(cm_forecasts.get(ticker, 0.0))
                ibs_f = get_ibs_forecast(ohlcv, regime=regime)
                combined = combine_forecasts(cm_f, ibs_f, regime)
                forecast = combined["combined_forecast"]

                # Compute momentum return for display
                lookback = 63
                skip = 5
                mom_return = None
                if len(ohlcv) >= lookback + skip + 5:
                    end_idx = -skip if skip > 0 else len(ohlcv)
                    start_idx = end_idx - lookback
                    p_end = float(ohlcv["close"].iloc[end_idx - 1])
                    p_start = float(ohlcv["close"].iloc[start_idx - 1])
                    if p_start > 0:
                        mom_return = (p_end - p_start) / p_start

                # Position sizing
                ann_vol = get_annual_vol(ohlcv["close"])
                opt_shares = optimal_shares(
                    capital=capital, forecast=forecast, price=close_price,
                    annual_vol=ann_vol, n_stocks=n_active,
                    tau_multiplier=tau_mult,
                )
                pos_value = opt_shares * close_price

                # Signal label
                if forecast > 5:
                    signal = "BUY"
                elif forecast > 0:
                    signal = "HOLD"
                elif forecast < -3:
                    signal = "REDUCE"
                else:
                    signal = "NEUTRAL"

                stock_rows.append({
                    "ticker": ticker,
                    "close": round(close_price, 0),
                    "momentum_return": round(mom_return, 4) if mom_return is not None else None,
                    "cm_forecast": round(cm_f, 1),
                    "ibs_forecast": round(ibs_f, 1),
                    "combined_forecast": round(forecast, 1),
                    "signal": signal,
                    "optimal_shares": opt_shares,
                    "position_value": round(pos_value, 0),
                    "annual_vol": round(ann_vol, 4),
                })

            # Momentum rank (1 = best)
            returns_for_rank = {
                r["ticker"]: r["momentum_return"]
                for r in stock_rows if r["momentum_return"] is not None
            }
            if returns_for_rank:
                sorted_tickers = sorted(returns_for_rank, key=returns_for_rank.get, reverse=True)
                rank_map = {t: i + 1 for i, t in enumerate(sorted_tickers)}
                for r in stock_rows:
                    r["momentum_rank"] = rank_map.get(r["ticker"])

            # Summary
            buy_count = sum(1 for r in stock_rows if r["signal"] == "BUY")
            hold_count = sum(1 for r in stock_rows if r["signal"] == "HOLD")
            reduce_count = sum(1 for r in stock_rows if r["signal"] == "REDUCE")
            neutral_count = sum(1 for r in stock_rows if r["signal"] == "NEUTRAL")
            total_exposure = sum(r["position_value"] for r in stock_rows)

            # Latest date
            latest_date = None
            for df in ohlcv_dict.values():
                if not df.empty:
                    d = df.index[-1]
                    if latest_date is None or d > latest_date:
                        latest_date = d

            return {
                "available": True,
                "scan_date": str(latest_date.date()) if latest_date else None,
                "regime": regime,
                "tau_multiplier": tau_mult,
                "stocks": stock_rows,
                "summary": {
                    "buy": buy_count,
                    "hold": hold_count,
                    "reduce": reduce_count,
                    "neutral": neutral_count,
                    "total": len(stock_rows),
                },
                "total_exposure": round(total_exposure, 0),
                "capital": capital,
                "exposure_pct": round(total_exposure / capital * 100, 1) if capital > 0 else 0,
                "n_active_positions": n_active,
                "idm": round(idm, 2),
            }

        except Exception as e:
            traceback.print_exc()
            return {"available": False, "error": str(e)}


# ─── Scanner (live signal detection) ─────────────────────────────────────────

_scanner_lock = threading.Lock()


@app.get("/api/scanner")
def get_scanner(n_stocks: int = 30, equity: float = 500_000_000):
    """
    Run the Martin Luk EMA scanner + breakout detector on recent data.
    Returns current classification, ADR, breakout signals, and position sizing.
    """
    with _scanner_lock, _with_overrides():
        try:
            from signals.ema_scanner import scan_single_stock
            from signals.breakout_detector import detect_breakouts
            from signals.market_health import compute_market_health
            from sizing.fixed_risk import compute_position_size
            from config import MARTIN_LUK

            universe = VN30_FULL[:n_stocks]
            end = datetime.today()
            start = end - timedelta(days=120)  # ~60 trading days for EMA(50) warmup

            # Fetch data (uses cache when available)
            from data.fetcher import fetch_multi
            ohlcv_dict = fetch_multi(universe, start, end, verbose=False)

            if not ohlcv_dict:
                return {"available": False, "error": "No data available. Check internet connection."}

            # Scan each stock
            ema_scans = {}
            stock_rows = []

            for ticker in universe:
                if ticker not in ohlcv_dict or ohlcv_dict[ticker].empty:
                    stock_rows.append({
                        "ticker": ticker,
                        "classification": "NO_DATA",
                        "adr": None,
                        "ema_9": None, "ema_21": None, "ema_50": None,
                        "close": None,
                        "breakout": None,
                    })
                    continue

                ohlcv = ohlcv_dict[ticker]
                scan = scan_single_stock(ohlcv)
                ema_scans[ticker] = scan

                if scan.empty:
                    continue

                last = scan.iloc[-1]
                last_ohlcv = ohlcv.iloc[-1]
                classification = str(last.get("classification", "LAGGARD"))
                adr = float(last.get("adr", 0)) if not pd.isna(last.get("adr", 0)) else 0
                ema_9 = float(last.get("ema_9", 0))
                ema_21 = float(last.get("ema_21", 0))
                ema_50 = float(last.get("ema_50", 0))
                close = float(last_ohlcv.get("close", 0))

                # Check for breakout signal on latest bar
                idx = len(ohlcv) - 1
                breakout = detect_breakouts(ohlcv, idx, scan, classification, adr, MARTIN_LUK)

                row: Dict[str, Any] = {
                    "ticker": ticker,
                    "classification": classification,
                    "adr": round(adr * 100, 2),  # as percentage
                    "ema_9": round(ema_9, 0),
                    "ema_21": round(ema_21, 0),
                    "ema_50": round(ema_50, 0),
                    "close": round(close, 0),
                    "breakout": None,
                }

                if breakout.get("triggered"):
                    entry = breakout["entry_price"]
                    stop = breakout["stop_price"]
                    r_val = breakout["r_value"]

                    # Compute recommended position size
                    sizing = compute_position_size(
                        equity=equity,
                        entry_price=entry,
                        stop_price=stop,
                        risk_pct=MARTIN_LUK["risk_per_trade_pct"],
                        lot_size=MARTIN_LUK["lot_size"],
                        max_position_pct=MARTIN_LUK["max_position_pct"],
                    )

                    row["breakout"] = {
                        "pattern": breakout["pattern"],
                        "entry_price": round(entry, 0),
                        "stop_price": round(stop, 0),
                        "r_value": round(r_val, 0),
                        "target_3r": round(entry + 3 * r_val, 0),
                        "target_5r": round(entry + 5 * r_val, 0),
                        "shares": sizing["shares"],
                        "position_value": round(sizing["position_value"], 0),
                        "risk_amount": round(sizing["risk_amount"], 0),
                    }

                stock_rows.append(row)

            # Market health
            latest_date = None
            for scan_df in ema_scans.values():
                if not scan_df.empty:
                    d = scan_df.index[-1]
                    if latest_date is None or d > latest_date:
                        latest_date = d

            health = {"health": "UNKNOWN", "leader_count": 0, "total_stocks": 0, "leader_pct": 0, "risk_multiplier": 0}
            if latest_date is not None:
                health = compute_market_health(ema_scans, latest_date, MARTIN_LUK)

            # Summary counts
            lead_count = sum(1 for s in stock_rows if s["classification"] == "LEAD")
            weakening_count = sum(1 for s in stock_rows if s["classification"] == "WEAKENING")
            laggard_count = sum(1 for s in stock_rows if s["classification"] == "LAGGARD")
            signal_count = sum(1 for s in stock_rows if s["breakout"] is not None)

            return {
                "available": True,
                "scan_date": str(latest_date.date()) if latest_date else None,
                "stocks": stock_rows,
                "market_health": health,
                "summary": {
                    "lead": lead_count,
                    "weakening": weakening_count,
                    "laggard": laggard_count,
                    "signals": signal_count,
                    "total": len(stock_rows),
                },
                "equity": equity,
            }

        except Exception as e:
            traceback.print_exc()
            return {"available": False, "error": str(e)}


# ─── Serve built frontend (production) ────────────────────────────────────────
_dist = Path("frontend/dist")
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
