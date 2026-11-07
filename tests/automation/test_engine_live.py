"""Real engine process + real pipe + real off-screen test applications (Qt and plain Win32).

Synthetic input paths run against the engine's FakeInput (`--fake-input`), so nothing is ever typed,
clicked or focused in the user's session; semantic UIA actions are real.
"""
from __future__ import annotations

import struct

import pytest

from glass.automation import win
from tests.automation.conftest import find_one, label, status, wait_until

pytestmark = pytest.mark.usefixtures("engine")


# ----------------------------------------------------------------------------- handshake / auth
def test_hello_and_status(client):
    st = client.call("engine.status")
    assert st["stopped"] is False and st["input"] == "FakeInput" and "act" in st["scopes"]


def test_bad_token_rejected(engine, loop):
    from tests.automation.conftest import SyncClient
    c = SyncClient(loop)
    err = None
    try:
        c.hello("not-a-token")
    except Exception as exc:  # RemoteError
        err = exc
    assert err is not None and getattr(err, "code", "") == "unauthorized"
    c.close()


def test_malformed_frame_over_real_pipe(engine, loop, tokens):
    from tests.automation.conftest import SyncClient
    c = SyncClient(loop)
    c.run(c.c.send_raw(struct.pack("<I", 4) + b"{no}"))
    msgs = c.notifications(wait=0.4)
    assert any(m.get("error", {}).get("code") == "invalid_params" for m in msgs)
    c.close()


# ----------------------------------------------------------------------------- discovery
def test_windows_and_apps(client, qt_target):
    wins = client.call("windows.list", {"all_desktops": True})
    me = next(w for w in wins if w["hwnd"] == qt_target)
    assert me["title"] == "Glass Test Target" and me["exe"].lower().startswith("python")
    assert me["foreground"] is False and me["elevated"] is False
    found = client.call("windows.find", {"query": "glass test target"})["matches"]
    assert [w["hwnd"] for w in found] == [qt_target]
    assert client.call("windows.find", {"query": str(qt_target)})["matches"][0]["hwnd"] == qt_target
    apps = client.call("apps.list", {"all_desktops": True})
    assert any(qt_target in a["windows"] for a in apps)


def test_inspect_coverage_full_and_none(client, qt_target, blank_target, win32_target):
    full = client.call("window.inspect", {"hwnd": qt_target})
    assert full["framework"] == "Qt" and full["coverage"]["level"] == "full"
    w32 = client.call("window.inspect", {"hwnd": win32_target})
    assert w32["framework"] == "Win32" and w32["coverage"]["level"] in ("full", "partial")
    none = client.call("window.inspect", {"hwnd": blank_target})
    assert none["coverage"]["level"] == "none" and "not possible" in none["coverage"]["note"]


def test_tree_limits_and_filter(client, qt_target):
    t = client.call("tree.get", {"hwnd": qt_target, "depth": 1})
    assert t["root"]["type"] == "Window" and t["truncated"] is True
    assert all("children" not in c for c in t["root"]["children"])
    small = client.call("tree.get", {"hwnd": qt_target, "depth": 8, "max_nodes": 10})
    assert small["count"] <= 10 and small["truncated"]
    inter = client.call("tree.get", {"hwnd": qt_target, "depth": 8, "max_nodes": 500, "filter": "interactive"})

    def walk(n):
        yield n
        for c in n.get("children", []):
            yield from walk(c)
    names = {n.get("name") for n in walk(inter["root"])}
    assert {"Say Hello", "Enable feature", "Cherry"} <= names
    pw = next(n for n in walk(inter["root"]) if n.get("name") == "Password")
    assert "password" in pw["states"] and "value" not in pw  # never reveal passwords


