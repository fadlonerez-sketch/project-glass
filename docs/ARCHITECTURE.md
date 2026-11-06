# Architecture

```
 Glass.Shell (pythonw -m glass.shell)            ── always on, one per user session
   ├ Qt Quick windows per display: TopBar.qml, Dock.qml (D3D11, alpha)
   ├ GlassController ("glass" in QML): theme, material, settings, Dynamic Glass state machine,
   │   media (GSMTC), battery/network (WinRT), audio (Core Audio), brightness (WMI), weather, notifications,
   │   power state, which display hosts the Dynamic Glass
   ├ DockController ("dock"): WindowTracker (WinEvent hooks; scans on a worker thread) → identity → AppRegistry
   │   → compute_dock() → compute_layout(); DockHover (hover state machine); Thumbnails (DWM live previews)
   ├ MarketsService ("markets"): quotes on a worker thread, market-aware refresh, freshness every 30 s
   ├ ShellServer  \\.\pipe\ProjectGlass.Shell.<user>        ← Glass.ControlCenter (owner token)
   ├ AppBars (SHAppBarMessage) · TaskbarController (reversible) · hotkeys
   ├ supervises → Glass.Automation  (restarted ≤3×/5 min)
   └ starts     → Glass.Recovery watchdog (detached)

 Glass.Automation (python -m glass.automation --parent-pid <shell>)   ── headless
   ├ UIA over comtypes on a dedicated MTA thread · CacheRequest tree reads · event handlers
   ├ \\.\pipe\ProjectGlass.Automation.<user>   ← Garvis adapter (garvis token), Shell & CC (owner token)
   └ automation.db: token hashes, scopes, deny list, stop flag, audit log

 Glass.ControlCenter (pythonw -m glass.controlcenter)  ── on demand, single instance
 Glass.Recovery      (pythonw -m glass.recovery --watch <pid> | --restore)
 LaunchDeck          (existing; reads %LOCALAPPDATA%\ProjectGlass\theme.json, accepts "launcher")
 Garvis              (existing; app/glass adapter + glass_* tools, GARVIS_GLASS_ENABLED)
```

There are four Glass processes, each for a concrete reason:
- **Engine:** UI Automation calls can block on hung apps and must never freeze the UI.
- **Control Center:** separate so it costs nothing while closed.
- **Watchdog:** has to outlive a crashed Shell.

## Packages

| Package | Contents |
|---|---|
| `glass/core` | Pure Python, no Qt, no Windows calls. Settings store (SQLite), colours, theme tokens, material model, app registry and `compute_dock`, Dynamic Glass state machine, weather client, IPC framing, DPAPI secrets, LaunchDeck bridge. |
| `glass/win` | Windows integration through documented APIs: ctypes / comtypes / pywinrt. |
| `glass/shell`, `glass/controlcenter`, `glass/recovery`, `glass/automation` | The processes. |
| `glass/ui` | QML (`qml/`), the Liquid Glass shader (`shaders/`), the glyph renderer. |

## Single sources of truth

- **Settings:** `settings.db`, written only by the Shell. The Control Center edits it over the Shell API, gets `settings.changed` and `theme.changed` back, and so previews live. If the Shell isn't running, the Control Center writes the same store directly, so nothing is lost.
- **Dock:**
  - `apps.db` holds identity, launch target, pin order and launch history;
  - the running set comes only from the tracker;
  - `compute_dock(records, running, …)` is a pure function, so the order is deterministic and tested.
  - Recently Used is derived from the running set, never the reverse. Apps running only on another desktop are excluded from Recent too, because they are not closed.
- **Appearance for other apps:** `theme.json`, written atomically on every change.

## The Dock

The Dock follows three rules.

**1. Geometry never depends on the pointer.**
- `glass.core.docklayout.compute_layout` turns the Dock rows into slots on a bar that spans the display. It places
  widgets at the two ends, centres the app cluster on the display, and shrinks the icons (then drops the oldest Recent
  items) only when the apps don't fit.
- QML positions each item from its slot. Magnification, lift, the launch bounce and drag are transforms on the item's
  visual, so neighbours never move and hit areas stay put.
- Slots animate only when the layout itself changes. A closing app stays briefly in place, flagged `leaving`: its slot
  collapses to zero while it fades, and its neighbours glide in.

**2. What appears above the bar follows one state machine.**
- `glass.core.dockhover.DockHoverMachine` has these states: idle, intent, tooltip, preview, in-preview, grace, pressed,
  dragging and menu.
