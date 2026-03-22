"""
data/fetcher.py — Market Data Fetcher with Disk Cache
=======================================================
Primary: yfinance (free, no API key, .VN / .HN suffixes)
Fallback: vnstock (rate-limited, register at vnstocks.com)

Cache:
  Downloaded OHLCV is saved to data/cache/<TICKER>.csv.
  On re-run, only missing dates are fetched (incremental update).
  Cache is always extended forward — never re-downloaded from scratch.
  To force a full re-fetch: delete data/cache/ or call clear_cache().

Returns clean OHLCV DataFrames with proper datetime index.
"""

import math
import os
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

CACHE_DIR = Path("data/cache")


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_ohlcv(
    ticker: str,
    start: datetime,
    end: datetime,
    chunk_days: int = 365,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a single ticker.
    Checks disk cache first — only downloads missing date ranges.

    Returns DataFrame with columns: open, high, low, close, volume
    Index: DatetimeIndex (timezone-naive)
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
            missing_after  = end   > cache_end   + timedelta(days=2)

            if not missing_before and not missing_after:
                # Cache fully covers requested range — return slice
                return cached[
                    (cached.index >= pd.Timestamp(start)) &
                    (cached.index <= pd.Timestamp(end))
                ]

            # Only missing recent days (most common case)
            if missing_after and not missing_before:
                fresh = _fetch_with_fallback(ticker, cache_end + timedelta(days=1), end, chunk_days)
                if fresh is not None and not fresh.empty:
                    combined = pd.concat([cached, fresh])
                    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
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
            fresh = _fetch_with_fallback(ticker, start, end, chunk_days)
            if fresh is not None and not fresh.empty:
                combined = pd.concat([fresh, cached])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                _cache_save(ticker, combined)
                return combined[
                    (combined.index >= pd.Timestamp(start)) &
                    (combined.index <= pd.Timestamp(end))
                ]

    # No usable cache — full fetch
    df = _fetch_with_fallback(ticker, start, end, chunk_days)
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

        if not from_cache:
            time.sleep(0.3)  # Only throttle actual network requests

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


# ─── Fetch helpers ────────────────────────────────────────────────────────────

def _fetch_with_fallback(ticker: str, start: datetime, end: datetime, chunk_days: int) -> pd.DataFrame | None:
    """
    Fetch in annual chunks. For any chunk where yfinance returns nothing,
    immediately retry that chunk via vnstock before moving on.
    This handles tickers like VHM.VN where Yahoo has gaps in early years
    but vnstock has complete history.
    """
    start, end = _to_dt(start), _to_dt(end)

    try:
        import yfinance as yf
        yf_available = True
    except ImportError:
        yf_available = False

    all_chunks = []
    cursor = start

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        chunk_start_str = cursor.strftime("%Y-%m-%d")
        chunk_end_str   = chunk_end.strftime("%Y-%m-%d")
        got_data = False

        # Try yfinance for this chunk
        if yf_available:
            try:
                raw = yf.download(
                    ticker,
                    start=chunk_start_str,
                    end=chunk_end_str,
                    progress=False,
                    auto_adjust=True,
                    timeout=30,
                )
                if raw is not None and not raw.empty:
                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = [c[0].lower() for c in raw.columns]
                    else:
                        raw.columns = [c.lower() if isinstance(c, str) else str(c).lower()
                                       for c in raw.columns]
                    raw.index = pd.to_datetime(raw.index).tz_localize(None)
                    all_chunks.append(raw)
                    got_data = True
            except Exception:
                pass

        # yfinance returned nothing for this chunk — try vnstock immediately
        if not got_data:
            vn = _fetch_vnstock(ticker, cursor, chunk_end)
            if vn is not None and not vn.empty:
                all_chunks.append(vn)
                print(f"  [fetcher] Data for {ticker} {chunk_start_str} -> {chunk_end_str} from vnstock")
            else:
                print(f"  [fetcher] No data for {ticker} {chunk_start_str} -> {chunk_end_str} from either source")

        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.2)

    if not all_chunks:
        return None

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df

