import pytest

from glass.core.apps import AppRecord, AppRegistry, RunningApp, compute_dock
from glass.core.states import DynamicGlassMachine, GlassState, HoverIntent


@pytest.fixture
def reg(tmp_path):
    return AppRegistry(tmp_path / "apps.db")


def add(reg, app_id, name, launched=None, pinned=False):
    reg.ensure(AppRecord(app_id=app_id, name=name, exe=f"C:\\{name}.exe"))
    if launched is not None:
        reg.record_launch(app_id, launched)
    if pinned:
        reg.pin(app_id)


def run(app_id, name, first_seen, windows=(1,), focused=False):
    return RunningApp(app_id=app_id, name=name, windows=tuple(windows), focused=focused, first_seen=first_seen)


def test_open_and_recent_are_disjoint_and_ordered(reg):
    add(reg, "a", "Alpha", 100)
    add(reg, "b", "Beta", 300)
    add(reg, "c", "Gamma", 200)
    add(reg, "d", "Delta", 400)
    running = {"d": run("d", "Delta", 400), "b": run("b", "Beta", 300)}
    lay = compute_dock(reg.all(), running)
    assert [i.app_id for i in lay.open] == ["b", "d"]            # launch order, newest at the end
    assert [i.app_id for i in lay.recent] == ["c", "a"]          # most recent launch first
    assert len(set(lay.ids())) == len(lay.ids())


def test_opening_moves_to_open_and_closing_returns_to_recent(reg):
    add(reg, "a", "Alpha", 100)
    add(reg, "b", "Beta", 200)
    lay = compute_dock(reg.all(), {})
    assert [i.app_id for i in lay.recent] == ["b", "a"] and lay.open == []
    reg.record_launch("a", 500)
    lay = compute_dock(reg.all(), {"a": run("a", "Alpha", 500)})
    assert [i.app_id for i in lay.open] == ["a"] and [i.app_id for i in lay.recent] == ["b"]
    reg.record_closed("a", 600)
    lay = compute_dock(reg.all(), {})
    assert [i.app_id for i in lay.recent] == ["a", "b"]           # 'a' was launched most recently


def test_pinned_follow_open_recent_rules_and_keep_manual_order(reg):
    for i, n in enumerate(["p1", "p2", "p3"]):
        add(reg, n, n.upper(), launched=10 + i, pinned=True)
    add(reg, "x", "X", 999)
    reg.move_pinned("p3", 0)                                      # manual order: p3, p1, p2
    lay = compute_dock(reg.all(), {"p1": run("p1", "P1", 50), "x": run("x", "X", 40)})
    assert [i.app_id for i in lay.open] == ["p1", "x"]            # running pinned app is among Open (first)
    assert [i.app_id for i in lay.recent] == ["p3", "p2"]         # closed pinned keep manual order
    assert all(i.pinned for i in lay.recent)


def test_pinned_never_drop_out_with_a_recent_limit(reg):
    add(reg, "old", "Old", 1, pinned=True)
    for i in range(10):
        add(reg, f"r{i}", f"R{i}", 100 + i)
    lay = compute_dock(reg.all(), {}, recent_limit=3)
    ids = [i.app_id for i in lay.recent]
    assert ids[0] == "old" and ids[1:] == ["r9", "r8", "r7"]
    lay = compute_dock(reg.all(), {}, show_recent=False)
    assert [i.app_id for i in lay.recent] == ["old"]


def test_unknown_running_apps_and_multiple_windows(reg):
    lay = compute_dock(reg.all(), {"z": run("z", "Zed", 5, windows=(11, 12, 13), focused=True)})
    item = lay.open[0]
    assert item.window_count == 3 and item.focused and item.windows == (11, 12, 13)


def test_hidden_apps_return_when_launched(reg):
    add(reg, "a", "Alpha", 100)
    reg.remove_from_dock("a")
    assert compute_dock(reg.all(), {}).recent == []
    reg.record_launch("a", 200)
    assert [i.app_id for i in compute_dock(reg.all(), {}).recent] == ["a"]


def test_deterministic_ties(reg):
    add(reg, "b", "Same", 100)
    add(reg, "a", "Same", 100)
    first = compute_dock(reg.all(), {}).ids()
    for _ in range(5):
        assert compute_dock(list(reversed(reg.all())), {}).ids() == first


def test_registry_persistence_and_aliases(tmp_path):
    r = AppRegistry(tmp_path / "apps.db")
    r.ensure(AppRecord(app_id="aumid:chrome", name="Chrome"))
    r.add_alias("exe:c:\\chrome.exe", "aumid:chrome")
    r.pin("aumid:chrome")
    r2 = AppRegistry(tmp_path / "apps.db")
    assert r2.resolve(["exe:c:\\chrome.exe"]) == "aumid:chrome"
    assert r2.get("aumid:chrome").pinned


