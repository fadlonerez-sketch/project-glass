"""Dock state: maps tracked windows to applications, keeps the registry's launch history, and exposes the
deterministic Dock contents (glass.core.apps.compute_dock) and geometry (glass.core.docklayout) to QML as
an animated list model. Also hosts the hover state machine (glass.core.dockhover) and live window
thumbnails for the window previews."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex, QObject, QTimer, Qt, Signal, Slot,
                            Property)
from PySide6.QtGui import QWindow

from glass.core import launchdeck
from glass.core.apps import AppRecord, AppRegistry, RunningApp, aumid_key, compute_dock, exe_key
from glass.core.dockhover import DockHoverMachine
from glass.core.docklayout import compute_layout
from glass.core.settings import SettingsStore
from glass.win import appwin, launch
from glass.win.thumbnails import ThumbnailHost
from glass.win.tracker import Snapshot, WindowTracker

log = logging.getLogger(__name__)

ROLES = ["uid", "kind", "appId", "name", "section", "pinned", "running", "focused", "windowCount", "icon",
         "launching", "otherDesktop", "widgetType", "widgetId", "attention", "leaving"]
LEAVE_MS = 280          # how long a departing icon stays (fading) while its neighbours close the gap


class DockModel(QAbstractListModel):
    """A list model updated by minimal insert/remove/move operations so QML can animate every change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._roles = {Qt.ItemDataRole.UserRole + i: name.encode() for i, name in enumerate(ROLES)}
        self._role_of = {v.decode(): k for k, v in self._roles.items()}

    def roleNames(self):
        return {k: QByteArray(v) for k, v in self._roles.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        name = self._roles.get(role)
        return self._items[index.row()].get(name.decode()) if name else None

    def items(self) -> list[dict]:
        return list(self._items)

    def apply(self, new: list[dict[str, Any]], keep_leaving: set[str] | None = None) -> None:
        """Make the model equal ``new``. Rows in ``keep_leaving`` that are no longer wanted stay where they
        were, flagged ``leaving``, so QML can fade them while their neighbours glide into the space."""
        new = [dict(i, leaving=False) for i in new]
        if keep_leaving:
            wanted = {i["uid"] for i in new}
            for row, it in enumerate(self._items):
                if it["uid"] in wanted or it["uid"] not in keep_leaving:
                    continue
                # re-insert after the nearest preceding row that is still there
                uids = [n["uid"] for n in new]
                prev = next((self._items[r]["uid"] for r in range(row - 1, -1, -1) if self._items[r]["uid"] in uids), None)
                at = uids.index(prev) + 1 if prev is not None else 0
                new.insert(at, dict(it, leaving=True))
        new_uids = [i["uid"] for i in new]
        # 1. removals
        for row in range(len(self._items) - 1, -1, -1):
            if self._items[row]["uid"] not in new_uids:
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._items[row]
                self.endRemoveRows()
        # 2. insertions and moves, walking the target order
        for target, item in enumerate(new):
            current = next((r for r, it in enumerate(self._items) if it["uid"] == item["uid"]), None)
            if current is None:
                self.beginInsertRows(QModelIndex(), target, target)
                self._items.insert(target, dict(item))
                self.endInsertRows()
                continue
            if current != target:
                dest = target if target < current else target + 1
                self.beginMoveRows(QModelIndex(), current, current, QModelIndex(), dest)
                self._items.insert(target, self._items.pop(current))
                self.endMoveRows()
            # 3. in-place updates
            old = self._items[target]
            changed = [self._role_of[k] for k, v in item.items() if old.get(k) != v and k in self._role_of]
            if changed:
                self._items[target] = dict(item)
                idx = self.index(target)
                self.dataChanged.emit(idx, idx, changed)


def icon_url(source: str, px: int = 128) -> str:
    return f"image://appicon/{px}/{quote(source, safe='')}" if source else ""


class DockHover(QObject):
    """The hover state machine for QML: enter/leave/press events in, what to show out. Event driven: a single
    timer runs only while a hover-intent or dismissal deadline is pending."""
    changed = Signal()

    def __init__(self, settings: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.machine = DockHoverMachine(settings.get("dock.hover_delay_ms") / 1000,
                                        settings.get("dock.dismiss_delay_ms") / 1000, bool(settings.get("dock.previews")))
        self._view = self.machine.view()
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._update)

    def apply_settings(self) -> None:
        self.machine.set_delays(self.settings.get("dock.hover_delay_ms") / 1000,
                                self.settings.get("dock.dismiss_delay_ms") / 1000)
        self.machine.previews = bool(self.settings.get("dock.previews"))

    def _update(self) -> None:
        now = time.monotonic()
        view = self.machine.tick(now)
        if view != self._view:
            self._view = view
            self.changed.emit()
        nxt = self.machine.next_deadline()
        if nxt is None:
            self._timer.stop()
        else:
            self._timer.start(max(1, int((nxt - now) * 1000) + 1))

    @Property(str, notify=changed)
    def state(self):
        return self._view.state.value

    @Property(str, notify=changed)
    def hovered(self):
        return self._view.hovered

    @Property(str, notify=changed)
    def preview(self):
        return self._view.preview

    @Property(str, notify=changed)
    def tooltip(self):
        return self._view.tooltip

    @Slot(str, bool)
    def iconEnter(self, item: str, has_windows: bool):
        self.machine.icon_enter(item, has_windows, time.monotonic())
        self._update()

    @Slot(str)
    def iconLeave(self, item: str):
        self.machine.icon_leave(item, time.monotonic())
        self._update()

    @Slot()
    def previewEnter(self):
        self.machine.preview_enter(time.monotonic())
        self._update()

    @Slot()
    def previewLeave(self):
        self.machine.preview_leave(time.monotonic())
        self._update()

    @Slot(str)
    def press(self, item: str):
        self.machine.press(item)
        self._update()

    @Slot()
    def chooseWindow(self):
        self.machine.choose_window()
        self._update()

    @Slot()
    def dragStart(self):
        self.machine.drag_start()
        self._update()

    @Slot()
    def dragEnd(self):
        self.machine.drag_end(time.monotonic())
        self._update()

    @Slot()
    def menuOpen(self):
        self.machine.menu_open()
        self._update()

    @Slot()
    def menuClose(self):
        self.machine.menu_close(time.monotonic())
        self._update()

    @Slot()
    def dismiss(self):
        self.machine.dismiss()
        self._update()

    @Slot(str, bool)
    def showNow(self, item: str, has_windows: bool):
        """Keyboard navigation: show an item's preview or tooltip at once (no hover intent)."""
        self.machine.show_now(item, has_windows)
        self._update()

    def windows_changed(self, item: str, count: int) -> None:
        self.machine.windows_changed(item, count)
        self._update()


class Thumbnails(QObject):
    """Live DWM window thumbnails inside Glass windows (window previews only: never captured, saved or sent)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hosts: dict[int, ThumbnailHost] = {}
        self._fade = QTimer(self, interval=16)
        self._fade.timeout.connect(self._step)

    def _host(self, window) -> ThumbnailHost | None:
        if not isinstance(window, QWindow):
            return None
        hwnd = int(window.winId())
        host = self._hosts.get(hwnd)
        if host is None:
            host = self._hosts[hwnd] = ThumbnailHost(hwnd)
        return host

    @Slot(QObject, "QVariantList", result="QVariantMap")
    def show(self, window, items):
        """Show live thumbnails at these logical rectangles of ``window``. Returns hwnd -> "" (live) or why not."""
        host = self._host(window)
        if host is None:
            return {}
        try:
            status = host.show([dict(i) for i in items], float(window.devicePixelRatio()))
        except Exception:
            log.exception("window thumbnails failed")
            return {}
        if host.thumbs:
            self._fade.start()
        return {str(k): v for k, v in status.items()}

    @Slot(QObject)
    def hide(self, window):
        host = self._host(window)
        if host is not None:
            host.hide_all()

    @Slot(QObject)
    def clear(self, window):
        host = self._host(window)
        if host is not None:
            host.clear()

    def count(self) -> int:
        return sum(len(h.thumbs) for h in self._hosts.values())

    def prune(self) -> None:
        for host in self._hosts.values():
            host.prune()

    def clear_all(self) -> None:
        for host in self._hosts.values():
            host.clear()
        self._hosts.clear()

    def _step(self) -> None:
        if not any([h.fade_step() for h in list(self._hosts.values())]):
            self._fade.stop()


class DockController(QObject):
    layoutChanged = Signal()
    modelChanged = Signal()
    toast = Signal(str)
    pinnedChanged = Signal()
    foregroundNameChanged = Signal()
    keyboardRequested = Signal()

    def __init__(self, settings: SettingsStore, registry: AppRegistry, catalog: appwin.AppCatalog,
                 tracker: WindowTracker, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.registry = registry
        self.catalog = catalog
        self.tracker = tracker
        self._model = DockModel(self)
        self._running_all: set[str] = set()
        self._windows: dict[str, list[appwin.WindowInfo]] = {}
        self._launching: dict[str, float] = {}
        self._first_seen: dict[str, float] = {}
        self._foreground_name = ""
        self._snapshot: Snapshot | None = None
        self._launch_timer = QTimer(self, interval=1000)
        self._launch_timer.timeout.connect(self._expire_launches)
        self._leave_timer = QTimer(self, singleShot=True, interval=LEAVE_MS)
        self._leave_timer.timeout.connect(self._finish_leaving)
        self._last_rows: list[dict] = []
        self._layout_rev = 0
        self._layout_cache: dict = {}
        self._prev_foreground = 0
        self.hover = DockHover(settings, self)
        self.thumbs = Thumbnails(self)
        tracker.changed.connect(self._on_snapshot)
        settings.subscribe(self._on_settings)

    # ------------------------------------------------------------------ properties
    @Property(QObject, notify=modelChanged)
    def model(self):
        return self._model

    @Property(str, notify=foregroundNameChanged)
    def foregroundName(self):
        return self._foreground_name

    @Property("QVariantList", notify=layoutChanged)
    def kinds(self):
        """[kind, widgetType] per row."""
        return [[r["kind"], r["widgetType"]] for r in self._model.items()]

    @Property(int, notify=layoutChanged)
    def layoutRevision(self):
        return self._layout_rev

    @Property(QObject, constant=True)
    def hoverState(self):
        return self.hover

    @Property(QObject, constant=True)
    def thumbnails(self):
        return self.thumbs

    @Slot(float, float, float, bool, result="QVariantMap")
    def layoutFor(self, length: float, icon: float, gap: float, horizontal: bool) -> dict:
        """The bar's geometry for this length (glass.core.docklayout). Hover never changes it."""
        key = (round(length, 2), round(icon, 2), round(gap, 2), bool(horizontal), self._layout_rev)
        hit = self._layout_cache.get(key)
        if hit is None:
            rows = [{"uid": r["uid"], "kind": r["kind"], "widgetType": r["widgetType"], "section": r["section"],
                     "leaving": bool(r.get("leaving"))} for r in self._model.items()]
            hit = compute_layout(rows, max(0.0, length), icon, gap, horizontal).to_dict()
            self._layout_cache = {key: hit}
        return hit

    # ------------------------------------------------------------------ first run
    def seed_from_launchdeck(self) -> int:
        """Initialise Recently Used from LaunchDeck's usage history (first run only)."""
        if self.registry.meta("seeded_launchdeck"):
            return 0
        added = 0
        by_name = {e.name.lower(): e for e in self.catalog.entries}
        for entry in reversed(launchdeck.usage_history()):
            cat = None
            if entry.is_packaged:
                cat = self.catalog.lookup([aumid_key(entry.target.split("\\", 1)[1])])
            else:
                cat = by_name.get(Path(entry.target).stem.lower())
                if cat is None and entry.target.lower().endswith(".exe"):
                    cat = self.catalog.lookup([exe_key(entry.target)])
            if cat is None:
                continue
            rec = self.registry.ensure(cat.record())
            if (rec.last_launched or 0) < entry.last_used:
                self.registry.record_launch(rec.app_id, entry.last_used)
            added += 1
        self.registry.set_meta("seeded_launchdeck", str(time.time()))
        log.info("seeded %d recent apps from LaunchDeck", added)
        return added

    def seed_default_pins(self) -> None:
        if self.registry.meta("seeded_pins"):
            return
        for wanted in ("microsoft.windows.explorer", "projectglass.controlcenter"):
            cat = self.catalog.lookup([aumid_key(wanted)])
            if cat:
                self.registry.ensure(cat.record())
                self.registry.pin(cat.record().app_id)
        self.registry.set_meta("seeded_pins", "1")

    # ------------------------------------------------------------------ tracking
    def _identify(self, info: appwin.WindowInfo) -> str:
        keys = info.keys()
        app_id = self.registry.resolve(keys)
        if app_id:
            return app_id
        cat = self.catalog.lookup(keys)
        if cat is not None:
            rec = self.registry.ensure(cat.record())
        else:
            name = appwin.file_description(info.exe) if info.exe else info.title
            if info.exe_name == "explorer.exe":
                name = "File Explorer"
            rec = self.registry.ensure(AppRecord(app_id=keys[0], name=name or keys[0], exe=info.exe,
                                                 aumid=info.aumid, launch=info.exe if info.exe_name not in appwin.GENERIC_HOSTS else "",
                                                 icon=info.exe))
        for k in keys:
            if k != rec.app_id:
                self.registry.add_alias(k, rec.app_id)
        return rec.app_id

    @Slot(object)
    def _on_snapshot(self, snap: Snapshot) -> None:
        self._snapshot = snap
        self.refresh()
        self.thumbs.prune()

    def refresh(self) -> None:
        snap = self._snapshot
        if snap is None:
            return
        all_desktops = bool(self.settings.get("dock.all_desktops"))
        garvis = self.tracker.garvis_desktops()
        groups: dict[str, list] = {}
        started: dict[str, float] = {}
        visible_here: dict[str, bool] = {}
        fg_app = ""
        for tw in snap.windows:
            try:
                app_id = self._identify(tw.info)
            except Exception:
                log.exception("identify failed")
                continue
            if tw.desktop_id and tw.desktop_id in garvis and not tw.on_current_desktop:
                continue  # Garvis's own automation desktop is never shown as user apps
            groups.setdefault(app_id, []).append(tw)
            started[app_id] = min(started.get(app_id, tw.started or time.time()), tw.started or time.time())
            if tw.on_current_desktop or all_desktops:
                visible_here[app_id] = True
            if tw.info.hwnd == snap.foreground:
                fg_app = app_id
        running_now = set(groups)
        # launch / close bookkeeping (only on transitions)
        for app_id in running_now - self._running_all:
            when = started.get(app_id) or time.time()
            rec = self.registry.get(app_id)
            if rec is not None and (rec.last_launched or 0) < when - 1:
                self.registry.record_launch(app_id, when)
            self._first_seen.setdefault(app_id, when)
            self._launching.pop(app_id, None)
        for app_id in self._running_all - running_now:
            self.registry.record_closed(app_id)
            self._first_seen.pop(app_id, None)
        self._running_all = running_now
        self._windows = {k: [tw.info for tw in v if tw.on_current_desktop or all_desktops] or [tw.info for tw in v]
                         for k, v in groups.items()}

        records = self.registry.all()
        pinned = {r.app_id for r in records if r.pinned}
        shown: dict[str, RunningApp] = {}
        other_desktop: set[str] = set()
        for app_id, tws in groups.items():
            here = visible_here.get(app_id, False)
            if not here and app_id not in pinned:
                continue
            if not here:
                other_desktop.add(app_id)
            rec = next((r for r in records if r.app_id == app_id), None)
            shown[app_id] = RunningApp(app_id=app_id, name=rec.name if rec else app_id,
                                       windows=tuple(tw.info.hwnd for tw in tws if tw.on_current_desktop or all_desktops) or tuple(tw.info.hwnd for tw in tws),
                                       focused=app_id == fg_app, first_seen=self._first_seen.get(app_id, 0.0),
                                       exe=tws[0].info.exe, aumid=tws[0].info.aumid)
        exclude = running_now - set(shown)
        layout = compute_dock(records, shown, show_recent=bool(self.settings.get("dock.show_recent")),
                              recent_limit=int(self.settings.get("dock.recent_limit")), exclude=exclude)
        name = ""
        if fg_app:
            rec = self.registry.get(fg_app)
            name = rec.name if rec else ""
        if name != self._foreground_name:
            self._foreground_name = name
            self.foregroundNameChanged.emit()
        self._publish(layout, other_desktop)

    def _publish(self, layout, other_desktop: set[str]) -> None:
        rows: list[dict[str, Any]] = []
        base = {k: "" for k in ("appId", "name", "section", "icon", "widgetType", "widgetId")}
        base.update(pinned=False, running=False, focused=False, windowCount=0, launching=False, otherDesktop=False,
                    attention=False)
        if self.settings.get("dock.show_launcher"):
            rows.append({**base, "uid": "launcher", "kind": "launcher", "name": "Search"})
        for item in layout.open:
            rows.append({**base, "uid": "app:" + item.app_id, "kind": "app", "appId": item.app_id, "name": item.name,
                         "section": "open", "pinned": item.pinned, "running": True, "focused": item.focused,
                         "windowCount": item.window_count, "icon": icon_url(item.icon or item.launch or item.exe),
                         "otherDesktop": item.app_id in other_desktop})
        if layout.open and layout.recent:
            rows.append({**base, "uid": "sep:recent", "kind": "separator"})
        for item in layout.recent:
            rows.append({**base, "uid": "app:" + item.app_id, "kind": "app", "appId": item.app_id, "name": item.name,
                         "section": "recent", "pinned": item.pinned, "icon": icon_url(item.icon or item.launch or item.exe),
                         "launching": item.app_id in self._launching})
        widgets = self.settings.get("dock.widgets")
        if widgets:
            rows.append({**base, "uid": "sep:widgets", "kind": "separator"})
            for w in widgets:
                rows.append({**base, "uid": "widget:" + w["id"], "kind": "widget", "widgetType": w["type"],
                             "widgetId": w["id"], "name": w["type"].title()})
        before = [(r["uid"], bool(r.get("leaving"))) for r in self._model.items()]
        current = {r["uid"] for r in self._model.items()}
        departing = current - {r["uid"] for r in rows}
        self._last_rows = rows
        self._model.apply(rows, keep_leaving=departing)
        if departing:
            self._leave_timer.start()
        if before != [(r["uid"], bool(r.get("leaving"))) for r in self._model.items()]:
            self._layout_rev += 1
            self.layoutChanged.emit()
        for r in rows:
            if r["kind"] == "app":
                self.hover.windows_changed("app:" + r["appId"], r["windowCount"])
        self.pinnedChanged.emit()

    def _finish_leaving(self) -> None:
        if any(r.get("leaving") for r in self._model.items()):
            self._model.apply(self._last_rows)
            self._layout_rev += 1
            self.layoutChanged.emit()

    def _on_settings(self, changed: dict) -> None:
        if any(k.startswith("dock.") for k in changed):
            QTimer.singleShot(0, self.hover.apply_settings)
            QTimer.singleShot(0, self.refresh)

    def _expire_launches(self) -> None:
        now = time.time()
        expired = [k for k, t in self._launching.items() if now - t > 10]
        for k in expired:
            self._launching.pop(k, None)
        if expired:
            self.refresh()
        if not self._launching:
            self._launch_timer.stop()

    # ------------------------------------------------------------------ actions (QML)
    @Slot(str)
    def activate(self, app_id: str) -> None:
        wins = self._windows.get(app_id) or []
        if not wins:
            self.launchApp(app_id)
            return
        fg = self._snapshot.foreground if self._snapshot else 0
        if len(wins) == 1 and wins[0].hwnd == fg and not wins[0].minimized:
            launch.minimize(wins[0].hwnd)        # clicking the focused app's only window minimises it
            return
        # Bring the most recently used window forward (EnumWindows order is z-order, top first).
        target = next((w for w in wins if not w.minimized), wins[0])
        launch.activate(target.hwnd)

    @Slot(str)
    def launchApp(self, app_id: str) -> None:
        rec = self.registry.get(app_id)
        if rec is None:
            return
        target = rec.launch or rec.exe
        try:
            launch.launch(target)
        except launch.LaunchError as exc:
            self.toast.emit(str(exc))
            return
        self._launching[app_id] = time.time()
        self._launch_timer.start()
        self.refresh()

    @Slot(str, result="QVariantList")
    def windowsFor(self, app_id: str) -> list:
        return [{"hwnd": w.hwnd, "title": w.title or "(untitled)", "minimized": w.minimized}
                for w in self._windows.get(app_id, [])]

    @Slot(str, result="QVariantList")
    def previewWindows(self, app_id: str) -> list:
        """The app's windows for the hover preview, most recently used first (z-order), with their aspect."""
        fg = self._snapshot.foreground if self._snapshot else 0
        out = []
        for w in self._windows.get(app_id, []):
            _, _, ww, hh = w.rect
            aspect = (ww / hh) if ww > 0 and hh > 0 and not w.minimized else 16 / 10
            out.append({"hwnd": w.hwnd, "title": w.title or "Untitled window", "minimized": w.minimized,
                        "active": w.hwnd == fg, "aspect": max(0.5, min(2.6, aspect))})
        return out

    @Slot(int)
    def focusWindow(self, hwnd: int) -> None:
        launch.activate(hwnd)

    @Slot(int)
    def minimizeWindow(self, hwnd: int) -> None:
        launch.minimize(hwnd)

    @Slot(int)
    def closeWindow(self, hwnd: int) -> None:
        launch.close(hwnd)

    @Slot(str)
    def quitApp(self, app_id: str) -> None:
        for w in self._windows.get(app_id, []):
            launch.close(w.hwnd)

    @Slot()
    def requestKeyboard(self) -> None:
        """The Dock keyboard hotkey: remember which window had focus, then hand the keyboard to the Dock."""
        self._prev_foreground = self._snapshot.foreground if self._snapshot else 0
        self.keyboardRequested.emit()

    @Slot()
    def returnFocus(self) -> None:
        """Leaving keyboard navigation without choosing anything: focus goes back where it was."""
        if self._prev_foreground:
            launch.activate(self._prev_foreground)
        self._prev_foreground = 0

    @Slot(str)
    def pin(self, app_id: str) -> None:
        self.registry.pin(app_id)
        self.refresh()

    @Slot(str)
    def unpin(self, app_id: str) -> None:
        self.registry.unpin(app_id)
        self.refresh()

    @Slot(str, int)
    def movePinned(self, app_id: str, index: int) -> None:
        try:
            self.registry.move_pinned(app_id, index)
        except KeyError:
            return
        self.refresh()

    @Slot(str, str)
    def movePinnedBefore(self, app_id: str, before_app_id: str) -> None:
        """Drag-and-drop: place app_id where before_app_id is in the pinned order ("" = at the end)."""
        order = [r.app_id for r in self.registry.pinned()]
        if app_id not in order:
            return
        order.remove(app_id)
        idx = order.index(before_app_id) if before_app_id in order else len(order)
        order.insert(idx, app_id)
        self.registry.set_pin_order(order)
        self.refresh()

    @Slot("QVariantList")
    def reorderPinned(self, section_order) -> None:
        """Drag-and-drop within one Dock section: these pinned apps, in this order. Pinned apps elsewhere (the other
        section) keep their places in the overall pin order."""
        order = [r.app_id for r in self.registry.pinned()]
        ids = [str(a) for a in section_order if str(a) in order]
        if len(set(ids)) != len(ids):
            return
        for pos, app_id in zip(sorted(order.index(a) for a in ids), ids):
            order[pos] = app_id
        self.registry.set_pin_order(order)
        self.refresh()

    @Slot(str)
    def removeFromDock(self, app_id: str) -> None:
        self.registry.remove_from_dock(app_id)
        self.refresh()

    @Slot(str, result=bool)
    def isPinned(self, app_id: str) -> bool:
        rec = self.registry.get(app_id)
        return bool(rec and rec.pinned)

    # ------------------------------------------------------------------ catalog (Control Center)
    def add_from_catalog(self, parsing: str) -> dict:
        entry = next((e for e in self.catalog.entries if e.parsing == parsing), None)
        if entry is None:
            return {"ok": False, "error": "That app is no longer installed."}
        rec = self.registry.add_to_dock(entry.record())
        for k in entry.keys():
            if k != rec.app_id:
                self.registry.add_alias(k, rec.app_id)
        self.refresh()
        return {"ok": True, "app_id": rec.app_id}

    def dock_apps(self) -> list[dict]:
        """Pinned apps (in order) plus recent ones, for the Control Center's Applications page."""
        out = []
        for r in self.registry.pinned():
            out.append({"app_id": r.app_id, "name": r.name, "pinned": True, "icon": r.icon or r.launch or r.exe,
                        "last_launched": r.last_launched, "running": r.app_id in self._running_all})
        for r in sorted((r for r in self.registry.all() if not r.pinned and r.last_launched and not r.hidden),
                        key=lambda r: -(r.last_launched or 0))[:40]:
            out.append({"app_id": r.app_id, "name": r.name, "pinned": False, "icon": r.icon or r.launch or r.exe,
                        "last_launched": r.last_launched, "running": r.app_id in self._running_all})
        return out
