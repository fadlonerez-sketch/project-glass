"""UI Automation event subscriptions (watch.subscribe).

Handlers are comtypes COM objects; UIA calls them on its own MTA threads. They only read cached
properties of the sender and hand a small dict to `sink(subscription_id, event)` -- never call back into
the target synchronously. Bursty events (structure/property changes) are rate-limited per subscription.
"""
from __future__ import annotations

import itertools
import threading
import time

import comtypes

from glass.automation import uia as U
from glass.automation import win

EVENT_TYPES = {"window_opened", "window_closed", "focus_changed", "structure_changed", "property_changed", "invoked"}
WATCHED_PROPS = {U.P_NAME: "name", U.P_VALUE: "value", U.P_TOGGLE_STATE: "toggle",
                 U.P_EXPAND_STATE: "expand", U.P_SELECTED: "selected", U.P_ENABLED: "enabled"}
_ids = itertools.count(1)


def _handler_classes(m):
    class AutomationHandler(comtypes.COMObject):
        _com_interfaces_ = [m.IUIAutomationEventHandler]

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        def IUIAutomationEventHandler_HandleAutomationEvent(self, sender, event_id):
            try:
                self.cb("automation", sender, event_id)
            except Exception:
                pass
            return 0

    class FocusHandler(comtypes.COMObject):
        _com_interfaces_ = [m.IUIAutomationFocusChangedEventHandler]

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        def IUIAutomationFocusChangedEventHandler_HandleFocusChangedEvent(self, sender):
            try:
                self.cb("focus", sender, None)
            except Exception:
                pass
            return 0

    class StructureHandler(comtypes.COMObject):
        _com_interfaces_ = [m.IUIAutomationStructureChangedEventHandler]

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        def IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent(self, sender, change_type, runtime_id):
            try:
                self.cb("structure", sender, change_type)
            except Exception:
                pass
            return 0

    class PropertyHandler(comtypes.COMObject):
        _com_interfaces_ = [m.IUIAutomationPropertyChangedEventHandler]

        def __init__(self, cb):
            super().__init__()
            self.cb = cb

        def IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(self, sender, prop_id, new_value):
            try:
                self.cb("property", sender, (prop_id, new_value))
            except Exception:
                pass
            return 0

    return AutomationHandler, FocusHandler, StructureHandler, PropertyHandler


class Subscription:
    def __init__(self, sid: str, session: str, hwnd: int | None, events: set[str]):
        self.id = sid
        self.session = session
        self.hwnd = hwnd
        self.pid = win.pid_of(hwnd) if hwnd else 0
        self.events = events
        self.registrations: list[tuple] = []
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, kind: str, min_gap: float) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last.get(kind, 0.0) < min_gap:
                return False
            self._last[kind] = now
            return True


