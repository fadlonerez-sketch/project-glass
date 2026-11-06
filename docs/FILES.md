# Files

## Project Glass (all new, in %USERPROFILE%\ProjectGlass)

- docs/ARCHITECTURE.md
- docs/LIMITATIONS.md
- docs/LIQUID_GLASS.md
- docs/NOTIFICATIONS.md
- docs/PROTOCOL.md
- glass/__init__.py
- glass/automation/__init__.py
- glass/automation/__main__.py
- glass/automation/aioclient.py
- glass/automation/engine.py
- glass/automation/events.py
- glass/automation/inputs.py
- glass/automation/main.py
- glass/automation/qtclient.py
- glass/automation/server.py
- glass/automation/store.py
- glass/automation/uia.py
- glass/automation/win.py
- glass/controlcenter/__init__.py
- glass/controlcenter/__main__.py
- glass/controlcenter/bridge.py
- glass/core/__init__.py
- glass/core/apps.py
- glass/core/colors.py
- glass/core/db.py
- glass/core/ipc.py
- glass/core/launchdeck.py
- glass/core/material.py
- glass/core/paths.py
- glass/core/pipeclient.py
- glass/core/security.py
- glass/core/settings.py
- glass/core/states.py
- glass/core/theme.py
- glass/core/weather.py
- glass/recovery/__init__.py
- glass/recovery/__main__.py
- glass/shell/__init__.py
- glass/shell/__main__.py
- glass/shell/app.py
- glass/shell/backdrop.py
- glass/shell/controller.py
- glass/shell/dock.py
- glass/shell/extras.py
- glass/shell/server.py
- glass/ui/__init__.py
- glass/ui/glyphs.py
- glass/ui/qml/Dock.qml
- glass/ui/qml/TopBar.qml
- glass/ui/qml/components/BatteryIcon.qml
- glass/ui/qml/components/ControlTile.qml
- glass/ui/qml/components/GlassPanel.qml
- glass/ui/qml/components/GlassSlider.qml
- glass/ui/qml/components/GlassSurface.qml
- glass/ui/qml/components/Glyphs.js
- glass/ui/qml/components/Icon.qml
- glass/ui/qml/components/IconButton.qml
- glass/ui/qml/components/Label.qml
- glass/ui/qml/components/Motion.js
- glass/ui/qml/components/SpeakerIcon.qml
- glass/ui/qml/components/Toggle.qml
- glass/ui/qml/components/WifiIcon.qml
- glass/ui/qml/controlcenter/AboutPage.qml
- glass/ui/qml/controlcenter/AppearancePage.qml
- glass/ui/qml/controlcenter/ApplicationsPage.qml
- glass/ui/qml/controlcenter/ColorPicker.qml
- glass/ui/qml/controlcenter/ControlCenter.qml
- glass/ui/qml/controlcenter/DockPage.qml
- glass/ui/qml/controlcenter/GarvisPage.qml
- glass/ui/qml/controlcenter/GlassPage.qml
- glass/ui/qml/controlcenter/GlassPreview.qml
- glass/ui/qml/controlcenter/NotificationsPage.qml
- glass/ui/qml/controlcenter/PushButton.qml
- glass/ui/qml/controlcenter/Row_.qml
- glass/ui/qml/controlcenter/Section.qml
- glass/ui/qml/controlcenter/Segmented.qml
- glass/ui/qml/controlcenter/SettingChoice.qml
- glass/ui/qml/controlcenter/SettingSlider.qml
- glass/ui/qml/controlcenter/SettingToggle.qml
- glass/ui/qml/controlcenter/SystemPage.qml
- glass/ui/qml/controlcenter/TopBarPage.qml
- glass/ui/qml/dock/DockItem.qml
- glass/ui/qml/dock/DockMenu.qml
- glass/ui/qml/dock/WeatherIcon.qml
- glass/ui/qml/dock/WeatherPopover.qml
- glass/ui/qml/dock/Widgets.qml
- glass/ui/qml/dock/WindowPicker.qml
- glass/ui/qml/topbar/ControlPanel.qml
- glass/ui/qml/topbar/DynamicGlass.qml
- glass/ui/qml/topbar/Equalizer.qml
- glass/ui/qml/topbar/Flyouts.qml
- glass/ui/qml/topbar/MediaProgress.qml
- glass/ui/shaders/liquidglass.frag
- glass/ui/shaders/liquidglass.frag.qsb
- glass/win/__init__.py
- glass/win/appwin.py
- glass/win/audio.py
- glass/win/display.py
- glass/win/icons.py
- glass/win/launch.py
- glass/win/media.py
- glass/win/notifications.py
- glass/win/shellbar.py
- glass/win/shellcom.py
- glass/win/startup.py
- glass/win/system.py
- glass/win/tracker.py
- glass/win/winapi.py
- glass/win/winrt_worker.py
- packaging/AppxManifest.xml
- scripts/install-identity.ps1
- scripts/install.py
- tests/__init__.py
- tests/automation/__init__.py
- tests/automation/conftest.py
- tests/automation/test_engine_live.py
- tests/automation/test_qtclient.py
- tests/automation/test_server.py
- tests/automation/test_units.py
- tests/conftest.py
- tests/core/test_dock_and_states.py
- tests/core/test_settings_theme_material.py
- tests/core/test_weather_ipc_launchdeck.py
- tests/shell/test_controller_server.py
- tests/shell/test_dock_controller.py
- tests/shell/test_render_recovery.py
- tests/shell/test_shell_process.py
- tools/perf/render_perf.py
- tools/preview/render.py
- tools/preview/render_cc.py
- tools/testtarget/target.py
- tools/testtarget/win32target.py
- README.md, requirements.txt, pytest.ini, .gitignore

