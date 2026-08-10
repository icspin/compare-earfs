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
- **Deck tabs** (build 109, +GROUND in 119): TIME / MAPS / ECLIPSES /
  POINTS / GROUND panes
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
  Build 119: standing controls live in the GROUND tab (globe toolbar is
  clean); flat-world ground uses the SPOTLIGHT POOL (radial gradient at the
  subsolar map point, p.feLight/p.feSun on the mg source), the sky blends
  day/night by pool DISTANCE not sun altitude (on a flat model the sun is
  always up - night IS the pool being far), and the height is a live
  variable `mskyH` (Ground-tab slider, 1000-12000 km, persisted) that also
  drives feSizeArcmin and the FE size chart - keep every FE number on it.
  Build 120: the picker is `Stand on...` - geo ('My location'), curated
  `window.STAND_CITIES` (resolved from WORLD_CITIES; unknown names drop),
  and points; `standAtLL` drops/reuses a named point, force-shows the globe
  panel and enters Earth view. Opening the GROUND tab auto-stands at point
  0 when available (incl. via tab restore on load).
  121-122: rings UNCONDITIONAL while flat-standing (ignore V.moonRing
  there), sunGrp scale floor 1.0, entering a flat world sets standMode
  'sun' (face the lamp); `mgBeam` = additive cone from the lamp's physical
  spot (subsolar x mskyH) to the pool - the visible light shower.
  PARKED (Blake): independent sun/moon heights (split mskyH in two, each
  driving its own alt/size/beam) - build after the ground UX settles.
  123: flat sky = SPACE always (no state flip - day is the pool/beam);
  mgMoon proxy fixes the invisible moon (moonMesh is a CHILD of earthMesh -
  hiding the globe hid it; the proxy is scene-level, emissive floor, lit by
  the model sun so FE phases self-report); sunRet deleted; moon ring obeys
  the toggle again; mgFog haze (sky objects fog:false, fog PARKED at 1e7
  when unused - never null it, that recompiles shaders); tex.anisotropy 8;
  stylized relief grain (display, not data); body.groundMode CSS guts panel
  toolbars to maximize-only while the GROUND tab is active.
  124: INDEPENDENT TAB WORKSPACES - `tabViews` per-tab lineup maps
  (capture on leave, `TAB_DEFAULTS` seed: ground={globe}, ecl={globe,
  gleason,mollweide}, others inherit), `#modelChips` (display:contents)
  DOCKS into the active pane via appendChild and edits THAT tab's lineup;
  leaving GROUND exits standing; tabViews persisted. Clock/points/overlays/
  eclipse/heights stay shared - one world, several instruments.
  125: GROUND = STREET VIEW - `syncGroundLineup()` forces {globe, companion
  map} where companion = groundCompanion() (gleason/bipolar/rect by world);
  drawFlat draws the you-are-here dot + facing cone (standAz + standFov)
  when deckTab==='ground'; `feMode` extends the spotlight-pool lighting to
  the companion map in Ground mode (fs = p.feSun || s) so map coverage
  tracks mskyH; the beam is gradient-textured with a soft sheath.
  126-127: ground finder rings per body (`groundRingSun/Moon`, Ground-pane
  chips); height slider is LOG (mskyHFromSlider/sliderFromMskyH, 100-60000
  km, canonical mid = 4828); `unitsImp`+`fmtDist` = km/mi display toggle
  (g_units in tab bar; math stays km) covering height readout, measure
  table, legs, FE chart.
  128-132: ground render CACHED behind `src._gk` (subsolar quantized +
  mskyH + lights + world - the every-frame 900px upload WAS the choppiness);
  mg sources render at 2x (cv PW*2, z:2 - vector, crisp free) + two-scale
  grain; SHARE = collectState() base64url in #s= (restoreState prefers it,
  then drops the hash; file:// needs the location.hash fallback);
  look-drag release listeners are on WINDOW (canvas-only ones went sticky
  when released outside the panel); standMode 'both' = midpoint aim + fov
  breathing (Face buttons cycle free/sun/moon/both); hover deck STAYS once
  revealed - right-click anywhere or Esc dismisses (Blake's call).
  133-135: deckBtn label is STATEFUL via syncDeckBtn (tucked = Controls on
  hover, open = Right-click hides); GROUND TEXTURE PERF RULES: no mipmaps
  on mg tex (regen per update was the spike), cache key at 0.2 deg steps,
  sheath culled when the camera is inside the beam. If ground choppiness
  returns, suspect texture upload frequency x size FIRST, stars last.
  136-138: TIME tab dissolved into the tab bar (compact strip; no
  tab_time/pane_time); tabs = SKY(id tab_maps)/GROUND/ECLIPSES, pane_pts
  rides with SKY (special-cased in setDeckTab, not in DECK_TABS); panel
  masks step at 0.01 deg. GROUND SMOOTHNESS ARCHITECTURE (137): the land
  texture is STATIC (gk = world+lights) - the moving darkness is mgPool, a
  60-unit quad with a soft hole sliding per frame; its texture rebuilds
  only when the pool radius changes. NEVER bake moving light into the
  ground texture again - that was three rounds of choppiness.
  139-140: flat sky blends by POOL DISTANCE (night->warm dusk->day,
  stars dim via cached material._b opacity - restore it in every other
  regime); hover deck is display-toggled IN FLOW (no absolute overlay) -
  layoutGrid on reveal AND dismiss.
  141-143: bothZoom factor rides the both-mode auto-fit; height slider
  0.1-60000 km log w/ default snap + tick; units = header Metric/Imperial
  buttons (setUnits/syncUnitsUI - NO module-scope syncUnitsUI call, it
  TDZ-aborts boot); standing persists in view.{stand,sw,sm} restored in
  applyView AFTER points; bcast guarded by bootDone (early interval or
  sibling-tab message during the slow sync boot = TDZ, dead app).
  ALSO QUEUED (Blake): professional ground texturing for ALL worlds from
  the ground view, GPU-cheap - pair it with the multi-world cut.
  146: SKY MODE shipped - `skyModel` (persisted, in share links), DEFAULT
  Real sky: sun/moon by true topocentric altAz (realSkySun/realSkyMoon
  next to modelSky), night = `mgNite` overlay quad (18x18 units, y 0.004)
  textured by the mg src's nite mask via extracted `nightMask()` (0.05
  deg key), a REAL sunset (sunGrp/mgMoon hidden below alt -0.55 - no
  globe occludes on a plane), sky/stars follow real sun altitude (blend
  else-branch now also colors mgFog). Sky button `g_sky` in the Ground
  pane; height slider is Model-physics-only UI. Model physics = the old
  lamp/pool/beam story, feMode companion lighting gated on skyModel.
  THREE GOTCHAS BURNED HERE: (1) canvas textures need
  `colorSpace = SRGBColorSpace` or dark tints render pale slate (the
  globe's image textures set it; mg canvas textures never did); (2) WebGL
  alpha-blends in LINEAR space - the same mask alpha reads ~half as dark
  as 2D-canvas compositing, so nightMask takes a linA flag and
  gamma-compensates (1-(1-a)^2.2); (3) mgFog.color.setRGB(bytes/255) fed
  LINEAR values = horizon glowing lighter than the sky - set fog color
  via HEX like setClearColor (fixed in both blend branches). Also: in
  headless verification a PAUSED clock freezes updateScene (dirty-flag
  rendering) - state probes read stale frames; keep the clock running or
  interact before reading.
  ALSO QUEUED: Face-both separation readout ("sun-moon: 97deg - view:
  118deg" - wide-fov panorama compression reads as a bug otherwise);
  half-earth pool option; multi-world comparison grounds - world CHIPS
  (multi-select) in the Ground pane, one clone ground panel per world,
  ONE shared gaze (copy standAz/Alt/Fov from AV per frame), companions
  per active world only. Blake asked explicitly; design agreed. PARKED:
  independent sun/moon heights. Blake hates panel-toolbar chrome - keep
  stripping, never add controls to panel bars.
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