def test_find_variants_and_errors(client, qt_target):
    assert find_one(client, qt_target, name="say hello", match="exact")["type"] == "Button"
    assert find_one(client, qt_target, name="^Ch.rry$", match="regex")["name"] == "Cherry"
    items = client.call("element.find", {"hwnd": qt_target, "type": "ListItem", "max": 3})
    # Qt exposes only the rows currently in view (44 exist), so `total` counts visible rows.
    assert len(items["matches"]) == 3 and items["total"] >= 3
    assert client.error("element.find", {"hwnd": qt_target, "type": "Spaceship"}).code == "invalid_params"
    assert client.error("element.find", {"hwnd": qt_target}).code == "invalid_params"
    assert client.error("window.inspect", {"hwnd": 12345678}).code == "stale_reference"


def test_element_get_fresh(client, qt_target):
    edit = find_one(client, qt_target, name="Name", type="Edit", match="exact")
    client.call("element.act", {"ref": edit["ref"], "action": "set_value", "value": "Ada"})
    got = client.call("element.get", {"ref": edit["ref"]})
    assert got["value"] == "Ada" and "set_value" in got["actions"]


# ----------------------------------------------------------------------------- semantic actions
def test_invoke_and_verify_via_label(client, qt_target):
    btn = find_one(client, qt_target, name="Say Hello")
    r = client.call("element.act", {"ref": btn["ref"], "action": "invoke"})
    assert r["performed"] and r["method"] == "InvokePattern"
    assert wait_until(lambda: label(client, qt_target) == "clicked:Say Hello")


def test_set_value_toggle_select(client, qt_target):
    edit = find_one(client, qt_target, name="Name", type="Edit", match="exact")
    r = client.call("element.act", {"ref": edit["ref"], "action": "set_value", "value": "Grace Hopper"})
    assert r["verification"]["changed"]["value"] == ["", "Grace Hopper"]
    assert wait_until(lambda: label(client, qt_target) == "text:Grace Hopper")
    cb = find_one(client, qt_target, name="Enable feature")
    r = client.call("element.act", {"ref": cb["ref"], "action": "toggle"})
    assert r["verification"]["changed"]["toggle"] == ["unchecked", "checked"]
    item = find_one(client, qt_target, name="Cherry", type="ListItem")
    r = client.call("element.act", {"ref": item["ref"], "action": "select"})
    assert r["verification"]["changed"]["selected"] == [False, True]
    assert wait_until(lambda: label(client, qt_target) == "list:Cherry")


def test_expand_collapse_win32_tree(client, win32_target):
    node = find_one(client, win32_target, name="Projects", type="TreeItem")
    r = client.call("element.act", {"ref": node["ref"], "action": "expand"})
    assert r["verification"]["changed"]["expand"] == ["collapsed", "expanded"]
    assert find_one(client, win32_target, name="Garvis", type="TreeItem")
    r = client.call("element.act", {"ref": node["ref"], "action": "collapse"})
    assert r["verification"]["changed"]["expand"] == ["expanded", "collapsed"]


def test_no_effect_is_reported_honestly(client, qt_target):
    # Qt advertises ExpandCollapse on tree items but ignores it: the engine must say nothing changed.
    node = find_one(client, qt_target, name="Projects", type="TreeItem")
    r = client.call("element.act", {"ref": node["ref"], "action": "expand", "verify_ms": 400})
    assert r["performed"] and r["verification"]["observed_change"] is False and r["verification"]["changed"] == {}


def test_expand_menu(client, qt_target):
    menu = find_one(client, qt_target, name="File", type="MenuItem")
    r = client.call("element.act", {"ref": menu["ref"], "action": "expand"})
    assert r["verification"]["changed"]["expand"] == ["collapsed", "expanded"]
    client.call("element.act", {"ref": menu["ref"], "action": "collapse"})


def test_set_range_on_scrollbar(client, qt_target):
    bars = client.call("element.find", {"hwnd": qt_target, "type": "ScrollBar"})["matches"]
    bar = next(b for b in bars if "set_range" in b.get("actions", []))
    client.call("element.act", {"ref": bar["ref"], "action": "set_range", "value": 10})
    assert wait_until(lambda: label(client, qt_target).startswith("scrolled:") or
                      label(client, qt_target).startswith("list:"))


