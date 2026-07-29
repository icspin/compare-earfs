# Solterm (compare-earfs)

Single-file solar-geometry console: one sun, one clock, every map model side by side.
**Everything lives in `index.html`** — no build step, no bundler, no runtime network
calls (three.js via import map; land data, textures, NOAA/NASA data all inlined).
Live at https://icspin.github.io/compare-earfs/ (GitHub Pages serves repo root, `main`).

## Workflow (Claude runs the whole loop)

The owner (Blake, GitHub `icspin`) directs; Claude edits, validates, verifies,
commits, and pushes. Every shipped change:

1. Edit `index.html` (for multi-part edits, write a Python patch script with
   exact-match asserts rather than hand-editing — heredocs with quotes are fragile
   in this shell).
2. Bump the amber **`build N`** in the footer by exactly +1.
3. Validate: extract the `<script type="module">` body to a file, `node --check` it.
4. **Verify on desktop AND mobile (390px viewport) — every change, no exceptions.**
   See "Verification tooling" below.
5. Commit with a descriptive message, push to `main`.
6. Tell Blake to hard-refresh `.../?v=<build>` (Pages caches hard).

**Current build: 97** (2026-07-26).

## Hard rules

- **No em dashes** anywhere — chat, code, comments. PowerShell-era encoding scars.
  Plain hyphens only.
- **Mobile verification is mandatory** for every change ("no mistakes").
- **The desktop grid never scrolls.** All selected panels visible simultaneously,
  all cells equal size, no dominant panel. (Grid is aspect-aware: squarish window
  gives 2x2 / 3x3; wide window may prefer a row.) Mobile is a scrolling stack.
- **Talk before building** UI redesigns or projection-math changes; small fixes and
  clearly-requested features ship directly.
- **Tools are modeless**: click = probe point, drag = pan/orbit, wheel = zoom,
  rim-drag spins round maps, middle-click = pause, middle-drag = time shuttle,
  click the sun = glare slider. Never reintroduce tool-mode buttons.
- **Honesty is the product.** The app claims "runs client-side, real ephemeris".
  Never fetch at runtime; baking externally sourced data at publish time is fine
  (NOAA sunspots, NASA Besselian elements) and should be labeled as such.
  Never show a number known to be wrong (e.g. eclipse durations are omitted
  because the simple formula is ~1.5x off).

## Architecture map (all inside index.html)

- **Views**: `views[]`, view 0 = primary canvas "A"; extra globe panels are clones
  (`gclones[]`, 2D canvases blitted from ONE shared offscreen renderer —
  `clearRect` before every blit or you get smear trails). `AV()` = active view;
  clicking a panel makes it toolbar-controlled.
- **Camera regimes** (`frameCamera` is the single router; every mode change goes
  through it): Earth view / Orbit view; `V.anchor` (From:) + `V.track`
  (`none|sun|moon|earth|both|trio`). Tracking shots derive the camera fresh each
  frame from knobs `trkR/trkT/trkPhi/trkFov` (drift impossible by construction).
  `both` = pair shot (minimal enclosing cone of anchor + other two bodies, smooth
  `pairBack` back-off — never demand something back-off can't change). `trio` =
  auto-framed group shot. Ground view: `standAt/standFov`, topocentric moon.
- **Zoom**: ONE pipeline `zoomView(V, dy)` — wheel, pinch, and the touch zoom rail
  (`zoomHold`, applied per frame by the main loop; never a private timer/rAF).
  Telescope handoff when the tracked body is small; fov floor derives from the
  tracked body (stops at ~85% frame fill).
- **Time**: SPEED / STEP / SET DATE clusters + Jump-to + **Eclipses picker**;
  middle-click-drag shuttle (`shuttleHold`, quadratic, 24 h/s max).
- **Ephemeris**: `sunPos` (simple solar), `moonPos` = principal Meeus ch.47 terms
  (~0.05 deg + true distance `distKm`) — accurate enough that eclipses genuinely
  render from path sites. Sun rotation: Carrington synodic 27.2753 d, calibrated
  `SUN_L0`/`SUN_L0_EPOCH` against NOAA.
- **Eclipses**: `ECL_SOLAR` = 28 central eclipses 2017-2035 as NASA Besselian
  elements; `eclCentral()` = fundamental-plane solution (verified vs published
  2024-04-08 path, exact). Path drawn on globe (`eclGrp` on `earthMesh`) and all
  flat maps (via `projectLine`); umbra disc rides with the clock (`eclNow`).
  `ECL_LUNAR` entries just jump the clock. Picker jumps to GLOBAL greatest;
  other path sites need their local time.
- **Sunspots**: REGIONS table between `SUNSPOT-DATA:BEGIN/END` markers +
  `SUNSPOT-CAL` line — **auto-refreshed weekly** by
  `.github/workflows/update-sunspots.yml` running `tools/update-sunspots.mjs`
  (fetches NOAA SWPC, rewrites markers, bumps build, commits as sunspot-bot).
  Never hand-edit between the markers.
- **Persistence**: `solterm.state` in localStorage (3s interval + beforeunload),
  restored defensively; `solterm.places` = user-saved locations (survives Reset).
  New user-facing state MUST be added to `collectState`/`restoreState`.
- **Ghost earth** = green hologram shell (shader `ghostA`/`dimA` uniforms);
  standing view dims the ground (dimA 0.55) and reaches 120 deg fov.

## Verification tooling (headless Edge + CDP)

Scripts pattern: spawn `msedge.exe --headless=new --remote-debugging-port`,
WebSocket CDP, `Runtime.evaluate` to drive the UI, `Page.captureScreenshot` to
observe. Desktop 1700x1100 + mobile 390x844 (`Emulation.setDeviceMetricsOverride`).
Hard-won gotchas:

- Headless produces frames ON DEMAND: rAF/animation is frozen while idle — "pump"
  frames with repeated throwaway screenshots to advance per-frame logic.
- Canvas `drawImage` pixel reads of the WebGL canvas return STALE buffers —
  **screenshots are the only trustworthy observation**; suspiciously-equal numbers
  mean the metric lied, not the app.
- `Input.dispatchTouchEvent` after scrollIntoView and `synthesizePinchGesture`
  can HANG the CDP channel — use mouse dispatch or untrusted `PointerEvent`s
  from page JS (they drive the same handlers). Kill orphaned Edge by matching
  `edgecdp*` in the process command line.
- `Runtime.evaluate` of async IIFEs needs `awaitPromise: true` or returns `{}`.
- Module-scope functions are unreachable from evaluate — test through the DOM.
- On mobile, panels sit below the fold: `scrollIntoView` before dispatching input.
- Reuse ONE `--user-data-dir` per script family; temp profiles leak ~1 GB each.

## Data provenance / refresh

- **Sunspots**: NOAA SWPC `solar_regions.json`, auto-refreshed weekly (see above).
- **Eclipse elements**: NASA GSFC `SEbeselm2001/SE{Y}{Mon}{D}{T|A|H}beselm.html`;
  to extend the catalog past 2035, fetch more pages into `ECL_SOLAR`.
- **Moon albedo, night lights, land polygons**: inlined; land data is verified
  correct (projection distortions are the projections' own, never "fix" them
  without explicit approval).

## Open / parked

- Standing-view true fisheye projection (Stellarium-style) if 120 deg isn't enough.
- Eclipse durations on labels (needs observer-rotation term in the formula).
- Blake asked where "Now" went (it's inside Jump-to); offered a dedicated button.
- Real-phone confirmation of pinch/rail/twist feel.
- Sun sightline arrows (build 30, reverted, "need to think about it").
- README screenshot is stale.
