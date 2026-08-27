# tasks.py
# Celery background tasks. Each task is triggered by a route in routes.py
# and runs asynchronously so the browser doesn't time out on long operations.
# Progress is reported via self.update_state() and polled by the frontend JS.

from app import celery
from app.helpers import *
from app.discord_bot import notify_approved, notify_quarantined, notify_tracked
import os
import time
import json

# ── Config ────────────────────────────────────────────────────────────────────
# Shared config values (env vars + container paths) live in helpers.py.
from app.helpers import sleep_time, cn4m_folder, cn4m_repo, cn4m_quarantine

# Print config at worker startup so it's easy to confirm settings in logs
print(".env google_sheet = " + str(os.getenv("GOOGLE_SHEET")))
print(".env exclude_files = " + str(os.getenv("EXCLUDE_FILES")))
print(".env sleep_time = " + str(os.getenv("TIME_BETWEEN_CHECKS")))
print("repo folder = " + str(cn4m_repo))
print("quarantine folder = " + str(cn4m_quarantine))

# Create repo/ and quarantine/ subdirectories inside WORKSPACE_FOLDER if they
# don't already exist, so a fresh workspace is usable without manual setup.
ensure_workspace_folders()


# ── Transcode assets ──────────────────────────────────────────────────────────

@celery.task(bind=True)
def transcode_assets(self, assets_json, preset_name):
    """
    Transcode selected assets one at a time using the named ffmpeg preset
    from config/ffmpeg_config.yaml. Reports progress per asset.
    """
    assets_to_transcode = json.loads(assets_json)
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))

    config = load_ffmpeg_config()
    preset = next((p for p in config.get("presets", []) if p["name"] == preset_name), None)

    if preset is None:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": f"preset '{preset_name}' not found"}

    i = 0
    for asset_id in assets_to_transcode:
        i += 1
        asset_data = assets["unreviewed_assets"].get(asset_id)
        if not asset_data:
            self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_transcode), 'status': f"skipped {asset_id} (not found)"})
            continue

        folder = asset_data["folder"]
        filename = asset_data["name"]
        src = os.path.join(folder, filename)

        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_transcode), 'status': filename})

        try:
            run_ffmpeg_preset(preset, src, asset_data=asset_data)
        except Exception as e:
            print(f"Error transcoding {src} with preset '{preset_name}': {e}")

        time.sleep(sleep_time)

    check_assets.delay()
    return {"current": len(assets_to_transcode), "total": len(assets_to_transcode), "status": "COMPLETE", "result": f"transcoded {len(assets_to_transcode)} asset(s) with '{preset_name}'"}


# ── Quarantine & transcode assets ────────────────────────────────────────────