def test_scroll_pattern_on_win32_listbox(client, win32_target):
    lst = find_one(client, win32_target, type="List")
    assert "scroll" in lst["actions"]
    item = find_one(client, win32_target, name="Item 3", match="exact")
    r = client.call("element.act", {"ref": lst["ref"], "action": "scroll", "direction": "down", "amount": "page"})
    assert r["method"] == "ScrollPattern" and r["verification"]["changed"].get("scroll")
    r = client.call("element.act", {"ref": lst["ref"], "action": "scroll", "percent": 100})
    assert r["method"] == "ScrollPattern.SetScrollPercent"
    assert r["verification"]["changed"]["scroll"][1][1] == 100.0
    client.call("element.act", {"ref": item["ref"], "action": "scroll_into_view"})
    r = client.call("element.act", {"ref": item["ref"], "action": "select"})
    # LB_SETCURSEL (what the proxy uses) sends no LBN_SELCHANGE, so verify through UIA state instead.
    assert r["verification"]["changed"]["selected"] == [False, True]
    btn = find_one(client, win32_target, name="Press Me")
    client.call("element.act", {"ref": btn["ref"], "action": "invoke"})
    assert wait_until(lambda: status(client, win32_target) == "win32:clicked")


def test_unsupported_action_does_nothing(client, qt_target):
    btn = find_one(client, qt_target, name="Say Hello")
    err = client.error("element.act", {"ref": btn["ref"], "action": "toggle"})
    assert err.code == "unsupported_pattern" and "invoke" in err.data["available"]
    assert label(client, qt_target) == "ready"
    assert client.error("element.act", {"ref": btn["ref"], "action": "fly"}).code == "invalid_params"


def test_stale_reference_is_never_redirected(client, qt_target):
    rm = find_one(client, qt_target, name="Remove Me")
    r = client.call("element.act", {"ref": rm["ref"], "action": "invoke"})
    assert r["verification"].get("element_gone") is True
    err = client.error("element.act", {"ref": rm["ref"], "action": "invoke"})
    assert err.code == "stale_reference"
    assert label(client, qt_target) == "removed"  # nothing else was pressed
    assert client.error("element.get", {"ref": "1:2.3"}).code == "stale_reference"


def test_dialog_new_window_and_close(client, qt_target):
    fg_before = win.foreground()
    btn = find_one(client, qt_target, name="Open Dialog")
    r = client.call("element.act", {"ref": btn["ref"], "action": "invoke"})
    new = r["verification"].get("new_windows", [])
    dlg = next(w for w in new if w["title"] == "Confirm Thing")
    assert win.foreground() == fg_before  # the user's focus was not stolen
    ok = find_one(client, dlg["hwnd"], name="OK", type="Button")
    client.call("element.act", {"ref": ok["ref"], "action": "invoke"})
    assert wait_until(lambda: label(client, qt_target) == "dialog:ok")


def test_window_ops_without_activation(client, qt_target):
    r = client.call("window.move", {"hwnd": qt_target, "x": -31000, "y": -31000, "width": 500, "height": 700})
    # The engine reports the rectangle the window really has: apps may enforce a minimum size (the Qt
    # target's minimum height depends on the DPI of the monitor its coordinates map to).
    assert r["rect"][:2] == [-31000, -31000] and r["rect"][2] == 500 and r["rect"][3] >= 700
    assert client.call("window.set_state", {"hwnd": qt_target, "state": "minimize"})["state"] == "minimized"
    assert client.call("window.set_state", {"hwnd": qt_target, "state": "restore"})["state"] == "normal"
    assert client.error("window.move", {"hwnd": qt_target, "width": 10}).code == "invalid_params"
    assert client.error("window.set_state", {"hwnd": qt_target, "state": "explode"}).code == "invalid_params"


def test_window_close(client, qt_target):
    r = client.call("window.set_state", {"hwnd": qt_target, "state": "close"})
    assert r["state"] == "closed"


