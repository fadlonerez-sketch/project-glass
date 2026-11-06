"""Now Playing via Windows' Global System Media Transport Controls (the same source the Windows media flyout uses).

Event-driven: session, metadata, playback and timeline changes arrive as WinRT events. Position between
timeline events is interpolated in the UI from (position, updated_at, rate), so no polling is needed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from glass.win.winrt_worker import WinRtWorker

log = logging.getLogger(__name__)

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import DataReader
    AVAILABLE = True
except Exception:  # pragma: no cover - only on systems without the WinRT projection
    AVAILABLE = False


def _ticks_to_s(value: Any) -> float:
    try:
        return value.total_seconds()
    except AttributeError:
        try:
            return float(value.duration) / 10_000_000
        except Exception:
            return 0.0


class MediaService(QObject):
    changed = Signal(dict)
    artworkReady = Signal(str, bytes)      # artwork id, encoded image bytes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = WinRtWorker.shared()
        self._mgr = None
        self._session = None
        self._tokens: list[tuple[Any, str, Any]] = []
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"present": False}
        self._art_seq = 0
        self._last_art_key = ""

    @property
    def state(self) -> dict:
        return dict(self._state)

    def start(self) -> None:
        if not AVAILABLE:
            log.warning("Media session API unavailable")
            return
        self._worker.submit(self._init())

    async def _init(self) -> None:
        self._mgr = await SessionManager.request_async()
        self._mgr.add_current_session_changed(lambda *_: self._worker.call_soon(self._schedule_attach))
        self._mgr.add_sessions_changed(lambda *_: self._worker.call_soon(self._schedule_attach))
        await self._attach()

    def _schedule_attach(self) -> None:
        self._worker.submit(self._attach())

    async def _attach(self) -> None:
        session = self._mgr.get_current_session() if self._mgr else None
        if session is None:
            # Fall back to any playing session (some players never become 'current').
            try:
                for s in self._mgr.get_sessions():
                    if s.get_playback_info().playback_status == PlaybackStatus.PLAYING:
                        session = s
                        break
            except Exception:
                pass
        if session is not self._session:
            self._detach()
            self._session = session
            if session is not None:
                self._tokens = [
                    (session, "media_properties_changed", session.add_media_properties_changed(lambda *_: self._worker.call_soon(self._schedule_refresh, True))),
                    (session, "playback_info_changed", session.add_playback_info_changed(lambda *_: self._worker.call_soon(self._schedule_refresh, False))),
                    (session, "timeline_properties_changed", session.add_timeline_properties_changed(lambda *_: self._worker.call_soon(self._schedule_refresh, False))),
                ]
        await self._refresh(True)

    def _detach(self) -> None:
        for obj, name, token in self._tokens:
            try:
                getattr(obj, "remove_" + name)(token)
            except Exception:
                pass
        self._tokens = []

    def _schedule_refresh(self, with_props: bool) -> None:
        self._worker.submit(self._refresh(with_props))

    async def _refresh(self, with_props: bool) -> None:
        s = self._session
        if s is None:
            self._publish({"present": False})
            return
        st = dict(self._state) if self._state.get("present") else {"present": True}
        try:
            info = s.get_playback_info()
            ctrl = info.controls
            st.update(
                present=True,
                app_id=s.source_app_user_model_id or "",
                playing=info.playback_status == PlaybackStatus.PLAYING,
                can_play=bool(ctrl.is_play_enabled), can_pause=bool(ctrl.is_pause_enabled),
                can_next=bool(ctrl.is_next_enabled), can_prev=bool(ctrl.is_previous_enabled),
                can_seek=bool(ctrl.is_playback_position_enabled),
                rate=float(info.playback_rate) if info.playback_rate is not None else 1.0,
            )
            tl = s.get_timeline_properties()
            start, end = _ticks_to_s(tl.start_time), _ticks_to_s(tl.end_time)
            st.update(position=max(0.0, _ticks_to_s(tl.position) - start), duration=max(0.0, end - start),
                      position_updated=time.time())
            if with_props or "title" not in st:
                props = await s.try_get_media_properties_async()
                st.update(title=props.title or "", artist=props.artist or props.album_artist or "",
                          album=props.album_title or "")
                art_key = f"{st.get('app_id')}|{st['title']}|{st['artist']}|{st['album']}"
                if props.thumbnail is not None and art_key != self._last_art_key:
                    data = await self._read_thumbnail(props.thumbnail)
                    if data:
                        self._art_seq += 1
                        st["artwork"] = f"art{self._art_seq}"
                        self._last_art_key = art_key
                        self.artworkReady.emit(st["artwork"], data)
                elif props.thumbnail is None:
                    st["artwork"] = ""
                    self._last_art_key = art_key
        except Exception as exc:  # the player went away mid-update
            log.debug("media refresh failed: %s", exc)
            return
        self._publish(st)

    @staticmethod
    async def _read_thumbnail(ref) -> bytes:
        try:
            stream = await ref.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > 8_000_000:
                return b""
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            return b""

    def _publish(self, st: dict) -> None:
        self._state = st
        self.changed.emit(dict(st))

    # ------------------------------------------------------------------ controls (called from the GUI thread)
    @Slot()
    def play_pause(self) -> None:
        self._control("try_toggle_play_pause_async")

    @Slot()
    def next(self) -> None:
        self._control("try_skip_next_async")

    @Slot()
    def previous(self) -> None:
        self._control("try_skip_previous_async")

    @Slot(float)
    def seek(self, seconds: float) -> None:
        s = self._session
        if s is None:
            return

        async def go():
            try:
                tl = s.get_timeline_properties()
                start = int(getattr(tl.start_time, "duration", 0) or 0) if not hasattr(tl.start_time, "total_seconds") else int(tl.start_time.total_seconds() * 10_000_000)
                await s.try_change_playback_position_async(start + int(seconds * 10_000_000))
            except Exception as exc:
                log.debug("seek failed: %s", exc)
        self._worker.submit(go())

    def _control(self, method: str) -> None:
        s = self._session
        if s is None:
            return

        async def go():
            try:
                await getattr(s, method)()
            except Exception as exc:
                log.debug("%s failed: %s", method, exc)
        self._worker.submit(go())
