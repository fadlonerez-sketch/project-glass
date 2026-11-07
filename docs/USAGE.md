# Using Project Glass

Day-to-day use: the power switch, recovery, the top bar, the Dock, Control Center and the Garvis tools. Install steps are in the [README](../README.md).

## Power: on and off

Glass has a master switch. **Off** puts Windows back exactly as normal:
- every Glass surface closes;
- the reserved screen space is released;
- the taskbar returns;
- background work pauses.

Settings are kept, and recovery stays armed. **On** brings back the whole configured experience. The switch always
shows Glass's real state.

| To switch Glass off | To switch it back on |
|---|---|
| Power button in the top bar, or **Turn Glass off** in the quick controls (click the Dynamic Glass) | **Start › Project Glass** |
| The Glass menu (the mark at the top left) | The switch at the top of **Control Center** |
| The switch at the top of **Control Center** | **Ctrl+Alt+Shift+G** |
| **Ctrl+Alt+Shift+G** | |

## Recovery: the Windows desktop is always one step away

| | |
|---|---|
| **Ctrl+Alt+Shift+R** | Owned by the watchdog process, so it works even if the Shell hangs. Restores the Windows taskbar and quits Glass. |
| Start › Project Glass › **Restore Windows Desktop** | Same, from the Start menu. |
| **Automatic** | If the Shell crashes, the watchdog restores the taskbar immediately and restarts Glass (at most 3 times in 10 minutes, then it stays on the standard desktop). |
| Manual | `.venv\Scripts\python -m glass.recovery --restore` |

Before Glass touches the taskbar, it records your original taskbar setting in
`%LOCALAPPDATA%\ProjectGlass\recovery-state.json`. That file is what every restore path uses.

## Using it

### Top bar
| Area | What it does |
|---|---|
| Glass mark (left) | Menu: Control Center, search, show the Windows tray, turn Glass off, restore the desktop. |
| Active app name | Shows the app in front. |
| **Dynamic Glass** (centre of the active display) | When music plays, the pill shows it compactly. **Rest the pointer** on it to expand the player, which stays attached to the pill. It reacts at once and opens after a 100 ms hover-intent delay, and it never opens by itself when music starts. **Click** opens the quick controls (Wi-Fi, Bluetooth, appearance, Garvis, the sliders, the power button). Neither takes keyboard focus or changes the active app. |
| **Markets** (either side of the pill) | Indices on the left, your watchlist on the right: price, daily change and a mini chart. A status always says how fresh the numbers are: Live, Delayed, Closed or Not updated since. Hover a ticker for details; click it to open the quote. |
| Dynamic Glass, other states | Notifications, volume/power/network pulses, and "Garvis is using …" with a **Stop** button. |
| Status area (right) | Tray access, network (Wi-Fi list, connect, toggle), sound, battery (health and power draw), clock (calendar and notification history). Each opens a flyout. Anything Windows has no supported API for opens the matching Settings page. |

### Dock
- **Layout:** a thin glass bar across the display:
  `widgets │ Search · Open apps | Recently Used │ widgets`.
  - The apps are centred.
  - Widgets sit at the two ends, in their configured order.
  - Nothing moves when you hover: icons swell under the pointer as a pure visual effect.
- **Pinned apps** follow the same Open/Recent rules, keep the order you set, and never drop out.
- **Window previews:** rest the pointer on an open app to see its windows, as live thumbnails drawn by Windows.
  - Click one to bring it forward.
  - The minimise/restore and close buttons appear on hover; close asks for a second click.
  - You can move freely from the icon to the preview, and from one app to the next.
  - Closed apps show their name instead.
- **Mouse:**
  - click: focus the app, or launch it;
  - click the focused app's only window: minimise it;
  - right-click: menu (windows, new window, keep in Dock, remove, quit);
  - middle-click: new instance;
  - drag pinned icons: reorder within their section;
  - drag one up and out: remove it.
- **Keyboard:** **Ctrl+Alt+Shift+D** moves focus to the Dock.
  - Arrows choose an item. **Up** (or Space) shows its windows; Left/Right pick one.
  - **Enter** opens it. **Shift+F10** opens the menu. **Esc** gives focus back.
- **Widgets**: Weather (Open-Meteo, city and units in Control Center › Dock), Calendar, Clock, System load, Garvis.
- **Virtual desktops**: shows the current desktop's apps by default. Garvis's automation desktop is never shown.

### Control Center
Power switch · Appearance (theme, full colour picker with HEX/RGB, saved colours, Apply/Reset) ·
Liquid Glass (Subtle / Liquid / Crystal presets with live previews, accent tint, every parameter) ·
Top Bar & Dynamic Glass · Dock (previews, apps, widgets, weather) · Markets (watchlist, indices, refresh) ·
Notifications · Applications (LaunchDeck) ·
System (startup, taskbar, recovery, display/battery/network/sound) · Garvis (permissions, deny list,
activity log, emergency stop) · About.

## Garvis

Enable it with `GARVIS_GLASS_ENABLED=true` in Garvis's `.env`, then restart Garvis.

Garvis then gets `glass_*` tools (list/inspect windows, find elements, act, enter text, keys, window ops, wait,
changes). These replace its legacy screen, mouse, keyboard, OCR and UIA tools. There is **no screenshot or OCR fallback**: if Glass isn't running,
the tools say so. Emergency stop: **Ctrl+Alt+Shift+Q**, the Stop button in the Dynamic Glass, or Control Center › Garvis.

