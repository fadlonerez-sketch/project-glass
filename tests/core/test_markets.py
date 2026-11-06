import json
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from glass.core import markets
from glass.core.markets import (DEFAULT_INDICES, DEFAULT_WATCHLIST, INDEX_NAMES, Freshness, MarketError, Quote,
                                YahooFinance, classify, format_local, next_refresh_delay, normalize_symbol,
                                parse_chart, session_state)

# Fixed "exchange-local" zone (US Eastern standard time) so labels never depend on the machine timezone.
TZ = timezone(timedelta(hours=-5))
DAY = datetime(2026, 11, 5, tzinfo=TZ)  # Thursday


def at(h, m=0, day=0):
    return (DAY + timedelta(days=day, hours=h, minutes=m)).timestamp()


PRE_START, OPEN, CLOSE, POST_END = at(4), at(9, 30), at(16), at(20)


def chart(symbol="AAPL", price=270.5, prev=274.0, closes=None, instrument="EQUITY", market_time=None,
          day=0, drop=(), **meta_extra):
    meta = {
        "symbol": symbol, "shortName": "Apple Inc.", "longName": "Apple Inc.", "currency": "USD",
        "exchangeName": "NMS", "fullExchangeName": "NasdaqGS", "instrumentType": instrument,
        "regularMarketPrice": price, "chartPreviousClose": prev, "previousClose": prev + 1 if prev else None,
        "regularMarketTime": market_time if market_time is not None else at(11, day=day),
        "regularMarketDayHigh": 275.25, "regularMarketDayLow": 268.0,
        "exchangeTimezoneName": "America/New_York", "gmtoffset": -18000,
        "currentTradingPeriod": {
            "pre": {"start": at(4, day=day), "end": at(9, 30, day=day), "timezone": "EST", "gmtoffset": -18000},
            "regular": {"start": at(9, 30, day=day), "end": at(16, day=day), "timezone": "EST", "gmtoffset": -18000},
            "post": {"start": at(16, day=day), "end": at(20, day=day), "timezone": "EST", "gmtoffset": -18000},
        },
    }
    meta.update(meta_extra)
    for k in drop:
        meta.pop(k, None)
    if closes is None:
        closes = [270.0, None, 271.0, 270.5]
    stamps = [int(at(9, 30, day=day)) + 300 * i for i in range(len(closes))]
    return {"chart": {"result": [{"meta": meta, "timestamp": stamps,
                                  "indicators": {"quote": [{"close": closes, "open": closes}]}}],
                      "error": None}}


NOT_FOUND = {"chart": {"result": None,
                       "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"}}}


def make_quote(**kw):
    base = dict(symbol="AAPL", name="Apple Inc.", price=100.0, previous_close=99.0, change=1.0, change_pct=1.0101,
                currency="USD", instrument="EQUITY", exchange="NasdaqGS", market_time=at(11),
                session_start=OPEN, session_end=CLOSE, pre_start=PRE_START, post_end=POST_END,
                day_high=101.0, day_low=98.0, spark=(99.0, 100.0), fetched_at=at(11))
    base.update(kw)
    return Quote(**base)


def as_bytes(payload):
    return json.dumps(payload).encode("utf-8")


# ------------------------------------------------------------------------------------------------ parsing
def test_parse_equity():
    q = parse_chart(chart(), fetched_at=at(11, 1))
    assert q.symbol == "AAPL" and q.name == "Apple Inc." and q.currency == "USD"
    assert q.instrument == "EQUITY" and q.exchange == "NasdaqGS"
    assert q.price == 270.5 and q.previous_close == 274.0
    assert q.change == pytest.approx(-3.5)
    assert q.change_pct == pytest.approx(-3.5 / 274.0 * 100)
    assert q.market_time == at(11) and q.fetched_at == at(11, 1)
    assert (q.pre_start, q.session_start, q.session_end, q.post_end) == (PRE_START, OPEN, CLOSE, POST_END)
    assert q.day_high == 275.25 and q.day_low == 268.0
    assert q.spark == (270.0, 271.0, 270.5) and not q.from_cache


def test_change_percent_math_negative_one_and_quarter():
    q = parse_chart(chart(price=98.75, prev=100.0), 0)
    assert q.change == pytest.approx(-1.25) and q.change_pct == pytest.approx(-1.25)
    up = parse_chart(chart(price=110.0, prev=100.0), 0)
    assert up.change_pct == pytest.approx(10.0)


