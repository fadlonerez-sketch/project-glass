# Status and known limitations

## Implemented and verified by automated tests

| Area | Evidence |
|---|---|
| Settings: store, validation, per-key independence, persistence, corruption recovery | `tests/core` |
| Liquid Glass parameter model: master × effect, values never reset; **Crystal default**; **presets**; **accent tint** with strength | `tests/core` |
| Theme tokens, accent tones with contrast guarantees, `theme.json` | `tests/core`, `tests/shell` |
| Dock contents: Open / Recent / pinned rules, determinism, persistence, aliases | `tests/core/test_dock_and_states.py` |
| **Dock geometry and hover behaviour** (pure logic, and the real QML at four display configurations) | `tests/core/test_dock_hover_layout.py`, `tests/shell/test_dock_qml.py` |
| **Window previews:** thumbnail host logic, registration and clean-up, fallbacks | `tests/shell/test_dock_previews.py` (fake DWM) |
| **Dynamic Glass:** the state machine, the "no auto-open when music starts" rule, the intent delay, island display selection | `tests/core`, `tests/shell` |
| **Markets:** data logic and freshness rules, and the service | `tests/core/test_markets.py`, `tests/shell/test_dock_previews.py` |
| **Power off/on** in the real Shell process: windows, AppBars, taskbar state, persistence, starting while off | `tests/shell/test_shell_process.py` |
| Shell process, engine, Garvis integration, LaunchDeck integration, recovery logic, weather | as before (see TESTING.md) |
| Idle cost and leak soak | `tools/perf/shell_soak.py` (off-screen) |

## Implemented, not yet exercised on the real desktop

No test injected input or put windows on the desktop, so these need your first run (checklist in TESTING.md):

- **Pointer feel:**
  - the 150 ms hover intent, 300 ms dismissal and 100 ms player intent (all tunable in Control Center);
  - magnification;
  - moving from an icon to its preview;
  - drag-and-drop.
- **Live DWM thumbnails** in previews. The API is documented and the host logic is tested with a fake DWM, but no real
  thumbnail has been looked at.
- **Dock keyboard navigation** (Ctrl+Alt+Shift+D): it needs real focus.
- **The Dynamic Glass following the active display** on your 144 Hz + 120 Hz, 100% + 150% pair.
- **Power off/on on the real Explorer:** taskbar and AppBar release and restore. Logic and real-process behaviour are
  tested in test mode, where the taskbar is untouched by design.
- **On-screen frame pacing of the v2 shader** (v1 measured 117 fps at 120 Hz). The idle CPU fix is measured off-screen
  only.
- From the earlier round: media controls, volume/brightness setting, Wi-Fi actions, the hotkeys, Garvis synthetic input.

## Limitations by design or by Windows

- **Refraction behind floating panels.** The bar and the Dock refract the real backdrop: your wallpaper, rendered exactly
  as Windows lays it out. The expanded player, flyouts, window previews and quote details refract the wallpaper layer,
  not the window under them. Highlights, glints, the caustic and the pointer light are lighting effects. See
  LIQUID_GLASS.md.
- **Window thumbnails are rectangles drawn by DWM above Glass's content.**
  - Glass can't round their corners or fade them together with the panel, so they fade in once the panel has settled
    and vanish at once when it moves or closes.
  - Minimised windows and windows on another virtual desktop have no live image (Windows doesn't provide one), so they
    show a fallback card.
- **Market data:** Yahoo Finance's chart endpoint is unofficial.
  - It has no published terms for apps, can change without notice, and quotes can be delayed by the exchange; the
    freshness label says so.
  - On a market holiday, Glass may only show "Closed · as of …" once the session data says so.
  - Cached quotes from an earlier session are always shown as stale.
- **The Dock lives on one display** (the main one), so that the screen space it reserves never jumps between displays and
  resizes windows. The Dynamic Glass, which reserves nothing extra, follows the active display.
- **While Glass is off**, the computer-control engine keeps serving Garvis. It is not part of the visual shell; quit Glass
  completely (Ctrl+Alt+Shift+R) to stop it too.
- **Windows notifications from other apps** need package identity (`scripts/install-identity.ps1`; per-user certificate
  trust, admin approval only with `-MachineWideTrust`; untested).
- **Tray icons** stay in the Windows taskbar; the supported route is the tray button.
- **No supported API** for switching audio output, power mode, Bluetooth pairing, or Wi-Fi networks needing more than a
  password: these open Settings.
- **UI Automation coverage** depends on each app. Elevated windows are refused (UIPI).
- **Same-user trust:** any process running as you can read the DPAPI tokens. Scopes, the deny list, the audit log and
  the stop button are the controls.
- **GARVIS_GLASS_ENABLED** defaults to false.