- Hover intent is 150 ms and dismissal grace 300 ms (both configurable). Once something is shown, the Dock is "warm" and
  moving to another icon switches immediately.
- Open apps get window previews, closed apps a tooltip, and a click hides everything until the pointer leaves.
- It is event driven: one timer, only while a deadline is pending.

**3. Previews are drawn by Windows, not captured.**
- `glass.win.thumbnails.ThumbnailHost` registers DWM thumbnails (`DwmRegisterThumbnail`) of an app's windows inside the
  Dock window, aspect-fitted in device pixels, and fades them in once the preview has come to rest.
- It unregisters them when the preview changes or closes, and prunes them when a source window disappears.
- No pixel reaches Glass, nothing is saved, and the automation engine (Garvis) has no access to them.
- Minimised windows and windows on another desktop get a fallback card.

**Input regions.** Window regions also clip drawing. The Dock and the top bar therefore compute their input regions
from *target* geometry (where the preview or the Dynamic Glass is going), apply them at once, and shrink them only
after closing animations. At rest only the bar itself takes input.

## Power

`system.enabled` is the master switch, and the Shell applies it:

- **Off:** closes every Glass window, unregisters the AppBars (the work area returns to normal), restores the taskbar,
  and pauses the tracker, weather, markets, notification mirroring and the system sampler.
- **On:** reverses all of it.

The switch shown in the top bar, the quick controls and Control Center reflects `glass.powered`, the real state after
the transition. Off is remembered across restarts.

While Glass is off, the Shell process, its API, the hotkeys and the recovery watchdog stay up, so switching on is
instant and recovery still works. The computer-control engine keeps serving Garvis; it is not part of the visual shell.

## Markets

`glass.core.markets` (pure) parses Yahoo Finance chart data and decides:
- the session state;
- freshness: live / delayed / closed / stale / error;
- the next refresh: the configured interval while a market is open, rarely when all are closed, back-off after errors.

`glass.shell.markets.MarketsService` runs fetches on a worker thread and re-evaluates freshness every 30 s without
fetching. Quotes cached from an earlier session are always shown as stale.

## Identity of an application

1. AppUserModelID of the window (`SHGetPropertyStoreForWindow`) or of the packaged process (`GetApplicationUserModelId`).
2. Otherwise the executable path.
3. For generic hosts (python, java, …) without an AUMID, the executable plus the window class.

Names and launch targets come from the Applications folder (`shell:AppsFolder`, the Start menu's own list),
and aliases join the AUMID and exe keys of one app.

## IPC and security

- **Framing:** 4-byte length plus a UTF-8 JSON object; JSON-RPC shape; versioned `hello`.
- **Pipes:** named after a hash of the user SID. ACL: current user only (`UserAccessOption`). Remote clients are refused (`GetNamedPipeClientComputerNameW`).
- **Tokens:** two of them, `owner` and `garvis`, 256-bit. Each client's copy is stored DPAPI-protected in `secrets\`; servers keep SHA-256 hashes only.
- **Garvis permissions:** scopes (inspect / act / text / windows / input), a per-app deny list, and an emergency stop.
  - Glass's own windows carry `ProjectGlass.Protected`, so Garvis can't change its own permissions through the UI.
  - Every call is written to the audit log.
- **Trust boundary:** the logged-on user. Any process running as that user can read the DPAPI secrets, and that is documented rather than hidden.

## Windows integration rules

- Out-of-context WinEvent hooks only: nothing is injected into other processes. Event-driven, no polling. The exceptions are a 2.5 s notification poll, used only when identity is granted, and a 2 s CPU sample, only while that widget is shown.
- Documented APIs only:
  - `SHAppBarMessage` for space reservation and full-screen detection;
  - `IVirtualDesktopManager`, `IDesktopWallpaper`, `IShellItemImageFactory`;
  - GSMTC, `PowerManager`, `NetworkInformation`, `WiFiAdapter`, `Radio`, Core Audio, WMI.
- **Taskbar:** auto-hide state via `ABM_SETSTATE` plus `ShowWindow`, recorded before any change, restored on quit, crash, the hotkey or the Start-menu command, and re-applied after Explorer restarts (`TaskbarCreated`).
- **Sleep/resume** (`WM_POWERBROADCAST`), **display changes** (`WM_DISPLAYCHANGE`, screen add/remove) and **wallpaper changes** (`WM_SETTINGCHANGE`) all trigger re-layout or refresh.
