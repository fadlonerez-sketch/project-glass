"""UI Automation client (comtypes, CUIAutomation8) used by the engine.

Threading: COM is initialised as MTA on every worker thread (`mta_init`). In the MTA, UIA objects may be
used from any MTA thread, so the engine runs requests on a small pool of MTA threads. Connection and
transaction timeouts keep a hung target from blocking a worker for long.

Element references are "<hwnd hex>:<runtimeId parts>" and are resolved by searching the window subtree
for that exact RuntimeId -- a missing element is reported as stale, never replaced by another one.
"""
from __future__ import annotations

import ctypes
import re
import threading
import time
from collections import OrderedDict

import comtypes
import comtypes.client
from comtypes.automation import VARIANT, VT_ARRAY, VT_I4

from glass.automation import win
from glass.core.ipc import ErrorCode, ProtocolError

_mod = None
_mod_lock = threading.Lock()


def mod():
    global _mod
    with _mod_lock:
        if _mod is None:
            _mod = comtypes.client.GetModule("UIAutomationCore.dll")
    return _mod


_tls = threading.local()


def mta_init() -> None:
    if not getattr(_tls, "com", False):
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # already initialised on this thread
        _tls.com = True


CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit",
    50005: "Hyperlink", 50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu",
    50010: "MenuBar", 50011: "MenuItem", 50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar",
    50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab", 50019: "TabItem", 50020: "Text",
    50021: "ToolBar", 50022: "ToolTip", 50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group",
    50027: "Thumb", 50028: "DataGrid", 50029: "DataItem", 50030: "Document", 50031: "SplitButton",
    50032: "Window", 50033: "Pane", 50034: "Header", 50035: "HeaderItem", 50036: "Table",
    50037: "TitleBar", 50038: "Separator", 50039: "SemanticZoom", 50040: "AppBar",
}
TYPE_IDS = {v.lower(): k for k, v in CONTROL_TYPES.items()}

# property ids
P_RUNTIME, P_RECT, P_PID, P_TYPE, P_NAME = 30000, 30001, 30002, 30003, 30005
P_FOCUS, P_FOCUSABLE, P_ENABLED, P_AID, P_CLASS = 30008, 30009, 30010, 30011, 30012
P_PASSWORD, P_HWND, P_OFFSCREEN, P_FRAMEWORK = 30019, 30020, 30022, 30024
A_EXPAND, A_INVOKE, A_RANGE, A_SCROLL, A_SCROLLITEM, A_SELITEM = 30028, 30031, 30033, 30034, 30035, 30036
A_TEXT, A_TOGGLE, A_VALUE, A_LEGACY = 30040, 30041, 30043, 30090
P_VALUE, P_VALUE_RO, P_RANGE_VALUE = 30045, 30046, 30047
P_VSCROLL, P_HSCROLL = 30055, 30053
P_EXPAND_STATE, P_SELECTED, P_TOGGLE_STATE = 30070, 30079, 30086
P_LEGACY_ACTION = 30100

CACHE_PROPS = [P_RUNTIME, P_RECT, P_PID, P_TYPE, P_NAME, P_FOCUS, P_FOCUSABLE, P_ENABLED, P_AID, P_CLASS,
               P_PASSWORD, P_HWND, P_OFFSCREEN, A_EXPAND, A_INVOKE, A_RANGE, A_SCROLL, A_SCROLLITEM, A_SELITEM,
               A_TEXT, A_TOGGLE, A_VALUE, A_LEGACY, P_VALUE, P_VALUE_RO, P_RANGE_VALUE, P_EXPAND_STATE,
               P_SELECTED, P_TOGGLE_STATE]

# pattern ids
PAT_INVOKE, PAT_SELECTION, PAT_VALUE, PAT_RANGE, PAT_SCROLL, PAT_EXPAND = 10000, 10001, 10002, 10003, 10004, 10005
PAT_SELITEM, PAT_TEXT, PAT_TOGGLE, PAT_SCROLLITEM, PAT_LEGACY = 10010, 10014, 10015, 10017, 10018

UIA_E_ELEMENTNOTAVAILABLE = -2147220991  # 0x80040201
UIA_E_ELEMENTNOTENABLED = -2147220992    # 0x80040200
UIA_E_NOTSUPPORTED = -2147220990         # 0x80040202 (not exact on every OS; we fall back to message)
E_ACCESSDENIED = -2147024891
# Toolkits (Qt in particular) expose a ValuePattern on buttons, windows and title bars; offering
# set_value there would mislead clients, so it is listed only where text entry makes sense.
VALUE_TYPES = {"Edit", "ComboBox", "Document", "Spinner", "DataItem", "Custom", "ListItem", "TreeItem",
               "Pane", "Group"}
