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
2. Bump the amber **`build N`** in the footer by exactly +1, AND add a
   matching one-line entry at the top of the LOG array in the footer hub
   snippet (markers `SOLTERM-LOG:BEGIN/END`) - the other-tools popup
   renders it as the public build log.
3. Validate: extract the `<script type="module">` body to a file, `node --check` it.
4. **Verify on desktop AND mobile (390px viewport) — every change, no exceptions.**
   See "Verification tooling" below.
5. Commit with a descriptive message, push to `main`.
6. Tell Blake to hard-refresh `.../?v=<build>` (Pages caches hard).

**Current build: check the amber footer in index.html** - the number moves
without Claude too: the weekly sunspot bot bumps it, and hub-related commits
may as well. Always read the footer before bumping (+1 from whatever is there),
and 'git pull --rebase' before pushing.

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
  through it): Earth view / Orbit view; `V.anchor` (From:) + **`V.frame`**
  (build 112: `{sun,earth,moon}` bool set - the FRAME chips replaced the old
  Track dropdown/both/trio). Checked set = auto-framed every frame: enclosing
  center C + PROJECTED-extent fit (off-axis extent sets the angle, toward-
  camera bodies push back); camera rides the C->From axis at
  `fit * trkR`, so framing breathes by MOVING, never by fov warping.
  Knobs `trkR` (multiplier) / `trkT`,`trkPhi` (walk along/around axis) /
  `trkFov` (telescope) derive the camera fresh per frame - no drift, no
  ratchets. From = the side you watch from, NOT a guaranteed-foreground body.
  SWIVEL (113): when From IS in the set, drag grabs it (2x2 Jacobian on
  `V._shot`); otherwise ring-walk. True scale defaults ON (113).
  REFERENCE shots (117): From NOT in the set -> entry starts on the far
  side (trkT -3, ~18 deg off-axis; 34 deg pushes the reference out of a
  45 deg frame) so the From body glows in the background beyond the set.
  Telescope handoff is SOLO-ONLY (117): multi-body sets stop at the trkR
  floor - narrowing fov onto a spread set's empty centroid shows nothing.
  Earth view: same chips (earth chip hidden - the globe IS the frame);
  checked bodies stay visible OVER the globe (deliberate semantic change from
  the pre-112 day-side Track). Migration: saved `track` strings -> frame sets.
  At true scale from the sun, earth-moon runs edge-on near new/full moon and
  face-on at quarters - the fill breathing with phase is HONEST geometry,
  don't "fix" it. Ground view: `standAt/standFov`, topocentric moon.
- **Zoom**: ONE pipeline `zoomView(V, dy)` — wheel, pinch, and the touch zoom rail
  (`zoomHold`, applied per frame by the main loop; never a private timer/rAF).
  Telescope handoff when the tracked body is small; fov floor derives from the
  tracked body (stops at ~85% frame fill).
- **Deck tabs** (build 109): TIME / MAPS / ECLIPSES / POINTS panes
  (`setDeckTab`, `deckTab` persisted); the clock transport (Pause, dir,
  speed) is pinned in the tab bar and never hides. Organization only - the
  panes show/hide, every control keeps its id. Mobile deck rows WRAP (the
  old hidden-scrollbar side-scroll hid features and is gone); wide `.grp`
  clusters wrap internally.
- **Time**: STEP / SET DATE clusters + Jump-to in the TIME pane;
  middle-click-drag shuttle (`shuttleHold`, quadratic, 24 h/s max).
- **Eclipse replay** (build 108): `eclReplay`/`eclSpan` (path time span from
  the same Besselian scan that draws the line, +-0.15 h pad; `rate` = one
  lap ~12 s), applied per frame by the main loop ahead of normal running.
  `stopReplay()` is called from EVERY manual time control (setRunning, dir,
  speed, jog, set, jump, shuttle). While replaying, `bc.onmessage` returns
  early - the replaying window sends, never follows, so a second window
  follows the loop. Auto chip (`eclAuto`) starts replay on pick.
- **Ephemeris**: `sunPos` (simple solar), `moonPos` = principal Meeus ch.47 terms
  (~0.05 deg + true distance `distKm`) — accurate enough that eclipses genuinely
  render from path sites. Moon ORIENTATION = full IAU/WGCCRE model (`moonIAU`,
  NAIF pck00010 constants): true pole + prime meridian W, so face roll AND
  libration are real. Sun rotation: Carrington synodic 27.2753 d, calibrated
  `SUN_L0`/`SUN_L0_EPOCH` against NOAA.
