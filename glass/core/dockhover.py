"""The Dock's hover state machine (pure; the Shell feeds it pointer events and a clock).

States::

    IDLE        nothing under the pointer, nothing shown
    INTENT      the pointer rests on an icon; waiting out the hover-intent delay before showing anything
    TOOLTIP     a closed (Recently Used) app or the launcher: its name is shown
    PREVIEW     an open app: its windows are shown; the pointer is on the icon
    IN_PREVIEW  the pointer is inside the window preview
    GRACE       the pointer left the icon or preview; the preview/tooltip stays until the dismissal delay ends
    PRESSED     the icon was clicked; nothing re-opens until the pointer leaves that icon
    DRAGGING    an icon is being dragged; nothing is shown
    MENU        a context menu is open; previews and tooltips wait for it to close

Rules that make it feel calm rather than nervous:

* Hover intent: nothing appears until the pointer has rested on an icon for ``intent_delay`` (~150 ms).
  Sweeping the pointer across the Dock shows nothing.
* Once something is shown, the Dock is "warm": moving to another icon switches immediately, so browsing
  neighbouring apps flows without repeated delays.
* Dismissal grace: leaving an icon or the preview starts a ``dismiss_delay`` (~300 ms); arriving at the
  preview (or back at the icon) within it keeps everything open. The gap between icon and preview can
  therefore be crossed comfortably.
* A click hides everything and nothing re-opens on that icon until the pointer has left it.
* Previews only ever show for apps with windows; closed apps get a tooltip, never an empty preview.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HoverState(str, Enum):
    IDLE = "idle"
    INTENT = "intent"
    TOOLTIP = "tooltip"
    PREVIEW = "preview"
    IN_PREVIEW = "in_preview"
    GRACE = "grace"
    PRESSED = "pressed"
    DRAGGING = "dragging"
    MENU = "menu"


@dataclass(frozen=True)
class HoverView:
    """What the Dock should show right now."""
    state: HoverState
    hovered: str          # the icon under the pointer ("" = none), for highlights
    preview: str          # app whose window preview is shown ("" = none)
    tooltip: str          # item whose name tooltip is shown ("" = none)


class DockHoverMachine:
    def __init__(self, intent_delay: float = 0.15, dismiss_delay: float = 0.30, previews: bool = True):
        self.intent_delay = intent_delay
        self.dismiss_delay = dismiss_delay
        self.previews = previews
        self.state = HoverState.IDLE
        self.hovered = ""           # icon under the pointer
        self.hovered_open = False   # does it have windows
        self.shown = ""             # item whose preview/tooltip is shown
        self.shown_kind = ""        # "preview" | "tooltip" | ""
        self.pressed = ""
        self._deadline: float | None = None

    # ------------------------------------------------------------------ inputs
    def icon_enter(self, item: str, has_windows: bool, now: float) -> None:
        if self.state in (HoverState.DRAGGING, HoverState.MENU):
            self.hovered, self.hovered_open = item, has_windows
            return
        self.hovered, self.hovered_open = item, has_windows
        if self.state == HoverState.PRESSED and item == self.pressed:
            return
        self.pressed = ""
        if self.shown and self.state in (HoverState.TOOLTIP, HoverState.PREVIEW, HoverState.IN_PREVIEW, HoverState.GRACE):
            # Warm: something is showing, so switch straight to this icon.
            self._show(item, has_windows)
            return
        self.state = HoverState.INTENT
        self._deadline = now + self.intent_delay

    def icon_leave(self, item: str, now: float) -> None:
        if item and item != self.hovered:
            return                      # a stale leave from an icon we already moved off
        self.hovered, self.hovered_open = "", False
        if self.state in (HoverState.DRAGGING, HoverState.MENU):
            return
        if self.state == HoverState.PRESSED:
            self.state, self.pressed = HoverState.IDLE, ""
            return
        if self.state == HoverState.INTENT:
            self._reset()
            return
        if self.state in (HoverState.TOOLTIP, HoverState.PREVIEW):
            self.state = HoverState.GRACE
            self._deadline = now + (self.dismiss_delay if self.shown_kind == "preview" else self.dismiss_delay * 0.5)

    def preview_enter(self, now: float) -> None:
        if self.shown_kind == "preview" and self.state in (HoverState.PREVIEW, HoverState.GRACE):
            self.state = HoverState.IN_PREVIEW
            self._deadline = None

    def preview_leave(self, now: float) -> None:
        if self.state == HoverState.IN_PREVIEW:
            if self.hovered:
                # straight back onto an icon (that icon_enter already switched what is shown)
                self.state = HoverState.PREVIEW if self.shown_kind == "preview" else HoverState.TOOLTIP
                return
            self.state = HoverState.GRACE
            self._deadline = now + self.dismiss_delay

    def press(self, item: str) -> None:
        """A click on an icon (launch / activate): hide everything until the pointer leaves it."""
        self._reset()
        self.state = HoverState.PRESSED
        self.pressed = item
        self.hovered = item

    def choose_window(self) -> None:
        """A window was picked in the preview: it is activated, so the preview closes."""
        self._reset()
        if self.hovered:
            self.state, self.pressed = HoverState.PRESSED, self.hovered

    def drag_start(self) -> None:
        self._reset()
        self.state = HoverState.DRAGGING

    def drag_end(self, now: float) -> None:
        if self.state == HoverState.DRAGGING:
            self.state = HoverState.IDLE
            if self.hovered:
                self.pressed = self.hovered
                self.state = HoverState.PRESSED

    def menu_open(self) -> None:
        self._reset()
        self.state = HoverState.MENU

    def menu_close(self, now: float) -> None:
        if self.state == HoverState.MENU:
            self.state = HoverState.IDLE
            if self.hovered:
                self.state, self.pressed = HoverState.PRESSED, self.hovered

    def dismiss(self) -> None:
        """Escape, another app came forward, the Dock hid: close everything now."""
        hovered = self.hovered
        self._reset()
        self.hovered = hovered
        if hovered:
            self.state, self.pressed = HoverState.PRESSED, hovered

    def windows_changed(self, item: str, count: int) -> None:
        """The shown app's windows changed; an app whose last window closed can't keep a preview."""
        if item == self.hovered:
            self.hovered_open = count > 0
        if item == self.shown and self.shown_kind == "preview" and count == 0:
            if self.state == HoverState.IN_PREVIEW or not self.hovered:
                self._reset()
            else:
                self._show(item, False)

    def show_now(self, item: str, has_windows: bool) -> None:
        """Keyboard navigation: show this item's preview or tooltip immediately (no hover intent)."""
        self.hovered, self.hovered_open = item, has_windows
        self.pressed = ""
        self._show(item, has_windows)

    def set_delays(self, intent: float | None = None, dismiss: float | None = None) -> None:
        if intent is not None:
            self.intent_delay = intent
        if dismiss is not None:
            self.dismiss_delay = dismiss

    # ------------------------------------------------------------------ clock
    def tick(self, now: float) -> HoverView:
        if self._deadline is not None and now >= self._deadline:
            self._deadline = None
            if self.state == HoverState.INTENT and self.hovered:
                self._show(self.hovered, self.hovered_open)
            elif self.state == HoverState.GRACE:
                self._reset()
        return self.view()

    def next_deadline(self) -> float | None:
        return self._deadline

    def view(self) -> HoverView:
        return HoverView(self.state, self.hovered,
                         self.shown if self.shown_kind == "preview" else "",
                         self.shown if self.shown_kind == "tooltip" else "")

    # ------------------------------------------------------------------ internals
    def _show(self, item: str, has_windows: bool) -> None:
        self._deadline = None
        if has_windows and self.previews:
            self.shown, self.shown_kind, self.state = item, "preview", HoverState.PREVIEW
        else:
            self.shown, self.shown_kind, self.state = item, "tooltip", HoverState.TOOLTIP

    def _reset(self) -> None:
        self.state = HoverState.IDLE
        self.shown, self.shown_kind = "", ""
        self.pressed = ""
        self._deadline = None