def test_parse_index_uses_short_display_name():
    q = parse_chart(chart(symbol="^GSPC", instrument="INDEX", shortName="S&P 500 INDEX", currency="USD"), 0)
    assert q.name == "S&P 500" and q.instrument == "INDEX"
    ta = parse_chart(chart(symbol="^TA125.TA", instrument="INDEX", shortName="TA-125 Index"), 0)
    assert ta.name == INDEX_NAMES["^TA125.TA"]


def test_name_fallbacks():
    assert parse_chart(chart(shortName=None, longName="Long Name Co"), 0).name == "Long Name Co"
    assert parse_chart(chart(drop=("shortName", "longName")), 0).name == "AAPL"


def test_nulls_in_closes_dropped_and_all_null_gives_empty_spark():
    q = parse_chart(chart(closes=[None, 1.0, None, None, 2.0, None]), 0)
    assert q.spark == (1.0, 2.0)
    assert parse_chart(chart(closes=[None, None]), 0).spark == ()
    payload = chart()
    del payload["chart"]["result"][0]["indicators"]
    assert parse_chart(payload, 0).spark == ()


def test_previous_close_fallbacks():
    q = parse_chart(chart(chartPreviousClose=None, previousClose=200.0, price=210.0), 0)
    assert q.previous_close == 200.0 and q.change == pytest.approx(10.0) and q.change_pct == pytest.approx(5.0)
    none = parse_chart(chart(drop=("chartPreviousClose", "previousClose")), 0)
    assert none.previous_close is None and none.change is None and none.change_pct is None
    zero = parse_chart(chart(prev=0, previousClose=0), 0)
    assert zero.change_pct is None  # never divide by zero


def test_missing_optional_meta_fields():
    q = parse_chart(chart(drop=("currentTradingPeriod", "regularMarketTime", "regularMarketDayHigh",
                                "fullExchangeName", "currency", "instrumentType")), 0)
    assert q.session_start is None and q.market_time is None and q.day_high is None
    assert q.exchange == "NMS" and q.currency == "" and q.instrument == ""


@pytest.mark.parametrize("payload", [
    NOT_FOUND,
    {"chart": {"result": None, "error": None}},
    {"chart": {"result": [], "error": None}},
    {"chart": {"result": [{"meta": None}], "error": None}},
    {"chart": {"result": None, "error": {"code": "Bad Request", "description": "Invalid input"}}},
    {"nope": 1},
    [],
])
def test_error_payloads_raise(payload):
    with pytest.raises(MarketError):
        parse_chart(payload, 0)


def test_not_found_payload_has_404_status():
    with pytest.raises(MarketError) as ei:
        parse_chart(NOT_FOUND, 0)
    assert ei.value.status == 404


def test_missing_price_raises():
    with pytest.raises(MarketError, match="no price"):
        parse_chart(chart(drop=("regularMarketPrice",)), 0)
    with pytest.raises(MarketError):
        parse_chart(chart(regularMarketPrice="270.5"), 0)


def test_spark_downsampling():
    closes = [float(i) for i in range(200)]
    q = parse_chart(chart(closes=closes), 0)
    assert len(q.spark) == markets.SPARK_POINTS == 80
    assert q.spark[0] == 0.0 and q.spark[-1] == 199.0
    steps = [b - a for a, b in zip(q.spark, q.spark[1:])]
    assert all(s > 0 for s in steps) and max(steps) - min(steps) <= 1.0  # even spacing
    exact = parse_chart(chart(closes=[float(i) for i in range(80)]), 0)
    assert exact.spark == tuple(float(i) for i in range(80))
    with_nulls = parse_chart(chart(closes=[None if i % 2 else float(i) for i in range(300)]), 0)
    assert len(with_nulls.spark) == 80 and None not in with_nulls.spark


def test_to_dict_is_json_friendly():
    q = parse_chart(chart(), at(11))
    d = q.to_dict()
    assert isinstance(d["spark"], list)
    assert json.loads(json.dumps(d))["price"] == 270.5
    assert Quote.from_dict(d) == q


# ------------------------------------------------------------------------------------------------ sessions
@pytest.mark.parametrize("now,expected", [
    (at(3, 59), "closed"),
    (PRE_START, "pre"),
    (at(9, 29), "pre"),
    (OPEN, "open"),
    (at(15, 59), "open"),
    (CLOSE, "post"),
    (at(19, 59), "post"),
    (POST_END, "closed"),
    (at(10, day=1), "closed"),  # yesterday's periods do not make tomorrow "open"
])
def test_session_state_windows(now, expected):
    assert session_state(make_quote(), now) == expected


