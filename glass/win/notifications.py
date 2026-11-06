"""Mirroring Windows notifications into the Dynamic Glass (UserNotificationListener).

Windows only grants the notification-listener capability to apps with *package identity*. Glass gets one
through a sparse (external-location) MSIX package: ``scripts/install-identity.ps1`` builds, signs and
registers it (docs/NOTIFICATIONS.md). Without identity this module reports ``needs_identity`` and Glass
shows only its own and Garvis notifications -- it never scrapes Explorer's notification UI.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from glass.win.winrt_worker import WinRtWorker

log = logging.getLogger(__name__)


def has_package_identity() -> bool:
    try:
        from winrt.windows.applicationmodel import Package
        return Package.current is not None
    except Exception:
        return False


class NotificationMirror(QObject):
    notification = Signal(dict)        # {app, title, body, id, time}
    statusChanged = Signal(str)        # needs_identity | denied | active | unavailable

    def __init__(self, parent=None, poll_ms: int = 2500):
        super().__init__(parent)
        self._worker = WinRtWorker.shared()
        self._listener = None
        self._seen: set[int] = set()
        self._started = time.time()
        self.status = "unavailable"
        self._timer = QTimer(self, interval=poll_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        if not has_package_identity():
            self._set_status("needs_identity")
            return
        self._worker.submit(self._init(), lambda ok, err: self._set_status("active" if ok else ("denied" if err is None else "unavailable")))

    def stop(self) -> None:
        self._timer.stop()

    async def _init(self) -> bool:
        from winrt.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus
        self._listener = UserNotificationListener.current
        status = await self._listener.request_access_async()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            return False
        await self._collect(initial=True)
        return True

    def _set_status(self, status: str) -> None:
        self.status = status
        if status == "active":
            QTimer.singleShot(0, self._timer.start)
        self.statusChanged.emit(status)

    def _poll(self) -> None:
        if self._listener is not None:
            self._worker.submit(self._collect(initial=False))

    async def _collect(self, initial: bool) -> None:
        from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
        try:
            items = await self._listener.get_notifications_async(NotificationKinds.TOAST)
        except Exception as exc:
            log.debug("notification read failed: %s", exc)
            return
        for n in items:
            if n.id in self._seen:
                continue
            self._seen.add(n.id)
            if initial:
                continue  # don't replay what was already in Action Center when Glass started
            try:
                binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                texts = [t.text for t in binding.get_text_elements()] if binding else []
                app = n.app_info.display_info.display_name if n.app_info else ""
                app_id = n.app_info.app_user_model_id if n.app_info else ""
            except Exception:
                continue
            self.notification.emit({"id": n.id, "app": app, "app_id": app_id, "title": texts[0] if texts else app,
                                    "body": " ".join(texts[1:3]), "time": time.time(), "source": "windows"})
