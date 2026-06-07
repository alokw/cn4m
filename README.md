# cn4m

**cn4m** (a riff on "conform") is a media conformance tool built by Creative Outbox. It scans incoming media deliveries from creative teams, extracts technical metadata from every file, and gives you a fast way to approve or quarantine assets before they go into production. Approved assets are automatically pushed to a Google Sheet for enterprise-level tracking.

---

## What it does

1. **Scan** — Walks a watched folder (your media delivery drop) and extracts metadata from every new file: codec, resolution, framerate, duration, audio format, sample rate, bit depth, file size, and timestamps.
2. **Review** — Displays all new assets in a sortable table so you can quickly assess whether they conform to spec. Cells that fail QC (wrong codec or resolution) are highlighted red.
3. **Approve or Quarantine** — Approved files stay in place and are ready to track. Quarantined files are physically moved to a separate folder for manual review.
4. **Track** — Pushes approved assets to a Google Sheet (one row per asset) for production tracking, with a status dropdown: `received → ingested → programmed → waiting → problem`. QC failures are highlighted red in the sheet too.
5. **Extract Audio** — For audio-only files, wraps the audio in a tiny 16×16 HAP-encoded `.mov` so disguise/d3 media servers can play it back as a standard video asset.

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows or Mac)
- A Google Cloud service account with access to the target Google Sheet (see [Configuration](#configuration))
- A Discord webhook URL for the target channel (see [Discord notifications](#discord-notifications))

---

## Installation

1. Install [Git](https://git-scm.com/) or [GitHub Desktop](https://desktop.github.com/)
2. Clone this repository:
   - In GitHub Desktop: **File → Clone Repository → URL** → `https://github.com/alokw/outbox_cn4m.git`
   - Or in a terminal: `git clone https://github.com/alokw/outbox_cn4m.git`
3. Copy `.env.example` to `.env` and fill in your settings (see [Configuration](#configuration))

---

## Configuration

All settings live in the `.env` file in the project root. Key variables:

| Variable | Description |
|---|---|
| `REPO_FOLDER` | Full path to the folder where media deliveries land on your machine (e.g. `M:\wbd26_aspera\project`) |
| `QUAR_FOLDER` | Full path to the quarantine folder on your machine |
| `TZ` | Your local timezone (e.g. `America/Los_Angeles`, `America/New_York`, `Europe/London`). Used to stamp correct local times on sheet entries. |
| `GOOGLE_SHEET` | The ID from your Google Sheet's URL: `https://docs.google.com/spreadsheets/d/`**`<ID>`**`/edit` |
| `GOOGLE_CREDS` | The full JSON content of your Google service account key file (paste as a single line) |
| `EXCLUDE_FILES` | Comma-separated list of filenames to ignore during scanning (robocopy logs, sync tool temp files, .DS_Store, etc.) |
| `TIME_BETWEEN_CHECKS` | Delay (in seconds) between processing each file — keeps Celery progress updates responsive in the UI. Default: `0.001` |
| `SECRET_KEY` | A random string used for Flask session security. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DISCORD_WEBHOOK_URL` | Webhook URL for the Discord channel to post notifications to (see [Discord notifications](#discord-notifications)) |
| `QC_CODEC` | Comma-separated list of allowed codecs (e.g. `NotchLC, Hap`). Assets with any other codec are flagged red in the UI and sheet. Leave blank to skip codec QC. |
| `QC_RESOLUTION` | Per-screen resolution rules as `SCREEN@WxH` entries, comma-separated (e.g. `A1@112x336, B1@224x448`). Width and height are checked independently — only the non-matching dimension turns red. Leave blank to skip resolution QC. |
| `CELERY_BROKER_URL` | Redis URL for the Celery task queue. Default: `redis://redis:6379/0` (no change needed for Docker) |
| `RESULT_BACKEND` | Redis URL for storing Celery task results. Default: `redis://redis:6379/0` |

### Google Sheets setup

1. Create a Google Cloud project and enable the Google Sheets API and Google Drive API.
2. Create a service account and download the JSON key file.
3. Share your target Google Sheet with the service account email address (give it **Editor** access).
4. Paste the entire JSON key file content as the value of `GOOGLE_CREDS` in `.env`.
5. Copy the Sheet ID from the URL and set it as `GOOGLE_SHEET`.

The app will automatically create `repository` and `quarantine` worksheets with headers, formatting, and dropdown validation on first use.

### Discord notifications

cn4m sends a message to a Discord channel when:
- **Files are approved** — lists each approved asset
- **Files are quarantined** — lists each quarantined asset
- **Google Sheet is updated** — confirms the push

To set this up:
1. In Discord, open the channel you want notifications posted to.
2. Go to **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Give it a name, optionally set an avatar, then click **Copy Webhook URL**. This is your `DISCORD_WEBHOOK_URL`.
4. Add it to your `.env` file.

Notifications are optional — if `DISCORD_WEBHOOK_URL` is missing from `.env`, the app will skip them silently.

### QC checks

cn4m can automatically flag assets that don't meet show specs:

**Codec** — set `QC_CODEC` to a comma-separated list of allowed codecs. Any asset whose codec doesn't match turns red in the review table and in the Google Sheet.

```
QC_CODEC='NotchLC, Hap'
```

**Resolution** — set `QC_RESOLUTION` to a comma-separated list of `SCREEN@WxH` rules. The screen ID is matched against the parsed screen field in the filename (case-insensitive). Width and height are checked independently — only the dimension(s) that don't match turn red.

```
QC_RESOLUTION='A1@112x336, B1@224x448, HD@1920x1080'
```

Both settings are optional. Leave either blank to skip that check entirely. Codec matching is case-insensitive. Screen ID matching is case-insensitive.

---

## Adding new Python dependencies

Any time you add a package to `requirements.txt`, you need to do a full Docker rebuild so the new package gets installed inside the container. **Code changes alone don't require this** — but dependency changes do.

```
docker compose down
docker compose build --no-cache
docker compose up -d
```

If you want to test a package quickly without a full rebuild (temporary — you still need to rebuild eventually):
```
docker exec -it flask_app sh
pip install <package-name>
exit
```

---

## Updating `.env` values

Running containers don't automatically pick up changes to `.env`. To reload your settings:

```
docker compose down
docker compose up
```

This is the safest universal command and works for any variable. The reason a simple `docker compose restart` isn't always enough: `REPO_FOLDER` and `QUAR_FOLDER` are interpolated by docker-compose into volume mounts, and volume mounts are locked in at container *creation* — not at start. So changing those paths specifically requires a full down/up cycle.

For variables that are only read by Python at startup (like `GOOGLE_SHEET`, `GOOGLE_CREDS`, `EXCLUDE_FILES`, `DISCORD_WEBHOOK_URL`, `QC_CODEC`, `QC_RESOLUTION`, `TZ`, `TIME_BETWEEN_CHECKS`), `docker compose restart` is enough — but down/up never hurts.

---

## Running cn4m

1. Make sure Docker Desktop is running.
2. Open a terminal (PowerShell on Windows, Terminal on Mac) and navigate to the project folder.
3. Start all services:
   ```
   docker compose up
   ```
   Or to run in the background:
   ```
   docker compose up -d
   ```
4. Open a browser and go to **http://localhost:5000**

### Stopping cn4m
```
docker compose down
```

---

## Workflow

Once the app is open in your browser:

**1. Check Assets**
Click **START** to scan the repo folder for new files. A progress bar shows each file being analyzed. When complete, all new assets appear in the table below.

**2. Review Assets**
The table shows each file's folder, name, duration, codec, resolution, audio specs, and size. Click any column header to sort. Use the checkboxes to select files.

- Codec and resolution cells that don't match your QC rules appear in red (hover for the expected value).
- The musical note button (♬) on each row will extract a HAP audio proxy for that file.
- Flagged files (invalid or corrupt) appear below the table with a warning note.

**3. Approve or Quarantine**
With files selected:
- **Approve Selected** — marks them as conforming and ready to track. Files stay where they are.
- **Quarantine Selected** — physically moves them to the quarantine folder for manual review.

**4. Track Assets**
Click **Update Google Sheet** to push all approved (not yet tracked) assets to the configured Google Sheet. Both repo and quarantine assets are pushed. Each asset gets a row with status set to `received`. QC failures are highlighted red in the sheet.

---

## How the app works (technical overview)

cn4m runs as four Docker services:

| Service | Role |
|---|---|
| `web` | Flask web server — serves the UI and handles HTTP requests |
| `worker` | Celery worker — runs all the background tasks (scanning, moving files, Google Sheets) |
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

## Troubleshooting

**"connect ENOENT \.\pipe\errorReporter" error from Docker at startup**
Add your Windows user to the docker-users group. In PowerShell (as Administrator):
```
net localgroup docker-users <your_windows_username> /add
```
Then restart Docker Desktop.

**Assets aren't showing up after a scan**
- Make sure the `REPO_FOLDER` path in `.env` matches the actual folder on your machine.
- Check that the path is correctly mapped in `docker-compose.yaml` under `volumes`.
- Run `docker compose logs worker` to see if there are any errors during the scan.

**Google Sheets push fails**
- Confirm the service account email has Editor access to the sheet.
- Check that `GOOGLE_CREDS` in `.env` contains valid JSON (no line breaks, properly escaped).
- Run `docker compose logs worker` for the full error.

**Need to add new Python dependencies**
See [Adding new Python dependencies](#adding-new-python-dependencies) above.

---

## Archive: Command Reference

These are useful Docker commands for managing and debugging the running containers.

```bash
# Show all running containers
docker ps

# View all service logs
docker compose logs

# Follow logs for a specific service
docker compose logs -f web
docker compose logs -f worker

# Open a shell inside the Flask container
docker exec -it flask_app sh

# Rebuild and restart containers (picks up code changes)
docker compose up --build

# Full rebuild with no cache (use when adding/removing Python packages)
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up

# Install new packages without a full rebuild (temporary — still rebuild eventually)
docker exec -it flask_app sh
pip install -r requirements.txt
exit
docker compose down
docker compose up --build -d

# Scale Celery workers (run multiple workers in parallel)
docker compose up --scale worker=3 -d
```
