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
5. Open **http://localhost:5000**, drop some media files into your workspace's `repo\` folder, and click **START**.

To stop: `docker compose down`. A Celery task dashboard (Flower) is also available at http://localhost:5555.

---

## What it does

1. **Scan** — Walks a watched folder (your media delivery drop) and extracts metadata from every new file: codec, resolution, framerate, duration, audio format, sample rate, bit depth, file size, and timestamps.
2. **Review** — Displays all new assets in a sortable, filterable table so you can quickly assess whether they conform to spec. Cells that fail QC (wrong codec, resolution, or framerate) are highlighted red, and a single button narrows the table to just the flagged assets. See [Reviewing assets](#reviewing-assets).
3. **Approve or Quarantine** — Approved files stay in place and are ready to track. Quarantined files are physically moved to a separate folder for manual review.
4. **Track** — Pushes approved assets to a Google Sheet (one row per asset) for production tracking, with a status dropdown: `received → ingested → programmed → waiting → problem`. QC failures are highlighted red in the sheet too.
5. **Transcode** — Runs selected assets through configurable ffmpeg presets (HAP, H.264 proxies, WAV extraction, audio-to-HAP wrapping for disguise/d3 media servers), optionally quarantining the originals afterward.

Optionally, cn4m posts a summary to a Discord channel whenever files are approved, quarantined, or pushed to the sheet.

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
    repo\                 ← auto-created — media deliveries land here
    quarantine\           ← auto-created — files moved here when quarantined
```

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

### Transcode presets

The **TRANSCODE** and **QUARANTINE & TRANSCODE** buttons run the selected assets through an ffmpeg preset chosen from the dropdown. Presets are defined in [config/ffmpeg_config.yaml](config/ffmpeg_config.yaml) — the file is heavily commented and ships with presets for HAP transcodes, H.264 review proxies, WAV audio extraction, and wrapping audio files in a tiny 16×16 HAP `.mov` (so disguise/d3 media servers can play them back as standard video assets). Adding your own preset is a copy-paste-edit of an existing block; no code changes needed.

Preset options can reference `{field}` tokens (like `{framerate}`) that are filled in at runtime from [config/project_config.yaml](config/project_config.yaml) or from the asset's own metadata. Both YAML files are read fresh on every transcode, so edits take effect without a restart.

---

## Workflow

Once the app is open in your browser:

**1. Check Assets**
Click **START** to scan the repo folder for new files. A progress bar shows each file being analyzed. When complete, all new assets appear in the table below.

**2. Review Assets**
The table shows each file's folder, name, screen, version, duration, codec, resolution, framerate, audio specs, and size. Sort by any column, filter by any column, and tick the rows you want to act on — see [Reviewing assets](#reviewing-assets) for the full set of controls.

- Codec, resolution, and framerate cells that fail your QC rules appear in red (hover for the expected value). **SHOW FLAGGED ONLY** narrows the table to just those files, and **SELECT ALL FLAGGED** selects them.
- Flagged files (invalid or corrupt) appear below the table with a warning note.

**3. Approve, Quarantine, or Transcode**
With files selected:
- **APPROVE SELECTED** — marks them as conforming and ready to track. Files stay where they are.
- **QUARANTINE SELECTED** — physically moves them to the quarantine folder for manual review.
- **TRANSCODE** — runs them through the ffmpeg preset chosen in the dropdown (output lands next to the source file).
- **QUARANTINE & TRANSCODE** — transcodes them, then quarantines the originals.

**4. Track Assets**
Click **UPDATE GOOGLE SHEET** to push all approved (not yet tracked) assets to the configured Google Sheet. Both repo and quarantine assets are pushed. Each asset gets a row with status set to `received`, and QC failures are highlighted red in the sheet.

---

## Reviewing assets

The review table (step 2) is built on [Tabulator](https://tabulator.info/) 6.5.2, vendored in `app/static/` — no build step or package manager involved.

### Sorting

Click any column header to sort, click again to reverse. Duration and Size sort by real magnitude rather than by their displayed text, and Screen / Stem groups audio files together ahead of everything else.

### Filtering

Every column has a filter box under its header.

| Column type | Filter |
|---|---|
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

**Right-click any cell** for `Filter by "<value>"`, which fills in that column's filter box, plus options to clear that column's filter, clear all filters, or reset the column layout.

### Flagged assets

"Flagged" means the asset fails any QC rule — codec, resolution or framerate — i.e. the rows showing red cells. Two buttons sit above the table:

- **SHOW FLAGGED ONLY (n)** — narrows the table to flagged assets. The count tells you how many the scan found without your having to click. Combines with the column filters rather than replacing them.
- **SELECT ALL FLAGGED** — selects the flagged rows in place, ready for QUARANTINE or TRANSCODE.

Both turn orange while active, and both disappear if no QC rules are configured in `.env`.

### Selecting

Tick rows individually, or use the checkbox in the header to select everything. **Selection follows your filters**: the header checkbox and SELECT ALL FLAGGED only ever touch rows you can currently see.

A count next to the action buttons shows how many assets are selected. Because a selection survives a filter change, it reads `12 selected (3 hidden by filter)` when some of the selected rows are no longer visible — worth a glance before approving or quarantining, since those actions move real files.

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
| `flower` | Celery task monitoring dashboard (http://localhost:5555) |

**The frontend** is a single page with no build step: jQuery, Bootstrap and Tabulator 6.5.2 are vendored as plain files in `app/static/`. `cn4m.js` polls the task status endpoint and owns the review table — column definitions, QC formatting, filters and selection.

**State** is stored in `assets.json` in the repo folder. Every file gets a unique ID (xxhash of its folder path + filename), and assets move through these buckets as they progress:

```
unreviewed_assets  →  untracked_repo_assets  →  tracked_repo_assets
                   →  untracked_quar_assets  →  tracked_quar_assets
                   →  unreviewed_flags
```

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