class EventManager:
    def __init__(self, uia: U.Uia, sink):
        self.uia = uia
        self.sink = sink  # sink(subscription, event_dict), thread-safe
        self.subs: dict[str, Subscription] = {}
        self._lock = threading.Lock()
        self._classes = _handler_classes(uia.m)

    def subscribe(self, session: str, hwnd: int | None, events: list[str]) -> Subscription:
        U.mta_init()
        evs = set(events or [])
        bad = evs - EVENT_TYPES
        if bad or not evs:
            raise ValueError(f"unknown or missing event types: {sorted(bad) or 'none given'}")
        sub = Subscription(f"s{next(_ids)}", session, hwnd, evs)
        Auto, Focus, Struct, Prop = self._classes
        a = self.uia.auto
        scope_el = self.uia.window_root(hwnd) if hwnd else a.GetRootElement()

        def cb(kind, sender, extra):
            self._dispatch(sub, kind, sender, extra)

        try:
            if "window_opened" in evs:
                h = Auto(cb)
                a.AddAutomationEventHandler(20016, a.GetRootElement(), 7, None, h)
                sub.registrations.append(("auto", 20016, a.GetRootElement(), h))
            if "window_closed" in evs:
                h = Auto(cb)
                target = scope_el if hwnd else a.GetRootElement()
                a.AddAutomationEventHandler(20017, target, 7, None, h)
                sub.registrations.append(("auto", 20017, target, h))
            if "invoked" in evs:
                h = Auto(cb)
                a.AddAutomationEventHandler(20009, scope_el, 7, None, h)
                sub.registrations.append(("auto", 20009, scope_el, h))
            if "focus_changed" in evs:
                h = Focus(cb)
                a.AddFocusChangedEventHandler(None, h)
                sub.registrations.append(("focus", h))
            if "structure_changed" in evs:
                h = Struct(cb)
                a.AddStructureChangedEventHandler(scope_el, 7, None, h)
                sub.registrations.append(("struct", scope_el, h))
            if "property_changed" in evs:
                h = Prop(cb)
                props = list(WATCHED_PROPS)
                arr = (ctypes_int_array(props))
                a.AddPropertyChangedEventHandlerNativeArray(scope_el, 7, None, h, arr, len(props))
                sub.registrations.append(("prop", scope_el, h))
        except Exception:
            self._remove_registrations(sub)
            raise
        with self._lock:
            self.subs[sub.id] = sub
        return sub

    def _dispatch(self, sub: Subscription, kind: str, sender, extra) -> None:
        U.mta_init()
        ev: dict = {"subscription": sub.id, "time": time.time()}
        try:
            name = sender.CurrentName or ""
        except Exception:
            name = ""
        try:
            pid = sender.CurrentProcessId
        except Exception:
            pid = 0
        try:
            native = sender.CurrentNativeWindowHandle or 0
        except Exception:
            native = 0
        if kind == "automation":
            ev["type"] = {20016: "window_opened", 20017: "window_closed", 20009: "invoked"}.get(extra, str(extra))
            if ev["type"] not in sub.events:
                return
            if sub.hwnd and ev["type"] == "window_opened" and pid != sub.pid:
                return
            if native:
                ev["hwnd"] = native
        elif kind == "focus":
            ev["type"] = "focus_changed"
            if sub.hwnd and pid != sub.pid:
                return
            if not sub.allow("focus", 0.05):
                return
        elif kind == "structure":
            ev["type"] = "structure_changed"
            ev["change"] = {0: "child_added", 1: "child_removed", 2: "children_invalidated",
                            3: "children_bulk_added", 4: "children_bulk_removed", 5: "children_reordered"}.get(extra, str(extra))
            if not sub.allow("structure", 0.15):
                return
        elif kind == "property":
            prop_id, value = extra
            ev["type"] = "property_changed"
            ev["property"] = WATCHED_PROPS.get(prop_id, str(prop_id))
            if isinstance(value, (str, int, float, bool)) or value is None:
                if prop_id == U.P_TOGGLE_STATE:
                    value = {0: "unchecked", 1: "checked", 2: "indeterminate"}.get(value, value)
                if prop_id == U.P_EXPAND_STATE:
                    value = {0: "collapsed", 1: "expanded", 2: "partially_expanded", 3: "leaf"}.get(value, value)
                ev["value"] = value if not isinstance(value, str) else value[:300]
            if not sub.allow("property:" + ev["property"], 0.03):
                return
        if name:
            ev["name"] = name[:200]
        if sub.hwnd:
            ev.setdefault("hwnd", sub.hwnd)
        try:
            rid = sender.GetRuntimeId()
            top = sub.hwnd or (win.root_window(native) if native else 0)
            if rid and top:
                ev["ref"] = U.Uia.make_ref(top, rid)
        except Exception:
            pass
        self.sink(sub, ev)

    def unsubscribe(self, sid: str, session: str | None = None) -> bool:
        with self._lock:
            sub = self.subs.get(sid)
            if not sub or (session and sub.session != session):
                return False
            del self.subs[sid]
        U.mta_init()
        self._remove_registrations(sub)
        return True

    def drop_session(self, session: str) -> None:
        with self._lock:
            ids = [s.id for s in self.subs.values() if s.session == session]
        for sid in ids:
            self.unsubscribe(sid)

    def _remove_registrations(self, sub: Subscription) -> None:
        a = self.uia.auto
        for reg in sub.registrations:
            try:
                if reg[0] == "auto":
                    a.RemoveAutomationEventHandler(reg[1], reg[2], reg[3])
                elif reg[0] == "focus":
                    a.RemoveFocusChangedEventHandler(reg[1])
                elif reg[0] == "struct":
                    a.RemoveStructureChangedEventHandler(reg[1], reg[2])
                elif reg[0] == "prop":
                    a.RemovePropertyChangedEventHandler(reg[1], reg[2])
            except Exception:
                pass
        sub.registrations.clear()


def ctypes_int_array(values):
    import ctypes
    return (ctypes.c_int * len(values))(*values)
