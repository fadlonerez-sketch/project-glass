"""Market quotes from Yahoo Finance's chart endpoint (no account, no key).

IMPORTANT - read before relying on this module:

* The endpoints used here (``query1.finance.yahoo.com/v8/finance/chart`` and ``/v1/finance/search``) are
  UNOFFICIAL. Yahoo publishes no documentation and no terms for programmatic use of them; they can change,
  rate-limit or disappear without notice. Requests are kept small (one chart call per symbol, at most four
  in parallel, refreshed no faster than the caller's interval) and identify themselves with a User-Agent.
* Quotes can be DELAYED (often ~15 minutes for some exchanges, and longer when the service lags) and the
  service gives no reliable "real-time" flag.
* Therefore nothing here ever claims data is live on the provider's word. :func:`classify` decides
  freshness from timestamps alone: a quote is "live" only when its market is in its regular session AND the
  quote's own market timestamp is recent AND the last successful fetch is recent. Anything older is shown as
  "Delayed", "Closed · as of ..." or "Not updated since ...". Quotes restored from the disk cache are always
  reported stale until a fresh fetch succeeds.

Only ticker symbols (and search text typed by the user) are sent. Successful quotes are cached on disk so the
UI can show the last known values offline (clearly marked stale).
"""
from __future__ import annotations

import json
import math
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Callable

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m&includePrePost=false"
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProjectGlass/1.0"
TIMEOUT_SECONDS = 8.0
MAX_WORKERS = 4
SPARK_POINTS = 80
SEARCH_MAX_CHARS = 40
CACHE_VERSION = 1

DEFAULT_INDICES = ["^GSPC", "^IXIC", "^DJI"]
DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA"]
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow", "^RUT": "Russell 2000",
               "^FTSE": "FTSE 100", "^N225": "Nikkei", "^TA125.TA": "TA-125"}

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,15}$")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_NETWORK_WORDS = ("internet", "network", "offline", "connection", "timed out", "timeout", "unreachable")


class MarketError(Exception):
    """User-presentable market-data failure. ``status`` carries the HTTP status (404 = unknown symbol)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    price: float | None
    previous_close: float | None
    change: float | None
    change_pct: float | None
    currency: str
    instrument: str
    exchange: str
    market_time: float | None
    session_start: float | None
    session_end: float | None
    pre_start: float | None
    post_end: float | None
    day_high: float | None
    day_low: float | None
    spark: tuple[float, ...]
    fetched_at: float
    from_cache: bool = False  # restored from disk at startup -> classify() always reports it stale

    def to_dict(self) -> dict:
        d = asdict(self)
        d["spark"] = list(self.spark)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Quote":
        names = {f.name for f in fields(Quote)}
        data = {k: v for k, v in d.items() if k in names}
        data["spark"] = tuple(float(x) for x in data.get("spark") or ())
        q = Quote(**data)
        if not isinstance(q.symbol, str) or not isinstance(q.fetched_at, (int, float)):
            raise TypeError("bad cached quote")
        return q


@dataclass(frozen=True)
class Freshness:
    status: str          # "live" | "delayed" | "closed" | "stale" | "error"
    age_s: float | None  # age of the market data (stale: time since the last successful fetch)
    label: str
    is_live: bool


# ---------------------------------------------------------------------------------------------- helpers
def normalize_symbol(s: str) -> str:
    sym = (s or "").strip().upper() if isinstance(s, str) else ""
    if not _SYMBOL_RE.match(sym):
        raise MarketError(f"Invalid symbol {s!r}" if s else "Enter a symbol")
    return sym


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _downsample(values: list[float], n: int = SPARK_POINTS) -> tuple[float, ...]:
    if len(values) <= n:
        return tuple(values)
    step = (len(values) - 1) / (n - 1)
    return tuple(values[round(i * step)] for i in range(n))


def _period(tp: dict, key: str, edge: str) -> float | None:
    p = tp.get(key) if isinstance(tp, dict) else None
    return _num(p.get(edge)) if isinstance(p, dict) else None


def parse_chart(payload: dict, fetched_at: float) -> Quote:
    """Turn a v8 chart response into a :class:`Quote`. Raises MarketError for error payloads."""
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise MarketError("Market data service returned an invalid response")
    err = chart.get("error")
    results = chart.get("result")
    if err or not results:
        if isinstance(err, dict) and str(err.get("code", "")).lower().replace(" ", "") == "notfound":
            raise MarketError("Unknown symbol", status=404)
        desc = err.get("description") if isinstance(err, dict) else None
        raise MarketError(f"Market data error: {desc}" if desc else "Market data service returned no data")
    res = results[0] if isinstance(results, list) else None
    meta = res.get("meta") if isinstance(res, dict) else None
    if not isinstance(meta, dict):
        raise MarketError("Market data service returned no data")
    price = _num(meta.get("regularMarketPrice"))
    if price is None:
        raise MarketError("Market data service returned no price")
    symbol = str(meta.get("symbol") or "")
    prev = _num(meta.get("chartPreviousClose"))
    if prev is None:
        prev = _num(meta.get("previousClose"))
    change = price - prev if prev is not None else None
    change_pct = change / prev * 100.0 if change is not None and prev else None

    indicators = res.get("indicators") if isinstance(res.get("indicators"), dict) else {}
    quote_list = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
    closes = quote_list[0].get("close") if quote_list and isinstance(quote_list[0], dict) else None
    closes = closes if isinstance(closes, list) else []
    # includePrePost=false -> every point is a regular-session close; just drop nulls/NaNs.
    spark = _downsample([c for c in (_num(x) for x in closes) if c is not None])

    tp = meta.get("currentTradingPeriod") or {}
    name = INDEX_NAMES.get(symbol) or meta.get("shortName") or meta.get("longName") or symbol
    return Quote(
        symbol=symbol, name=str(name), price=price, previous_close=prev, change=change, change_pct=change_pct,
        currency=str(meta.get("currency") or ""), instrument=str(meta.get("instrumentType") or ""),
        exchange=str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        market_time=_num(meta.get("regularMarketTime")),
        session_start=_period(tp, "regular", "start"), session_end=_period(tp, "regular", "end"),
        pre_start=_period(tp, "pre", "start"), post_end=_period(tp, "post", "end"),
        day_high=_num(meta.get("regularMarketDayHigh")), day_low=_num(meta.get("regularMarketDayLow")),
        spark=spark, fetched_at=float(fetched_at),
    )


def session_state(q: Quote, now: float) -> str:
    """Return "pre" | "open" | "post" | "closed" from the quote's trading-period epochs. Crypto is 24/7."""
    if q.instrument.upper() == "CRYPTOCURRENCY":
        return "open"
    s, e = q.session_start, q.session_end
    if s is None or e is None:
        return "closed"
    if s <= now < e:
        return "open"
    if q.pre_start is not None and q.pre_start <= now < s:
        return "pre"
    if q.post_end is not None and e <= now < q.post_end:
        return "post"
    return "closed"