def test_session_state_missing_data_and_crypto():
    bare = make_quote(session_start=None, session_end=None, pre_start=None, post_end=None)
    assert session_state(bare, at(11)) == "closed"
    assert session_state(make_quote(pre_start=None, post_end=None), at(8)) == "closed"
    btc = make_quote(symbol="BTC-USD", instrument="CRYPTOCURRENCY", session_start=None, session_end=None)
    assert session_state(btc, at(3)) == "open"
    assert session_state(make_quote(instrument="CRYPTOCURRENCY"), at(23)) == "open"  # 24/7 regardless of periods


# ------------------------------------------------------------------------------------------------ freshness
def test_format_local_is_deterministic():
    assert format_local(at(10, 42), at(12), TZ) == "10:42"
    assert format_local(at(10, 42, day=-1), at(12), TZ) == "Wed 10:42"
    assert format_local(at(16, day=-3), at(12), TZ) == "Mon 16:00"
    assert format_local(at(9, 5, day=-10), at(12), TZ) == "26 Oct 09:05"
    other = timezone(timedelta(hours=2))
    assert format_local(at(10, 42), at(12), other) == "17:42"


def test_classify_live():
    now = at(11, 1)
    f = classify(make_quote(market_time=at(11), fetched_at=now), now, refresh_s=60, tz=TZ)
    assert f == Freshness("live", 60.0, "Live", True)


def test_classify_delayed():
    now = at(11, 15)
    f = classify(make_quote(market_time=at(11), fetched_at=now), now, refresh_s=60, tz=TZ)
    assert f.status == "delayed" and not f.is_live and f.label == "Delayed · 15 min" and f.age_s == 900
    long = classify(make_quote(market_time=at(10), fetched_at=at(15)), at(15), 60, tz=TZ)
    assert long.label == "Delayed · 5 h" and not long.is_live
    unknown = classify(make_quote(market_time=None, fetched_at=now), now, 60, tz=TZ)
    assert unknown.status == "delayed" and not unknown.is_live


def test_classify_live_threshold_boundary():
    # threshold = max(refresh, 120) + 90 = 210 s for refresh 60
    q = make_quote(market_time=at(11), fetched_at=at(11, 4))
    assert classify(q, at(11) + 210, 60, tz=TZ).is_live
    assert not classify(q, at(11) + 211, 60, tz=TZ).is_live


def test_classify_closed_pre_post():
    closed_same_day = classify(make_quote(market_time=CLOSE, fetched_at=at(21)), at(21), 300, tz=TZ)
    assert closed_same_day == Freshness("closed", 5 * 3600.0, "Closed · as of 16:00", False)
    weekend = make_quote(market_time=CLOSE, fetched_at=at(10, day=2))  # Saturday, Thursday's periods
    f = classify(weekend, at(10, day=2), 300, tz=TZ)
    assert f.status == "closed" and f.label == "Closed · as of Thu 16:00" and not f.is_live
    pre = classify(make_quote(market_time=at(16, day=-1), fetched_at=at(8)), at(8), 300, tz=TZ)
    assert pre.status == "closed" and pre.label == "Pre-market · as of Wed 16:00" and not pre.is_live
    post = classify(make_quote(market_time=CLOSE, fetched_at=at(17)), at(17), 300, tz=TZ)
    assert post.status == "closed" and post.label == "After hours · as of 16:00" and not post.is_live


def test_classify_stale_by_age():
    q = make_quote(market_time=at(10, 41), fetched_at=at(10, 42))
    # 2 * 60 + 60 = 180 s allowed since the last successful fetch
    assert classify(q, at(10, 42) + 180, 60, tz=TZ).status != "stale"
    f = classify(q, at(10, 42) + 181, 60, tz=TZ)
    assert f.status == "stale" and f.label == "Not updated since 10:42" and not f.is_live
    yesterday = classify(make_quote(market_time=at(10, 41, day=-1), fetched_at=at(10, 42, day=-1)), at(11), 60, tz=TZ)
    assert yesterday.label == "Not updated since Wed 10:42"


def test_classify_stale_uses_last_success_conservatively():
    q = make_quote(market_time=at(11), fetched_at=at(11))
    f = classify(q, at(11, 1), 60, last_success=at(10, 30), tz=TZ)
    assert f.status == "stale" and f.label == "Not updated since 10:30"
    # a newer last_success never makes an old quote fresher than its own fetch time
    old = make_quote(market_time=at(10), fetched_at=at(10))
    assert classify(old, at(11), 60, last_success=at(11), tz=TZ).status == "stale"


