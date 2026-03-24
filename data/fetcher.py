"""
data/fetcher.py — Market Data Fetcher with Disk Cache
=======================================================
Primary: VPS TradingView API (free, no auth, no rate limit)
Fallback: vnstock v3 KBS (rate-limited 20 req/min for guest)

Cache:
  Downloaded OHLCV is saved to data/cache/<TICKER>.csv.
  On re-run, only missing dates are fetched (incremental update).
  To force a full re-fetch: delete data/cache/ or call clear_cache().

Returns clean OHLCV DataFrames with proper datetime index.
All prices are in VND (e.g., VCB = 59,000 VND, not 59.0).
"""

import math
import os
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

warnings.filterwarnings("ignore")

CACHE_DIR = Path("data/cache")

# VPS TradingView API — no auth, no rate limit
_VPS_URL = "https://histdatafeed.vps.com.vn/tradingview/history"
_VPS_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# vnstock rate limit tracking (guest: 20 req/min) — fallback only
_vnstock_calls: list = []
_VNSTOCK_MAX_PER_MIN = 18


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_ohlcv(
    ticker: str,
    start: datetime,
    end: datetime,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a single ticker.
    Checks disk cache first — only downloads missing date ranges.

    Returns DataFrame with columns: open, high, low, close, volume
    Index: DatetimeIndex (timezone-naive), prices in VND.
    Returns empty DataFrame on failure.
    """
    start = _to_dt(start)
    end   = _to_dt(end)

    if use_cache:
        cached = _cache_load(ticker)
        if cached is not None and not cached.empty:
            cache_end = cached.index.max()
            cache_start = cached.index.min()

            missing_before = start < cache_start - timedelta(days=5)
            # Allow up to 5 days tolerance for weekends + holidays
            missing_after  = end   > cache_end   + timedelta(days=5)

            if not missing_before and not missing_after:
                return cached[
                    (cached.index >= pd.Timestamp(start)) &
                    (cached.index <= pd.Timestamp(end))
                ]

            # Only missing recent days (most common case)
            if missing_after and not missing_before:
                fresh = _fetch_data(ticker, cache_end + timedelta(days=1), end)
                if fresh is not None and not fresh.empty:
                    combined = pd.concat([cached, fresh])
                    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                    combined = _clean_ohlcv(combined)
                    _cache_save(ticker, combined)
                    return combined[
                        (combined.index >= pd.Timestamp(start)) &
                        (combined.index <= pd.Timestamp(end))
                    ]
                return cached[
                    (cached.index >= pd.Timestamp(start)) &
                    (cached.index <= pd.Timestamp(end))
                ]

            # Missing earlier data — fetch full range and merge
            fresh = _fetch_data(ticker, start, end)
            if fresh is not None and not fresh.empty:
                combined = pd.concat([fresh, cached])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                combined = _clean_ohlcv(combined)
                _cache_save(ticker, combined)
                return combined[
                    (combined.index >= pd.Timestamp(start)) &
                    (combined.index <= pd.Timestamp(end))
                ]

    # No usable cache — full fetch
    df = _fetch_data(ticker, start, end)
    if df is None or df.empty:
        return pd.DataFrame()

    df = _clean_ohlcv(df)
    if use_cache and not df.empty:
        _cache_save(ticker, df)
    return df


def fetch_multi(
    tickers: list,
    start: datetime,
    end: datetime,
    verbose: bool = True,
    use_cache: bool = True,
) -> dict:
    """Fetch OHLCV for multiple tickers. Returns {ticker: DataFrame}."""
    results = {}
    for i, ticker in enumerate(tickers):
        cached = _cache_load(ticker) if use_cache else None
        from_cache = _cache_covers(cached, start, end)

        if verbose:
            tag = "[cache]" if from_cache else "[fetch]"
            print(f"  {tag}  {ticker} ({i+1}/{len(tickers)})")

        df = fetch_ohlcv(ticker, start, end, use_cache=use_cache)
        if not df.empty:
            results[ticker] = df

    return results


def fetch_close_matrix(
    tickers: list,
    start: datetime,
    end: datetime,
    verbose: bool = True,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch multiple tickers, return aligned close price matrix."""
    data = fetch_multi(tickers, start, end, verbose=verbose, use_cache=use_cache)
    if not data:
        return pd.DataFrame()
    close_dict = {ticker: df["close"] for ticker, df in data.items()}
    matrix = pd.DataFrame(close_dict)
    matrix = matrix.ffill().dropna(how="all")
    return matrix


def clear_cache(ticker: str = None):
    """Delete cache. Pass ticker string to clear one stock, None to clear all."""
    if ticker:
        p = _cache_path(ticker)
        if p.exists():
            p.unlink()
            print(f"  [cache] Cleared {ticker}")
        else:
            print(f"  [cache] No cache found for {ticker}")
    else:
        if CACHE_DIR.exists():
            files = list(CACHE_DIR.glob("*.csv"))
            for f in files:
                f.unlink()
            print(f"  [cache] Cleared {len(files)} cached tickers")


def cache_status() -> pd.DataFrame:
    """Return a summary of what's currently cached."""
    if not CACHE_DIR.exists():
        return pd.DataFrame()
    rows = []
    for p in sorted(CACHE_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            rows.append({
                "ticker": p.stem.replace("_", "."),
                "rows": len(df),
                "from": str(df.index.min().date()),
                "to":   str(df.index.max().date()),
                "size_kb": round(p.stat().st_size / 1024, 1),
            })
        except Exception:
            pass
    return pd.DataFrame(rows)


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> Path:
    safe = ticker.replace(".", "_").replace("^", "IDX_")
    return CACHE_DIR / f"{safe}.csv"


def _cache_load(ticker: str) -> pd.DataFrame | None:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df if not df.empty else None
    except Exception:
        return None


def _cache_save(ticker: str, df: pd.DataFrame):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df_clean = _clean_ohlcv(df.copy())
    if not df_clean.empty:
        _cache_path(ticker).write_text("")  # truncate first
        df_clean.to_csv(_cache_path(ticker))


def _cache_covers(cached: pd.DataFrame | None, start: datetime, end: datetime) -> bool:
    if cached is None or cached.empty:
        return False
    s, e = _to_dt(start), _to_dt(end)
    return (cached.index.min() <= pd.Timestamp(s) + timedelta(days=5) and
            cached.index.max() >= pd.Timestamp(e) - timedelta(days=2))


# ─── Fetch: VPS TradingView API (primary) ────────────────────────────────────

def _fetch_data(ticker: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """Fetch data: try VPS first, fall back to vnstock if VPS fails."""
    start, end = _to_dt(start), _to_dt(end)

    # Skip very short gaps (<=5 days) — likely weekend/holiday
    if (end - start).days <= 5:
        return None

    symbol = _to_symbol(ticker)

    # Try VPS TradingView API (no rate limit)
    df = _fetch_vps(symbol, start, end)
    if df is not None and not df.empty:
        return df

    # Fallback to vnstock (rate-limited)
    print(f"  [fetcher] VPS failed for {symbol}, trying vnstock...")
    df = _fetch_vnstock(ticker, start, end)
    return df


def _fetch_vps(symbol: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """
    Fetch from VPS TradingView API.
    No auth required, no rate limit, supports stocks + indices.
    Returns prices in thousands VND (rescaled to VND before return).
    """
    ts_from = int(start.replace(tzinfo=timezone.utc).timestamp())
    ts_to   = int(end.replace(tzinfo=timezone.utc).timestamp())

    try:
        resp = requests.get(
            _VPS_URL,
            params={
                "symbol": symbol,
                "resolution": "D",
                "from": str(ts_from),
                "to": str(ts_to),
            },
            headers=_VPS_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        if data.get("s") == "no_data" or "t" not in data or not data["t"]:
            return None

        df = pd.DataFrame({
            "open":   data["o"],
            "high":   data["h"],
            "low":    data["l"],
            "close":  data["c"],
            "volume": data["v"],
        })
        df.index = pd.to_datetime(
            [datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None) for t in data["t"]]
        )
        df.index.name = "date"

        # VPS returns prices in thousands VND (e.g., 59.0 = 59,000 VND).
        # Rescale to actual VND to match capital units.
        _rescale_thousands_vnd(df, symbol)

        return df

    except Exception as e:
        print(f"  [fetcher] VPS error for {symbol}: {e}")
        return None


# ─── Fetch: vnstock (fallback) ───────────────────────────────────────────────

def _vnstock_rate_check() -> bool:
    """Check if we can make a vnstock call without hitting rate limit. Waits if needed."""
    now = time.time()
    _vnstock_calls[:] = [t for t in _vnstock_calls if now - t < 60]
    if len(_vnstock_calls) >= _VNSTOCK_MAX_PER_MIN:
        wait = 60 - (now - _vnstock_calls[0]) + 1
        if wait > 0:
            print(f"  [fetcher] vnstock rate limit: waiting {wait:.0f}s...")
            time.sleep(wait)
            _vnstock_calls.clear()
    _vnstock_calls.append(time.time())
    return True


def _fetch_vnstock(ticker: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """
    Fallback to vnstock v3 (pip install vnstock>=3.0).
    Uses KBS source via Quote.history().
    """
    _vnstock_rate_check()

    symbol = _to_symbol(ticker)

    try:
        from vnstock.explorer.kbs.quote import Quote
    except ImportError:
        try:
            from vnstock import Vnstock
            q = Vnstock().stock(symbol=symbol, source="KBS").quote
        except ImportError:
            print("  [fetcher] vnstock not installed. Run: pip install vnstock")
            return None
        except Exception as e:
            print(f"  [fetcher] vnstock init error for {symbol}: {e}")
            return None
    else:
        try:
            q = Quote(symbol)
        except Exception as e:
            print(f"  [fetcher] vnstock Quote init error for {symbol}: {e}")
            return None

    try:
        raw = q.history(
            start=_to_dt(start).strftime("%Y-%m-%d"),
            end=_to_dt(end).strftime("%Y-%m-%d"),
            interval="1D",
            to_df=True,
            show_log=False,
        )
        if raw is None or raw.empty:
            return None

        raw.columns = [c.lower() for c in raw.columns]

        if "time" in raw.columns:
            raw = raw.set_index("time")
        elif "date" in raw.columns:
            raw = raw.set_index("date")

        raw.index = pd.to_datetime(raw.index).tz_localize(None)

        # vnstock also returns prices in thousands VND — rescale to VND
        _rescale_thousands_vnd(raw, symbol)

        return raw

    except Exception as e:
        print(f"  [fetcher] vnstock error for {symbol}: {e}")
        return None


# ─── Data cleaning ───────────────────────────────────────────────────────────

def _rescale_thousands_vnd(df: pd.DataFrame, symbol: str):
    """
    Both VPS and vnstock return prices in thousands VND (e.g., 15.30 = 15,300 VND).
    Detect and rescale to actual VND so prices match capital units.
    """
    if "close" not in df.columns or df.empty:
        return
    median_close = float(df["close"].median())
    if 0 < median_close < 500:
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] * 1000
        print(f"  [fetcher] {symbol}: rescaled x1000 ({median_close:.1f} -> {median_close*1000:.0f} VND)")


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise column names, remove bad rows, detect price spikes, forward-fill gaps."""
    col_map = {
        "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume",
        "adj close": "close",
    }
    df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    required = ["open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame()

    df = df[required + (["volume"] if "volume" in df.columns else [])].copy()
    df = df[(df["close"] > 0) & (df["high"] >= df["low"])]

    # Normalize timestamps to midnight — different data sources return different
    # timezone offsets (e.g. 00:00 vs 07:00 for the same trading day).
    # Without this, close_matrix alignment fails silently.
    df.index = df.index.normalize()
    df = df[~df.index.duplicated(keep="last")]

    df = df.sort_index()

    # ── Detect corrupted prices (spikes >15% day-to-day) ──────────────────
    # VN stocks have ±7% daily limit (HOSE). A >15% change indicates
    # corrupted data or unadjusted corporate actions.
    if len(df) > 1:
        pct_change = df["close"].pct_change().abs()
        spike_mask = pct_change > 0.15
        spike_mask.iloc[0] = False
        n_spikes = spike_mask.sum()
        if n_spikes > 0:
            spike_dates = df.index[spike_mask].tolist()
            print(f"  [clean] detected {n_spikes} price spike(s) >15% at {[str(d.date()) for d in spike_dates[:5]]}")

            first_spike_idx = spike_mask.idxmax()
            post_spike = df.loc[first_spike_idx:, "close"]
            pre_spike = df.loc[:first_spike_idx, "close"].iloc[:-1]
            if len(pre_spike) > 0 and len(post_spike) > 1:
                pre_median = pre_spike.tail(20).median()
                post_median = post_spike.head(5).median()
                if post_median > pre_median * 2:
                    df = df.loc[:first_spike_idx].iloc[:-1]
                    print(f"  [clean] Removed {n_spikes} corrupted rows from {first_spike_idx} onward (price level shift)")
                else:
                    df = df[~spike_mask]
                    print(f"  [clean] Removed {n_spikes} price spike rows")

    df = df.ffill()
    df = df.dropna()
    return df


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _to_symbol(ticker: str) -> str:
    """Convert ticker to exchange symbol: VCB.VN → VCB, VNINDEX stays VNINDEX."""
    return ticker.replace(".VN", "").replace(".HN", "").upper()


def _to_dt(d) -> datetime:
    """Ensure we have a plain datetime object."""
    if isinstance(d, datetime):
        return d
    return pd.Timestamp(d).to_pydatetime().replace(tzinfo=None)


def fetch_index_prices(
    primary_ticker: str,
    fallback_tickers: list,
    start: datetime,
    end: datetime,
    universe_close_matrix=None,
    use_cache: bool = True,
) -> "pd.Series":
    """
    Fetch VNIndex with a graceful fallback chain.

    Level 1: primary_ticker  (e.g. "VNINDEX")
    Level 2: fallback_tickers (e.g. ["E1VFVN30.VN", "VN30F1M.VN"])
    Level 3: universe mean   (portfolio average — good enough for MA-regime detection)
    """
    for ticker in [primary_ticker] + (fallback_tickers or []):
        df = fetch_ohlcv(ticker, start, end, use_cache=use_cache)
        if not df.empty:
            close = df["close"]
            median_val = float(close.median())
            # VNIndex should be > 100 points. If still scaled wrong, fix it.
            if median_val < 100:
                close = close * 1000
                print(f"  [index] Rescaled {ticker} by 1000x (median was {median_val:.2f})")
                df_corrected = df.copy()
                for col in ["open", "high", "low", "close"]:
                    if col in df_corrected.columns:
                        df_corrected[col] = df_corrected[col] * 1000
                _cache_save(ticker, df_corrected)
            print(f"  [index] Using {ticker} as market index proxy")
            return close

    # Final fallback: equal-weight mean of the portfolio universe
    if universe_close_matrix is not None and not universe_close_matrix.empty:
        print("  [index] WARNING: All index tickers failed -- using universe mean as regime proxy")
        proxy = universe_close_matrix.mean(axis=1)
        proxy.name = "vnindex_proxy"
        return proxy

    print("  [index] ERROR: No index data available at all")
    return pd.Series(dtype=float)
