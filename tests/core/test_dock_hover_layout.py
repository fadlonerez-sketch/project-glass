"""The Dock's hover state machine and its geometry: the logic behind 'calm, stable, never jumpy'."""
import pytest

from glass.core.dockhover import DockHoverMachine, HoverState
from glass.core.docklayout import MIN_SCALE, compute_layout, drop_index, magnification

INTENT, DISMISS = 0.15, 0.30


def machine(**kw):
    return DockHoverMachine(intent_delay=INTENT, dismiss_delay=DISMISS, **kw)


# ---------------------------------------------------------------------------------------------- hover

def test_nothing_appears_before_hover_intent():
    m = machine()
    m.icon_enter("chrome", True, 0.0)
    assert m.tick(0.10).preview == "" and m.state == HoverState.INTENT
    v = m.tick(0.16)
    assert v.preview == "chrome" and v.state == HoverState.PREVIEW


def test_sweeping_across_icons_shows_nothing():
    m = machine()
    t = 0.0
    for app in ("a", "b", "c", "d"):
        m.icon_enter(app, True, t)
        t += 0.05
        m.tick(t)
        m.icon_leave(app, t)
    assert m.tick(t + 1).preview == "" and m.state == HoverState.IDLE


def test_closed_app_gets_a_tooltip_never_a_preview():
    m = machine()
    m.icon_enter("notepad", False, 0.0)
    v = m.tick(0.2)
    assert v.tooltip == "notepad" and v.preview == ""


def test_previews_disabled_fall_back_to_tooltips():
    m = machine(previews=False)
    m.icon_enter("chrome", True, 0.0)
    assert m.tick(0.2).tooltip == "chrome"


def test_moving_from_icon_to_preview_keeps_it_open():
    m = machine()
    m.icon_enter("chrome", True, 0.0)
    m.tick(0.2)
    m.icon_leave("chrome", 0.3)          # crossing the gap above the icon
    assert m.tick(0.45).preview == "chrome" and m.state == HoverState.GRACE
    m.preview_enter(0.5)                  # within the grace period
    assert m.tick(5.0).preview == "chrome" and m.state == HoverState.IN_PREVIEW


def test_leaving_the_preview_dismisses_after_the_grace_period():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.icon_leave("chrome", 0.3); m.preview_enter(0.35)
    m.preview_leave(1.0)
    assert m.tick(1.0 + DISMISS - 0.01).preview == "chrome"
    assert m.tick(1.0 + DISMISS + 0.01).preview == "" and m.state == HoverState.IDLE


def test_leaving_the_icon_without_reaching_the_preview_dismisses():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.icon_leave("chrome", 0.3)
    assert m.tick(0.3 + DISMISS + 0.01).preview == ""


def test_switching_apps_is_immediate_once_warm():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.icon_leave("chrome", 0.3)
    m.icon_enter("explorer", True, 0.32)
    v = m.tick(0.32)
    assert v.preview == "explorer" and m.state == HoverState.PREVIEW   # no second intent delay
    m.icon_leave("explorer", 0.4)
    m.icon_enter("notepad", False, 0.42)
    v = m.tick(0.42)
    assert v.tooltip == "notepad" and v.preview == ""                  # closed app: tooltip, preview gone


def test_back_from_preview_to_another_icon_switches():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.icon_leave("chrome", 0.3); m.preview_enter(0.35)
    m.icon_enter("explorer", True, 0.9)      # enter fires before the preview's leave
    m.preview_leave(0.9)
    v = m.tick(0.95)
    assert v.preview == "explorer" and m.state == HoverState.PREVIEW


def test_stale_leave_from_previous_icon_is_ignored():
    m = machine()
    m.icon_enter("a", True, 0.0); m.tick(0.2)
    m.icon_enter("b", True, 0.25)            # enter of the neighbour arrives first
    m.icon_leave("a", 0.25)
    assert m.tick(0.26).preview == "b" and m.state == HoverState.PREVIEW


def test_click_hides_and_does_not_reopen_until_the_pointer_leaves():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.press("chrome")
    assert m.tick(0.25).preview == "" and m.state == HoverState.PRESSED
    m.icon_enter("chrome", True, 0.3)        # jitter on the same icon
    assert m.tick(2.0).preview == ""
    m.icon_leave("chrome", 2.1)
    m.icon_enter("chrome", True, 2.2)
    assert m.tick(2.4).preview == "chrome"