def format_local(ts: float, now: float, tz: tzinfo | None = None) -> str:
    """HH:MM if ``ts`` is on the same local day as ``now``; "Thu 10:42" within a week; "29 Oct 10:42" older.

    ``tz`` None means the machine's local timezone; tests pass a fixed tzinfo. Names are English and do not
    depend on the process locale.
    """
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
    today = (datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now)).date()
    hm = f"{dt.hour:02d}:{dt.minute:02d}"
    if dt.date() == today:
        return hm
    if abs((today - dt.date()).days) < 7:
        return f"{_WEEKDAYS[dt.weekday()]} {hm}"
    return f"{dt.day} {_MONTHS[dt.month - 1]} {hm}"


def _is_network_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(w in m for w in _NETWORK_WORDS)


def classify(q: Quote | None, now: float, refresh_s: float, last_error: str = "",
             last_success: float | None = None, tz: tzinfo | None = None) -> Freshness:
    """Decide how a quote may be presented. Overriding rule: old or delayed data is NEVER reported live."""
    if q is None:
        return Freshness("error", None, "Offline" if _is_network_error(last_error) else "Unavailable", False)

    # Use the OLDER of the caller's last-success time and the quote's own fetch time (conservative).
    ref = q.fetched_at if last_success is None else min(float(last_success), q.fetched_at)
    if q.from_cache or now - ref > 2 * refresh_s + 60:
        return Freshness("stale", max(0.0, now - ref), f"Not updated since {format_local(ref, now, tz)}", False)

    state = session_state(q, now)
    age = max(0.0, now - q.market_time) if q.market_time is not None else None
    if state == "open":
        if age is not None and age <= max(refresh_s, 120) + 90:
            return Freshness("live", age, "Live", True)
        if age is None:
            return Freshness("delayed", None, "Delayed", False)
        minutes = max(1, round(age / 60))
        text = f"{minutes} min" if minutes < 120 else f"{round(age / 3600)} h"
        return Freshness("delayed", age, f"Delayed · {text}", False)

    prefix = {"pre": "Pre-market", "post": "After hours"}.get(state, "Closed")
    if q.market_time is None:
        return Freshness("closed", None, prefix, False)
    return Freshness("closed", age, f"{prefix} · as of {format_local(q.market_time, now, tz)}", False)


def next_refresh_delay(quotes: list[Quote], now: float, refresh_s: float, consecutive_errors: int = 0) -> float:
    """Seconds until the next poll: fast while a market is open, slow otherwise, backoff after errors."""
    if consecutive_errors > 0:
        return float(max(30.0, min(refresh_s, 30.0 * 2 ** min(consecutive_errors - 1, 20))))
    if not quotes:
        return float(refresh_s)
    states = [session_state(q, now) for q in quotes]
    if "open" in states:
        return float(refresh_s)
    if "pre" in states or "post" in states:
        return float(max(refresh_s, 600))
    starts = [t for q in quotes for t in (q.pre_start, q.session_start) if t is not None and t > now]
    if not starts:
        # Yahoo usually still reports the finished session after the close; poll gently until it rolls over.
        return 1800.0
    return float(min(max(min(starts) - now + 30, 600.0), 3 * 3600.0))