def test_classify_from_cache_is_always_stale():
    now = at(11)
    q = make_quote(market_time=now, fetched_at=now, from_cache=True)
    f = classify(q, now, 60, tz=TZ)
    assert f.status == "stale" and not f.is_live and f.label == "Not updated since 11:00"


def test_classify_none():
    assert classify(None, at(11), 60) == Freshness("error", None, "Unavailable", False)
    assert classify(None, at(11), 60, last_error="No internet connection").label == "Offline"
    assert classify(None, at(11), 60, last_error="Market data request timed out").label == "Offline"
    assert classify(None, at(11), 60, last_error="Unknown symbol AAPLX").label == "Unavailable"


@pytest.mark.parametrize("refresh_s", [15, 60, 300, 900])
@pytest.mark.parametrize("instrument", ["EQUITY", "CRYPTOCURRENCY"])
def test_never_live_when_old(refresh_s, instrument):
    now = at(12)
    live_limit = max(refresh_s, 120) + 90
    fetch_limit = 2 * refresh_s + 60
    for market_age in range(0, 6 * 3600, 37):
        for fetch_age in (0, 30, fetch_limit, fetch_limit + 1, 3600, 86400):
            for from_cache in (False, True):
                q = make_quote(instrument=instrument, market_time=now - market_age,
                               fetched_at=now - fetch_age, from_cache=from_cache)
                f = classify(q, now, refresh_s, tz=TZ)
                should_be_live = market_age <= live_limit and fetch_age <= fetch_limit and not from_cache
                assert f.is_live == should_be_live, (market_age, fetch_age, from_cache)
                assert f.is_live == (f.status == "live")
                if f.is_live:
                    assert f.label == "Live"
                else:
                    assert "Live" not in f.label
    # outside the session nothing is live, however fresh
    for now2 in (at(3), at(8), at(17), at(22), at(12, day=2)):
        q = make_quote(market_time=now2, fetched_at=now2)
        assert not classify(q, now2, refresh_s, tz=TZ).is_live


# ------------------------------------------------------------------------------------------------ scheduling
def test_next_refresh_delay_open_and_pre_post():
    assert next_refresh_delay([make_quote()], at(11), 60) == 60
    assert next_refresh_delay([make_quote()], at(8), 60) == 600
    assert next_refresh_delay([make_quote()], at(17), 900) == 900
    mixed = [make_quote(), make_quote(symbol="BTC-USD", instrument="CRYPTOCURRENCY")]
    assert next_refresh_delay(mixed, at(22), 60) == 60
    assert next_refresh_delay([], at(22), 45) == 45


def test_next_refresh_delay_closed_waits_for_next_open():
    tomorrow = make_quote(pre_start=at(4, day=1), session_start=at(9, 30, day=1),
                          session_end=at(16, day=1), post_end=at(20, day=1))
    assert next_refresh_delay([tomorrow], at(22), 60) == 3 * 3600  # 6 h away -> clamped to 3 h
    assert next_refresh_delay([tomorrow], at(2, day=1), 60) == 2 * 3600 + 30
    assert next_refresh_delay([tomorrow], at(3, 58, day=1), 60) == 600  # 2 min away -> clamped up to 10 min
    no_pre = make_quote(pre_start=None, post_end=None, session_start=at(9, 30, day=1), session_end=at(16, day=1))
    assert next_refresh_delay([no_pre], at(8, day=1), 60) == 90 * 60 + 30
    earliest = [tomorrow, make_quote(pre_start=None, post_end=None, session_start=at(1, day=1), session_end=at(3, day=1))]
    assert next_refresh_delay(earliest, at(0, day=1), 60) == 3630
    finished = make_quote()  # only today's (past) periods known
    d = next_refresh_delay([finished], at(22), 60)
    assert 600 <= d <= 3 * 3600


def test_next_refresh_delay_backoff():
    q = [make_quote()]
    assert next_refresh_delay(q, at(11), 300, consecutive_errors=1) == 30
    assert next_refresh_delay(q, at(11), 300, consecutive_errors=2) == 60
    assert next_refresh_delay(q, at(11), 300, consecutive_errors=3) == 120
    assert next_refresh_delay(q, at(11), 300, consecutive_errors=5) == 300
    assert next_refresh_delay(q, at(11), 300, consecutive_errors=500) == 300
    assert next_refresh_delay(q, at(11), 10, consecutive_errors=1) == 30  # never below 30 s


