# Liquid Glass

## Settings and how they combine

| Setting | Default (Crystal Glass) | Effect |
|---|---:|---|
| Overall Intensity | **100%** | Master control |
| Blur | **100%** | Mip-chain blur of the backdrop (up to 6 mip levels), smoothed with a rotated 9-tap kernel |
| Light Refraction | **100%** | Rays bend through a circular-profile bevel around the edge (steepening towards the rim), a slight magnification of the flat top, and chromatic dispersion that grows towards the rim |
| Specular Shine | **100%** | Fresnel brightening at the rim, a key rim highlight (upper left), an internal reflection on the opposite rim, a thin glint inside the top edge, a top sheen, a caustic along the bottom inner edge, and the pointer light |
| Accent tint | **On** | The accent colour tints the glass body itself |
| Tint strength | **40%** | How much colour the glass holds |
| Material appearance (frost) | 12% | Crystal clear ↔ frosted: diffuses highlights and lifts the body |
| Edge treatment | 80% | Hairline and rim definition |
| Visual depth | 70% | Two-layer shadow (wide ambient + tight key) and elevation |
| Appearance › Transparency | 60% | How see-through the tint becomes at full intensity |

**Rule:** what you see of an effect is *its value × Overall Intensity*. The multiplication happens in the shader
(`glass/ui/shaders/liquidglass.frag`). Stored values are never changed by the master. At 0% the surface is exactly the
base theme material: an opaque tint, the hairline and the shadow, because edge and depth belong to the base material.
Every slider is validated and stored independently. The tests change each slider and assert that the others are untouched
(`tests/core/test_settings_theme_material.py`).

## Presets

| Preset | Identity | Intensity | Blur | Refraction | Shine | Frost | Edge | Depth | Tint |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Subtle Glass** | Quiet frosted glass, barely-there distortion | 60% | 90% | 35% | 45% | 55% | 50% | 45% | 20% |
| **Liquid Glass** | Fluid lensing at the edges over a softer blur | 85% | 65% | 90% | 75% | 28% | 65% | 60% | 32% |
| **Crystal Glass** (default) | Clear, brilliant and deep: every effect at full strength | 100% | 100% | 100% | 100% | 12% | 80% | 70% | 40% |

Choosing a preset writes its values. Each stays independently adjustable. Control Center shows which preset the current
values match, or "Custom". Each preset card is a live preview: the real shader with that preset's values and your theme
and accent. Defaults are the Crystal preset, and a fresh install matches it exactly (tested).

## The accent tint

With the accent tint on, the accent colour is part of the material, not just borders and icons:

- **Absorption:** the body absorbs towards the accent colour, more where the glass is thick (the flat top) and less at
  the rim, like real tinted glass.
- **Tint layer:** the tint layer moves towards a theme-appropriate shade of the accent (deeper in Dark, lighter in Light).
- **Edges:** the Fresnel reflection, the internal reflection and the caustic pick up a little of the hue.
- **Dispersion:** the dispersion fringe at the very rim leans towards it.

Purple therefore gives refined purple-tinted glass. Tint strength scales all of this, and turning the tint off removes it
without forgetting the strength.

## Readability

Text on glass must stay readable over any wallpaper, in both themes:

- **Adaptive tint:** per pixel, the shader measures the backdrop under the glass and quietly thickens the tint where it
  fights the text colour:
  - bright areas under light text (Dark);
  - dark or highly saturated areas under dark text (Light).
- **Text-heavy panels:** flyouts, menus, window previews and quote details keep at least 56% tint.
- **The Dynamic Glass pill:** it is always deep smoked glass.

Reviewed on a deliberately hostile test backdrop (saturated stripes and large black text) in Light and Dark:
`tools/preview/render.py --test-backdrop`.

## Rendering

- **One fragment shader pass per surface** (`GlassSurface.qml`, a QML `ShaderEffect`). It draws:
  - the analytic two-layer shadow;
  - the anti-aliased edge at one device pixel;
  - refraction, blur, vibrancy, absorption, tint, every light term, the hairline and an optional accent rim glow.
