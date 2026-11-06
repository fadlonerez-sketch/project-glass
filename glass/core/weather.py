"""Weather from Open-Meteo (no account, no key; https://open-meteo.com, CC BY 4.0 data).

Only the configured city's coordinates are sent. Responses are cached so the Dock shows the last known
weather offline and refreshes at most every 20 minutes.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "ProjectGlass/1.0 (+desktop weather widget)"
REFRESH_SECONDS = 20 * 60

# WMO weather interpretation codes -> (condition, icon key)
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"), 1: ("Mostly Clear", "clear"), 2: ("Partly Cloudy", "partly"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Freezing Fog", "fog"),
    51: ("Light Drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy Drizzle", "drizzle"),
    56: ("Freezing Drizzle", "sleet"), 57: ("Freezing Drizzle", "sleet"),
    61: ("Light Rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy Rain", "heavy_rain"),
    66: ("Freezing Rain", "sleet"), 67: ("Freezing Rain", "sleet"),
    71: ("Light Snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy Snow", "snow"), 77: ("Snow Grains", "snow"),
    80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Violent Showers", "heavy_rain"),
    85: ("Snow Showers", "snow"), 86: ("Snow Showers", "snow"),
    95: ("Thunderstorm", "thunder"), 96: ("Thunderstorm, Hail", "thunder"), 99: ("Thunderstorm, Hail", "thunder"),
}


class WeatherError(Exception):
    pass


@dataclass
class Place:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    region: str = ""
    timezone: str = ""

    @property
    def label(self) -> str:
        return ", ".join(p for p in (self.name, self.region if self.region != self.name else "", self.country) if p)


@dataclass
class HourPoint:
    time: str
    temperature: float
    code: int
    icon: str
    is_day: bool
    precip_probability: int | None = None


@dataclass
class DayPoint:
    date: str
    high: float
    low: float
    code: int
    icon: str
    condition: str


@dataclass
class WeatherReport:
    temperature: float
    apparent: float
    code: int
    condition: str
    icon: str
    is_day: bool
    humidity: int | None
    wind: float | None
    high: float | None
    low: float | None
    units: str
    place: str
    updated: float
    hourly: list[HourPoint] = field(default_factory=list)
    daily: list[DayPoint] = field(default_factory=list)
    stale: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "WeatherReport":
        d = dict(d)
        d["hourly"] = [HourPoint(**h) for h in d.get("hourly", [])]
        d["daily"] = [DayPoint(**x) for x in d.get("daily", [])]
        return WeatherReport(**d)


def describe(code: int) -> tuple[str, str]:
    return WMO.get(int(code), ("Unknown", "cloudy"))


def _http_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        return json.loads(resp.read().decode("utf-8"))


class OpenMeteo:
    def __init__(self, fetch: Callable[[str], dict] = _http_json, cache_path: Path | None = None):
        self._fetch = fetch
        self.cache_path = cache_path

    def search(self, query: str, count: int = 8) -> list[Place]:
        query = query.strip()
        if len(query) < 2:
            return []
        url = GEOCODE_URL + "?" + urllib.parse.urlencode({"name": query, "count": count, "language": "en", "format": "json"})
        try:
            data = self._fetch(url)
        except Exception as exc:
            raise WeatherError(f"City search failed: {exc}") from exc
        out = []
        for r in data.get("results") or []:
            out.append(Place(name=r.get("name", ""), latitude=float(r["latitude"]), longitude=float(r["longitude"]),
                             country=r.get("country", "") or "", region=r.get("admin1", "") or "",
                             timezone=r.get("timezone", "") or ""))
        return out

    def forecast(self, lat: float, lon: float, units: str = "c", place: str = "") -> WeatherReport:
        params = {
            "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m,weather_code,is_day,precipitation_probability",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 5, "timezone": "auto",
            "temperature_unit": "fahrenheit" if units == "f" else "celsius",
            "wind_speed_unit": "mph" if units == "f" else "kmh",
        }
        url = FORECAST_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = self._fetch(url)
        except Exception as exc:
            cached = self.cached(lat, lon, units)
            if cached:
                cached.stale = True
                return cached
            raise WeatherError(f"Weather update failed: {exc}") from exc
        report = self.parse(data, units, place)
        self._store(lat, lon, units, report)
        return report

    @staticmethod
    def parse(data: dict, units: str, place: str = "") -> WeatherReport:
        cur = data.get("current") or {}
        if "temperature_2m" not in cur:
            raise WeatherError("Weather service returned no current conditions")
        code = int(cur.get("weather_code", 3))
        condition, icon = describe(code)
        daily = data.get("daily") or {}
        days: list[DayPoint] = []
        for i, d in enumerate(daily.get("time") or []):
            c = int(daily["weather_code"][i])
            cond, ic = describe(c)
            days.append(DayPoint(d, float(daily["temperature_2m_max"][i]), float(daily["temperature_2m_min"][i]), c, ic, cond))
        hourly = data.get("hourly") or {}
        hours: list[HourPoint] = []
        cur_time = cur.get("time", "")
        times = hourly.get("time") or []
        start = 0
        for i, t in enumerate(times):
            if t[:13] >= cur_time[:13]:
                start = i
                break
        for i in range(start, min(start + 8, len(times))):
            c = int(hourly["weather_code"][i])
            probs = hourly.get("precipitation_probability") or []
            hours.append(HourPoint(times[i], float(hourly["temperature_2m"][i]), c, describe(c)[1],
                                   bool(hourly.get("is_day", [1] * len(times))[i]),
                                   int(probs[i]) if i < len(probs) and probs[i] is not None else None))
        return WeatherReport(
            temperature=float(cur["temperature_2m"]), apparent=float(cur.get("apparent_temperature", cur["temperature_2m"])),
            code=code, condition=condition, icon=icon, is_day=bool(cur.get("is_day", 1)),
            humidity=int(cur["relative_humidity_2m"]) if cur.get("relative_humidity_2m") is not None else None,
            wind=float(cur["wind_speed_10m"]) if cur.get("wind_speed_10m") is not None else None,
            high=days[0].high if days else None, low=days[0].low if days else None,
            units=units, place=place, updated=time.time(), hourly=hours, daily=days,
        )

    # ------------------------------------------------------------------ cache
    def _key(self, lat: float, lon: float, units: str) -> str:
        return f"{lat:.3f},{lon:.3f},{units}"

    def cached(self, lat: float, lon: float, units: str) -> WeatherReport | None:
        if not self.cache_path or not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if data.get("key") != self._key(lat, lon, units):
                return None
            return WeatherReport.from_dict(data["report"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _store(self, lat: float, lon: float, units: str, report: WeatherReport) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"key": self._key(lat, lon, units), "report": report.to_dict()}), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError:
            pass
