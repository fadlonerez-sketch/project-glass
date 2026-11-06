"""Dynamic Glass state system (pure; the Shell feeds it inputs and a clock).

States, highest priority first::

    CONTROL_CENTER   the user clicked the pill: the expanded control panel is open
    CONTROLS         an indicator flyout (network / battery / audio / tray / clock) is open
    MEDIA_EXPANDED   the pointer rests on the media pill (hover intent), interactive player shown
    NOTIFICATION     a notification is being presented (transient, queued)
    ACTIVITY         a system activity pulse: volume, brightness, power, network change (transient)
    GARVIS           Garvis is controlling the computer (persistent while active)
    MEDIA            something is playing (compact: artwork + visualiser)
    IDLE             the quiet capsule

User-driven states win over transient ones, transient ones over persistent ones. Hover and click are
separate inputs: hover only ever leads to MEDIA_EXPANDED (and only while media exists); a click toggles
CONTROL_CENTER.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GlassState(str, Enum):
    IDLE = "idle"
    MEDIA = "media"
    MEDIA_EXPANDED = "media_expanded"
    NOTIFICATION = "notification"
    ACTIVITY = "activity"
    CONTROL_CENTER = "control_center"
    GARVIS = "garvis"
    CONTROLS = "controls"


PRIORITY = [GlassState.CONTROL_CENTER, GlassState.CONTROLS, GlassState.MEDIA_EXPANDED, GlassState.NOTIFICATION,
            GlassState.ACTIVITY, GlassState.GARVIS, GlassState.MEDIA, GlassState.IDLE]


class HoverIntent:
    """Delayed expand on enter, delayed collapse on leave; re-entering cancels a pending collapse."""

    def __init__(self, expand_delay: float = 0.16, collapse_delay: float = 0.65):
        self.expand_delay = expand_delay
        self.collapse_delay = collapse_delay
        self.inside = False
        self.expanded = False
        self._deadline: float | None = None

    def enter(self, now: float) -> None:
        self.inside = True
        self._deadline = None if self.expanded else now + self.expand_delay

    def leave(self, now: float) -> None:
        self.inside = False
        self._deadline = (now + self.collapse_delay) if self.expanded else None

    def cancel(self) -> None:
        self.inside = False
        self.expanded = False
        self._deadline = None

    def tick(self, now: float) -> bool:
        if self._deadline is not None and now >= self._deadline:
            self.expanded = self.inside
            self._deadline = None
        return self.expanded

    def next_deadline(self) -> float | None:
        return self._deadline


def pick_island_screen(top_bars: list[str], primary: str, mode: str, foreground_screen: str, current: str) -> str:
    """Which display hosts the Dynamic Glass.

    ``top_bars``: displays that have a top bar. ``mode``: "active" (follow the frontmost app's display) or "primary".
    ``foreground_screen``: the frontmost app's display ("" when unknown or when the desktop itself is in front, in which
    case the island stays where it is rather than jumping around).
    """
    if not top_bars:
        return ""
    home = primary if primary in top_bars else top_bars[0]
    if mode != "active" or len(top_bars) == 1:
        return home
    if foreground_screen in top_bars:
        return foreground_screen
    return current if current in top_bars else home


class HoverArming:
    """Only a hover the user *made* counts.

    When the pill grows (music starts, a notification arrives) under a pointer that is resting near the top
    of the screen, the window system reports a hover although the user did nothing. Such a hover must not
    open the media player. A hover counts when the pointer actually moves after the pill last changed shape.
    """

    def __init__(self, settle: float = 1.5):
        self.settle = settle
        self._anchor: tuple[int, int] | None = None   # pointer position when the pill last changed shape
        self._changed_at = -1e9
        self.pending = False                          # inside, but not yet by the user's own movement

    def shape_changed(self, cursor: tuple[int, int], now: float) -> None:
        self._anchor = cursor
        self._changed_at = now

    def enter(self, cursor: tuple[int, int], now: float) -> bool:
        """The pointer is reported inside. True if this counts as the user hovering."""
        if self._anchor is not None and cursor == self._anchor and now - self._changed_at < self.settle:
            self.pending = True
            return False
        self.pending = False
        return True

    def move(self, cursor: tuple[int, int]) -> bool:
        """The pointer moved inside. True if this turns a pending hover into a real one."""
        if self.pending and cursor != self._anchor:
            self.pending = False
            return True
        return False

    def leave(self) -> None:
        self.pending = False


@dataclass
class Notice:
    kind: str                 # "notification" | "activity"
    payload: dict[str, Any]
    duration: float
    priority: int = 1         # 0 low, 1 normal, 2 high
    started: float | None = None


@dataclass
class Inputs:
    media_present: bool = False
    media_playing: bool = False
    control_center_open: bool = False
    controls_open: bool = False
    garvis_active: bool = False
    media_enabled: bool = True
    hover_expand_enabled: bool = True


@dataclass
class Resolved:
    state: GlassState
    payload: dict[str, Any] = field(default_factory=dict)


class DynamicGlassMachine:
    def __init__(self, expand_delay: float = 0.16, collapse_delay: float = 0.65):
        self.inputs = Inputs()
        self.hover = HoverIntent(expand_delay, collapse_delay)
        self._notifications: deque[Notice] = deque()
        self._activity: Notice | None = None
        self._current_notice: Notice | None = None
        self.last: Resolved = Resolved(GlassState.IDLE)

    # ------------------------------------------------------------------ inputs
    def set(self, **changes: Any) -> None:
        for k, v in changes.items():
            if not hasattr(self.inputs, k):
                raise AttributeError(k)
            setattr(self.inputs, k, v)
        if not self.inputs.media_present:
            self.hover.cancel()

    def pointer_enter(self, now: float) -> None:
        if self.inputs.media_present and self.inputs.media_enabled and self.inputs.hover_expand_enabled:
            self.hover.enter(now)

    def pointer_leave(self, now: float) -> None:
        self.hover.leave(now)

    def click(self) -> None:
        """A click toggles the control centre; it never means 'hover'."""
        self.inputs.control_center_open = not self.inputs.control_center_open
        if self.inputs.control_center_open:
            self.hover.cancel()

    def notify(self, payload: dict[str, Any], duration: float, priority: int = 1) -> None:
        notice = Notice("notification", payload, duration, priority)
        if priority >= 2:
            self._notifications.appendleft(notice)
        else:
            self._notifications.append(notice)
        while len(self._notifications) > 20:
            self._notifications.pop()

    def activity(self, payload: dict[str, Any], duration: float = 1.6, now: float | None = None) -> None:
        """Activity pulses replace each other (e.g. successive volume steps update one HUD)."""
        if self._activity and self._activity.started is not None and self._activity.payload.get("kind") == payload.get("kind"):
            self._activity.payload = payload
            self._activity.started = now if now is not None else self._activity.started
            self._activity.duration = duration
        else:
            self._activity = Notice("activity", payload, duration)

    def dismiss_notification(self) -> None:
        self._current_notice = None

    # ------------------------------------------------------------------ resolution
    def resolve(self, now: float) -> Resolved:
        self.hover.tick(now)
        # expire transients
        if self._current_notice and self._current_notice.started is not None:
            if now >= self._current_notice.started + self._current_notice.duration:
                self._current_notice = None
        if self._activity and self._activity.started is not None and now >= self._activity.started + self._activity.duration:
            self._activity = None

        i = self.inputs
        if i.control_center_open:
            return self._set(GlassState.CONTROL_CENTER, {})
        if i.controls_open:
            return self._set(GlassState.CONTROLS, {})
        if self.hover.expanded and i.media_present and i.media_enabled:
            return self._set(GlassState.MEDIA_EXPANDED, {})
        if self._current_notice is None and self._notifications:
            self._current_notice = self._notifications.popleft()
            self._current_notice.started = now
        if self._current_notice is not None:
            return self._set(GlassState.NOTIFICATION, self._current_notice.payload)
        if self._activity is not None:
            if self._activity.started is None:
                self._activity.started = now
            return self._set(GlassState.ACTIVITY, self._activity.payload)
        if i.garvis_active:
            return self._set(GlassState.GARVIS, {})
        if i.media_present and i.media_enabled:
            return self._set(GlassState.MEDIA, {"playing": i.media_playing})
        return self._set(GlassState.IDLE, {})

    def next_deadline(self) -> float | None:
        """When resolve() should be called again (earliest pending timer), for an event-driven shell."""
        candidates = [self.hover.next_deadline()]
        if self._current_notice and self._current_notice.started is not None:
            candidates.append(self._current_notice.started + self._current_notice.duration)
        if self._activity and self._activity.started is not None:
            candidates.append(self._activity.started + self._activity.duration)
        candidates = [c for c in candidates if c is not None]
        return min(candidates) if candidates else None

    def pending_notifications(self) -> int:
        return len(self._notifications)

    def _set(self, state: GlassState, payload: dict[str, Any]) -> Resolved:
        self.last = Resolved(state, payload)
        return self.last