# ------------------------------------------------------------------------------------------------ client
class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def router(table, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        for key, value in table.items():
            if f"/chart/{key}?" in url:
                if isinstance(value, BaseException):
                    raise value
                return as_bytes(value)
        raise AssertionError(f"unexpected url {url}")
    return fetch


def test_quotes_success_url_and_symbols(tmp_path):
    calls = []
    yf = YahooFinance(cache_path=tmp_path / "m.json",
                      fetch=router({"AAPL": chart(), "%5EGSPC": chart(symbol="^GSPC", instrument="INDEX")}, calls),
                      clock=FakeClock(at(11, 1)))
    quotes, errors = yf.quotes(["aapl ", "^GSPC", "AAPL"])
    assert errors == {} and set(quotes) == {"AAPL", "^GSPC"}
    assert len(calls) == 2  # duplicate removed
    assert any("/v8/finance/chart/%5EGSPC?range=1d&interval=5m&includePrePost=false" in u for u in calls)
    assert quotes["^GSPC"].name == "S&P 500" and quotes["AAPL"].fetched_at == at(11, 1)
    assert classify(quotes["AAPL"], at(11, 1), 60, tz=TZ).is_live


def test_quotes_partial_failure(tmp_path):
    yf = YahooFinance(cache_path=tmp_path / "m.json", clock=FakeClock(at(11)), fetch=router({
        "AAPL": chart(),
        "MSFT": urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None),
        "NVDA": urllib.error.URLError(OSError("getaddrinfo failed")),
        "AAPLX": urllib.error.HTTPError("u", 404, "Not Found", {}, None),
        "ZZZZ": NOT_FOUND,
        "SLOW": TimeoutError("timed out"),
        "BAD": MarketError("boom"),
    }))
    quotes, errors = yf.quotes(["AAPL", "MSFT", "NVDA", "AAPLX", "ZZZZ", "SLOW", "BAD", "no good!"])
    assert list(quotes) == ["AAPL"]
    assert errors["MSFT"] == "Market data service unavailable (HTTP 503)"
    assert errors["NVDA"] == "No internet connection"
    assert errors["AAPLX"] == "Unknown symbol AAPLX"
    assert errors["ZZZZ"] == "Unknown symbol ZZZZ"
    assert errors["SLOW"] == "Market data request timed out"
    assert errors["BAD"] == "boom"
    assert "no good!" in errors
    assert set(yf.cached(["AAPL", "MSFT"])) == {"AAPL"}


def test_invalid_json_response(tmp_path):
    yf = YahooFinance(fetch=lambda url: b"<html>oops</html>", clock=FakeClock(0))
    _, errors = yf.quotes(["AAPL"])
    assert errors == {"AAPL": "Market data service returned an invalid response"}


