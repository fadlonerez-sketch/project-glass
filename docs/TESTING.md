# Testing

All numbers come from runs on this PC on 2026-11-05: Windows 11 Pro 26200, Python 3.14.5, PySide6 6.11.2, and two
displays (2560×1440 at 144 Hz, 100%; 2560×1600 at 120 Hz, 150%).

## Automated suites (design and Dock redesign round)

| Suite | Command | Result |
|---|---|---|
| **Project Glass** | `.venv\Scripts\python -m pytest` | **344 passed** (3 min 6 s, including the off-screen QML renders) |
| ├ core | `tests/core` | 193 passed |
| ├ shell | `tests/shell` | 100 passed |
| └ automation | `tests/automation` | 51 passed |
| **Garvis** (untouched this round) | `.venv\Scripts\python -m pytest` | 1993 passed, 2 skipped, **1 failed**: `test_real_ui_automation_reads_the_taskbar_passively`. It reads the *live* Windows taskbar through UI Automation, and the running Glass is hiding that taskbar, so there is nothing to read. It passed (1994 passed) when the taskbar was visible. |
| **LaunchDeck** (untouched this round) | `.venv\Scripts\python -m pytest` | 145 passed, 1 skipped |

Quick run without the render tests: `pytest -m "not slow"`.

### Off-screen subset (CI)

`.github/workflows/ci.yml` runs `ruff check .` and the tests that need no visible window, no real shell process and no
live UI Automation targets, with `QT_QPA_PLATFORM=offscreen`:

```bat
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/core tests/shell tests/automation/test_units.py tests/automation/test_server.py -m "not slow" --ignore tests/shell/test_shell_process.py --ignore tests/shell/test_dock_qml.py
```

On 2026-11-07 (Python 3.14.5, PySide6 6.11.2) this gave **305 passed, 2 deselected** locally.

### What the new tests cover

| Area | Tests |
|---|---|
| **Dock geometry:** the bar spans the display; the cluster is centred; one consistent spacing; widgets split between the ends; crowded Docks shrink icons and then drop the oldest Recent items; open apps are never dropped; deterministic; resolution-independent | `tests/core/test_dock_hover_layout.py` |
| **Dock hover state machine:** intent delay; sweeping shows nothing; tooltips for closed apps; icon → preview within the grace period; leaving dismisses; warm switching between apps; stale leave events; click suppression; choosing a window; drag; menu; the last window closing; dismiss | `tests/core/test_dock_hover_layout.py` |
| **Real Dock QML, off-screen, at 1080p, 1440p, a 150%-scaled laptop and 1280×720:** no warnings; thin full-width bar; **magnification moves no slot by even a pixel**; previews for open apps stay on the display and above the Dock; tooltips (never previews) for closed apps; at rest only the bar takes input; a closing app collapses while its neighbours close the gap | `tests/shell/test_dock_qml.py` |
| **Window previews** (DWM thumbnail host with a fake DWM): live vs fallback (minimised, other desktop, closed, unsupported); aspect fit in device pixels; the wanted set is followed; pruning when a window closes; fade-in and instant hide | `tests/shell/test_dock_previews.py` |
| **Departure animation rows**, **drag-and-drop reordering** within a section, **layout caching** | `tests/shell/test_dock_previews.py` |
| **Dynamic Glass:** music starting under a resting pointer does **not** open the player; a real pointer movement does; it expands within the intent delay; island display selection across displays; power state signals | `tests/shell/test_controller_server.py`, `test_dock_previews.py` |
| **Markets:** parsing, sessions, live/delayed/closed/stale/error, "never live when stale" across ages, refresh scheduling and back-off, cache, partial failures, search, symbol validation (77 tests, no network); the Qt service: a cached quote is stale; fresh is live; 47-minute-old is "Delayed · 47 min"; off fetches nothing | `tests/core/test_markets.py`, `tests/shell/test_dock_previews.py` |
| **Liquid Glass:** the Crystal default; presets complete and distinct; a preset then a tweak gives Custom; the tint switch keeps the strength; sliders independent (now including tint strength) | `tests/core/test_settings_theme_material.py` |
| **Real Shell process:** power off closes every window, releases the AppBars, restores the taskbar, is remembered and leaves other settings untouched; power on restores the same windows; a Glass that was off starts off; `markets.get` | `tests/shell/test_shell_process.py` |

### Isolation (changed this round)

Tests now use their own pipe names (a per-run `GLASS_PIPE_SUFFIX`). Before this, a Shell API test could connect to a
Glass already running on the PC. The process tests use the Shell's own window handles, never a window title.

## Visual review without touching the desktop

- `tools/preview/render.py` renders:
  - every top-bar state, the markets, flyouts (including power), the Dock at rest, magnified, with a tooltip and with a
    window preview;
  - light and dark, on a fixed 1920×1080 virtual display.
  - `--test-backdrop` puts a deliberately hostile backdrop behind them, to judge refraction and readability.
- `tools/preview/render_cc.py` renders every Control Center page in light and dark.
- `tools/preview/dockprobe.py` measures the real Dock QML; the Dock UI tests use it.
- `tools/perf/shell_soak.py` covers idle CPU and leaks (see LIQUID_GLASS.md). `tools/perf/render_perf.py` covers on-screen
  frame pacing; it shows overlay windows for about 13 s, so it was not re-run this round.

Reference renders are in `docs/preview/`. Live DWM thumbnails can't appear in off-screen captures, so previews there
show the fallback cards.

## Not verified on the real desktop

Per the standing rule, no test injected input, took over the desktop or showed windows on it. That leaves:
- real mouse feel: hover timing, magnification, dragging, moving from an icon to a preview;
- live DWM thumbnails in the preview;
- the Dynamic Glass moving between your two displays;
- on-screen frame pacing of the v2 shader;
- real AppBar release and restore on power off/on.

## Your first live run: checklist

**Before you start:** the Glass that is running now is the previous build. Press **Ctrl+Alt+Shift+R** (it quits and
restores the taskbar), then start **Start › Project Glass**.

1. **Dock:** a thin glass bar across the bottom of the main display.
   - Move along the icons: they swell under the pointer and nothing else moves.
   - Rest on Chrome or Explorer: after about 0.15 s its windows appear as **live** thumbnails.
   - Move up into the preview and click a window. Move between icons while a preview is open: it follows without delay.
   - Rest on a closed app: you see its name only.
2. **Dock keyboard:** press **Ctrl+Alt+Shift+D**, then arrows, **Up**, arrows, **Enter**. Press **Esc** to give focus
   back.
3. **Music:** start playing with the pointer resting near the top centre. The pill shows the music, and the player
   must **not** open.
   - Move onto the pill: it reacts at once and the player opens about 0.1 s later, attached to the pill.
   - The app you were using keeps focus.
4. **Displays:** click into a window on the laptop display. The Dynamic Glass and the markets move there, centred.
5. **Markets:** check the status next to your watchlist (Live / Delayed / Closed). Hover a ticker for details.
6. **Power:** click the power icon in the top bar and choose Turn Glass off. The taskbar returns and maximised windows
   regain the full screen. Press **Ctrl+Alt+Shift+G** (or Start › Project Glass): everything returns.
7. **Liquid Glass:** Control Center › Liquid Glass. Try the three presets, the accent tint and its strength.
8. **Idle CPU:** with nothing happening, Task Manager › Details › pythonw.exe (Glass) should sit near 0%.
9. **Recovery:** **Ctrl+Alt+Shift+R** still quits Glass and restores the taskbar, also while Glass is switched off.
