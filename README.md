# cn4m

**cn4m** (a riff on "conform") is a media tracking and conformance tool. It scans incoming media deliveries from creative teams, extracts technical metadata from every file, and provides a fast way to approve or quarantine assets before they are pushed to media servers and programmed. Approved assets are pushed to a Google Sheet for tracking.

## Screenshots

<!-- TODO: add screenshots before release -->
<!-- ![Review table with QC highlighting](docs/screenshots/review-table.png) -->
<!-- ![Google Sheet tracker](docs/screenshots/google-sheet.png) -->

*Screenshots coming soon.*

---

## Quickstart

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows or Mac).
2. Clone the repo:
   ```
   git clone https://github.com/alokw/cn4m.git
   cd cn4m
   ```
3. Copy `.env.example` to `.env` and fill in at minimum:
   - `WORKSPACE_FOLDER` — a folder on your machine where media deliveries will land (see [Workspace folder layout](#workspace-folder-layout))
   - `GOOGLE_SHEET` and `GOOGLE_CREDS` — see [Google Sheets setup](#google-sheets-setup)
   - `TZ` — your local timezone (e.g. `America/Los_Angeles`)
4. Start everything:
   ```
   docker compose up -d
   ```
5. Open **http://localhost:2640**, drop some media files into your workspace's `repo\` folder, and click **START**.

To stop: `docker compose down`. A Celery task dashboard (Flower) is also available at http://localhost:2641. Both ports come from the suite-wide allocation — see [The cn4m suite](#the-cn4m-suite).

---

## What it does

1. **Scan** — Walks a watched folder (your media delivery drop) and extracts metadata from every new file: codec, resolution, framerate, duration, audio format, sample rate, bit depth, file size, and timestamps.
2. **Review** — Displays all new assets in a sortable, filterable table so you can quickly assess whether they conform to spec. Cells that fail QC (wrong codec, resolution, or framerate) are highlighted red, and a single button narrows the table to just the flagged assets. A delivery that arrives at a version you have already approved gets a caution icon, and anything misnamed can be renamed in place from the table. See [Reviewing assets](#reviewing-assets).
3. **Approve or Quarantine** — Approved files stay in place and are ready to track. Quarantined files are physically moved to a separate folder for manual review.
4. **Track** — Pushes approved assets to a Google Sheet (one row per asset) for production tracking, with a status dropdown: `received → ingested → programmed → waiting → problem`. QC failures are highlighted red in the sheet too.
5. **Transcode** — Runs selected assets through configurable ffmpeg presets (Hap, Hap Alpha, 1/2–1/8-res Hap Alpha proxies, H.264 proxies, WAV extraction, audio-to-Hap wrapping for disguise/d3 media servers), optionally quarantining the originals afterward. Available on new assets and on anything already approved or quarantined.

Optionally, cn4m posts a summary to a Discord channel whenever files are approved, quarantined, or pushed to the sheet.

---

## The cn4m suite

cn4m is one of several tools sharing the same workflow and naming. The others live in their own repos and none of them are needed to run this one — they're listed here so the port allocation lives in one place.

The suite reserves the **264x** range so every tool can run side by side on one machine without colliding:

| Port | Service | In this repo |
|---|---|---|
| **2640** | cn4m web GUI (Flask) | ✔ |
| **2641** | cn4m task monitor (Flower) | ✔ |
| **2642** | cn4m message broker (Redis) | ✔ |
| 2645 | cn4m-inbound | |
| 2646 | cn4m-smartsync | |
| 2647 | cn4m-symmetry | |
| 2649 | cn4m-cascade | |

Only the first three are configured here, in [docker-compose.yaml](docker-compose.yaml). 2640 is ours end to end — it's the port Flask itself listens on. 2641 and 2642 are host-side mappings onto the stock ports inside the Flower and Redis images (5555 and 6379), which are left alone: the containers talk to each other over the Docker network, so `CELERY_BROKER_URL=redis://redis:6379/0` names the *container* port and is deliberately unchanged.

Publishing 2642 at all is only so you can inspect Redis from the host — the worker reaches it over the Docker network either way, and you can drop that mapping without affecting anything.

**Upgrading from an earlier version?** The web GUI moved from 5000 to 2640 and Flower from 5555 to 2641, so `docker compose up -d` is required to republish the ports (a plain `restart` keeps the old mapping). Update any bookmarks.

---

## Configuration

All settings live in the `.env` file in the project root (copy `.env.example` to get started — it documents every variable in detail). Summary:

| Variable | Required | Description |
|---|---|---|
| `WORKSPACE_FOLDER` | ✔ | Full path to the workspace folder containing `repo\` and `quarantine\` subdirectories (see [Workspace folder layout](#workspace-folder-layout)) |
| `GOOGLE_SHEET` | ✔ | The ID from your Google Sheet's URL: `https://docs.google.com/spreadsheets/d/`**`<ID>`**`/edit` |
| `GOOGLE_CREDS` | ✔ | The full JSON content of your Google service account key file, pasted as a single line |
| `TZ` | ✔ | Your local timezone (e.g. `America/Los_Angeles`, `Europe/London`). Used to stamp correct local times on sheet entries. |
| `DISCORD_WEBHOOK_URL` | | Webhook URL for Discord notifications (see [Discord notifications](#discord-notifications)). Omit to disable. |
| `EXCLUDE_FILES` | | Comma-separated filenames to ignore during scanning. Supports glob wildcards (`videoin_*.mov`, `*.tmp`); case-insensitive. |
| `EXCLUDE_FOLDERS` | | Comma-separated folder names to skip entirely during scanning (not even descended into). Same wildcard matching as `EXCLUDE_FILES`. |
| `QC_CODEC` | | Comma-separated allowed codecs (e.g. `NotchLC, Hap`). Anything else is flagged red. Omit to skip codec QC. |
| `QC_RESOLUTION` | | Resolution rules, comma-separated. `SCREEN@WxH` applies to files on that screen; a bare `WxH` applies to every file, including files with no screen field (e.g. `A1@112x336, 1920x1080`). A file passes if it matches any applicable rule. Omit to skip resolution QC. |
| `QC_FPS` | | Comma-separated allowed framerates (e.g. `29.97, 30`). Omit to skip framerate QC. |
| `TIME_BETWEEN_CHECKS` | | Delay (seconds) between processing each file — keeps progress updates responsive in the UI. Default: `0.001` |
| `SECRET_KEY` | | Random string for Flask session security. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |

`CELERY_BROKER_URL` and `RESULT_BACKEND` are set automatically by docker-compose and don't need to be configured.

### Workspace folder layout

cn4m expects a single workspace folder on your host machine. Point `WORKSPACE_FOLDER` in `.env` at that folder — you create the parent, and cn4m auto-creates the two subdirectories on first startup:

```
M:\your_workspace\        ← WORKSPACE_FOLDER points here (you create this)
    assets.json           ← cn4m's state file — every asset it knows about
    repo\                 ← auto-created — media deliveries land here
    quarantine\           ← auto-created — files moved here when quarantined
```

`assets.json` sits at the workspace root rather than inside `repo\`, so the scanner isn't walking over its own state file. **Upgrading from an older version?** Nothing to do — cn4m reads the old `repo\assets.json` and moves it up on its next write (scan, approve, quarantine or track). The new file is written before the old one is removed, so an interrupted migration leaves your state intact. Once it's moved you can drop `assets.json` from `EXCLUDE_FILES` in `.env`, though leaving it there is harmless.

**Why one folder?** Docker treats each bind mount as a separate filesystem inside the container. If `repo` and `quarantine` were mounted separately, quarantining a file would fall back to a full byte-copy through the Docker Desktop virtualization layer — extremely slow for large media files. Putting both under a single mount makes quarantine a metadata-only rename that completes instantly.

### Google Sheets setup

1. Create a Google Cloud project and enable the Google Sheets API and Google Drive API.
2. Create a service account and download the JSON key file.
3. Share your target Google Sheet with the service account email address (give it **Editor** access).
4. Paste the entire JSON key file content as the value of `GOOGLE_CREDS` in `.env` (single line, no line breaks).
5. Copy the Sheet ID from the URL and set it as `GOOGLE_SHEET`.

The app automatically creates `repository` and `quarantine` worksheets with headers, formatting, and a status dropdown on first use.

### Discord notifications

cn4m posts a message to a Discord channel when files are approved, files are quarantined, or the Google Sheet is updated. To set this up:

1. In Discord, open the channel you want notifications posted to.
2. Go to **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Give it a name, then click **Copy Webhook URL**. This is your `DISCORD_WEBHOOK_URL`.
4. Add it to your `.env` file.

Notifications are optional — if `DISCORD_WEBHOOK_URL` is not set, they're skipped silently.

### QC checks

cn4m can automatically flag assets that don't meet show specs. All three checks are optional and independent — leave a variable blank to skip that check. Matching is case-insensitive throughout.

**Codec** — flag any asset whose codec isn't in the allowed list:

```
QC_CODEC='NotchLC, Hap'
```

**Resolution** — two rule forms, mixable in one list. `SCREEN@WxH` applies only to files whose screen field (parsed from the filename) matches that screen ID. A bare `WxH` is a global rule that applies to every file, including files with no screen field at all — so a list of only bare entries QCs the whole delivery against a set of allowed sizes:

```
QC_RESOLUTION='A1@112x336, B1@224x448, 1920x1080, 3840x2160'
```

A file is checked against the global rules plus its own screen rule, and passes if it matches any one of them outright. If none match, the closest rule decides which dimension(s) turn red — a 1920×1920 file checked against `1920x1080` flags only the height.
**Framerate** — flag any asset whose framerate doesn't match one of the allowed values:

```
QC_FPS='29.97, 30'
```

### Filename convention

cn4m parses structured fields out of filenames following the convention `{id}_{desc}_{screen}_{version}.{ext}`, e.g. `1000_prestige_segment_ab_v01.mov` → id `1000`, description `prestige_segment`, screen `ab`, version `v01`. The screen field is what `SCREEN@WxH` resolution rules match against, and the version field powers version-up detection (a new file whose base name — id, description **and** screen, everything but the version — matches an already-tracked asset is marked as a version-up ☝️ rather than a new asset 🆕, so the same content delivered for two different screens counts as two new assets rather than a version of one; when several versions of the same base name turn up in a single scan, the lowest is the new asset and the rest are version-ups). The NAME column shows just the id and description; the screen lives in its own SCREEN column. Files that don't match the convention are still processed — they just won't have screen/version metadata, so only the screen-less `WxH` resolution rules apply to them.

The version field also drives the caution icon in the review table, which fires when a delivery is *not* newer than an asset you have already approved — see [Version conflicts](#version-conflicts).

### Transcode presets

The **TRANSCODE** and **QUARANTINE & TRANSCODE** buttons run the selected assets through an ffmpeg preset chosen from the dropdown. Presets are defined in [config/ffmpeg_config.yaml](config/ffmpeg_config.yaml) — the file is heavily commented and ships with presets for Hap and Hap Alpha transcodes, 1/2, 1/4 and 1/8-resolution Hap Alpha proxies (`_proxy1` / `_proxy2` / `_proxy3`, padded up to a multiple of 16, at the source framerate), H.264 review proxies, WAV audio extraction, and wrapping audio files in a tiny 16×16 Hap `.mov` (so disguise/d3 media servers can play them back as standard video assets). Adding your own preset is a copy-paste-edit of an existing block; no code changes needed.

Preset options can reference `{field}` tokens (like `{framerate}`) that are filled in at runtime from [config/project_config.yaml](config/project_config.yaml) or from the asset's own metadata. Both YAML files are read fresh on every transcode, so edits take effect without a restart.

An output lands next to its source and becomes an asset on your next check. When it does, cn4m stamps `created from <source filename>` on it, which shows up in the Google Sheet's NOTES column — so a transcode's origin is still legible months later. (Transcodes run from the QUARANTINED tab write into the quarantine folder, which isn't scanned, so those outputs never become assets.)

---

## Workflow

Once the app is open in your browser, you land on the **NEW** tab. Its three sections — CHECK ASSETS, REVIEW ASSETS and TRACK ASSETS — share a single pane that expands as you go, so you're never looking at a stage you can't use yet.

**1. Check Assets**
Click **START** to scan the repo folder for new files. A progress bar shows each file being analyzed. When the scan completes, the **REVIEW ASSETS** pane opens with everything it found.

Re-checking is safe at any point: assets you've already approved or quarantined are skipped, anything still awaiting review is re-read so its metadata refreshes, and assets whose file has since been deleted or moved out of the repo are dropped from the review list and reported below the table.

**2. Review Assets**
The table shows each file's folder, name, screen, version, duration, codec, resolution, framerate, audio specs, and size. Sort by any column, filter by any column, and tick the rows you want to act on — see [Reviewing assets](#reviewing-assets) for the full set of controls.

- Codec, resolution, and framerate cells that fail your QC rules appear in red (hover for the expected value). **SHOW FLAGGED ONLY** narrows the table to just those files, and **SELECT ALL FLAGGED** selects them.
- A caution icon in the leftmost **!** column marks a delivery that isn't newer than something already approved — hover it for the filename it collided with. See [Version conflicts](#version-conflicts).
- Right-click a row and choose **Rename…** to fix a bad filename in place without leaving the browser. See [Renaming](#renaming).
- Files that couldn't be parsed at all (invalid or corrupt) are listed below the table with a warning note.

**3. Approve, Quarantine, or Transcode**
With files selected:
- **APPROVE SELECTED** — marks them as conforming and ready to track. Files stay where they are.
- **QUARANTINE SELECTED** — physically moves them to the quarantine folder for manual review.
- **TRANSCODE** — runs them through the ffmpeg preset chosen in the dropdown (output lands next to the source file).
- **QUARANTINE & TRANSCODE** — transcodes them, then quarantines the originals.

Approving or quarantining opens the **TRACK ASSETS** pane.

**4. Track Assets**
Click **UPDATE GOOGLE SHEET** to push all approved (not yet tracked) assets to the configured Google Sheet. Both repo and quarantine assets are pushed. Each asset gets a row with status set to `received`, and QC failures are highlighted red in the sheet.

The NOTES column carries the file-type emoji plus where the file came from: `created from …` for a transcode output, `renamed from …` for a file renamed during review, or both.

**Afterwards**
The **APPROVED** and **QUARANTINED** tabs show everything already in each state, so you can look back over past deliveries, check what's still waiting to reach the sheet, or re-transcode something without scanning it in again. See [Tabs](#tabs).

---

## Tabs

Three tabs sit opposite the logo:

| Tab | What it shows |
|---|---|
| **NEW** | The working view — scan, review, approve/quarantine, track. Selected by default. |
| **APPROVED** | Every approved asset in the repo. Browse, filter, and re-transcode. |
| **QUARANTINED** | Every quarantined asset. Same controls as APPROVED. |

**APPROVED and QUARANTINED each list both tracked and untracked assets** — everything in that state, whether or not it has reached the Google Sheet yet. The TRACKED column tells them apart, and you can filter on it to see just what's still waiting to be pushed.

The NEW tab reveals its panes as you go: **CHECK ASSETS** on its own at first, **REVIEW ASSETS** once a scan finishes, and **TRACK ASSETS** once you've approved or quarantined something. (If assets from an earlier session are still waiting to be pushed to the sheet, the track pane opens straight away, so you can always reach it.)

APPROVED and QUARANTINED are the same table as the review view — same columns, sorting, filters, selection and clipboard copy — plus a **TRACKED** column at the end showing whether each asset has been pushed to the Google Sheet yet, and minus the version conflict column and the rename menu item, both of which only make sense while an asset is still awaiting review. Each also has its own preset dropdown and **TRANSCODE** button, so you can re-encode something that has already been approved or quarantined without scanning it in again. Approve and quarantine themselves stay on the NEW tab. They re-read `assets.json` each time you open them, so they always reflect what you just did on the NEW tab.

Note that the FOLDER column on the QUARANTINED tab shows where an asset was *delivered*, not the quarantine folder it now lives in — the original path is kept so you can see where it came from. Transcoding resolves the real location, so a quarantined asset is read from (and its output written to) the quarantine folder.

---

## Reviewing assets

The review table is built on [Tabulator](https://tabulator.info/) 6.5.2, vendored in `app/static/` — no build step or package manager involved. The same table powers the APPROVED and QUARANTINED tabs, so everything below applies there too, except [Version conflicts](#version-conflicts) and [Renaming](#renaming), which are NEW-tab only.

### Sorting

Click any column header to sort, click again to reverse. Duration and Size sort by real magnitude rather than by their displayed text, and Screen / Stem groups audio files together ahead of everything else.

### Filtering

Every column has a filter box under its header.

| Column type | Filter |
|---|---|
| **!** (version conflict) | dropdown: `higher exists` / `equal exists` |
| Folder, Name | type any text — matches anywhere in the value, case-insensitive |
| Screen, Version, Ext, Codec, Audio | dropdown of the values present in this scan |
| Width, Height, FPS, Rate, Bits, Ch, Duration, Size | number, with comparison operators |

Numeric columns accept operators, so you can type:

```
2992      exactly 2992
>3000     greater than 3000
>=3000    3000 or more
<3000     less than 3000
<=3000    3000 or less
!=1080    anything but 1080
```

**Duration filters in seconds and Size filters in MiB** (the units are shown in each box), even though the columns display a timecode and a human-readable size. Files with no value for a column — an audio stem has no width — are excluded whenever that column is filtered.

**Right-click any cell** for `Filter by "<value>"`, which fills in that column's filter box, plus options to clear that column's filter, clear all filters, or reset the column layout. On the NEW tab the same menu offers **Rename…** — see [Renaming](#renaming).

### Flagged assets

"Flagged" means the asset fails any QC rule — codec, resolution or framerate — i.e. the rows showing red cells. Red QC cells appear on every tab; these two buttons are on the NEW tab, above the table:

- **SHOW FLAGGED ONLY (n)** — narrows the table to flagged assets. The count tells you how many the scan found without your having to click. Combines with the column filters rather than replacing them.
- **SELECT ALL FLAGGED** — selects the flagged rows in place, ready for QUARANTINE or TRANSCODE.

Both turn orange while active, and both disappear if no QC rules are configured in `.env`.

### Version conflicts

The narrow **!** column at the far left carries a caution icon when a delivery is *not* newer than an asset you have already approved:

| Icon | Meaning |
|---|---|
| amber triangle | **equal version already approved** — an approved asset carries this exact version, usually the same cut in another format (you approved `1000_test_v2.png`, and now `1000_test_v2.mov` turns up) |
| red triangle | **higher version already approved** — this delivery is behind what you hold (you approved `v008`, and now `v007` arrives) |

Hover the icon for the filename it collided with. The column has its own dropdown filter (`higher exists` / `equal exists`) so you can isolate them, and right-click works as it does anywhere else in the table.

**Only approved assets count as peers.** Two versions arriving in the same delivery are alternates that nobody has ruled on yet, so a dump containing `v007` and `v008` doesn't flag either of them. Quarantined assets aren't peers either — a redelivery at the same version is the expected fix after a rejection, not a problem.

**Only the version number orders anything.** `v02_nlc` and `v02_hap` are separate variants of one version, not a conflict, and neither is higher than the other whatever the suffixes do alphabetically. Zero-padding and case are ignored, so `v02` and `V2` are the same version. A version that isn't a number (`v_final`) is only ever compared for equality.

This is separate from QC flagging: a version conflict isn't a red cell, and SHOW FLAGGED ONLY won't narrow to it. It's a prompt to look, not a verdict — the delivery may well be a legitimate alternate.

### Renaming

Right-click a row on the **NEW** tab and choose **Rename…** to correct a filename in place — most useful when a delivery arrives at a repurposed or lower version number and you'd rather fix it than send it back. The box opens with the current filename and the stem selected, leaving the extension out of the selection the way a file manager does. Enter renames, Esc cancels.

The file is renamed in its own folder and immediately re-scanned, so the row comes back with freshly parsed screen and version fields and its version conflict re-evaluated — including on the row it collided with, which may lose its caution icon as a result. Your selection, sort and filters survive.

A rename is refused, with the reason shown in the box so you can correct it, if the name is empty, contains characters a Windows/SMB share won't accept (`< > : " / \ | ? *`), ends in a space or a full stop, matches one of your `EXCLUDE_FILES` patterns (the file would vanish on the next check), or collides with a file already in that folder. Nothing on disk is touched unless the rename goes through.

The original filename is recorded on the asset as `renamed from <original>` and travels with it into the Google Sheet's NOTES column. Renaming twice keeps pointing at the name the file actually arrived under, and renaming back to that name clears the note.

**Renaming is offered on the NEW tab only.** Once an asset is approved or quarantined its name is recorded in the Google Sheet, and renaming it here would quietly diverge from that.

**If you use cn4m-symmetry:** a rename here only renames the file in the cn4m repo — the symlink source is left untouched, so the two names diverge from that point on. Rename at the source instead if the original name matters downstream.

### Selecting

Tick rows individually, or use the checkbox in the header to select everything. **Selection follows your filters**: the header checkbox and SELECT ALL FLAGGED only ever touch rows you can currently see.

On the NEW tab a count sits next to the action buttons. Because a selection survives a filter change, it reads `12 selected (3 hidden by filter)` when some of the selected rows are no longer visible — worth a glance before approving or quarantining, since those actions move real files. On APPROVED and QUARANTINED the same count appears in the panel header (`14 assets · 3 selected`).

### Copying to a spreadsheet

Click anywhere in the table and press **Ctrl+C** (**Cmd+C** on Mac) to copy it to the clipboard as tab-separated text, ready to paste into Google Sheets or Excel. Column headers are included, and the values are copied as plain data — no icons or formatting.

**You copy what you can see**: only the rows passing the current filters are copied, in the current sort order. So to send someone the flagged assets from a delivery, click SHOW FLAGGED ONLY, then copy. Pasting *into* the table does nothing — it's a review table, not a spreadsheet.

### Column layout

Drag a column's edge to resize it, including narrower than its contents — long filenames get truncated with an ellipsis. Widths, order and the current sort are remembered in your browser between sessions.

Filters are deliberately **not** remembered, so a new scan always opens showing everything.

To get back to the defaults, right-click any cell and choose **Reset column layout**. Double-clicking a column's edge re-fits just that column to its contents.

---

## How it works (technical overview)

cn4m runs as four Docker services:

| Service | Role |
|---|---|
| `web` | Flask web server — serves the UI and handles HTTP requests |
| `worker` | Celery worker — runs all the background tasks (scanning, moving files, transcoding, Google Sheets) |
| `redis` | Message broker between Flask and Celery |
| `flower` | Celery task monitoring dashboard (http://localhost:2641) |

**The frontend** is a single page with no build step: jQuery, Bootstrap and Tabulator 6.5.2 are vendored as plain files in `app/static/`. `cn4m.js` polls the task status endpoint and owns the asset tables — column definitions, QC formatting, filters and selection. All three tables (review, repo, quarantine) are built by one `create_asset_table()` factory, differing only in whether rows are selectable and whether the TRACKED column is shown.

Two read-only endpoints back the browse tabs: `GET /assets/repo` and `GET /assets/quarantine` merge the tracked and untracked buckets and stamp each asset with `tracked`. `GET /untracked_count` reports how many assets are still waiting to be pushed to the sheet. These read `assets.json` directly rather than going through Celery, so **the `web` service mounts your workspace folder too** — read-only, since every mutation happens in the worker. If you add these routes to an existing deployment, `docker compose up -d` is required (a plain `restart` won't pick up a new volume).

**State** is stored in `assets.json` at the workspace root. Every file gets a unique ID (xxhash of its folder path + filename), and assets move through these buckets as they progress:

```
unreviewed_assets  →  untracked_repo_assets  →  tracked_repo_assets
                   →  untracked_quar_assets  →  tracked_quar_assets
                   →  unreviewed_flags
```

Actions that can be started from more than one tab look an asset up across *all* of these buckets rather than assuming it's still unreviewed, and resolve its path accordingly — a quarantined asset's stored `folder` is where it was delivered, but the file itself now lives in the quarantine folder.

One further top-level key, `pending_transcodes`, is not an asset bucket. A transcode output isn't an asset until the next scan finds it, so "created from `<source>`" is parked there — keyed by the ID that scan will compute for the file — and handed to the asset on discovery. Renaming an asset from the review pane records "renamed from `<original>`" on it directly. Both notes travel with the asset into the Google Sheet's NOTES column.

**All actions are async**: each button click fires a POST request that starts a Celery task, and the browser polls a `/status/<task_id>` endpoint to update the progress display.

**The worker runs as root** (via `C_FORCE_ROOT=1` in docker-compose). This is intentional: media deliveries arrive owned by `root` when mounted from the host, and the worker needs to write transcode outputs and move files throughout that tree. Running as a non-root user leaves it unable to write into the delivery folders. cn4m is meant to run on a single trusted workstation processing your own media, so container-root is an acceptable trade-off for reliable file access.

---

## Common operations

### Changing `.env` values

Running containers don't pick up `.env` changes automatically. The safe universal reload is:

```
docker compose down
docker compose up -d
```

(A plain `docker compose restart` works for most variables, but not for `WORKSPACE_FOLDER` — that path is baked into the volume mount at container *creation*, so it specifically needs the full down/up cycle.)

### Adding Python dependencies

Code changes are picked up automatically (the project folder is bind-mounted and both services hot-reload), but changes to `requirements.txt` require a rebuild:

```
docker compose down
docker compose build --no-cache
docker compose up -d
```

To try a package quickly without a rebuild (temporary — the container forgets it on recreate):

```
docker exec -it flask_app sh
pip install <package-name>
exit
```

### Handy Docker commands

```bash
docker ps                        # show running containers
docker compose logs -f web      # follow logs for a service (web / worker / redis / flower)
docker exec -it flask_app sh    # open a shell inside the Flask container
docker compose up --scale worker=3 -d   # run multiple Celery workers in parallel
```

---

## Troubleshooting

**"connect ENOENT \.\pipe\errorReporter" error from Docker at startup**
Add your Windows user to the docker-users group. In PowerShell (as Administrator):
```
net localgroup docker-users <your_windows_username> /add
```
Then restart Docker Desktop.

**Assets aren't showing up after a scan**
- Make sure the `WORKSPACE_FOLDER` path in `.env` matches the actual folder on your machine. The `repo\` and `quarantine\` subdirectories are auto-created if missing, but the parent folder must already exist.
- If you changed `WORKSPACE_FOLDER` recently, run `docker compose down && docker compose up -d` — a restart alone won't remount the volume.
- Run `docker compose logs worker` to see if there are any errors during the scan.

**Edits to the UI aren't showing up**
- **JavaScript / CSS** (`app/static/`) are read from disk on every request — a browser hard-refresh (`Ctrl`/`Cmd`+`Shift`+`R`) is enough.
- **Templates** (`app/templates/*.html`) are compiled and cached by Jinja. `TEMPLATES_AUTO_RELOAD` is enabled in `app/__init__.py` so template edits are also picked up on refresh; without it you would need `docker compose restart web` after every HTML change.
- **On debug mode:** Flask's `FLASK_ENV` variable was removed in Flask 2.3 and silently does nothing on modern versions, so it has been dropped from `docker-compose.yaml`. This project therefore runs with debug **off** — no interactive debugger and no automatic template reloading beyond the config flag above. To turn debug on for development, add `--debug` to the `flask run` command in `docker-compose.yaml`. Leave it off for anything internet-facing: the debugger allows arbitrary code execution.

**Google Sheets push fails**
- Confirm the service account email has Editor access to the sheet.
- Check that `GOOGLE_CREDS` in `.env` contains valid JSON on a single line.
- Run `docker compose logs worker` for the full error.
