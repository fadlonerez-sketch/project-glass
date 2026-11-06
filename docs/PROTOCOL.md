# Project Glass — Computer Control Protocol (Automation pipe), version 1

`Glass.Automation` (`python -m glass.automation`) is a headless process that exposes semantic Windows
UI Automation over a named pipe. It never takes screenshots, never runs OCR and never runs AI models.
Garvis talks to it through its isolated adapter (`garvis/app/glass/`). The Shell and the Control Center
also connect: they use the *owner* token for status, the activity feed, permissions and the emergency stop.

## Transport

* Pipe: `\\.\pipe\ProjectGlass.Automation.<sha256(user SID)[:16]>` (`glass.core.security.pipe_path("Automation")`).
* ACL: current user only (Qt `QLocalServer.UserAccessOption`). The server also rejects remote clients
  (`GetNamedPipeClientComputerNameW` succeeds only for remote clients) and logs the client PID and image.
* Framing: a 4-byte little-endian length, then a UTF-8 JSON object (`glass.core.ipc`). The maximum frame is 8 MB.
* Messages follow the JSON-RPC shape: `{"id", "method", "params"}`, then `{"id", "result"}` or `{"id", "error": {"code", "message", "data"}}`.
  Notifications from the server have no `id`: `{"method": "event", "params": {...}}`.
* Requests on one connection are answered in order. Each client may keep **one** connection; reconnects are expected.

## Handshake

The first request must be `hello`:

```json
{"id":1,"method":"hello","params":{"protocol":1,"client":"garvis","client_version":"x","token":"<token>"}}
```

The result is:

```json
{"protocol":1,"server":"Glass.Automation","server_version":"1.0.0","session":"…",
 "client":"garvis","scopes":["inspect","act","text","windows","input"],
 "capabilities":["windows","tree","find","act","text","window_ops","keys","watch","wait","verify","coverage"],
 "stopped":false}
```

* A protocol version mismatch returns `unsupported_version` with `data.supported`.
* Tokens:
  * `owner`: Shell and Control Center. It may call `admin.*`.
  * `garvis`: scopes come from the permission store.
  * The plain tokens live DPAPI-protected in `%LOCALAPPDATA%\ProjectGlass\secrets\{owner,garvis}.dpapi`.
  * The engine stores only their SHA-256 hashes (`automation.db`).
  * The engine creates both tokens on first start.

## Scopes

| Scope | Allows |
|---|---|
| `inspect` | `apps.list`, `windows.*` reads, `window.inspect`, `tree.get`, `element.find`, `element.get`, `watch.*`, `wait.for` |
| `act` | `element.act` with semantic actions: invoke, toggle, select, expand, collapse, scroll, scroll_into_view, focus, set_range, default_action |
| `text` | `element.act` `set_value` (ValuePattern, no keystrokes) |
| `windows` | `window.focus`, `window.set_state`, `window.move` |
| `input` | **synthetic input**, always reported as such: `element.act` `click` and `type_text`, and `input.keys`. The target window must be in the foreground. |

Also enforced for every call that targets a window:

* **Deny list** of process image names. Defaults:
  * password managers;
  * `CredentialUIBroker.exe`, `consent.exe`, `LogonUI.exe`, `SecHealthUI.exe`;
  * Glass's own Control Center, so a client can't change its own permissions.
* **Emergency stop**: while stopped, every non-admin call except `hello` and `engine.status` fails with `stopped`.

## Element references

`ref` = `"<hwnd hex>:<runtimeId parts joined by '.'>"`, for example `"1a0b2c:42.660012.4"`.

* A ref is self-contained. The engine resolves it by searching the window's subtree for that exact
  `RuntimeId` (cached refs are re-validated).
* If the element is gone, the call fails with `stale_reference`, and **no other element is ever
  substituted**. The client must re-query.
* The window part must still be a live window; otherwise the error is also `stale_reference`.

## Node shape (compact)

```json
{"ref":"1a0b2c:42.660012.4","type":"Button","name":"Save","aid":"SaveBtn","cls":"Button",
 "value":"…","states":["disabled","focusable","focused","offscreen","selected","checked|unchecked|indeterminate","expanded|collapsed|partially_expanded|leaf","readonly","password"],
 "actions":["invoke","toggle","select","expand","collapse","set_value","scroll","focus","default_action"],
 "rect":[x,y,w,h],"children":[…],"more":12}
```

* Empty or false fields are omitted. Elements are enabled unless `disabled` is listed.
* `set_value` is listed only for text-entry types (Edit, ComboBox, Document, Spinner, …). Some toolkits (Qt) advertise a writable ValuePattern on buttons and windows too, and listing it there would mislead clients.
* `value` is never returned for password fields.
* `more` counts children cut off by the limits.

## Methods