INTERACTIVE = {"Button", "CheckBox", "ComboBox", "Edit", "Hyperlink", "ListItem", "MenuItem", "RadioButton",
               "Slider", "Spinner", "TabItem", "TreeItem", "SplitButton", "DataItem", "Document",
               "HeaderItem", "ScrollBar", "List", "Tree", "Tab", "Menu"}


def _hr(exc) -> int:
    hr = getattr(exc, "hresult", None)
    if hr is None and exc.args:
        hr = exc.args[0] if isinstance(exc.args[0], int) else None
    return hr or 0


class Uia:
    """One shared IUIAutomation; methods may run on any MTA thread."""

    def __init__(self) -> None:
        mta_init()
        m = mod()
        self.m = m
        self.auto = comtypes.client.CreateObject(m.CUIAutomation8, interface=m.IUIAutomation6)
        try:
            self.auto.ConnectionTimeout = 3000
            self.auto.TransactionTimeout = 8000
        except Exception:
            pass
        self.control_view = self.auto.ControlViewCondition
        self.true_cond = self.auto.CreateTrueCondition()
        self.cache = self._make_cache(self.control_view)
        self._refs: OrderedDict[str, object] = OrderedDict()
        self._refs_lock = threading.Lock()

    def _make_cache(self, tree_filter):
        cache = self.auto.CreateCacheRequest()
        for p in CACHE_PROPS:
            cache.AddProperty(p)
        cache.TreeFilter = tree_filter
        return cache

    # ------------------------------------------------------------------ refs
    @staticmethod
    def parse_ref(ref: str) -> tuple[int, list[int]]:
        try:
            h, rid = ref.split(":", 1)
            return int(h, 16), [int(x) for x in rid.split(".") if x != ""]
        except (ValueError, AttributeError):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, f"'{ref}' is not an element reference")

    @staticmethod
    def make_ref(hwnd: int, runtime_id) -> str:
        return f"{hwnd:x}:" + ".".join(str(int(x)) for x in (runtime_id or ()))

    def _remember(self, ref: str, el) -> None:
        with self._refs_lock:
            self._refs[ref] = el
            self._refs.move_to_end(ref)
            while len(self._refs) > 6000:
                self._refs.popitem(last=False)

    def _runtime_condition(self, rid: list[int]):
        sa = comtypes.safearray._midlSAFEARRAY(ctypes.c_int).create(rid)
        v = VARIANT()
        v._.c_void_p = ctypes.cast(sa, ctypes.c_void_p).value
        v.vt = VT_ARRAY | VT_I4
        return self.auto.CreatePropertyCondition(P_RUNTIME, v)

    def window_root(self, hwnd: int):
        if not win.is_window(hwnd):
            raise ProtocolError(ErrorCode.STALE_REFERENCE, "That window no longer exists. List the windows again.",
                                {"hwnd": hwnd})
        try:
            return self.auto.ElementFromHandleBuildCache(hwnd, self.cache)
        except comtypes.COMError as exc:
            raise self._com_error(exc, hwnd)

    def resolve(self, ref: str):
        """The live element for `ref` (cached with fresh properties), or a stale_reference error."""
        hwnd, rid = self.parse_ref(ref)
        if not win.is_window(hwnd):
            raise ProtocolError(ErrorCode.STALE_REFERENCE,
                                "The window of that element has closed; nothing was done. Inspect again.",
                                {"ref": ref})
        with self._refs_lock:
            cached = self._refs.get(ref)
        if cached is not None:
            try:
                el = cached.BuildUpdatedCache(self.cache)
                if list(el.GetCachedPropertyValue(P_RUNTIME) or ()) == rid:
                    return el
            except comtypes.COMError:
                pass
        root = self.window_root(hwnd)
        if list(root.GetCachedPropertyValue(P_RUNTIME) or ()) == rid:
            return root
        try:
            el = root.FindFirstBuildCache(7, self._runtime_condition(rid), self.cache)  # TreeScope_Subtree
        except comtypes.COMError as exc:
            raise self._com_error(exc, hwnd)
        if not el:
            raise ProtocolError(ErrorCode.STALE_REFERENCE,
                                "That element no longer exists (the UI changed). Nothing was done -- "
                                "inspect the window again and use a fresh reference.", {"ref": ref})
        self._remember(ref, el)
        return el

    def _com_error(self, exc, hwnd: int | None = None) -> ProtocolError:
        hr = _hr(exc)
        if hr == UIA_E_ELEMENTNOTAVAILABLE:
            return ProtocolError(ErrorCode.STALE_REFERENCE, "The element is no longer available.")
        if hr == E_ACCESSDENIED or (hwnd and win.is_elevated(win.pid_of(hwnd))):
            return ProtocolError(ErrorCode.ELEVATED_TARGET,
                                 "Windows blocks access: the window runs as administrator and Glass does not.")
        if hr == UIA_E_ELEMENTNOTENABLED:
            return ProtocolError(ErrorCode.UNSUPPORTED, "The element is disabled.")
        if hr in (-2147220989, -2146233083):  # UIA_E_TIMEOUT / COR_E_TIMEOUT
            return ProtocolError(ErrorCode.TIMEOUT, "The application did not respond to UI Automation in time.")
        return ProtocolError(ErrorCode.INTERNAL, f"UI Automation error: {exc}")

    # ------------------------------------------------------------------ node building
    @staticmethod
    def _get(el, prop):
        try:
            v = el.GetCachedPropertyValue(prop)
        except comtypes.COMError:
            return None
        if isinstance(v, comtypes.IUnknown) or type(v).__name__.startswith("POINTER"):
            return None  # UIA's ReservedNotSupportedValue / ReservedMixedAttributeValue sentinels
        return v

    def node(self, el, hwnd: int) -> dict:
        g = lambda p: self._get(el, p)  # noqa: E731
        rid = g(P_RUNTIME) or ()
        ref = self.make_ref(hwnd, rid)
        self._remember(ref, el)
        ctype = CONTROL_TYPES.get(g(P_TYPE) or 0, "Unknown")
        out: dict = {"ref": ref, "type": ctype}
        name = (g(P_NAME) or "").strip()
        if name:
            out["name"] = name[:300]
        aid = g(P_AID) or ""
        if aid:
            out["aid"] = aid[:200]
        cls = g(P_CLASS) or ""
        if cls:
            out["cls"] = cls[:120]
        password = bool(g(P_PASSWORD))
        has_value = bool(g(A_VALUE))
        if has_value and not password:
            val = g(P_VALUE)
            if val not in (None, ""):
                out["value"] = str(val)[:500]
        elif g(A_RANGE):
            rv = g(P_RANGE_VALUE)
            if rv is not None:
                out["value"] = rv
        states = []
        if not g(P_ENABLED):
            states.append("disabled")
        if g(P_FOCUSABLE):
            states.append("focusable")
        if g(P_FOCUS):
            states.append("focused")
        if g(P_OFFSCREEN):
            states.append("offscreen")
        if g(A_SELITEM) and g(P_SELECTED):
            states.append("selected")
        if g(A_TOGGLE):
            ts = g(P_TOGGLE_STATE)
            states.append({0: "unchecked", 1: "checked", 2: "indeterminate"}.get(ts, "unchecked"))
        expand_state = g(P_EXPAND_STATE) if g(A_EXPAND) else None
        if expand_state is not None:
            states.append({0: "collapsed", 1: "expanded", 2: "partially_expanded", 3: "leaf"}.get(expand_state, ""))
        if has_value and g(P_VALUE_RO):
            states.append("readonly")
        if password:
            states.append("password")
        if states:
            out["states"] = [s for s in states if s]
        actions = self.actions_of(el, ctype, expand_state)
        if actions:
            out["actions"] = actions
        r = g(P_RECT)
        if r is not None:
            if hasattr(r, "left"):
                x, y, w, h = r.left, r.top, r.right - r.left, r.bottom - r.top
            else:  # the cached VARIANT form is (left, top, width, height)
                x, y, w, h = (list(r) + [0, 0, 0, 0])[:4]
            if w > 0 and h > 0:
                out["rect"] = [int(x), int(y), int(w), int(h)]
        return out

    def actions_of(self, el, ctype: str | None = None, expand_state=None) -> list[str]:
        g = lambda p: self._get(el, p)  # noqa: E731
        acts = []
        if g(A_INVOKE):
            acts.append("invoke")
        if g(A_TOGGLE):
            acts.append("toggle")
        if g(A_SELITEM):
            acts.append("select")
        if g(A_EXPAND):
            if expand_state is None:
                expand_state = g(P_EXPAND_STATE)
            if expand_state in (0, 2, None):
                acts.append("expand")
            if expand_state in (1, 2, None):
                acts.append("collapse")
        if g(A_VALUE) and not g(P_VALUE_RO) and (ctype or "") in VALUE_TYPES and not _qt_container(el, ctype):
            acts.append("set_value")
        if g(A_RANGE):
            acts.append("set_range")
        if g(A_SCROLL):
            acts.append("scroll")
        if g(A_SCROLLITEM):
            acts.append("scroll_into_view")
        if g(P_FOCUSABLE):
            acts.append("focus")
        if g(A_LEGACY) and not acts and (ctype or "") in INTERACTIVE:
            acts.append("default_action")
        return acts

    # ------------------------------------------------------------------ reading
    def children(self, el):
        try:
            arr = el.FindAllBuildCache(2, self.control_view, self.cache)  # TreeScope_Children
        except comtypes.COMError:
            return []
        return [arr.GetElement(i) for i in range(arr.Length)] if arr else []

    def tree(self, el, hwnd: int, depth: int, max_nodes: int, include_offscreen: bool,
             interactive_only: bool = False, deadline_s: float = 8.0) -> tuple[dict, int, bool]:
        deadline = time.monotonic() + deadline_s
        count = 0
        truncated = False

        def build(e, d) -> dict | None:
            nonlocal count, truncated
            n = self.node(e, hwnd)
            count += 1
            if d >= depth:
                kids = self.children(e)
                if kids:
                    n["more"] = len(kids)
                    truncated = True
                return n
            kids = self.children(e)
            out = []
            for i, k in enumerate(kids):
                if count >= max_nodes or time.monotonic() > deadline:
                    n["more"] = len(kids) - i
                    truncated = True
                    break
                if not include_offscreen and self._get(k, P_OFFSCREEN) and not self._get(k, P_FOCUS):
                    # Off-screen subtrees (scrolled away, collapsed) are skipped but counted.
                    n["more"] = n.get("more", 0) + 1
                    continue
                c = build(k, d + 1)
                if c is not None:
                    out.append(c)
            if out:
                n["children"] = out
            return n

        root = build(el, 0)
        if interactive_only:
            root = _prune(root) or root
        return root, count, truncated

    def find(self, scope_el, hwnd: int, name: str | None, match: str, ctype: str | None, aid: str | None,
             cls: str | None, max_results: int) -> tuple[list[dict], int]:
        conds = [self.control_view]
        if ctype:
            tid = TYPE_IDS.get(ctype.lower())
            if tid is None:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown control type '{ctype}'",
                                    {"known": sorted(CONTROL_TYPES.values())})
            conds.append(self.auto.CreatePropertyCondition(P_TYPE, tid))
        if aid:
            conds.append(self.auto.CreatePropertyCondition(P_AID, aid))
        if cls:
            conds.append(self.auto.CreatePropertyCondition(P_CLASS, cls))
        regex = None
        if name:
            if match == "exact":
                conds.append(self.auto.CreatePropertyConditionEx(P_NAME, name, 1))  # IgnoreCase
            elif match == "regex":
                try:
                    regex = re.compile(name, re.IGNORECASE)
                except re.error as exc:
                    raise ProtocolError(ErrorCode.INVALID_PARAMS, f"bad regex: {exc}")
            else:
                conds.append(self.auto.CreatePropertyConditionEx(P_NAME, name, 3))  # IgnoreCase|Substring
        cond = conds[0]
        for c in conds[1:]:
            cond = self.auto.CreateAndCondition(cond, c)
        try:
            arr = scope_el.FindAllBuildCache(4, cond, self.cache)  # TreeScope_Descendants
        except comtypes.COMError as exc:
            raise self._com_error(exc, hwnd)
        els = [arr.GetElement(i) for i in range(arr.Length)] if arr else []
        if regex is not None:
            els = [e for e in els if regex.search(self._get(e, P_NAME) or "")]
        total = len(els)
        return [self.node(e, hwnd) for e in els[:max_results]], total

    def text_of(self, el, limit: int = 4000) -> str | None:
        if not self._get(el, A_TEXT) or self._get(el, P_PASSWORD):
            return None
        try:
            tp = el.GetCurrentPattern(PAT_TEXT).QueryInterface(self.m.IUIAutomationTextPattern)
            return (tp.DocumentRange.GetText(limit) or "")[:limit]
        except comtypes.COMError:
            return None

    def focused(self) -> dict | None:
        try:
            el = self.auto.GetFocusedElementBuildCache(self.cache)
        except comtypes.COMError:
            return None
        if not el:
            return None
        hwnd = self._get(el, P_HWND) or 0
        top = win.root_window(hwnd) if hwnd else 0
        if not top:
            pid = self._get(el, P_PID) or 0
            top = next((h for h in win.top_level_windows() if win.pid_of(h) == pid), 0)
        n = self.node(el, top)
        return {k: n[k] for k in ("ref", "type", "name") if k in n}

    def framework(self, hwnd: int) -> str:
        try:
            root = self.auto.ElementFromHandle(hwnd)
            return root.GetCurrentPropertyValue(P_FRAMEWORK) or ""
        except comtypes.COMError:
            return ""

    def coverage(self, hwnd: int, budget: int = 1500, deadline_s: float = 4.0) -> dict:
        root = self.window_root(hwnd)
        deadline = time.monotonic() + deadline_s
        queue = [root]
        controls = named = actionable = 0
        while queue and controls < budget and time.monotonic() < deadline:
            el = queue.pop(0)
            controls += 1
            if (self._get(el, P_NAME) or "").strip():
                named += 1
            ctype = CONTROL_TYPES.get(self._get(el, P_TYPE) or 0, "")
            if self.actions_of(el, ctype):
                actionable += 1
            queue.extend(self.children(el))
        ratio = named / controls if controls else 0
        if controls <= 2 or actionable == 0 and named <= 1:
            level, note = "none", ("This window exposes almost no UI Automation information (custom-drawn, "
                                   "a game, or a canvas). Semantic control is not possible here.")
        elif actionable == 0:
            level, note = "minimal", "Only static content is exposed; no controls can be operated semantically."
        elif actionable >= 3 and ratio >= 0.5:
            level, note = "full", "Controls are named and operable."
        else:
            level, note = "partial", ("Some regions are unnamed or not operable (common in Chromium/Electron "
                                      "before accessibility warms up). Expect gaps.")
        return {"level": level, "controls": controls, "named": named, "actionable": actionable,
                "note": note, "sampled": bool(queue)}

    # ------------------------------------------------------------------ state for verification
    def snapshot(self, el) -> dict:
        try:
            e = el.BuildUpdatedCache(self.cache)
        except comtypes.COMError:
            return {"_gone": True}
        g = lambda p: self._get(e, p)  # noqa: E731
        snap = {"name": (g(P_NAME) or "").strip(), "enabled": bool(g(P_ENABLED))}
        if g(A_VALUE) and not g(P_PASSWORD):
            snap["value"] = g(P_VALUE)
        if g(A_TOGGLE):
            snap["toggle"] = {0: "unchecked", 1: "checked", 2: "indeterminate"}.get(g(P_TOGGLE_STATE))
        if g(A_EXPAND):
            snap["expand"] = {0: "collapsed", 1: "expanded", 2: "partially_expanded", 3: "leaf"}.get(g(P_EXPAND_STATE))
        if g(A_SELITEM):
            snap["selected"] = bool(g(P_SELECTED))
        if g(A_RANGE):
            snap["range"] = g(P_RANGE_VALUE)
        if g(A_SCROLL):
            try:
                snap["scroll"] = [round(e.GetCurrentPropertyValue(P_HSCROLL), 1), round(e.GetCurrentPropertyValue(P_VSCROLL), 1)]
            except comtypes.COMError:
                pass
        return snap

    # ------------------------------------------------------------------ patterns
    def pattern(self, el, pid: int, iface: str):
        try:
            p = el.GetCurrentPattern(pid)
        except comtypes.COMError as exc:
            raise self._com_error(exc)
        if not p:
            return None
        return p.QueryInterface(getattr(self.m, iface))


def _qt_container(el, ctype) -> bool:
    # Qt's scroll areas/groups report a writable ValuePattern that does nothing useful.
    return ctype in ("Pane", "Group") and not (Uia._get(el, P_FOCUSABLE) and Uia._get(el, A_TEXT))


def _prune(n: dict) -> dict | None:
    kids = [c for c in (_prune(k) for k in n.get("children", [])) if c]
    keep = bool(n.get("actions")) or (n.get("type") == "Text" and n.get("name"))
    if kids:
        n = dict(n, children=kids)
    elif "children" in n:
        n = {k: v for k, v in n.items() if k != "children"}
    return n if keep or kids else None
