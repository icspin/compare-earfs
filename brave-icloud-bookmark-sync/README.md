# Sync Brave bookmarks with Safari / iCloud on Windows

**Goal:** save a bookmark in Brave on Windows and have it appear in Safari on
your iPhone/iPad/Mac — and vice-versa.

## Why this is hard (and why your Chrome-folder trick didn't work)

iCloud for Windows can sync Safari bookmarks with **Chrome, Edge, and Firefox**,
but **not Brave**. That's a confirmed, still-open Brave bug:
[brave/brave-browser#31443](https://github.com/brave/brave-browser/issues/31443).

The important part: iCloud does **not** sync by reading a browser's `Bookmarks`
file on disk. It talks to a browser **extension** ("iCloud Bookmarks") over a
channel called **native messaging**, registered to a specific browser. So when
you repointed Chrome's data folder at Brave's folder, iCloud was still talking
to *Chrome's extension over Chrome's channel* — Brave was never in the
conversation. That's exactly the "the extension and app talk, but not to Brave"
symptom. You diagnosed it right; the fix just needs to happen at the
messaging/extension layer, not the file layer.

Since Brave can't be the iCloud endpoint, the reliable strategy is:

> Let iCloud sync with a browser it **does** support (**Edge**, which ships with
> Windows), then keep **Edge ⇄ Brave** bookmarks in lock-step.

```
Brave  ⇄  Edge  ⇄  iCloud  ⇄  Safari / iPhone
      (link 1)   (link 2, official)
```

Link 2 (Edge ⇄ iCloud) is Apple's own supported extension. This project is about
link 1 (Brave ⇄ Edge), and there are two ways to do it.

---

## ✅ Recommended: the floccus chain (reliable, live, minimal code)

[**floccus**](https://floccus.org/) is a mature, open-source extension that does
**live two-way bookmark sync** and explicitly supports **both Brave and Edge**.
It works *through the running browser*, so there's no file locking, no closing
browsers, and no corruption risk — bookmarks sync the moment you save them.

### One-time setup (~20 minutes)

1. **Install iCloud for Windows** (Microsoft Store) and sign in. In the iCloud
   app, enable **Bookmarks** and choose **Edge** (or Chrome) as the browser.
2. **Set up link 2 — Edge ⇄ iCloud:**
   - Open **Microsoft Edge**.
   - Install the **iCloud Bookmarks** extension (Edge Add-ons / Chrome Web
     Store). Edge will now mirror Safari's bookmarks in real time.
   - Confirm your Safari bookmarks show up in Edge before continuing.
3. **Set up link 1 — Brave ⇄ Edge with floccus:**
   - Install the **floccus** extension in **both Edge and Brave**
     ([Chrome Web Store](https://chromewebstore.google.com/detail/floccus-bookmarks-sync/fnaicdffflnofjppbagibeoednhnbjhg)).
   - Pick a backend both browsers can reach. Easiest zero-infrastructure option:
     **Google Drive** (floccus can end-to-end encrypt it). WebDAV / Nextcloud /
     Dropbox also work if you prefer self-hosting.
   - In floccus **on Edge**: create a profile → choose the backend → sign in →
     set it to sync the **whole** bookmark tree, bidirectional. Run one sync.
   - In floccus **on Brave**: create a profile pointing at the **same** backend
     file → bidirectional → sync. Brave now pulls everything Edge pushed.
   - Set floccus to auto-sync (e.g. every 5–15 min, and on change).

### Result

- Save in Brave → floccus pushes to the shared file → Edge pulls it → iCloud
  extension uploads to Safari.
- Save on iPhone/Safari → iCloud pushes to Edge → floccus syncs it to Brave.

Edge needs to run periodically for links to tick (it's the hub). Easiest is to
let it launch at login and sit minimized, or just open it a couple times a day.

**Watch-outs**

- Keep it to a **single hub**: only Edge runs *both* iCloud and floccus. Don't
  also put the iCloud extension in Chrome, or you can create sync loops.
- First sync merges both sides. If Edge and Brave already had different
  bookmarks, expect a one-time union (no data loss, but tidy up duplicates once).
- Set floccus to **bidirectional**, not "slave"/"master", unless you truly want
  one side to win.

---

## 🔧 Fallback: fully-local file bridge (no cloud account)

If you don't want Google Drive / WebDAV in the loop, `bookmark_bridge.py` in this
folder syncs Edge's and Brave's `Bookmarks` files directly on your machine. You
still need **link 2** (Edge ⇄ iCloud) from step 2 above; this script replaces
floccus for link 1.

It's robust (set-based two-way merge, correct deletion handling, backups,
Chromium checksum recomputation) but has one inherent limitation the floccus
approach avoids:

> **A running Chromium browser owns its `Bookmarks` file and will overwrite it.**
> The bridge therefore only *writes* to a browser that is currently **closed**
> (it always *reads* both). Changes flow into Brave/Edge the next time that
> browser is shut while the bridge runs. It is near-real-time, not instant.

### Setup

1. Install **Python 3** (`winget install Python.Python.3.12`).
2. Copy this folder somewhere permanent (e.g. your `scripts` folder).
3. Preview what it would do — safe, writes nothing:
   ```
   python bookmark_bridge.py --dry-run
   ```
4. Run a real sync once (close Brave/Edge first so both sides can be written):
   ```
   python bookmark_bridge.py
   ```
5. Automate it — registers a scheduled task (every 15 min + at logon):
   ```
   powershell -ExecutionPolicy Bypass -File .\Install-BridgeTask.ps1
   ```

### How the merge stays correct

The bridge keys every bookmark by `(root, folder-path, name, url)` and stores a
**baseline** of the last synced state (`sync_state.json`). On each run it
computes, per side, what was **added** and **deleted** versus the baseline:

```
final = (baseline ∪ added_on_either_side) − deleted_on_either_side
```

That's why a delete propagates instead of the bookmark reappearing forever, and
why the first run (empty baseline) simply merges both sides without deleting
anything. The baseline only advances once **both** browsers reflect the merged
result, so a change that couldn't be written (browser open) is retried next run.

Renames/moves are handled as delete-plus-add, so the final set is always
correct; the only trade-off is that renaming the *same* bookmark differently on
both sides at once yields two copies rather than silently picking a winner —
non-destructive by design.

### Safety

- Every write is preceded by a timestamped backup next to the file
  (`Bookmarks.bridge-backup-YYYYMMDD-HHMMSS`, last 10 kept).
- Writes are atomic (temp file + rename) and recompute Chromium's MD5 checksum
  so the browser accepts the file without complaint. (Even if a future Chromium
  changed the checksum scheme, it *loads the bookmarks anyway* on mismatch and
  recomputes — it does not delete them.)

### Options

```
python bookmark_bridge.py --dry-run          # show changes, write nothing
python bookmark_bridge.py --force            # write even if a browser is open (risky)
python bookmark_bridge.py --edge  "<path>"   # override Edge  Bookmarks path
python bookmark_bridge.py --brave "<path>"   # override Brave Bookmarks path
python bookmark_bridge.py --state "<path>"   # override baseline location
```

Default profile paths (change with `--edge` / `--brave` if you use a non-Default
profile):

```
Edge :  %LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Bookmarks
Brave:  %LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Bookmarks
```

---

## Which should I use?

| | floccus chain (recommended) | Local file bridge |
|---|---|---|
| Sync latency | Instant, live | Next time the browser is closed |
| Reliability | High (browser API, no file races) | Good, but browser-must-be-closed to receive |
| Third-party backend | Yes (Drive/WebDAV/etc., E2E-encryptable) | None — 100% local |
| Custom code to trust | None | This script |
| Corruption risk | None | Very low (backups + atomic writes) |

Start with the **floccus chain**. Use the **local bridge** only if you
specifically want to avoid any sync backend.

---

## Note on the "make Brave pretend to be Chrome" idea

It is *theoretically* possible to install the iCloud extension in Brave and
mirror iCloud's native-messaging registration into Brave's registry location so
Brave finds the channel. But per the open Brave bug above it's reported flaky in
Brave specifically, resets when iCloud updates, and nobody has a confirmed clean
recipe. The Edge-hub approaches on this page are why they exist: they route
around Brave's limitation instead of fighting it.