| Method | Scope | Params → Result |
|---|---|---|
| `hello` | — | see above |
| `engine.status` | — | → `{stopped, scopes, deny_list, uptime_s, clients}` |
| `apps.list` | inspect | `{all_desktops?}` → `[{app_id, name, exe, pids, windows:[hwnd]}]` |
| `windows.list` | inspect | `{all_desktops?: false, include_hidden?: false}` → `[{hwnd, title, app, exe, pid, rect, state, foreground, on_current_desktop, elevated}]` |
| `windows.find` | inspect | `{query}` → windows whose title or app matches. Ambiguous results are returned as a list; the engine never picks one. |
| `window.inspect` | inspect | `{hwnd}` → `{window, framework, coverage:{level: full\|partial\|minimal\|none, controls, named, actionable, note}, focused}` |
| `tree.get` | inspect | `{hwnd \| ref, depth=6 (≤12), max_nodes=400 (≤3000), include_offscreen=false, filter?: "interactive"}` → `{root: node, count, truncated}` |
| `element.find` | inspect | `{hwnd \| ref, name?, match: exact\|contains\|regex = contains, type?, aid?, cls?, max=20}` → `{matches:[node], total}` |
| `element.get` | inspect | `{ref}` → node with fresh properties, plus `text` (TextPattern, ≤4000 chars) |
| `element.act` | act/text/input | `{ref, action, value?, direction?: up\|down\|left\|right, amount?: line\|page\|percent, percent?, verify: true, verify_ms: 800}` → `{performed, method, verification:{changed:{prop:[before,after]}, focused, new_windows, closed_windows, element_gone}}` |
| `input.keys` | input | `{hwnd, keys}` (for example `"ctrl+s"`, `"enter"`, `"alt+f4"`). The window is focused first, and the call fails if it can't be. → `{performed, method:"synthetic_keys", foreground}` |
| `window.focus` | windows | `{hwnd}` → `{foreground}` |
| `window.set_state` | windows | `{hwnd, state: minimize\|maximize\|restore\|close}` → `{state}` |
| `window.move` | windows | `{hwnd, x?, y?, width?, height?}` → `{rect}` |
| `watch.subscribe` | inspect | `{hwnd?, events: [window_opened, window_closed, focus_changed, structure_changed, property_changed, invoked]}` → `{subscription}`. The engine then pushes `event` notifications: `{subscription, type, hwnd, ref?, name?, property?, value?, time}`. |
| `watch.unsubscribe` | inspect | `{subscription}` |
| `wait.for` | inspect | `{condition:{kind: window_exists\|window_gone\|element_exists\|element_gone\|value_equals\|name_contains\|focus_on, hwnd?, ref?, query?, name?, type?, value?}, timeout_ms ≤ 30000}` → `{satisfied, elapsed_ms, match?}` |
| `admin.permissions.get` | owner | → `{clients:{owner:[…], garvis:[…]}, deny_list:[…], all_scopes:[…], stopped}` |
| `admin.permissions.set` | owner | `{client?: "garvis", scopes?: […], deny_list?: […]}` → `{scopes?, deny_list?}`. Takes effect immediately for connected sessions; the owner always keeps every scope. |
| `notify.post` | inspect | `{title, body?, kind?: info\|confirmation\|reminder\|message, app?}` → `{posted:true}`. The engine broadcasts it to admin subscribers as notification `notification` `{title, body, kind, app, client, time}`. Rate limit: 10 per minute per client (`busy`). |
| `admin.audit.read` | owner | `{limit=200, since_id?}` → `{entries:[{id, time, client, method, target, outcome, detail}]}`. Without `since_id` the newest come first; with it, entries newer than that id come in ascending order. |
| `admin.stop` / `admin.resume` | owner | → `{stopped}` |
| `admin.subscribe` | owner | Starts `activity` notifications: `{client, method, target, outcome, time}`, `control_state {active, client, app}` and `stopped {stopped}` |

## Actions and verification

* `element.act` uses UI Automation patterns first:

  | Action | Pattern |
  |---|---|
  | `invoke` | Invoke |
  | `toggle` | Toggle |
  | `select` | SelectionItem |
  | `expand` / `collapse` | ExpandCollapse |
  | `set_value` | Value |
  | `scroll` | Scroll |
  | `scroll_into_view` | ScrollItem |
  | `set_range` | RangeValue |
  | `default_action` | LegacyIAccessible.DoDefaultAction |
  | `focus` | SetFocus |

  These work on background windows and move neither the mouse nor the focus.
* If the element lacks the pattern, the call fails with `unsupported_pattern` and lists `data.available` actions. There is **no** automatic click fallback.
* `click` and `type_text` are explicit synthetic input (scope `input`). The target window is focused first, and the response says `method: "synthetic_click"`.
* `verification.observed_change` is false when nothing observable changed. That's common for an Invoke whose effect is elsewhere in the window, and for toolkits that accept a pattern call but ignore it (for example Qt tree items ignore ExpandCollapse). Clients must not report success on a false `observed_change` without checking.
* With `verify`, the engine snapshots the target (name, value, toggle/expand/selection state, enabled), the focused element and the process's top-level windows. It acts, then waits up to `verify_ms` for a change (UIA events and short re-reads). It reports exactly what changed. `changed: {}` means no observable effect, which is reported, never hidden.

## Coverage

`window.inspect.coverage` reports how well an app exposes itself, from the control view:

* `full`: many named, actionable controls (typical of WPF, WinUI, UWP, Qt with accessibility, most Win32).
* `partial`: some unnamed or unactionable regions (common in Electron/Chromium before accessibility warms up).
* `minimal` / `none`: custom-drawn surfaces, games, or a canvas exposing only a pane.

Engine flags for tests: `--fake-input` records `click`, `type_text`, `input.keys` and `window.focus` instead of performing them, and `engine.status` then returns `input_log`. `--pipe-name` and `--data-dir` isolate a test instance; `--parent-pid` makes the engine exit with its parent.

Self-protection: windows carrying the `ProjectGlass.Protected` window property (`SetPropW(hwnd, "ProjectGlass.Protected", 1)`; the Shell and Control Center must set it) and windows of the client's own process can be inspected but never acted on.

Clients must tell the user plainly when semantic control is not possible. No screenshot or OCR fallback exists.

## Errors

The error codes are in `glass.core.ipc.ErrorCode`:

`unauthorized`, `forbidden_scope`, `denied_app`, `stopped`, `stale_reference`, `not_found`, `ambiguous`, `unsupported_pattern`, `insufficient_semantics`, `elevated_target`, `invalid_params`, `timeout`, `unsupported_version`, `internal`, `unknown_method`, `busy`.