# ----------------------------------------------------------------------------- synthetic input (FakeInput)
def test_input_paths_are_explicit_and_recorded(client, qt_target):
    r = client.call("input.keys", {"hwnd": qt_target, "keys": "ctrl+s"})
    assert r == {"performed": True, "method": "synthetic_keys", "foreground": True}
    assert client.error("input.keys", {"hwnd": qt_target, "keys": "ctrl+banana"}).code == "invalid_params"
    btn = find_one(client, qt_target, name="Say Hello")
    r = client.call("element.act", {"ref": btn["ref"], "action": "click", "verify": False})
    assert r["method"] == "synthetic_click"
    edit = find_one(client, qt_target, name="Name", type="Edit", match="exact")
    r = client.call("element.act", {"ref": edit["ref"], "action": "type_text", "value": "hi", "verify": False})
    assert r["method"] == "synthetic_typing"
    assert client.call("window.focus", {"hwnd": qt_target})["foreground"] is True
    log = client.call("engine.status")["input_log"]
    kinds = [c[0] for c in log[-7:]]
    assert kinds == ["focus", "keys", "focus", "click", "focus", "text", "focus"]
    assert log[-6][1] == [[0x11, ord("S")]] or log[-6][0] == "keys"


# ----------------------------------------------------------------------------- policy
def test_scopes_enforced(client, owner, qt_target):
    owner.call("admin.permissions.set", {"client": "garvis", "scopes": ["inspect"]})
    btn = find_one(client, qt_target, name="Say Hello")  # inspect still works
    err = client.error("element.act", {"ref": btn["ref"], "action": "invoke"})
    assert err.code == "forbidden_scope" and err.data["scope"] == "act"
    assert client.error("input.keys", {"hwnd": qt_target, "keys": "a"}).code == "forbidden_scope"
    assert client.error("window.move", {"hwnd": qt_target, "x": 1}).code == "forbidden_scope"
    owner.call("admin.permissions.set", {"client": "garvis", "scopes": ["inspect", "act"]})
    edit = find_one(client, qt_target, name="Name", type="Edit", match="exact")
    assert client.error("element.act", {"ref": edit["ref"], "action": "set_value", "value": "x"}).code == "forbidden_scope"
    assert label(client, qt_target) == "ready"


def test_deny_list(client, owner, qt_target):
    owner.call("admin.permissions.set", {"deny_list": ["python.exe", "pythonw.exe"]})
    assert all(w["hwnd"] != qt_target for w in client.call("windows.list", {"all_desktops": True}))
    err = client.error("window.inspect", {"hwnd": qt_target})
    assert err.code == "denied_app"


def test_protected_glass_windows(client, protected_target):
    btn = find_one(client, protected_target, name="Say Hello")  # reading is allowed
    err = client.error("element.act", {"ref": btn["ref"], "action": "invoke"})
    assert err.code == "denied_app" and "Project Glass" in err.message


def test_emergency_stop(client, owner, qt_target):
    owner.call("admin.subscribe")
    owner.call("admin.stop")
    assert client.error("windows.list").code == "stopped"
    assert client.call("engine.status")["stopped"] is True
    assert any(n.get("method") == "stopped" for n in owner.notifications(wait=0.2))
    owner.call("admin.resume")
    assert client.call("windows.list", {"all_desktops": True})


def test_admin_forbidden_for_garvis_and_audit(client, owner, qt_target):
    assert client.error("admin.audit.read").code == "forbidden_scope"
    owner.call("admin.subscribe")
    btn = find_one(client, qt_target, name="Say Hello")
    client.call("element.act", {"ref": btn["ref"], "action": "invoke"})
    entries = owner.call("admin.audit.read", {"limit": 20})["entries"]
    e = next(x for x in entries if x["method"] == "element.act" and x["client"] == "garvis")
    assert e["outcome"] == "ok" and "Say Hello" in e["detail"] and "Glass Test Target" in e["target"]
    notes = owner.notifications(wait=0.3)
    assert any(n["method"] == "activity" and n["params"]["method"] == "element.act" for n in notes)
    assert any(n["method"] == "control_state" and n["params"]["active"] for n in notes)
    perms = owner.call("admin.permissions.get")
    assert set(perms["clients"]) == {"owner", "garvis"} and perms["all_scopes"]