- **Eclipses**: `ECL_SOLAR` = 28 central eclipses 2017-2035 as NASA Besselian
  elements; `eclCentral()` = fundamental-plane solution (verified vs published
  2024-04-08 path, exact). Path drawn on globe (`eclGrp` on `earthMesh`) and all
  flat maps (via `projectLine`); umbra disc rides with the clock (`eclNow`).
  `ECL_LUNAR` entries just jump the clock. Picker jumps to GLOBAL greatest;
  other path sites need their local time.
- **Kaleidoscope** (110, rebuilt 114 as THE TURNING DRUM): `defs.kaleido`
  with `kal:1, srcKey:'gleason'` - COMPOSITED, not projected: the Gleason
  scene renders into hidden `kalSrc` per panel, stamped 12x (6 rotations +
  6 mirrors) behind FIXED mirrors while the earth turns beneath:
  `kalSrc.rot = (s.lon - 15)*D2R + p.rot` keeps the noon meridian mid-wedge
  (empirical sign: shown lon = wedge angle + rot deg; the first cut had it
  flipped and rode the MIDNIGHT meridian - verify with a +6h timestamp
  pair, not one shot). Rim-drag = drum twist, not image spin. Probing goes
  through a custom `p.toLL` that unfolds the live rotation. Not in the
  measure table. Tooltips stay deadpan - no explicit satire, ever.
- **Tour** (build 111): `TOUR` steps + `tourStep/startTour/tourEnd`; one
  spotlight div (giant box-shadow) + card. Auto-shows once - localStorage
  key `solterm.tour`, deliberately separate from app state so it SURVIVES
  Reset app; header `?` replays. `deckReveal` early-returns while touring.
- **Flat maps**: cover-fit, edge to edge - each panel's canvas buffer tracks
  the panel's aspect (`p.fitStage()`, called per frame, no-op unless resized);
  default zoom covers the panel, zoom-out floor shows the whole map. The earth
  sphere uses polygonOffset so surface lines never z-fight at true scale.
- **Measure drawer**: opens when points exist; minimize button (`probeMin`)
  collapses it, the right-edge MEASURE tab reopens; per-point remove buttons
  in the table rows and sky-card headers.
- **Model ground** (built 115 as 2D strips, REPLACED in 118 by true 3D):
  `modelSky(def, site, body)` computes alt/az/size the map itself predicts
  (sun+moon at `MSKY_H` 4828 km, radius 25.75 km - the SAME constants as
  `feSizeArcmin`; keep them in sync). While standing, the World toggle
  (`V.standWorld`: globe|gleason|bipolar) swaps the territory: ground =
  live map render on `mgPlane` (map (mx,my) -> ((mx-450)*MG_S,0,(my-450)*MG_S),
  MG_S 0.02), bodies placed by modelSky, moon lit by the model's sun.
  Flat worlds hide `earthMesh` ONLY - `earthRoot` contains the moon, hiding
  it kills the moon (bug found in verification). Finder rings (`moonRet` +
  `sunRet` twin) work while flat-standing - model bodies are honest specks.
  FE models only (gleason, bipolar) - projections of the globe get no sky.
  alt = atan(h/D) > 0 always: the model sun never sets, visibly.
- **Sunspots**: REGIONS table between `SUNSPOT-DATA:BEGIN/END` markers +
  `SUNSPOT-CAL` line — **auto-refreshed weekly** by
  `.github/workflows/update-sunspots.yml` running `tools/update-sunspots.mjs`
  (fetches NOAA SWPC, rewrites markers, bumps build, commits as sunspot-bot).
  Never hand-edit between the markers. The click-the-sun glare popup shows the
  data's observation date (`SUN_L0_EPOCH`) and warns when the clock is weeks
  away (the visible face may genuinely be spotless then - never invent spots).
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
- The reused profile SESSION-RESTORES the previous run's app pages as ghost
  tabs with live clocks that bcast on the BroadcastChannel and fight the page
  under test (symptom: tRate/simT mysteriously overwritten). At startup, list
  `/json`, keep ONE page target, `/json/close/{id}` the rest.
- `localStorage.clear()` before navigating away is USELESS - beforeunload
  persistState re-saves state after the clear. Register
  `Page.addScriptToEvaluateOnNewDocument` with the clear instead (runs before
  the app boots); remove it via its identifier to test returning-visitor flows.
- The working tree is CRLF (git stores LF, autocrlf converts). Python patch
  scripts must translate `\n` -> `\r\n` in match strings or nothing matches.

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
- Real-phone confirmation of pinch/rail/twist feel (now also: tabs, tour, replay).
- Sun sightline arrows (build 30, reverted, "need to think about it").
- README screenshot is stale (now very stale - tabs changed the deck).
- City lights fetch from unpkg at RUNTIME (im.src in the lights loader) -
  contradicts "nothing fetched at runtime"; inline the texture someday.
- Kaleidoscope is not in the measure table (deliberate; Blake can overrule).