@celery.task(bind=True)
def quarantine_and_transcode(self, assets_json, preset_name):
    """
    Transcode selected assets one at a time, then move the originals to quarantine.
    Progress is reported across both phases as a single continuous count.
    """
    assets_to_process = json.loads(assets_json)
    total = len(assets_to_process) * 2
    i = 0

    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))

    config = load_ffmpeg_config()
    preset = next((p for p in config.get("presets", []) if p["name"] == preset_name), None)

    if preset is None:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": f"preset '{preset_name}' not found"}

    # ── Phase 1: Transcode ──────────────────────────────────────────────────
    # Only assets whose transcode actually completes (no error, and a non-empty
    # output file exists) are eligible to be quarantined in Phase 2. This keeps
    # a failed transcode from ever moving the original out from under the user.
    transcoded_ok = set()
    for asset_id in assets_to_process:
        i += 1
        asset_data = assets["unreviewed_assets"].get(asset_id)
        if not asset_data:
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': f"skipped {asset_id} (not found)"})
            continue

        filename = asset_data["name"]
        src = os.path.join(asset_data["folder"], filename)

        self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': f"transcoding {filename}"})

        try:
            out_path = run_ffmpeg_preset(preset, src, asset_data=asset_data)
            if out_path and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                transcoded_ok.add(asset_id)
            else:
                print(f"Transcode of {src} produced no output — will not quarantine")
        except Exception as e:
            print(f"Error transcoding {src} with preset '{preset_name}': {e} — will not quarantine")

        time.sleep(sleep_time)

    # Reload assets in case the transcode triggered a check_assets
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))

    # ── Phase 2: Quarantine originals (only the ones that transcoded) ────────
    for asset_id in assets_to_process:
        i += 1
        asset_data = assets["unreviewed_assets"].get(asset_id)
        if not asset_data:
            continue

        filename = asset_data["name"]

        # Transcode failed for this asset — leave the original in place and flag it
        # so the user knows it wasn't quarantined (rather than silently moving it).
        if asset_id not in transcoded_ok:
            assets["unreviewed_flags"][asset_id] = assets["unreviewed_assets"].pop(asset_id)
            assets["unreviewed_flags"][asset_id]["note"] = "transcode failed — original left in place, not quarantined"
            assets["unreviewed_flags"][asset_id]["severity"] = "warn"
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': f"skipped {filename} (transcode failed)"})
            time.sleep(sleep_time)
            continue

        src = os.path.join(asset_data["folder"], filename)
        dest = os.path.join(cn4m_quarantine, filename)

        self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': f"quarantining {filename}"})

        if os.path.isfile(src):
            move_files(asset_id, src, dest)
            assets["untracked_quar_assets"][asset_id] = assets["unreviewed_assets"].pop(asset_id)
        else:
            assets["unreviewed_flags"][asset_id] = assets["unreviewed_assets"].pop(asset_id)
            assets["unreviewed_flags"][asset_id]["note"] = "marked for quarantine but no longer found"
            assets["unreviewed_flags"][asset_id]["severity"] = "warn"

        time.sleep(sleep_time)

    write_json_file(assets, "assets.json")

    quarantined_data = {fid: assets["untracked_quar_assets"][fid] for fid in assets_to_process if fid in assets["untracked_quar_assets"]}
    notify_quarantined(quarantined_data)

    check_assets.delay()
    return {"current": total, "total": total, "status": "COMPLETE", "result": f"transcoded and quarantined {len(assets_to_process)} asset(s) with '{preset_name}'"}


# ── Approve assets ────────────────────────────────────────────────────────────

@celery.task(bind=True)
def approve_assets(self, assets):
    """
    Move selected assets from unreviewed_assets → untracked_repo_assets.
    'Approved' means the files look good and are ready to be pushed to Google Sheets.
    The files themselves stay in place — only the JSON state changes.
    """
    assets_to_approve = json.loads(assets)
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))
    i = 0
    for asset in assets_to_approve:
        i = i+1
        assets["untracked_repo_assets"][asset] = assets["unreviewed_assets"].pop(asset, None)
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_approve), 'status': asset})
        time.sleep(sleep_time)

    write_json_file(assets, "assets.json")

    # Notify Discord with the list of approved files
    approved_data = {fid: assets["untracked_repo_assets"][fid] for fid in assets_to_approve if fid in assets["untracked_repo_assets"]}
    notify_approved(approved_data)

    return {"current": len(assets_to_approve), "total": len(assets_to_approve), "status": "COMPLETE", "result": assets_to_approve}


# ── Quarantine assets ─────────────────────────────────────────────────────────

@celery.task(bind=True)
def quarantine_assets(self, assets):
    """
    Physically move selected files from the repo folder to the quarantine folder,
    then update the JSON state: unreviewed_assets → untracked_quar_assets.
    If a file has disappeared since the last check, flag it instead of crashing.
    """
    assets_to_quarantine = json.loads(assets)
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))
    i = 0
    for asset in assets_to_quarantine:
        i = i+1
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_quarantine), 'status': asset})
        folder = assets["unreviewed_assets"][asset]["folder"]
        filename = assets["unreviewed_assets"][asset]["name"]
        src = os.path.join(folder, filename)
        dest = os.path.join(cn4m_quarantine, filename)

        if os.path.isfile(src):
            # Move file and record it as a quarantined asset
            move_files(asset, src, dest)
            assets["untracked_quar_assets"][asset] = assets["unreviewed_assets"].pop(asset, None)
        else:
            # File is gone — flag it so the user knows rather than silently dropping it
            assets["unreviewed_flags"][asset] = assets["unreviewed_assets"].pop(asset, None)
            assets["unreviewed_flags"][asset]["note"] = "marked for quarantine but no longer found"
            assets["unreviewed_flags"][asset]["severity"] = "warn"

        time.sleep(sleep_time)

    write_json_file(assets, "assets.json")

    # Notify Discord with the list of quarantined files (only those actually moved, not flagged)
    quarantined_data = {fid: assets["untracked_quar_assets"][fid] for fid in assets_to_quarantine if fid in assets["untracked_quar_assets"]}
    notify_quarantined(quarantined_data)

    return {"current": len(assets_to_quarantine), "total": len(assets_to_quarantine), "status": "COMPLETE", "result": assets_to_quarantine}


