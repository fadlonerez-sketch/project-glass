"""Markets for the top bar: indices on one side of the Dynamic Glass, the watchlist on the other.

Quotes come from glass.core.markets (Yahoo Finance's unofficial chart endpoint) on a worker thread. The refresh
cadence follows the markets: every ``markets.refresh_s`` (3 minutes by default) while a watched market is open,
rarely while all are closed, with back-off after errors. Freshness is re-evaluated every 30 seconds without
fetching, so a quote turns from "Live" to "Delayed" or "Not updated since ..." on time even when the network
is down. Cached quotes from a previous session are only ever shown as stale.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from glass.core import markets as mk
from glass.core import paths
from glass.core.settings import SettingsStore

log = logging.getLogger(__name__)

STATUS_ORDER = ["error", "stale", "delayed", "closed", "live"]   # the overall status is the weakest one shown


class MarketsService(QObject):
    changed = Signal()
    _fetched = Signal(object, object, float)      # quotes, errors, fetched_at (worker -> UI thread)

    def __init__(self, settings: SettingsStore, client: mk.YahooFinance | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.client = client or mk.YahooFinance(cache_path=paths.cache_dir() / "markets.json")
        self._quotes: dict[str, mk.Quote] = {}
        self._errors: dict[str, str] = {}
        self._last_error = ""
        self._last_success: float | None = None
        self._failures = 0
        self._busy = False
        self._active = False
        self._view: dict = {"enabled": False, "indices": [], "watchlist": [], "status": "loading", "label": "", "updated": ""}
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.refresh)
        self._clock = QTimer(self, interval=30_000)
        self._clock.timeout.connect(self._rebuild)
        self._fetched.connect(self._on_fetched)
        settings.subscribe(lambda ch: QTimer.singleShot(0, lambda: self._on_settings(ch)))

    # ------------------------------------------------------------------ lifecycle
    def symbols(self) -> list[str]:
        s = self.settings
        out = list(s.get("markets.indices")) if s.get("markets.show_indices") else []
        return out + [x for x in s.get("markets.watchlist") if x not in out]

    def start(self) -> None:
        self._active = True
        if not self.settings.get("markets.enabled"):
            self._rebuild()
            return
        cached = self.client.cached(self.symbols())
        for sym, q in cached.items():
            self._quotes.setdefault(sym, q)
        self._rebuild()
        self._clock.start()
        self.refresh()

    def stop(self) -> None:
        self._active = False
        self._timer.stop()
        self._clock.stop()

    def _on_settings(self, changed: dict) -> None:
        if not any(k.startswith("markets.") for k in changed):
            return
        if not self._active:
            return
        if self.settings.get("markets.enabled"):
            self._clock.start()
            self.refresh()
        else:
            self._timer.stop()
            self._clock.stop()
        self._rebuild()

    # ------------------------------------------------------------------ fetching
    @Slot()
    def refresh(self) -> None:
        if not self._active or not self.settings.get("markets.enabled") or self._busy:
            return
        symbols = self.symbols()
        if not symbols:
            self._rebuild()
            return
        self._busy = True

        def work():
            try:
                quotes, errors = self.client.quotes(symbols)
            except Exception as exc:  # the client reports per-symbol errors; this is a safety net
                quotes, errors = {}, {s: str(exc) for s in symbols}
            self._fetched.emit(quotes, errors, time.time())
        threading.Thread(target=work, name="glass-markets", daemon=True).start()

    def _on_fetched(self, quotes: dict, errors: dict, fetched_at: float) -> None:
        self._busy = False
        self._quotes.update(quotes)
        self._errors = dict(errors)
        if quotes:
            self._last_success = fetched_at
            self._failures = 0
            self._last_error = ""
        else:
            self._failures += 1
            self._last_error = next(iter(errors.values()), "Market data unavailable")
            log.info("market data unavailable: %s", self._last_error)
        self._rebuild()
        if self._active and self.settings.get("markets.enabled"):
            delay = mk.next_refresh_delay(list(self._quotes.values()), time.time(), float(self.settings.get("markets.refresh_s")),
                                          self._failures)
            self._timer.start(int(delay * 1000))

    # ------------------------------------------------------------------ view model for QML
    def _entry(self, symbol: str, now: float, refresh_s: float) -> dict:
        q = self._quotes.get(symbol)
        err = self._errors.get(symbol, "")
        fr = mk.classify(q, now, refresh_s, last_error=err or self._last_error,
                         last_success=self._last_success if q is not None and not q.from_cache else None)
        name = mk.INDEX_NAMES.get(symbol) or (q.name if q else symbol)
        show_name = mk.INDEX_NAMES.get(symbol) or symbol.split(".")[0]
        return {"symbol": symbol, "name": name, "label": show_name,
                "price": q.price if q else None, "change": q.change if q else None,
                "changePct": q.change_pct if q else None, "currency": q.currency if q else "",
                "dayHigh": q.day_high if q else None, "dayLow": q.day_low if q else None,
                "previousClose": q.previous_close if q else None,
                "spark": list(q.spark) if q else [], "exchange": q.exchange if q else "",
                "status": fr.status, "statusLabel": fr.label, "live": fr.is_live, "error": err,
                "session": mk.session_state(q, now) if q else "closed"}

    def _rebuild(self) -> None:
        s = self.settings
        now = time.time()
        refresh_s = float(s.get("markets.refresh_s"))
        enabled = bool(s.get("markets.enabled"))
        indices = [self._entry(x, now, refresh_s) for x in s.get("markets.indices")] if s.get("markets.show_indices") else []
        watch = [self._entry(x, now, refresh_s) for x in s.get("markets.watchlist")]
        shown = [e for e in indices + watch if e["price"] is not None]
        if not enabled:
            status, label = "off", ""
        elif not shown:
            status = "loading" if self._busy or (self._last_success is None and not self._last_error) else "error"
            label = "Loading markets…" if status == "loading" else ("Offline" if "internet" in self._last_error.lower() else "Markets unavailable")
        else:
            status = min((e["status"] for e in shown), key=lambda st: STATUS_ORDER.index(st) if st in STATUS_ORDER else 0)
            label = next(e["statusLabel"] for e in shown if e["status"] == status)
        updated = ""
        if self._last_success:
            updated = "Updated " + mk.format_local(self._last_success, now)
        view = {"enabled": enabled, "indices": indices, "watchlist": watch, "status": status, "label": label,
                "updated": updated, "sparklines": bool(s.get("markets.sparklines")), "error": self._last_error,
                "source": "Yahoo Finance (unofficial)"}
        if view != self._view:
            self._view = view
            self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def data(self):
        return self._view

    @Slot(str)
    def openQuote(self, symbol: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://finance.yahoo.com/quote/" + symbol))
