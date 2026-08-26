# cn4m

**cn4m** (a riff on "conform") is a media conformance tool built by Creative Outbox. It scans incoming media deliveries from creative teams, extracts technical metadata from every file, and gives you a fast way to approve or quarantine assets before they go into production. Approved assets are automatically pushed to a Google Sheet for enterprise-level tracking.

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
   git clone https://github.com/alokw/outbox_cn4m.git
   cd outbox_cn4m
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
2. **Review** — Displays all new assets in a sortable table so you can quickly assess whether they conform to spec. Cells that fail QC (wrong codec, resolution, or framerate) are highlighted red.
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
The table shows each file's folder, name, screen, version, duration, codec, resolution, framerate, audio specs, and size. Click any column header to sort. Use the checkboxes to select files (**SELECT ALL AUDIO** grabs every audio file at once).

- Codec, resolution, and framerate cells that fail your QC rules appear in red (hover for the expected value).
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

## How it works (technical overview)

cn4m runs as four Docker services:

| Service | Role |
|---|---|
| `web` | Flask web server — serves the UI and handles HTTP requests |
| `worker` | Celery worker — runs all the background tasks (scanning, moving files, transcoding, Google Sheets) |
| `redis` | Message broker between Flask and Celery |
| `flower` | Celery task monitoring dashboard (http://localhost:5555) |

**State** is stored in `assets.json` in the repo folder. Every file gets a unique ID (xxhash of its folder path + filename), and assets move through these buckets as they progress:

```
unreviewed_assets  →  untracked_repo_assets  →  tracked_repo_assets
                   →  untracked_quar_assets  →  tracked_quar_assets
                   →  unreviewed_flags
```

**All actions are async**: each button click fires a POST request that starts a Celery task, and the browser polls a `/status/<task_id>` endpoint to update the progress display.

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

**Google Sheets push fails**
- Confirm the service account email has Editor access to the sheet.
- Check that `GOOGLE_CREDS` in `.env` contains valid JSON on a single line.
- Run `docker compose logs worker` for the full error.