# ── Check assets ──────────────────────────────────────────────────────────────

@celery.task(bind=True)
def check_assets(self):
    """
    Scan the repo folder for new files and extract their media metadata.

    Files already in tracked or untracked buckets are skipped (no re-scanning).
    New files are parsed with pymediainfo; files with no video width AND no audio
    track are considered invalid/corrupt and moved to unreviewed_flags.
    Valid new files are sorted alphabetically by dumbpath and added to unreviewed_assets.
    """
    repo_folder = get_folder(cn4m_repo)
    quar_folder = get_folder(cn4m_quarantine)
    repo_files = get_files_from_folder(cn4m_repo)
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))

    tracked_repo_assets = assets["tracked_repo_assets"]
    tracked_quar_assets = assets["tracked_quar_assets"]
    untracked_repo_assets = assets["untracked_repo_assets"]
    untracked_quar_assets = assets["untracked_quar_assets"]
    unreviewed_assets = {}  # fresh dict — new discoveries only; existing unreviewed assets are merged in later

    # Build the set of already-known file IDs so we don't re-scan them
    current_fileids = set(tracked_repo_assets.keys()).union(untracked_repo_assets.keys())

    i = 0
    progress_qty = len(repo_files) * 2  # x2: one pass for scanning, one for validation

    # ── Pass 1: scan and extract metadata ─────────────────────────────────────
    for file in repo_files:
        filename = os.path.basename(file)
        folder = str(os.path.normpath(os.path.dirname(file)))
        fileid = fast_hash(folder + "|" + filename)

        # Skip: excluded filenames (matched with wildcards via is_excluded) and already-known files
        if not is_excluded(filename) and fileid not in current_fileids:
            unreviewed_assets = check_asset(unreviewed_assets, file, filename)
            i = i+1
            self.update_state(state='PROGRESS', meta={'current': i, 'total': progress_qty, 'status': str("analyzing " + str(filename)) })
            time.sleep(sleep_time)

    # ── Pass 2: validate — flag files with no video and no audio ──────────────
    invalid_assets = {}
    for asset in unreviewed_assets:
        if "width" not in unreviewed_assets[asset] and "audio" not in unreviewed_assets[asset]:
            invalid_assets[asset] = unreviewed_assets[asset]
            invalid_assets[asset]["note"] = "invalid or corrupt, ignoring"
            invalid_assets[asset]["severity"] = "warn"
        i = i+1
        self.update_state(state='PROGRESS', meta={'current': i, 'total': progress_qty, 'status': str("validating " + str(unreviewed_assets[asset]["name"])) })
        time.sleep(sleep_time)

    # Move invalid files to the flags bucket and remove them from the main set
    assets["unreviewed_flags"].update(invalid_assets)
    for asset in invalid_assets:
        del unreviewed_assets[asset]

    # ── Version-up detection ──────────────────────────────────────────────────
    # Collect basenames of all repo assets we've already seen (tracked + untracked).
    # Checks both "basename" (current naming) and "asset_basename" (older entries)
    # so existing assets.json files don't need to be migrated.
    # Comparison is case-insensitive — basenames are lowercased on both sides
    # so e.g. "100_TeSt_A" (existing) matches "100_test_a" (new).
    existing_basenames = set()
    for bucket in (tracked_repo_assets, untracked_repo_assets):
        for existing in bucket.values():
            bn = existing.get("basename") or existing.get("asset_basename")
            if bn:
                existing_basenames.add(bn.casefold())

    # Flag any new asset whose basename matches an existing repo asset (i.e. it's a new version)
    for asset in unreviewed_assets.values():
        bn = asset.get("basename")
        asset["is_version_up"] = bool(bn) and bn.casefold() in existing_basenames

    # The set above only knows assets from previous scans, so a basename arriving
    # more than once within this same batch (e.g. v02 and v03 both land before
    # anyone reviews them) wouldn't be caught. Group the batch by basename and
    # mark all but the lowest version as version-ups too.
    # Assets with no parsed version sit this out: their basename is just the
    # filename stem, so two unrelated non-conforming files could collide.
    same_scan_groups = {}
    for asset in unreviewed_assets.values():
        bn = asset.get("basename")
        if bn and asset.get("version"):
            same_scan_groups.setdefault(bn.casefold(), []).append(asset)

    for group in same_scan_groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda a: version_sort_key(a.get("version", "")))
        for asset in group[1:]:  # lowest version stays 🆕; everything above it is a version-up
            asset["is_version_up"] = True
    # Sort valid new assets alphabetically by dumbpath (case-insensitive parent.filename)
    unreviewed_assets = dict(
        sorted(unreviewed_assets.items(), key=lambda item: item[1]["dumbpath"])
    )

    # Final safety net: purge any excluded filenames that slipped through
    purge_exclude_files(unreviewed_assets)

    # Merge new discoveries into existing unreviewed_assets (preserves any not yet reviewed)
    assets["unreviewed_assets"].update(unreviewed_assets)
    write_json_file(assets, "assets.json")

    result = {
        "assets": unreviewed_assets,
        "flags": assets["unreviewed_flags"]
    }
    return {"current": progress_qty, "total": progress_qty, "status": "COMPLETE", "result": result}