## Garvis (%USERPROFILE%\PycharmProjects\garvis)

Modified (originals in ..\garvis-backups\pre-glass-2026-11-05\):
- app/core/config.py: glass_enabled, glass_pipe_name, glass_secrets_dir
- app/agent/build.py: glass tools in build_extra_tools (legacy desktop tools dropped when enabled), GlassNotifier, context note
- app/ui/dashboard.py: a TOOL_GROUPS entry for glass_ tools

New:
- app/glass/__init__.py, build.py, client.py, credentials.py, notifier.py, tools.py
- tests/test_glass_adapter.py, tests/test_glass_e2e.py

## LaunchDeck (%USERPROFILE%\LaunchDeck; backup ..\LaunchDeck-backups\pre-glass-2026-11-05.tar)

Modified: launchdeck/ui/theme.py, launchdeck/ui/launcher_window.py, launchdeck/winsys/single_instance.py, launchdeck/app/application.py, main.py, tests/conftest.py
New: tests/test_glass_integration.py

## Design & Dock redesign round (2026-11-05, evening)

Garvis and LaunchDeck: **no files changed** in this round.

**New Project Glass files**
- `glass/core/dockhover.py`: the Dock hover state machine
- `glass/core/docklayout.py`: Dock geometry
- `glass/core/markets.py`: market data, sessions, freshness rules
- `glass/shell/markets.py`: the markets service (Qt)
- `glass/win/thumbnails.py`: DWM live window thumbnails
- `glass/ui/qml/dock/WindowPreview.qml`
- `glass/ui/qml/topbar/MarketStrip.qml`
- `glass/ui/qml/controlcenter/MarketsPage.qml`
- `glass/ui/qml/controlcenter/PresetCard.qml`
- `tests/core/test_dock_hover_layout.py`
- `tests/core/test_markets.py`
- `tests/shell/test_dock_previews.py`
- `tests/shell/test_dock_qml.py`
- `tools/preview/dockprobe.py`
- `tools/perf/shell_soak.py`
- `docs/perf/shell_soak.json`

**Modified Project Glass files**
- Core:
  - `glass/core/settings.py`: Crystal defaults, accent tint, Dock, markets, power and island settings
  - `glass/core/material.py`: presets, tint uniforms
  - `glass/core/states.py`: hover arming, island selection
- Windows and Shell:
  - `glass/win/tracker.py`: worker-thread scans
  - `glass/shell/app.py`: power, island, markets, hotkeys, API
  - `glass/shell/controller.py`
  - `glass/shell/dock.py`
- Control Center: `glass/controlcenter/bridge.py`, `glass/controlcenter/__main__.py`
- Shader: `glass/ui/shaders/liquidglass.frag`, `liquidglass.frag.qsb` (v2 material)
- QML:
  - `glass/ui/qml/components/GlassSurface.qml`
  - `glass/ui/qml/Dock.qml` and `glass/ui/qml/dock/DockItem.qml` (both rewritten)
  - `glass/ui/qml/dock/Widgets.qml`
  - `glass/ui/qml/TopBar.qml`
  - `glass/ui/qml/topbar/DynamicGlass.qml`, `Equalizer.qml`, `ControlPanel.qml`, `Flyouts.qml`
  - `glass/ui/qml/controlcenter/ControlCenter.qml`, `GlassPage.qml`, `DockPage.qml`, `TopBarPage.qml`
- Tools: `tools/preview/render.py` (deterministic virtual display), `tools/preview/render_cc.py`
- Tests:
  - `tests/conftest.py`: per-run pipe names
  - `tests/core/test_settings_theme_material.py`
  - `tests/shell/test_controller_server.py`
  - `tests/shell/test_render_recovery.py`
  - `tests/shell/test_shell_process.py`
  - `tests/automation/test_units.py`
- Docs: `README.md`, `docs/ARCHITECTURE.md`, `docs/LIQUID_GLASS.md`, `docs/TESTING.md`, `docs/LIMITATIONS.md`, this
  file, `docs/preview/*` (regenerated)

**Removed**
- `glass/ui/qml/dock/WindowPicker.qml`: replaced by the hover window previews