def test_parallel_fetch_is_bounded():
    lock = threading.Lock()
    active = [0, 0]

    def fetch(url):
        with lock:
            active[0] += 1
            active[1] = max(active[1], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return as_bytes(chart())

    quotes, errors = YahooFinance(fetch=fetch, clock=FakeClock(0)).quotes([f"S{i}" for i in range(9)])
    assert len(quotes) == 9 and not errors
    assert 2 <= active[1] <= markets.MAX_WORKERS == 4
    assert quotes["S3"].symbol == "S3"  # keyed and labelled by the requested symbol


def test_cache_round_trip_and_merge(tmp_path):
    path = tmp_path / "sub" / "markets.json"
    YahooFinance(cache_path=path, fetch=router({"AAPL": chart()}), clock=FakeClock(at(11))).quotes(["AAPL"])
    YahooFinance(cache_path=path, fetch=router({"MSFT": chart(symbol="MSFT", shortName="Microsoft")}),
                 clock=FakeClock(at(11, 5))).quotes(["MSFT"])
    restored = YahooFinance(cache_path=path, fetch=router({})).cached(["AAPL", "msft", "NVDA", "bad sym"])
    assert set(restored) == {"AAPL", "MSFT"}
    a = restored["AAPL"]
    assert a.from_cache and a.price == 270.5 and a.fetched_at == at(11) and a.spark == (270.0, 271.0, 270.5)
    assert restored["MSFT"].name == "Microsoft" and restored["MSFT"].fetched_at == at(11, 5)
    f = classify(a, at(11) + 1, 60, tz=TZ)
    assert f.status == "stale" and not f.is_live and f.label == "Not updated since 11:00"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["quotes"]["AAPL"]["from_cache"] is False


def test_corrupt_cache(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{not json", encoding="utf-8")
    yf = YahooFinance(cache_path=path, fetch=router({"AAPL": chart()}), clock=FakeClock(at(11)))
    assert yf.cached(["AAPL"]) == {}
    quotes, errors = yf.quotes(["AAPL"])  # rewrites a valid cache
    assert "AAPL" in quotes and yf.cached(["AAPL"])["AAPL"].from_cache
    path.write_text(json.dumps({"quotes": {"AAPL": {"symbol": "AAPL"}, "MSFT": "x",
                                           "NVDA": make_quote(symbol="NVDA").to_dict()}}), encoding="utf-8")
    assert set(yf.cached(["AAPL", "MSFT", "NVDA"])) == {"NVDA"}
    path.write_text("[1, 2]", encoding="utf-8")
    assert yf.cached(["AAPL"]) == {}
    assert YahooFinance(cache_path=None, fetch=router({})).cached(["AAPL"]) == {}


def test_search_parsing():
    calls = []

    def fetch(url):
        calls.append(url)
        return as_bytes({"quotes": [
            {"symbol": "AAPL", "shortname": "Apple Inc.", "longname": "Apple Inc.", "exchDisp": "NASDAQ",
             "quoteType": "EQUITY"},
            {"symbol": "APC.F", "longname": "Apple Inc.", "exchDisp": "Frankfurt", "quoteType": "EQUITY"},
            {"shortname": "no symbol"},
            {"symbol": "WEIRD SYMBOL WITH SPACES"},
            "junk",
        ], "news": []})

    yf = YahooFinance(fetch=fetch)
    res = yf.search("  apple ")
    assert res == [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type": "EQUITY"},
                   {"symbol": "APC.F", "name": "Apple Inc.", "exchange": "Frankfurt", "type": "EQUITY"}]
    assert calls[0].startswith(markets.SEARCH_URL + "?q=apple&")
    assert "quotesCount=8" in calls[0] and "newsCount=0" in calls[0]
    assert yf.search("") == [] and yf.search("   ") == [] and len(calls) == 1
    yf.search("x" * 500)
    assert "q=" + "x" * markets.SEARCH_MAX_CHARS + "&" in calls[-1]


def test_search_failure_raises():
    def offline(url):
        raise urllib.error.URLError(OSError("network unreachable"))

    with pytest.raises(MarketError, match="No internet connection"):
        YahooFinance(fetch=offline).search("apple")


def test_default_http_get_sends_user_agent_and_timeout(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        seen["timeout"] = timeout
        seen["url"] = req.full_url
        return Resp()

    monkeypatch.setattr(markets.urllib.request, "urlopen", fake_urlopen)
    assert markets._http_get("https://example.invalid/x") == b"{}"
    assert seen["ua"] == markets.USER_AGENT and "ProjectGlass/1.0" in seen["ua"]
    assert seen["timeout"] == 8.0

    def failing(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)

    monkeypatch.setattr(markets.urllib.request, "urlopen", failing)
    with pytest.raises(MarketError, match=r"HTTP 503") as ei:
        markets._http_get("https://example.invalid/x")
    assert ei.value.status == 503


# ------------------------------------------------------------------------------------------------ symbols
@pytest.mark.parametrize("raw,expected", [
    ("aapl", "AAPL"), ("  msft ", "MSFT"), ("^gspc", "^GSPC"), ("BRK-B", "BRK-B"), ("brk.b", "BRK.B"),
    ("EURUSD=X", "EURUSD=X"), ("^TA125.TA", "^TA125.TA"), ("BTC-USD", "BTC-USD"), ("A" * 15, "A" * 15),
])
def test_normalize_symbol_valid(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "AA PL", "AAPL;", "A" * 16, "../etc", "AAPL&x=1", "שלום", None, 5])
def test_normalize_symbol_invalid(raw):
    with pytest.raises(MarketError):
        normalize_symbol(raw)


def test_default_lists():
    assert DEFAULT_INDICES == ["^GSPC", "^IXIC", "^DJI"]
    assert DEFAULT_WATCHLIST == ["AAPL", "MSFT", "NVDA"]
    assert all(normalize_symbol(s) == s for s in DEFAULT_INDICES + DEFAULT_WATCHLIST + list(INDEX_NAMES))
    assert all(s in INDEX_NAMES for s in DEFAULT_INDICES)
