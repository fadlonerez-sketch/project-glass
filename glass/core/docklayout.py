"""The Dock's geometry (pure). The Dock is a thin bar that spans the usable width of its display:

    [ widgets (start zone) ]        [ launcher · Open apps | Recently Used ]        [ widgets (end zone) ]

* The bar's length never depends on its contents or on the pointer: it is the display's length minus a
  margin. Hover, magnification and previews are purely visual and never feed back into this layout, which
  is what keeps the Dock from jumping.
* The application cluster is centred on the display (the visual axis it shares with the Dynamic Glass)
  and only slides aside if the widget zones would otherwise overlap it.
* Widgets split between the two ends in their configured order: the first half at the start, the rest at
  the end.
* When there are more apps than room, icons shrink (to at most ``MIN_SCALE``) and, only then, the oldest
  Recently Used items are left out. Everything is deterministic, so identical input gives identical
  pixels.
* Items that are leaving (an app just closed) take no room; their neighbours glide into the space.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MIN_SCALE = 0.72
# Widget length along a horizontal bar, in icon sizes. Vertical bars use square widgets.
WIDGET_LENGTH = {"weather": 4.3, "calendar": 3.3, "clock": 2.4, "system": 3.1, "garvis": 3.0}


@dataclass(frozen=True)
class Slot:
    uid: str
    pos: float          # start along the bar's axis, from the bar's inner origin
    length: float       # 0 for leaving or hidden items
    zone: str           # "start" | "cluster" | "end"
    hidden: bool = False

    @property
    def center(self) -> float:
        return self.pos + self.length / 2


@dataclass(frozen=True)
class DockLayout:
    length: float
    icon: float                          # effective icon size (may be scaled down to fit)
    gap: float
    slots: dict[str, Slot] = field(default_factory=dict)
    cluster: tuple[float, float] = (0.0, 0.0)
    hidden: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"length": self.length, "icon": self.icon, "gap": self.gap, "cluster": list(self.cluster),
                "hidden": list(self.hidden),
                "slots": {u: {"pos": s.pos, "len": s.length, "center": s.center, "zone": s.zone, "hidden": s.hidden}
                          for u, s in self.slots.items()}}


def _widget_len(wtype: str, icon: float, horizontal: bool) -> float:
    return icon * WIDGET_LENGTH.get(wtype, 1.0) if horizontal else icon


def _run(items: list[dict], icon: float, gap: float, horizontal: bool) -> tuple[list[tuple[str, float, float]], float]:
    """Lay items out one after another from 0. Returns [(uid, pos, len)] and the total length. A separator is
    a hairline (1/38 of an icon) with a little more breathing room on each side than between icons."""
    out, acc, prev = [], 0.0, None
    for it in items:
        if it.get("leaving"):
            out.append((it["uid"], max(0.0, acc - (gap / 2 if prev else 0)), 0.0))
            continue
        kind = it["kind"]
        if kind == "separator":
            length = icon / 38.0
        elif kind == "widget":
            length = _widget_len(it.get("widgetType", ""), icon, horizontal)
        else:
            length = icon
        if prev is not None:
            acc += gap * (1.4 if "separator" in (kind, prev) else 1.0)
        out.append((it["uid"], acc, length))
        acc += length
        prev = kind
    return out, acc


def compute_layout(items: list[dict], length: float, icon: float, gap: float, horizontal: bool = True,
                   zone_gap: float | None = None) -> DockLayout:
    """``items``: Dock rows in model order (uid, kind, widgetType, section, leaving).
    ``length``: the bar's inner length along its axis (logical px)."""
    zone_gap = icon * 0.9 if zone_gap is None else zone_gap
    rows = [it for it in items if not (it["kind"] == "separator" and it["uid"] == "sep:widgets")]
    widgets = [it for it in rows if it["kind"] == "widget"]
    split = math.ceil(len(widgets) / 2)
    start_w, end_w = widgets[:split], widgets[split:]
    cluster_items = [it for it in rows if it["kind"] != "widget"]

    start_run, start_len = _run(start_w, icon, gap, horizontal)
    end_run, end_len = _run(end_w, icon, gap, horizontal)
    room = max(0.0, length - start_len - end_len - (zone_gap if start_w else 0) - (zone_gap if end_w else 0))

    scale, hidden = 1.0, []
    visible = list(cluster_items)
    run, total = _run(visible, icon, gap, horizontal)
    if total > room > 0:
        scale = max(MIN_SCALE, room / total)
        run, total = _run(visible, icon * scale, gap * scale, horizontal)
        # Still too long: leave out the oldest Recently Used apps (the end of the list), then a dangling separator.
        while total > room and any(it.get("section") == "recent" and not it.get("leaving") for it in visible):
            idx = max(i for i, it in enumerate(visible) if it.get("section") == "recent" and not it.get("leaving"))
            hidden.append(visible.pop(idx)["uid"])
            if not any(it.get("section") == "recent" for it in visible):
                for i in range(len(visible) - 1, -1, -1):
                    if visible[i]["kind"] == "separator":
                        hidden.append(visible.pop(i)["uid"])
            run, total = _run(visible, icon * scale, gap * scale, horizontal)
    eff_icon, eff_gap = icon * scale, gap * scale

    # Centre the cluster on the display, sliding aside only if a widget zone would overlap it.
    lo = start_len + (zone_gap if start_w else 0)
    hi = length - end_len - (zone_gap if end_w else 0)
    origin = (length - total) / 2
    origin = min(max(origin, lo), max(lo, hi - total))

    slots: dict[str, Slot] = {}
    for uid, pos, ln in start_run:
        slots[uid] = Slot(uid, pos, ln, "start")
    for uid, pos, ln in end_run:
        slots[uid] = Slot(uid, length - end_len + pos, ln, "end")
    for uid, pos, ln in run:
        slots[uid] = Slot(uid, origin + pos, ln, "cluster")
    for uid in hidden:
        slots[uid] = Slot(uid, origin + total, 0.0, "cluster", hidden=True)
    for it in rows:   # any row not placed (cannot happen, but never leave QML without a slot)
        slots.setdefault(it["uid"], Slot(it["uid"], 0.0, 0.0, "cluster", hidden=True))
    return DockLayout(length=length, icon=eff_icon, gap=eff_gap, slots=slots, cluster=(origin, origin + total),
                      hidden=tuple(hidden))


def drop_index(pinned_centers: list[float], pointer: float) -> int:
    """Where a dragged pinned app lands among the other pinned apps: the number of centres before the pointer."""
    return sum(1 for c in pinned_centers if c < pointer)


def magnification(distance: float, icon: float, scale: float, amount: float = 1.0) -> float:
    """Visual scale of an icon whose centre is ``distance`` from the pointer (Gaussian falloff). Purely a
    transform: it never changes any slot."""
    if scale <= 1.0 or amount <= 0.0:
        return 1.0
    sigma = icon * 1.1
    return 1.0 + (scale - 1.0) * amount * math.exp(-(distance * distance) / (2 * sigma * sigma))