# ---------------------------------------------------------------------------------------------- network
def _friendly(exc: BaseException) -> MarketError:
    if isinstance(exc, MarketError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return MarketError("Not found (HTTP 404)", status=404)
        if exc.code == 429:
            return MarketError("Market data service is limiting requests (HTTP 429)", status=429)
        return MarketError(f"Market data service unavailable (HTTP {exc.code})", status=exc.code)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return MarketError("Market data request timed out")
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return MarketError("Market data request timed out")
        return MarketError("No internet connection")
    if isinstance(exc, (ValueError, UnicodeDecodeError)):
        return MarketError("Market data service returned an invalid response")
    if isinstance(exc, OSError):
        return MarketError("No internet connection")
    return MarketError(f"Market data request failed: {exc}")


def _http_get(url: str, timeout: float = TIMEOUT_SECONDS) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
            return resp.read()
    except Exception as exc:
        raise _friendly(exc) from exc


class YahooFinance:
    def __init__(self, cache_path: Path | None = None, fetch: Callable[[str], bytes] | None = None,
                 clock: Callable[[], float] = time.time):
        self.cache_path = cache_path
        self._fetch = fetch or _http_get
        self._clock = clock
        self._lock = threading.Lock()

    def _get_json(self, url: str) -> dict:
        try:
            raw = self._fetch(url)
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, (bytes, bytearray)):
                raw = bytes(raw).decode("utf-8")
            data = json.loads(raw)
        except Exception as exc:
            raise _friendly(exc) from exc
        if not isinstance(data, dict):
            raise MarketError("Market data service returned an invalid response")
        return data

    def _one(self, symbol: str) -> Quote:
        url = CHART_URL.format(symbol=urllib.parse.quote(symbol, safe=""))
        try:
            q = parse_chart(self._get_json(url), self._clock())
        except MarketError as exc:
            if exc.status == 404:
                raise MarketError(f"Unknown symbol {symbol}", status=404) from exc
            raise
        if q.symbol != symbol:  # key everything by the symbol we asked for
            name = INDEX_NAMES.get(symbol) or (q.name if q.name and q.name != q.symbol else symbol)
            q = replace(q, symbol=symbol, name=name)
        return q

    def quotes(self, symbols: list[str]) -> tuple[dict[str, Quote], dict[str, str]]:
        """Fetch fresh quotes in parallel. Returns (quotes by symbol, user-facing errors by symbol)."""
        out: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        wanted: list[str] = []
        for s in symbols:
            try:
                sym = normalize_symbol(s)
            except MarketError as exc:
                errors[str(s)] = str(exc)
                continue
            if sym not in wanted:
                wanted.append(sym)
        if wanted:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(wanted))) as pool:
                futures = {sym: pool.submit(self._one, sym) for sym in wanted}
                for sym, fut in futures.items():
                    try:
                        out[sym] = fut.result()
                    except Exception as exc:
                        errors[sym] = str(_friendly(exc))
        if out:
            self._store(out)
        return out, errors

    def search(self, text: str) -> list[dict]:
        q = (text or "").strip()[:SEARCH_MAX_CHARS].strip()
        if not q:
            return []
        url = SEARCH_URL + "?" + urllib.parse.urlencode({"q": q, "quotesCount": 8, "newsCount": 0})
        try:
            data = self._get_json(url)
        except MarketError as exc:
            if exc.status == 404:
                raise MarketError("Symbol search unavailable (HTTP 404)", status=404) from exc
            raise
        out: list[dict] = []
        for item in data.get("quotes") or []:
            if not isinstance(item, dict):
                continue
            try:
                sym = normalize_symbol(str(item.get("symbol") or ""))
            except MarketError:
                continue  # e.g. odd suffixes we could not request anyway
            out.append({"symbol": sym,
                        "name": str(item.get("shortname") or item.get("longname") or sym),
                        "exchange": str(item.get("exchDisp") or item.get("exchange") or ""),
                        "type": str(item.get("quoteType") or item.get("typeDisp") or "")})
        return out

    # ------------------------------------------------------------------ cache
    def _read_cache(self) -> dict:
        if not self.cache_path or not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            quotes = data.get("quotes") if isinstance(data, dict) else None
            return quotes if isinstance(quotes, dict) else {}
        except (OSError, ValueError):
            return {}

    def cached(self, symbols: list[str]) -> dict[str, Quote]:
        """Last good quotes from disk, flagged ``from_cache`` so classify() reports them stale."""
        stored = self._read_cache()
        out: dict[str, Quote] = {}
        for s in symbols:
            try:
                sym = normalize_symbol(s)
                q = Quote.from_dict(stored[sym])
            except (MarketError, KeyError, TypeError, ValueError, AttributeError):
                continue
            out[sym] = replace(q, symbol=sym, from_cache=True)
        return out

    def _store(self, quotes: dict[str, Quote]) -> None:
        if not self.cache_path:
            return
        with self._lock:
            try:
                merged = self._read_cache()
                for sym, q in quotes.items():
                    merged[sym] = replace(q, from_cache=False).to_dict()
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"version": CACHE_VERSION, "quotes": merged}), encoding="utf-8")
                tmp.replace(self.cache_path)
            except OSError:
                pass