def test_choosing_a_window_closes_the_preview():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.icon_leave("chrome", 0.3); m.preview_enter(0.35)
    m.choose_window()
    assert m.tick(0.4).preview == "" and m.state == HoverState.IDLE


def test_drag_suppresses_everything():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.drag_start()
    m.icon_enter("explorer", True, 0.5)
    assert m.tick(3.0).preview == "" and m.state == HoverState.DRAGGING
    m.drag_end(3.1)
    assert m.state == HoverState.PRESSED and m.tick(4.0).preview == ""


def test_menu_suppresses_previews_until_closed():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.menu_open()
    assert m.tick(0.3).preview == "" and m.state == HoverState.MENU
    m.menu_close(1.0)
    assert m.tick(2.0).preview == ""           # pointer still on the icon: no instant re-open
    m.icon_leave("chrome", 2.1)
    assert m.state == HoverState.IDLE


def test_last_window_closing_turns_the_preview_into_a_tooltip_or_closes_it():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.windows_changed("chrome", 0)             # pointer on the icon
    v = m.tick(0.3)
    assert v.preview == "" and v.tooltip == "chrome"
    m2 = machine()
    m2.icon_enter("chrome", True, 0.0); m2.tick(0.2); m2.icon_leave("chrome", 0.3); m2.preview_enter(0.35)
    m2.windows_changed("chrome", 0)            # pointer inside the preview
    assert m2.tick(0.4).preview == "" and m2.state == HoverState.IDLE


def test_dismiss_closes_everything_now():
    m = machine()
    m.icon_enter("chrome", True, 0.0); m.tick(0.2)
    m.dismiss()
    assert m.tick(0.21).preview == ""


def test_deadline_is_reported_for_an_event_driven_shell():
    m = machine()
    assert m.next_deadline() is None
    m.icon_enter("a", True, 1.0)
    assert m.next_deadline() == pytest.approx(1.0 + INTENT)


# ---------------------------------------------------------------------------------------------- layout

def rows(n_open=4, n_recent=3, widgets=("weather", "calendar", "system"), launcher=True):
    out = []
    if launcher:
        out.append({"uid": "launcher", "kind": "launcher", "section": ""})
    out += [{"uid": f"app:o{i}", "kind": "app", "section": "open"} for i in range(n_open)]
    if n_open and n_recent:
        out.append({"uid": "sep:recent", "kind": "separator", "section": ""})
    out += [{"uid": f"app:r{i}", "kind": "app", "section": "recent"} for i in range(n_recent)]
    if widgets:
        out.append({"uid": "sep:widgets", "kind": "separator", "section": ""})
    out += [{"uid": f"widget:{w}", "kind": "widget", "widgetType": w, "section": ""} for w in widgets]
    return out


def ordered(lay, prefix="app:"):
    return sorted((s for u, s in lay.slots.items() if u.startswith(prefix) and not s.hidden), key=lambda s: s.pos)


def test_bar_length_is_independent_of_contents():
    a = compute_layout(rows(2, 1), 2400, 38, 10)
    b = compute_layout(rows(12, 6), 2400, 38, 10)
    assert a.length == b.length == 2400


def test_cluster_is_centred_on_the_display():
    lay = compute_layout(rows(4, 3, widgets=("weather", "system")), 2400, 38, 10)
    lo, hi = lay.cluster
    assert abs((lo + hi) / 2 - 1200) < 0.5


def test_no_overlaps_and_consistent_spacing():
    lay = compute_layout(rows(6, 4), 2400, 38, 10)
    slots = sorted((s for s in lay.slots.values() if s.length > 0), key=lambda s: s.pos)
    for a, b in zip(slots, slots[1:]):
        assert b.pos >= a.pos + a.length - 1e-6, (a, b)
    apps = ordered(lay)
    gaps = {round(b.pos - (a.pos + a.length), 3) for a, b in zip(apps, apps[1:]) if b.pos - a.pos < 60}
    assert gaps == {10.0}