# ----------------------------------------------------------------------------- events and waiting
def test_watch_events(client, qt_target):
    sub = client.call("watch.subscribe", {"hwnd": qt_target, "events": ["window_opened", "structure_changed"]})
    btn = find_one(client, qt_target, name="Open Dialog")
    client.call("element.act", {"ref": btn["ref"], "action": "invoke", "verify": False})
    events = wait_until(lambda: [n for n in client.notifications(wait=0.2) if n.get("method") == "event"], timeout=4)
    assert events and all(e["params"]["subscription"] == sub["subscription"] for e in events)
    assert {"window_opened", "structure_changed"} & {e["params"]["type"] for e in events}
    assert client.call("watch.unsubscribe", {"subscription": sub["subscription"]})["removed"] is True
    assert client.error("watch.subscribe", {"events": ["telepathy"]}).code == "invalid_params"


def test_wait_for_conditions(client, qt_target):
    btn = find_one(client, qt_target, name="Open Dialog")
    client.call("element.act", {"ref": btn["ref"], "action": "invoke", "verify": False})
    r = client.call("wait.for", {"condition": {"kind": "window_exists", "query": "Confirm Thing"}, "timeout_ms": 3000})
    assert r["satisfied"] and r["match"]["title"] == "Confirm Thing"
    edit = find_one(client, qt_target, name="Name", type="Edit", match="exact")
    client.call("element.act", {"ref": edit["ref"], "action": "set_value", "value": "Linus", "verify": False})
    assert client.call("wait.for", {"condition": {"kind": "value_equals", "ref": edit["ref"], "value": "Linus"}})["satisfied"]
    lbl = find_one(client, qt_target, aid="QApplication.Target.QWidget.lastAction")
    assert client.call("wait.for", {"condition": {"kind": "name_contains", "ref": lbl["ref"], "name": "Linus"}})["satisfied"]
    assert client.call("wait.for", {"condition": {"kind": "element_exists", "hwnd": qt_target, "name": "Cherry"}})["satisfied"]
    r = client.call("wait.for", {"condition": {"kind": "element_exists", "hwnd": qt_target, "name": "Unicorn"},
                                 "timeout_ms": 300})
    assert r["satisfied"] is False and r["elapsed_ms"] >= 250
    assert client.error("wait.for", {"condition": {"kind": "vibes"}}).code == "invalid_params"


# ----------------------------------------------------------------------------- notifications
def test_notify_post_broadcast_and_rate_limit(client, owner):
    owner.call("admin.subscribe")
    owner.notifications(wait=0.1)
    r = client.call("notify.post", {"title": "Garvis needs your approval", "body": "send_email", "kind": "confirmation"})
    assert r == {"posted": True}
    notes = [n for n in owner.notifications(wait=0.3) if n["method"] == "notification"]
    assert notes and notes[0]["params"]["title"] == "Garvis needs your approval"
    assert notes[0]["params"]["client"] == "garvis" and notes[0]["params"]["kind"] == "confirmation"
    assert notes[0]["params"]["app"] == "Garvis" and notes[0]["params"]["time"] > 0
    assert client.error("notify.post", {"title": ""}).code == "invalid_params"
    assert client.error("notify.post", {"title": "x", "kind": "spam"}).code == "invalid_params"
    codes = []
    for _ in range(12):
        try:
            client.call("notify.post", {"title": "again"})
            codes.append("ok")
        except Exception as exc:
            codes.append(getattr(exc, "code", "?"))
    assert "busy" in codes and codes.count("ok") <= 9