def test_set_pin_order_requires_same_set(reg):
    add(reg, "a", "A", pinned=True)
    add(reg, "b", "B", pinned=True)
    reg.set_pin_order(["b", "a"])
    assert [r.app_id for r in reg.pinned()] == ["b", "a"]
    with pytest.raises(ValueError):
        reg.set_pin_order(["a"])
    reg.unpin("b")
    assert [r.app_id for r in reg.pinned()] == ["a"]


# ------------------------------------------------------------------ Dynamic Glass states

def test_idle_media_and_priorities():
    m = DynamicGlassMachine()
    assert m.resolve(0).state == GlassState.IDLE
    m.set(media_present=True, media_playing=True)
    assert m.resolve(0).state == GlassState.MEDIA
    m.set(garvis_active=True)
    assert m.resolve(0).state == GlassState.GARVIS
    m.activity({"kind": "volume", "level": 0.4}, duration=1.5, now=0)
    assert m.resolve(0.1).state == GlassState.ACTIVITY
    m.notify({"title": "Hi"}, duration=3)
    assert m.resolve(0.2).state == GlassState.NOTIFICATION
    m.set(controls_open=True)
    assert m.resolve(0.3).state == GlassState.CONTROLS
    m.click()
    assert m.resolve(0.4).state == GlassState.CONTROL_CENTER


def test_hover_is_not_click():
    m = DynamicGlassMachine(expand_delay=0.2, collapse_delay=0.5)
    m.set(media_present=True)
    m.pointer_enter(0.0)
    assert m.resolve(0.1).state == GlassState.MEDIA
    assert m.resolve(0.25).state == GlassState.MEDIA_EXPANDED
    assert not m.inputs.control_center_open
    m.pointer_leave(1.0)
    assert m.resolve(1.3).state == GlassState.MEDIA_EXPANDED      # still within collapse delay
    m.pointer_enter(1.4)                                          # re-entering cancels the collapse
    assert m.resolve(2.0).state == GlassState.MEDIA_EXPANDED
    m.pointer_leave(2.0)
    assert m.resolve(2.6).state == GlassState.MEDIA
    m.click()
    assert m.resolve(2.7).state == GlassState.CONTROL_CENTER
    m.click()
    assert m.resolve(2.8).state == GlassState.MEDIA


def test_hover_needs_media():
    m = DynamicGlassMachine(expand_delay=0.0)
    m.pointer_enter(0)
    assert m.resolve(1).state == GlassState.IDLE
    m.set(media_present=True, hover_expand_enabled=False)
    m.pointer_enter(2)
    assert m.resolve(3).state == GlassState.MEDIA


def test_media_ending_cancels_expansion():
    m = DynamicGlassMachine(expand_delay=0.0)
    m.set(media_present=True)
    m.pointer_enter(0)
    assert m.resolve(0.01).state == GlassState.MEDIA_EXPANDED
    m.set(media_present=False)
    assert m.resolve(0.02).state == GlassState.IDLE


def test_notification_queue_and_expiry():
    m = DynamicGlassMachine()
    m.notify({"title": "one"}, duration=2)
    m.notify({"title": "two"}, duration=2)
    m.notify({"title": "urgent"}, duration=2, priority=2)
    r = m.resolve(0)
    assert r.state == GlassState.NOTIFICATION and r.payload["title"] == "urgent"
    assert m.next_deadline() == 2
    assert m.resolve(2.0).payload["title"] == "one"
    assert m.resolve(4.0).payload["title"] == "two"
    assert m.resolve(6.0).state == GlassState.IDLE


def test_activity_pulses_replace_each_other():
    m = DynamicGlassMachine()
    m.activity({"kind": "volume", "level": 0.2}, duration=1.0, now=0)
    m.resolve(0)
    m.activity({"kind": "volume", "level": 0.3}, duration=1.0, now=0.8)
    r = m.resolve(1.5)
    assert r.state == GlassState.ACTIVITY and r.payload["level"] == 0.3
    assert m.resolve(1.9).state == GlassState.IDLE


def test_hover_intent_unit():
    h = HoverIntent(0.1, 0.3)
    h.enter(0)
    assert not h.tick(0.05) and h.tick(0.1)
    h.leave(1)
    assert h.tick(1.2) and not h.tick(1.31)


def test_apps_running_elsewhere_are_not_recent(reg):
    add(reg, "a", "Alpha", 100)
    add(reg, "b", "Beta", 50)
    lay = compute_dock(reg.all(), {}, exclude={"a"})
    assert [i.app_id for i in lay.recent] == ["b"]
