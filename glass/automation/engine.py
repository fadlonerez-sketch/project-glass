"""Method implementations for the Computer Control protocol (see docs/PROTOCOL.md).

`Engine.handle()` runs on an MTA worker thread. It enforces scopes, the emergency stop, the deny list
and self-protection, audits every state-changing call, and returns plain JSON-able results.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

import comtypes

from glass import __version__
from glass.automation import uia as U
from glass.automation import win
from glass.automation.events import EventManager
from glass.automation.inputs import InputBackend, parse_keys
from glass.automation.store import ALL_SCOPES, Store
from glass.core.ipc import ErrorCode, ProtocolError

METHOD_SCOPES = {
    "engine.status": None,
    "apps.list": "inspect", "windows.list": "inspect", "windows.find": "inspect", "window.inspect": "inspect",
    "tree.get": "inspect", "element.find": "inspect", "element.get": "inspect",
    "watch.subscribe": "inspect", "watch.unsubscribe": "inspect", "wait.for": "inspect",
    "element.act": "act",  # refined per action below
    "input.keys": "input",
    "notify.post": "inspect",
    "window.focus": "windows", "window.set_state": "windows", "window.move": "windows",
}
ACTION_SCOPES = {
    "invoke": "act", "toggle": "act", "select": "act", "add_to_selection": "act", "remove_from_selection": "act",
    "expand": "act", "collapse": "act", "scroll": "act", "scroll_into_view": "act", "focus": "act",
    "set_range": "act", "default_action": "act", "set_value": "text", "click": "input", "type_text": "input",
}
STATE_CHANGING = {"element.act", "input.keys", "window.focus", "window.set_state", "window.move"}


@dataclass
class Ctx:
    session: str
    client: str
    scopes: list[str]
    pid: int = 0
    notify: object = None           # notify(method, params) -> to this session
    extra: dict = field(default_factory=dict)


def _int(params: dict, key: str, default=None, lo=None, hi=None, required=False):
    v = params.get(key, default)
    if v is None:
        if required:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, f"'{key}' is required")
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ProtocolError(ErrorCode.INVALID_PARAMS, f"'{key}' must be an integer")
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


class Engine:
    def __init__(self, store: Store, input_backend: InputBackend, activity=None, event_sink=None):
        self.store = store
        self.input = input_backend
        self.activity = activity or (lambda **kw: None)   # activity(client=..., method=..., ...) thread-safe
        self.started = time.time()
        U.mta_init()
        self.uia = U.Uia()
        self.events = EventManager(self.uia, event_sink or (lambda sub, ev: None))
        self.client_count = lambda: 0
        self.notify_sink = lambda note: None                # set by the server: broadcast to owner subscribers
        self._notes: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ entry point
    def handle(self, ctx: Ctx, method: str, params: dict):
        U.mta_init()
        if not isinstance(params, dict):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "params must be an object")
        fn = getattr(self, "m_" + method.replace(".", "_"), None)
        if fn is None or method.startswith("admin.") or method == "hello":
            raise ProtocolError(ErrorCode.UNKNOWN_METHOD, f"unknown method '{method}'")
        scope = METHOD_SCOPES.get(method)
        if method == "element.act":
            scope = ACTION_SCOPES.get(str(params.get("action", "")))
            if scope is None:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown action '{params.get('action')}'",
                                    {"actions": sorted(ACTION_SCOPES)})
        if scope and scope not in ctx.scopes:
            self._audit(ctx, method, params, "forbidden", f"missing scope {scope}")
            raise ProtocolError(ErrorCode.FORBIDDEN_SCOPE,
                                f"Glass has not granted this client the '{scope}' permission "
                                "(change it in Control Center > Garvis).", {"scope": scope})
        if method != "engine.status" and self.store.stopped():
            raise ProtocolError(ErrorCode.STOPPED, "Computer control is paused by the emergency stop. "
                                "The user can resume it in Project Glass.")
        try:
            result = fn(ctx, params)
        except ProtocolError as exc:
            if method in STATE_CHANGING:
                self._audit(ctx, method, params, exc.code, exc.message)
            raise
        except comtypes.COMError as exc:
            err = self.uia._com_error(exc)
            if method in STATE_CHANGING:
                self._audit(ctx, method, params, err.code, err.message)
            raise err
        if method in STATE_CHANGING:
            self._audit(ctx, method, params, "ok", result.get("method", "") if isinstance(result, dict) else "")
        return result

    # ------------------------------------------------------------------ policy
    def check_target(self, ctx: Ctx, hwnd: int, acting: bool) -> dict:
        if not win.is_window(hwnd):
            raise ProtocolError(ErrorCode.STALE_REFERENCE, "That window no longer exists.", {"hwnd": hwnd})
        pid = win.pid_of(hwnd)
        exe = os.path.basename(win.image_of(pid)).lower()
        if exe and exe in set(self.store.deny_list()):
            raise ProtocolError(ErrorCode.DENIED_APP,
                                f"'{exe}' is on the Project Glass deny list; it cannot be inspected or controlled.",
                                {"exe": exe})
        if acting:
            if win.is_protected(hwnd):
                raise ProtocolError(ErrorCode.DENIED_APP,
                                    "Project Glass's own windows (Shell, Control Center) cannot be controlled by a client.")
            if ctx.pid and pid == ctx.pid:
                raise ProtocolError(ErrorCode.DENIED_APP,
                                    "A client cannot control its own windows (this protects its approval prompts).")
            if win.is_elevated(pid):
                raise ProtocolError(ErrorCode.ELEVATED_TARGET,
                                    "That window runs as administrator; Windows blocks a normal process from driving it.")
        return {"pid": pid, "exe": exe}

    def _audit(self, ctx: Ctx, method: str, params: dict, outcome: str, detail: str = "") -> None:
        target = ""
        hwnd = params.get("hwnd")
        ref = params.get("ref")
        if ref and isinstance(ref, str):
            try:
                hwnd = U.Uia.parse_ref(ref)[0]
            except ProtocolError:
                pass
        info = {}
        if isinstance(hwnd, int) and win.is_window(hwnd):
            info = {"app": win.friendly_name(win.image_of(win.pid_of(hwnd))), "title": win.title(hwnd)[:120]}
            target = f"{info['app']} — {info['title']}"
        action = params.get("action") or params.get("state") or params.get("keys") or ""
        name = ctx.extra.pop("element_name", "")
        detail_full = " ".join(x for x in (str(action), f"'{name}'" if name else "", detail) if x)
        self.store.audit(ctx.client, method, target, outcome, detail_full)
        self.activity(client=ctx.client, method=method, target=target, outcome=outcome,
                      detail=detail_full, app=info.get("app", ""), title=info.get("title", ""))

    # ------------------------------------------------------------------ status
    def m_engine_status(self, ctx: Ctx, p: dict) -> dict:
        out = {"stopped": self.store.stopped(), "scopes": ctx.scopes, "deny_list": self.store.deny_list(),
               "uptime_s": round(time.time() - self.started, 1), "clients": self.client_count(),
               "version": __version__, "input": type(self.input).__name__}
        if type(self.input).__name__ == "FakeInput":  # test mode: show what would have been sent
            out["input_log"] = self.input.log()[-50:]
        return out

    # ------------------------------------------------------------------ windows
    def m_windows_list(self, ctx: Ctx, p: dict) -> list:
        deny = set(self.store.deny_list())
        out = []
        for w in win.list_windows(bool(p.get("all_desktops")), bool(p.get("include_hidden"))):
            if w["exe"].lower() in deny:
                continue
            out.append(w)
        return out

    def m_apps_list(self, ctx: Ctx, p: dict) -> list:
        apps: dict[str, dict] = {}
        for w in self.m_windows_list(ctx, p):
            image = win.image_of(w["pid"])
            key = image.lower() or f"pid:{w['pid']}"
            a = apps.setdefault(key, {"app_id": key, "name": w["app"], "exe": w["exe"], "pids": [], "windows": []})
            if w["pid"] not in a["pids"]:
                a["pids"].append(w["pid"])
            a["windows"].append(w["hwnd"])
        return list(apps.values())

    def m_windows_find(self, ctx: Ctx, p: dict) -> dict:
        q = str(p.get("query") or "").strip()
        if not q:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "'query' is required")
        wins = self.m_windows_list(ctx, {"all_desktops": p.get("all_desktops", True)})
        if q.isdigit() or re.fullmatch(r"0x[0-9a-fA-F]+", q):
            h = int(q, 0)
            return {"matches": [w for w in wins if w["hwnd"] == h]}
        ql = q.lower()
        exact = [w for w in wins if w["title"].lower() == ql or w["app"].lower() == ql
                 or os.path.splitext(w["exe"])[0].lower() == ql]
        if exact:
            return {"matches": exact}
        return {"matches": [w for w in wins if ql in w["title"].lower() or ql in w["app"].lower()
                            or ql in w["exe"].lower()]}

    def m_window_inspect(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd", required=True)
        self.check_target(ctx, hwnd, acting=False)
        info = win.describe(hwnd)
        cov = self.uia.coverage(hwnd)
        return {"window": info, "framework": self.uia.framework(hwnd), "coverage": cov,
                "focused": self.uia.focused() if info["foreground"] else None}

    # ------------------------------------------------------------------ tree / find / get
    def _scope(self, ctx: Ctx, p: dict, acting=False):
        if p.get("ref"):
            el = self.uia.resolve(str(p["ref"]))
            hwnd = U.Uia.parse_ref(str(p["ref"]))[0]
        else:
            hwnd = _int(p, "hwnd", required=True)
            el = None
        self.check_target(ctx, hwnd, acting)
        if el is None:
            el = self.uia.window_root(hwnd)
        return hwnd, el

    def m_tree_get(self, ctx: Ctx, p: dict) -> dict:
        hwnd, el = self._scope(ctx, p)
        depth = _int(p, "depth", 6, 0, 12)
        max_nodes = _int(p, "max_nodes", 400, 1, 3000)
        root, count, truncated = self.uia.tree(el, hwnd, depth, max_nodes, bool(p.get("include_offscreen")),
                                               p.get("filter") == "interactive")
        return {"root": root, "count": count, "truncated": truncated}

    def m_element_find(self, ctx: Ctx, p: dict) -> dict:
        hwnd, el = self._scope(ctx, p)
        match = p.get("match", "contains")
        if match not in ("exact", "contains", "regex"):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "match must be exact, contains or regex")
        if not any(p.get(k) for k in ("name", "type", "aid", "cls")):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "give at least one of name, type, aid, cls")
        matches, total = self.uia.find(el, hwnd, p.get("name"), match, p.get("type"), p.get("aid"), p.get("cls"),
                                       _int(p, "max", 20, 1, 200))
        return {"matches": matches, "total": total}

    def m_element_get(self, ctx: Ctx, p: dict) -> dict:
        ref = str(p.get("ref") or "")
        if not ref:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "'ref' is required")
        hwnd = U.Uia.parse_ref(ref)[0]
        self.check_target(ctx, hwnd, acting=False)
        el = self.uia.resolve(ref)
        node = self.uia.node(el, hwnd)
        text = self.uia.text_of(el)
        if text:
            node["text"] = text
        return node

    # ------------------------------------------------------------------ actions
    def m_element_act(self, ctx: Ctx, p: dict) -> dict:
        ref = str(p.get("ref") or "")
        action = str(p.get("action"))
        if not ref:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "'ref' is required")
        hwnd = U.Uia.parse_ref(ref)[0]
        self.check_target(ctx, hwnd, acting=True)
        el = self.uia.resolve(ref)
        node = self.uia.node(el, hwnd)
        ctx.extra["element_name"] = node.get("name", node.get("type", ""))
        if "disabled" in node.get("states", []) and action not in ("scroll_into_view",):
            raise ProtocolError(ErrorCode.UNSUPPORTED, f"'{node.get('name', node['type'])}' is disabled.",
                                {"element": node})
        verify = p.get("verify", True)
        verify_ms = _int(p, "verify_ms", 800, 0, 5000)
        before = self._observe(el, hwnd) if verify else None
        method = self._perform(el, hwnd, node, action, p)
        result = {"performed": True, "method": method, "element": {k: node[k] for k in ("ref", "type", "name") if k in node}}
        if verify:
            result["verification"] = self._verify(el, hwnd, before, verify_ms)
        return result

    def _need(self, node: dict, action: str) -> None:
        if action not in node.get("actions", []):
            raise ProtocolError(ErrorCode.UNSUPPORTED,
                                f"'{node.get('name') or node['type']}' does not support '{action}'. Nothing was done.",
                                {"available": node.get("actions", []), "element": {k: node.get(k) for k in ("ref", "type", "name")}})

    def _perform(self, el, hwnd: int, node: dict, action: str, p: dict) -> str:
        u = self.uia
        if action == "invoke":
            self._need(node, "invoke")
            u.pattern(el, U.PAT_INVOKE, "IUIAutomationInvokePattern").Invoke()
            return "InvokePattern"
        if action == "toggle":
            self._need(node, "toggle")
            u.pattern(el, U.PAT_TOGGLE, "IUIAutomationTogglePattern").Toggle()
            return "TogglePattern"
        if action in ("select", "add_to_selection", "remove_from_selection"):
            self._need(node, "select")
            pat = u.pattern(el, U.PAT_SELITEM, "IUIAutomationSelectionItemPattern")
            {"select": pat.Select, "add_to_selection": pat.AddToSelection,
             "remove_from_selection": pat.RemoveFromSelection}[action]()
            return "SelectionItemPattern"
        if action in ("expand", "collapse"):
            self._need(node, action)
            pat = u.pattern(el, U.PAT_EXPAND, "IUIAutomationExpandCollapsePattern")
            (pat.Expand if action == "expand" else pat.Collapse)()
            return "ExpandCollapsePattern"
        if action == "set_value":
            if "value" not in p:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "'value' is required for set_value")
            self._need(node, "set_value")
            u.pattern(el, U.PAT_VALUE, "IUIAutomationValuePattern").SetValue(str(p["value"]))
            return "ValuePattern"
        if action == "set_range":
            self._need(node, "set_range")
            try:
                val = float(p.get("value"))
            except (TypeError, ValueError):
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "'value' must be a number for set_range")
            u.pattern(el, U.PAT_RANGE, "IUIAutomationRangeValuePattern").SetValue(val)
            return "RangeValuePattern"
        if action == "scroll":
            self._need(node, "scroll")
            pat = u.pattern(el, U.PAT_SCROLL, "IUIAutomationScrollPattern")
            if p.get("percent") is not None:
                pct = max(0.0, min(100.0, float(p["percent"])))
                horiz = p.get("direction") in ("left", "right")
                pat.SetScrollPercent(pct if horiz else -1.0, -1.0 if horiz else pct)
                return "ScrollPattern.SetScrollPercent"
            direction = p.get("direction", "down")
            amount = p.get("amount", "page")
            if direction not in ("up", "down", "left", "right") or amount not in ("line", "page"):
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "direction up/down/left/right, amount line/page")
            inc = 3 if amount == "page" else 4      # LargeIncrement / SmallIncrement
            dec = 0 if amount == "page" else 1      # LargeDecrement / SmallDecrement
            no = 2
            h = inc if direction == "right" else dec if direction == "left" else no
            v = inc if direction == "down" else dec if direction == "up" else no
            pat.Scroll(h, v)
            return "ScrollPattern"
        if action == "scroll_into_view":
            self._need(node, "scroll_into_view")
            u.pattern(el, U.PAT_SCROLLITEM, "IUIAutomationScrollItemPattern").ScrollIntoView()
            return "ScrollItemPattern"
        if action == "default_action":
            pat = u.pattern(el, U.PAT_LEGACY, "IUIAutomationLegacyIAccessiblePattern")
            if pat is None:
                self._need(node, "default_action")
            pat.DoDefaultAction()
            return "LegacyIAccessible.DoDefaultAction"
        if action == "focus":
            self._need(node, "focus")
            el.SetFocus()
            return "SetFocus"
        if action == "click":
            rect = node.get("rect")
            if not rect:
                raise ProtocolError(ErrorCode.UNSUPPORTED, "The element has no on-screen rectangle to click.")
            if not self.input.focus(hwnd):
                raise ProtocolError(ErrorCode.UNSUPPORTED, "Windows did not bring the window to the foreground; "
                                    "synthetic clicks need it in front. Nothing was clicked.")
            button = p.get("button", "left")
            if button not in ("left", "right", "middle"):
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "button must be left, right or middle")
            self.input.click(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2, button, _int(p, "count", 1, 1, 3))
            return "synthetic_click"
        if action == "type_text":
            text = p.get("value")
            if not isinstance(text, str) or not text:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "'value' (text) is required for type_text")
            if len(text) > 20000:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, "text is too long (max 20000 characters)")
            if not self.input.focus(hwnd):
                raise ProtocolError(ErrorCode.UNSUPPORTED, "Windows did not bring the window to the foreground; "
                                    "typing needs it in front. Nothing was typed.")
            try:
                el.SetFocus()
            except comtypes.COMError:
                pass
            self.input.text(text)
            return "synthetic_typing"
        raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown action '{action}'")

    def _observe(self, el, hwnd: int) -> dict:
        return {"element": self.uia.snapshot(el), "focused": self.uia.focused(),
                "windows": {h: win.title(h) for h in win.window_ids()}}

    def _verify(self, el, hwnd: int, before: dict, verify_ms: int) -> dict:
        deadline = time.monotonic() + verify_ms / 1000.0
        after = before
        changed_once = False
        while True:
            time.sleep(0.06)
            after = self._observe(el, hwnd)
            differs = (after["element"] != before["element"] or after["windows"].keys() != before["windows"].keys()
                       or (after["focused"] or {}).get("ref") != (before["focused"] or {}).get("ref"))
            if differs and changed_once:
                break
            if differs:
                changed_once = True  # one more read so the state settles
                continue
            if time.monotonic() >= deadline:
                break
        b, a = before["element"], after["element"]
        out: dict = {}
        if a.get("_gone"):
            out["element_gone"] = True
            changed = {}
        else:
            changed = {k: [b.get(k), a.get(k)] for k in set(a) | set(b) if k != "_gone" and a.get(k) != b.get(k)}
        out["changed"] = changed
        new_w = [{"hwnd": h, "title": t} for h, t in after["windows"].items() if h not in before["windows"]]
        gone_w = [{"hwnd": h, "title": t} for h, t in before["windows"].items() if h not in after["windows"]]
        if new_w:
            out["new_windows"] = new_w
        if gone_w:
            out["closed_windows"] = gone_w
        if (after["focused"] or {}).get("ref") != (before["focused"] or {}).get("ref"):
            out["focused"] = after["focused"]
        out["observed_change"] = bool(changed or new_w or gone_w or out.get("element_gone") or "focused" in out)
        return out

    def m_input_keys(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd", required=True)
        self.check_target(ctx, hwnd, acting=True)
        try:
            chords = parse_keys(str(p.get("keys") or ""))
        except ValueError as exc:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, str(exc))
        if not self.input.focus(hwnd):
            raise ProtocolError(ErrorCode.UNSUPPORTED, "Windows did not bring the window to the foreground; "
                                "keys were not sent.", {"foreground": self.input.foreground()})
        self.input.keys(chords)
        return {"performed": True, "method": "synthetic_keys", "foreground": self.input.foreground() == hwnd}

    # ------------------------------------------------------------------ window operations
    def m_window_focus(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd", required=True)
        self.check_target(ctx, hwnd, acting=True)
        ok = self.input.focus(hwnd)
        return {"foreground": bool(ok), "method": "SetForegroundWindow"}

    def m_window_set_state(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd", required=True)
        state = p.get("state")
        if state not in ("minimize", "maximize", "restore", "close"):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "state must be minimize, maximize, restore or close")
        self.check_target(ctx, hwnd, acting=True)
        win.set_state(hwnd, state)
        deadline = time.monotonic() + 1.5
        want = {"minimize": "minimized", "maximize": "maximized", "restore": "normal"}.get(state)
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if state == "close":
                if not win.is_window(hwnd):
                    return {"state": "closed", "method": "WM_CLOSE"}
            elif win.state_of(hwnd) == want:
                return {"state": want, "method": "ShowWindow"}
        if state == "close":
            return {"state": "open", "method": "WM_CLOSE",
                    "note": "The window is still open -- it may be asking to save changes. Inspect it."}
        return {"state": win.state_of(hwnd), "method": "ShowWindow", "note": "The window did not reach that state."}

    def m_window_move(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd", required=True)
        self.check_target(ctx, hwnd, acting=True)
        vals = {k: _int(p, k) for k in ("x", "y", "width", "height")}
        if all(v is None for v in vals.values()):
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "give x/y and/or width/height")
        for k in ("width", "height"):
            if vals[k] is not None and vals[k] < 50:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"{k} must be at least 50 pixels")
        win.move(hwnd, vals["x"], vals["y"], vals["width"], vals["height"])
        deadline = time.monotonic() + 1.0
        rect = win.rect_of(hwnd)
        while time.monotonic() < deadline:
            time.sleep(0.04)
            rect = win.rect_of(hwnd)
            if all(vals[k] is None or rect[i] == vals[k] for i, k in enumerate(("x", "y", "width", "height"))):
                break
        return {"rect": rect, "method": "SetWindowPos"}

    # ------------------------------------------------------------------ watching / waiting
    def m_watch_subscribe(self, ctx: Ctx, p: dict) -> dict:
        hwnd = _int(p, "hwnd")
        if hwnd:
            self.check_target(ctx, hwnd, acting=False)
        try:
            sub = self.events.subscribe(ctx.session, hwnd, list(p.get("events") or []))
        except ValueError as exc:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, str(exc))
        return {"subscription": sub.id}

    def m_watch_unsubscribe(self, ctx: Ctx, p: dict) -> dict:
        return {"removed": self.events.unsubscribe(str(p.get("subscription") or ""), ctx.session)}

    def m_wait_for(self, ctx: Ctx, p: dict) -> dict:
        cond = p.get("condition") or {}
        kind = cond.get("kind")
        timeout = _int(p, "timeout_ms", 5000, 0, 30000) / 1000.0
        checks = {
            "window_exists": self._c_window_exists, "window_gone": self._c_window_gone,
            "element_exists": self._c_element_exists, "element_gone": self._c_element_gone,
            "value_equals": self._c_value_equals, "name_contains": self._c_name_contains,
            "focus_on": self._c_focus_on,
        }
        if kind not in checks:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown condition kind '{kind}'", {"kinds": sorted(checks)})
        if cond.get("hwnd"):
            self.check_target(ctx, int(cond["hwnd"]), acting=False)
        start = time.monotonic()
        while True:
            match = checks[kind](ctx, cond)
            if match is not None:
                return {"satisfied": True, "elapsed_ms": int((time.monotonic() - start) * 1000), "match": match}
            if time.monotonic() - start >= timeout:
                return {"satisfied": False, "elapsed_ms": int((time.monotonic() - start) * 1000)}
            time.sleep(0.1)

    def _c_window_exists(self, ctx, c):
        m = self.m_windows_find(ctx, {"query": c.get("query") or c.get("name") or ""})["matches"]
        return m[0] if m else None

    def _c_window_gone(self, ctx, c):
        h = int(c.get("hwnd") or 0)
        return {"hwnd": h} if not win.is_window(h) or not win.user32.IsWindowVisible(h) else None

    def _c_element_exists(self, ctx, c):
        hwnd = int(c.get("hwnd") or 0)
        if not win.is_window(hwnd):
            return None
        try:
            ms, _ = self.uia.find(self.uia.window_root(hwnd), hwnd, c.get("name"), c.get("match", "contains"),
                                  c.get("type"), c.get("aid"), None, 1)
        except ProtocolError:
            return None
        return ms[0] if ms else None

    def _c_element_gone(self, ctx, c):
        try:
            self.uia.resolve(str(c.get("ref")))
            return None
        except ProtocolError as exc:
            return {"ref": c.get("ref")} if exc.code == ErrorCode.STALE_REFERENCE else None

    def _read(self, c):
        try:
            el = self.uia.resolve(str(c.get("ref")))
            return self.uia.snapshot(el)
        except ProtocolError:
            return None

    def _c_value_equals(self, ctx, c):
        s = self._read(c)
        if s is None:
            return None
        want = str(c.get("value"))
        val = s.get("value") if "value" in s else s.get("name")
        return {"value": val} if str(val) == want else None

    def _c_name_contains(self, ctx, c):
        s = self._read(c)
        return {"name": s["name"]} if s and str(c.get("name", "")).lower() in s.get("name", "").lower() else None

    def _c_focus_on(self, ctx, c):
        f = self.uia.focused()
        return f if f and f.get("ref") == c.get("ref") else None

    # ------------------------------------------------------------------ notifications for the Shell
    NOTE_KINDS = ("info", "confirmation", "reminder", "message")
    NOTE_RATE = 10  # per client per minute

    def m_notify_post(self, ctx: Ctx, p: dict) -> dict:
        title = str(p.get("title") or "").strip()
        if not title:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, "'title' is required")
        kind = p.get("kind", "info")
        if kind not in self.NOTE_KINDS:
            raise ProtocolError(ErrorCode.INVALID_PARAMS, f"kind must be one of {list(self.NOTE_KINDS)}")
        now = time.time()
        recent = [t for t in self._notes.get(ctx.client, []) if now - t < 60]
        if len(recent) >= self.NOTE_RATE:
            self._notes[ctx.client] = recent
            raise ProtocolError(ErrorCode.BUSY, "Too many notifications; try again in a minute.",
                                {"limit_per_minute": self.NOTE_RATE})
        recent.append(now)
        self._notes[ctx.client] = recent
        note = {"title": title[:200], "body": str(p.get("body") or "")[:1000], "kind": kind,
                "app": str(p.get("app") or ctx.client.capitalize())[:60], "client": ctx.client, "time": now}
        self.notify_sink(note)
        return {"posted": True}

    # ------------------------------------------------------------------ admin (owner only; called by the server)
    def admin(self, method: str, p: dict) -> dict:
        s = self.store
        if method == "admin.permissions.get":
            return {"clients": s.clients(), "deny_list": s.deny_list(), "all_scopes": ALL_SCOPES,
                    "stopped": s.stopped()}
        if method == "admin.permissions.set":
            out = {}
            if "scopes" in p:
                client = str(p.get("client") or "garvis")
                try:
                    out["scopes"] = s.set_scopes(client, list(p["scopes"] or []))
                except KeyError:
                    raise ProtocolError(ErrorCode.NOT_FOUND, f"no client '{client}'")
            if "deny_list" in p:
                out["deny_list"] = s.set_deny_list(list(p["deny_list"] or []))
            s.audit("owner", method, "", "ok", str(out)[:500])
            return out
        if method == "admin.audit.read":
            return {"entries": s.read_audit(_int(p, "limit", 200, 1, 2000), _int(p, "since_id"))}
        raise ProtocolError(ErrorCode.UNKNOWN_METHOD, f"unknown method '{method}'")
