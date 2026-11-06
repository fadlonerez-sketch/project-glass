import hashlib
import os
import sqlite3
import time

import pytest

from glass.core import ipc, launchdeck
from glass.core.weather import OpenMeteo, WeatherError, describe

SAMPLE = {
    "current": {"time": "2026-11-05T11:00", "temperature_2m": 21.4, "apparent_temperature": 20.1,
                "relative_humidity_2m": 55, "weather_code": 2, "is_day": 1, "wind_speed_10m": 12.3},
    "hourly": {"time": [f"2026-11-05T{h:02d}:00" for h in range(24)],
               "temperature_2m": [15 + h * 0.3 for h in range(24)], "weather_code": [1] * 24,
               "is_day": [1 if 6 <= h < 18 else 0 for h in range(24)], "precipitation_probability": [10] * 24},
    "daily": {"time": ["2026-11-05", "2026-11-06"], "weather_code": [2, 61],
              "temperature_2m_max": [23.0, 19.5], "temperature_2m_min": [14.0, 12.0]},
}


def test_parse_forecast():
    r = OpenMeteo.parse(SAMPLE, "c", "Tel Aviv")
    assert r.temperature == 21.4 and r.condition == "Partly Cloudy" and r.icon == "partly"
    assert r.high == 23.0 and r.low == 14.0 and r.humidity == 55
    assert r.hourly[0].time == "2026-11-05T11:00" and len(r.hourly) == 8
    assert r.daily[1].icon == "rain"


def test_forecast_uses_units_and_cache(tmp_path):
    urls = []

    def fetch(url):
        urls.append(url)
        return SAMPLE

    om = OpenMeteo(fetch=fetch, cache_path=tmp_path / "w.json")
    om.forecast(32.08, 34.78, "f", "TLV")
    assert "temperature_unit=fahrenheit" in urls[0] and "latitude=32.0800" in urls[0]

    def broken(url):
        raise OSError("offline")

    stale = OpenMeteo(fetch=broken, cache_path=tmp_path / "w.json").forecast(32.08, 34.78, "f", "TLV")
    assert stale.stale and stale.temperature == 21.4
    with pytest.raises(WeatherError):
        OpenMeteo(fetch=broken, cache_path=tmp_path / "none.json").forecast(1, 2, "c")


def test_search_parsing():
    om = OpenMeteo(fetch=lambda url: {"results": [{"name": "Haifa", "latitude": 32.8, "longitude": 34.98,
                                                   "country": "Israel", "admin1": "Haifa District"}]})
    places = om.search("Haifa")
    assert places[0].label == "Haifa, Haifa District, Israel"
    assert om.search("x") == []


def test_wmo_fallback():
    assert describe(95)[1] == "thunder"
    assert describe(12345) == ("Unknown", "cloudy")


def test_framing_roundtrip_and_partial():
    dec = ipc.FrameDecoder()
    data = ipc.encode(ipc.request(1, "hello", {"x": "שלום"})) + ipc.encode(ipc.notification("event", {"a": 1}))
    assert dec.feed(data[:3]) == []
    out = dec.feed(data[3:20]) + dec.feed(data[20:])
    assert out[0]["params"]["x"] == "שלום" and out[1]["method"] == "event"


def test_framing_rejects_garbage():
    with pytest.raises(ipc.ProtocolError):
        ipc.FrameDecoder().feed((5).to_bytes(4, "little") + b"nope!")
    with pytest.raises(ipc.ProtocolError):
        ipc.FrameDecoder().feed((ipc.MAX_FRAME + 1).to_bytes(4, "little"))
    with pytest.raises(ipc.ProtocolError):
        ipc.FrameDecoder().feed((2).to_bytes(4, "little") + b"[]")


def test_launchdeck_instance_name_matches_its_algorithm(tmp_path):
    d = tmp_path / "LaunchDeck"
    expected = "LaunchDeck-" + hashlib.sha1(os.path.normcase(os.path.abspath(str(d))).encode()).hexdigest()[:12]
    assert launchdeck.instance_name(d) == expected


def test_launchdeck_usage_history(tmp_path):
    d = tmp_path / "ld"
    d.mkdir()
    with sqlite3.connect(d / "data.db") as c:
        c.execute("CREATE TABLE usage (key TEXT PRIMARY KEY, count INTEGER, last_used REAL)")
        now = time.time()
        c.executemany("INSERT INTO usage VALUES (?,?,?)", [
            ("app:c:\\start menu\\claude.lnk", 3, now),
            ("file:c:\\downloads\\x.pdf", 2, now + 1),
            ("app:shell:appsfolder\\microsoft.windowsnotepad_8wekyb3d8bbwe!app", 1, now - 5),
            ("website:yt", 9, now + 2),
        ])
    hist = launchdeck.usage_history(d)
    assert [h.target for h in hist] == ["c:\\start menu\\claude.lnk",
                                        "shell:appsfolder\\microsoft.windowsnotepad_8wekyb3d8bbwe!app"]
    assert hist[1].is_packaged
    assert launchdeck.usage_history(tmp_path / "missing") == []


def test_launchdeck_send_when_not_running(tmp_path):
    assert launchdeck.send("launcher", tmp_path / "not-running", timeout=0.2) is False
