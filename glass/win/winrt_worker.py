"""A background asyncio loop for WinRT async operations, so the Qt GUI thread never blocks on them."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


class WinRtWorker:
    _instance: "WinRtWorker | None" = None

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="glass-winrt", daemon=True)
        self._thread.start()

    @classmethod
    def shared(cls) -> "WinRtWorker":
        if cls._instance is None:
            cls._instance = WinRtWorker()
        return cls._instance

    def _run(self) -> None:
        try:
            import winrt.runtime  # noqa: F401 -- initialises the WinRT apartment for this thread
        except Exception:
            pass
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Awaitable, on_done: Callable[[Any, BaseException | None], None] | None = None) -> concurrent.futures.Future:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_done is not None:
            def _cb(f: concurrent.futures.Future):
                try:
                    on_done(f.result(), None)
                except BaseException as exc:  # noqa: BLE001 - reported to the caller
                    on_done(None, exc)
            fut.add_done_callback(_cb)
        return fut

    def call_soon(self, fn: Callable, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)