def _fetch_yfinance_chunked(ticker: str, start: datetime, end: datetime, chunk_days: int) -> pd.DataFrame | None:
    """Fetch from yfinance in annual chunks to avoid read timeouts."""
    try:
        import yfinance as yf
    except ImportError:
        print("  [fetcher] yfinance not installed. Run: pip install yfinance")
        return None

    chunks = []
    cursor = _to_dt(start)
    while cursor < _to_dt(end):
        chunk_end = min(cursor + timedelta(days=chunk_days), _to_dt(end))
        try:
            raw = yf.download(
                ticker,
                start=cursor.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
                timeout=30,
            )
            if raw is not None and not raw.empty:
                chunks.append(raw)
        except Exception as e:
            print(f"  [fetcher] yfinance chunk error for {ticker}: {e}")
        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.2)

    if not chunks:
        return None

    df = pd.concat(chunks)
    df = df[~df.index.duplicated(keep="first")]
    df.index = pd.to_datetime(df.index).tz_localize(None)

    # yfinance >=0.2.x returns MultiIndex columns like ("Close", "VCB.VN")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() if isinstance(c, str) else str(c).lower()
                      for c in df.columns]
    return df


def _fetch_vnstock(ticker: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """
    Fallback to vnstock v3 (pip install vnstock>=3.0).
    Uses KBS source via Quote.history() — works for stocks AND indices (VNINDEX, VN30).

    vnstock v3 API changed completely from v0.x:
      OLD (broken): from vnstock import stock_historical_data
      NEW (correct): from vnstock.explorer.kbs.quote import Quote
    """
    # Strip exchange suffix: VCB.VN → VCB, VNINDEX stays VNINDEX
    symbol = ticker.replace(".VN", "").replace(".HN", "").upper()

    try:
        from vnstock.explorer.kbs.quote import Quote
    except ImportError:
        try:
            # Older v3 path
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

        # v3 returns columns: time, open, high, low, close, volume
        raw.columns = [c.lower() for c in raw.columns]

        # Set index to the date column (named "time" in v3)
        if "time" in raw.columns:
            raw = raw.set_index("time")
        elif "date" in raw.columns:
            raw = raw.set_index("date")

        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        return raw

    except Exception as e:
        print(f"  [fetcher] vnstock error for {symbol}: {e}")
        return None


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
    df = df.sort_index()

    # ── Detect corrupted prices (spikes >50% day-to-day) ──────────────────
    # VN stocks have ±7% daily limit (HOSE), so any >50% jump is data corruption
    # from yfinance auto_adjust miscalculating corporate actions.
    if len(df) > 1:
        pct_change = df["close"].pct_change().abs()
        spike_mask = pct_change > 0.50  # 50% daily change = impossible on HOSE
        spike_mask.iloc[0] = False      # first row has NaN pct_change
        n_spikes = spike_mask.sum()
        if n_spikes > 0:
            # Remove the corrupted rows (and everything after if it's a level shift)
            first_spike_idx = spike_mask.idxmax()
            # Check if it's a level shift (prices stay high) vs isolated spike
            post_spike = df.loc[first_spike_idx:, "close"]
            pre_spike = df.loc[:first_spike_idx, "close"].iloc[:-1]
            if len(pre_spike) > 0 and len(post_spike) > 1:
                pre_median = pre_spike.tail(20).median()
                post_median = post_spike.head(5).median()
                if post_median > pre_median * 2:
                    # Level shift — all data from spike onward is corrupted
                    df = df.loc[:first_spike_idx].iloc[:-1]
                    print(f"  [clean] Removed {n_spikes} corrupted rows from {first_spike_idx} onward (price level shift)")
                else:
                    # Isolated spikes — just remove those rows
                    df = df[~spike_mask]
                    print(f"  [clean] Removed {n_spikes} price spike rows")

    df = df.ffill()
    df = df.dropna()
    return df


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
    Fetch VNIndex with a graceful three-level fallback chain.

    Level 1: primary_ticker  (e.g. "VNINDEX")
    Level 2: fallback_tickers (e.g. ["E1VFVN30.VN", "VN30F1M.VN"])
    Level 3: universe mean   (portfolio average — good enough for MA-regime detection)

    ^VNINDEX was removed from Yahoo Finance ~2025. Use this function instead of
    fetch_ohlcv(VNINDEX_TICKER, ...) everywhere index prices are needed.
    """
    for ticker in [primary_ticker] + (fallback_tickers or []):
        df = fetch_ohlcv(ticker, start, end, use_cache=use_cache)
        if not df.empty:
            close = df["close"]
            # Scale sanity check: VNIndex has always been > 100 points.
            # Some data sources (vnstock, yfinance auto_adjust) return values
            # divided by 1000 (e.g., 1.16 instead of 1160).
            median_val = float(close.median())
            if median_val < 100:
                scale = 1000.0
                close = close * scale
                print(f"  [index] Rescaled {ticker} by {scale}x (median was {median_val:.2f}, now {median_val*scale:.0f})")
                # Re-save corrected data to cache
                df_corrected = df.copy()
                for col in ["open", "high", "low", "close"]:
                    if col in df_corrected.columns:
                        df_corrected[col] = df_corrected[col] * scale
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