- **Backend:** Qt Quick's threaded render loop on Direct3D 11.
- **Shader build:** compiled once to `liquidglass.frag.qsb` (HLSL, GLSL and MSL) with PySide6's `qsb`.
- **Pointer light ("dynamic light response"):** while the pointer is on the Dock or the Dynamic Glass, the edges near it
  catch light. It costs nothing when the pointer is elsewhere.
- **Idle cost:** nothing redraws without a change. There are no endless decorative animations, because each one would
  redraw a whole display-wide window 144 times a second. The visualiser and the Garvis orb run only while music plays or
  Garvis works, and only on render-thread animators. Media progress repaints at 4 Hz.

## What is behind the glass: true vs. simulated refraction

Windows doesn't give a window access to the pixels behind it. The options investigated:

| Approach | Result |
|---|---|
| DWM backdrops (Mica/Acrylic) | Blur and tint only. They can't distort, can't be shaped as a pill with smooth edges, and Qt Quick can't sample them. |
| **GDI region capture** (BitBlt) | Measured **8.3–8.6 ms** per 1000×230 region (p95 up to 15.9 ms). That is a whole 120 Hz frame budget, so rejected. |
| DXGI Desktop Duplication into the Qt RHI (zero copy) | Feasible: PySide6 exposes `QQuickWindow.createTextureFromRhiTexture` / `setGraphicsDevice`. It needs a large ctypes COM layer and costs continuous full-monitor duplication. **Not implemented.** |
| **Wallpaper backdrop** (implemented) | The top bar and the Dock sit in work-area strips Glass reserves (AppBars), so what is physically behind them is the desktop wallpaper. Glass renders each monitor's wallpaper exactly as Windows lays it out (`IDesktopWallpaper`: path, fill/fit/stretch/center/tile/span, background colour) into a mipmapped texture. The shader refracts, blurs and disperses it. |

What that means:

- **True refraction:** where the backdrop is the wallpaper, Glass refracts the real backdrop. That always holds for the
  reserved bar strips, at zero per-frame cost and with no screen capture of any kind.
- **Approximation:** panels that open *over application windows* (the expanded Dynamic Glass, flyouts, menus, window
  previews, quote details) refract the wallpaper layer, not the window under them.
- **Lighting effects, not optics:** the highlights, glints, caustic and pointer light.

Translucency and the adaptive tint make the difference subtle, but nothing claims to be physical refraction of window
content.

The texture is loaded only while Overall Intensity is above 0. It is refreshed when the wallpaper changes
(`WM_SETTINGCHANGE`), when displays change, and on resume.

## Performance

### Frame pacing (measured with the v1 shader)

**Setup:**
- Intel Arc 140V, 2560×1600 at **120 Hz**, DPR 1.5.
- Tool: `tools/perf/render_perf.py`. Two overlay windows, each animating continuously.

| | Top bar | Dock |
|---|---|---|
| Glass at 100%: fps / median frame | 117.2 / 8.36 ms | 115.2 / 8.34 ms |
| p99 / worst frame | 16.6 / 17.2 ms | 17.0 / 17.2 ms |
| Frames that missed a vsync | 2.4% | 4.2% |

v2 samples the backdrop 27 times per pixel (v1: 15), on the same small surfaces. The on-screen pacing run was **not**
repeated for v2, because it puts overlay windows on the desktop. Run `tools/perf/render_perf.py` to re-measure.

### Idle cost and leaks (v2, measured)

`tools/perf/shell_soak.py` runs the real Shell in test mode (windows rendered but parked off-screen) and cycles power
off/on. Results are in `docs/perf/shell_soak.json`:

| | |
|---|---|
| Idle CPU after start-up | **0.7%** of one core, and 0.08% later |
| The previous build, running on this PC (on screen, idle) | 24.7% of one core, caused by an endless idle pulse animation (fixed) |
| Handles / GDI / USER objects after 25 power cycles | −8 / 0 / −1 (no leak) |
| Private memory after 25 and after 60 power cycles | +15 MB and +18 MB: it levels off (QML type and texture caches), not growth per cycle |

Parked windows may be throttled differently from on-screen ones, so confirm the idle CPU during the first live run
(Task Manager › Details › pythonw.exe).