# ── Track assets ──────────────────────────────────────────────────────────────

@celery.task(bind=True)
def track_assets(self):
    """
    Push approved (untracked) assets to Google Sheets and move them to the tracked buckets.
    Handles both repo and quarantine assets in one call.
    Does nothing if there are no untracked assets.
    """
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))
    total = len(assets["untracked_repo_assets"]) + len(assets["untracked_quar_assets"])

    if total > 0:
        sheet = connect_to_google_sheet()
        setup_google_sheet(sheet)  # creates worksheets if they don't exist yet
        i = 0

        # ── Repository assets ──────────────────────────────────────────────────
        repo_rows = []
        repo_assets_to_move = []
        for asset in assets["untracked_repo_assets"]:
            i = i+1
            repo_assets_to_move.append(asset)
            asset_data = assets["untracked_repo_assets"][asset]
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': asset_data["name"]})
            repo_rows.append(build_google_row(asset_data))
            time.sleep(sleep_time)

        qc_codecs = parse_qc_codecs()
        qc_resolutions = parse_qc_resolutions()
        qc_fps = parse_qc_fps()

        update_google_sheet(sheet, "repository", repo_rows, qc_codecs=qc_codecs, qc_resolutions=qc_resolutions, qc_fps=qc_fps)
        for asset in repo_assets_to_move:
            assets["tracked_repo_assets"][asset] = assets["untracked_repo_assets"].pop(asset, None)

        # ── Quarantine assets ──────────────────────────────────────────────────
        quar_rows = []
        quar_assets_to_move = []
        for asset in assets["untracked_quar_assets"]:
            i = i+1
            quar_assets_to_move.append(asset)
            asset_data = assets["untracked_quar_assets"][asset]
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': asset_data["name"]})
            quar_rows.append(build_google_row(asset_data))
            time.sleep(sleep_time)

        update_google_sheet(sheet, "quarantine", quar_rows, qc_codecs=qc_codecs, qc_resolutions=qc_resolutions, qc_fps=qc_fps)
        for asset in quar_assets_to_move:
            assets["tracked_quar_assets"][asset] = assets["untracked_quar_assets"].pop(asset, None)

        write_json_file(assets, "assets.json")
        notify_tracked()
        return {"current": total, "total": total, "status": "COMPLETE", "result": "untracked items tracked"}

    else:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": "no assets to track"}


# ── Clear flags ───────────────────────────────────────────────────────────────

@celery.task(bind=True)
def clear_flags(self):
    """
    Move all current unreviewed_flags → untracked_flags (archiving them) and reset
    the unreviewed_flags bucket to empty. Called automatically after each asset check
    so the flags panel stays fresh and only shows results from the latest scan.
    """
    assets = get_json_file(os.path.join(cn4m_repo, "assets.json"))
    total = len(assets["unreviewed_flags"])

    if total > 0:
        assets["untracked_flags"] = assets["unreviewed_flags"].copy()
        assets["unreviewed_flags"] = {}
        write_json_file(assets, "assets.json")
        return {"current": total, "total": total, "status": "COMPLETE", "result": "flags cleared"}
    else:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": "no flags to clear"}


# Explicitly define what gets imported when using `from app.tasks import *`
__all__ = ["check_assets", "approve_assets", "quarantine_assets", "track_assets", "clear_flags", "transcode_assets", "quarantine_and_transcode"]