def test_widgets_split_between_the_ends_in_order():
    lay = compute_layout(rows(3, 2, widgets=("weather", "calendar", "system")), 2400, 38, 10)
    assert lay.slots["widget:weather"].zone == "start" and lay.slots["widget:calendar"].zone == "start"
    assert lay.slots["widget:system"].zone == "end"
    assert lay.slots["widget:weather"].pos == 0
    s = lay.slots["widget:system"]
    assert abs(s.pos + s.length - 2400) < 1e-6
    assert "sep:widgets" not in lay.slots


def test_cluster_slides_aside_rather_than_overlap_a_wide_zone():
    lay = compute_layout(rows(10, 6, widgets=("weather", "calendar", "clock")), 1500, 38, 10)
    start_end = max(s.pos + s.length for s in lay.slots.values() if s.zone == "start")
    assert lay.cluster[0] >= start_end - 1e-6
    end_start = min(s.pos for s in lay.slots.values() if s.zone == "end" and s.length)
    assert lay.cluster[1] <= end_start + 1e-6


def test_crowded_dock_shrinks_icons_then_drops_oldest_recent():
    lay = compute_layout(rows(10, 8), 1100, 38, 10)
    assert lay.icon < 38 and lay.icon >= 38 * MIN_SCALE - 1e-9
    huge = compute_layout(rows(25, 10), 1100, 38, 10)
    assert huge.icon == pytest.approx(38 * MIN_SCALE)
    assert huge.hidden and all(h.startswith("app:r") or h == "sep:recent" for h in huge.hidden)
    assert huge.hidden[0] == "app:r9"                          # the oldest recent goes first
    assert huge.cluster[1] - huge.cluster[0] <= 1100
    assert all(f"app:o{i}" not in huge.hidden for i in range(25))   # open apps are never dropped


def test_layout_is_deterministic():
    a = compute_layout(rows(5, 3), 2000, 38, 10).to_dict()
    b = compute_layout(rows(5, 3), 2000, 38, 10).to_dict()
    assert a == b


def test_leaving_item_takes_no_room_and_neighbours_close_up():
    base = rows(4, 0, widgets=())
    before = compute_layout(base, 2000, 38, 10)
    leaving = [dict(r, leaving=True) if r["uid"] == "app:o1" else r for r in base]
    after = compute_layout(leaving, 2000, 38, 10)
    assert after.slots["app:o1"].length == 0
    span = lambda lay: lay.cluster[1] - lay.cluster[0]
    assert span(after) == pytest.approx(span(before) - 48)
    assert after.slots["app:o2"].pos - after.slots["app:o0"].pos == pytest.approx(48)


def test_scaling_is_resolution_independent():
    """Layout works in logical px; at any DPI the same logical input gives the same logical result."""
    a = compute_layout(rows(6, 3), 1707, 38, 10)
    phys = compute_layout(rows(6, 3), 1707 * 1.5, 38 * 1.5, 10 * 1.5)
    for uid, s in a.slots.items():
        assert phys.slots[uid].pos == pytest.approx(s.pos * 1.5) and phys.slots[uid].length == pytest.approx(s.length * 1.5)


def test_vertical_dock_uses_square_widgets():
    lay = compute_layout(rows(3, 2), 900, 38, 10, horizontal=False)
    assert lay.slots["widget:weather"].length == 38


def test_drop_index_and_magnification_are_pure():
    assert drop_index([100, 150, 200], 90) == 0
    assert drop_index([100, 150, 200], 160) == 2
    assert drop_index([100, 150, 200], 999) == 3
    assert magnification(0, 38, 1.3) == pytest.approx(1.3)
    assert 1.0 < magnification(48, 38, 1.3) < 1.3
    assert magnification(500, 38, 1.3) == pytest.approx(1.0, abs=1e-6)
    assert magnification(0, 38, 1.3, amount=0) == 1.0


def test_magnified_neighbours_never_overlap_at_default_spacing():
    """Magnification is a transform around fixed slots; at the defaults neighbours must not collide."""
    icon, gap, scale = 38, 10, 1.3
    for pointer in [i * 0.5 for i in range(0, 97)]:     # pointer anywhere across two slots
        centers = [0, icon + gap, 2 * (icon + gap)]
        half = [icon * magnification(abs(c - pointer), icon, scale) / 2 for c in centers]
        for i in range(2):
            assert centers[i] + half[i] <= centers[i + 1] - half[i + 1] + 0.5
