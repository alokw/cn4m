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
    assets = get_json_file(ASSETS_JSON)

    config = load_ffmpeg_config()
    preset = next((p for p in config.get("presets", []) if p["name"] == preset_name), None)

    if preset is None:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": f"preset '{preset_name}' not found"}

    i = 0
    outputs = []  # (output path, source filename) for the provenance note below
    for asset_id in assets_to_transcode:
        i += 1
        # Searched across every bucket, not just unreviewed_assets: transcode can
        # now be run from the APPROVED and QUARANTINED tabs too.
        asset_data, bucket = find_asset(assets, asset_id)
        if not asset_data:
            self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_transcode), 'status': f"skipped {asset_id} (not found)"})
            continue

        filename = asset_data["name"]
        src = asset_source_path(asset_data, bucket)

        if not os.path.isfile(src):
            self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_transcode), 'status': f"skipped {filename} (file missing)"})
            continue

        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_transcode), 'status': filename})

        try:
            out_path = run_ffmpeg_preset(preset, src, asset_data=asset_data)
            outputs.append((out_path, filename))
        except Exception as e:
            print(f"Error transcoding {src} with preset '{preset_name}': {e}")

        time.sleep(sleep_time)

    # Park "created from <source>" for each output so the scan below can stamp it
    # onto the asset it discovers. Re-read first: a long transcode run leaves the
    # copy loaded at the top of this task stale, and writing it back wholesale
    # would undo anything reviewed in the meantime.
    if outputs:
        assets = get_json_file(ASSETS_JSON)
        for out_path, source_name in outputs:
            record_transcode_output(assets, out_path, source_name, preset_name)
        write_json_file(assets, "assets.json")

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

    assets = get_json_file(ASSETS_JSON)

    config = load_ffmpeg_config()
    preset = next((p for p in config.get("presets", []) if p["name"] == preset_name), None)

    if preset is None:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": f"preset '{preset_name}' not found"}

    # ── Phase 1: Transcode ──────────────────────────────────────────────────
    # Only assets whose transcode actually completes (no error, and a non-empty
    # output file exists) are eligible to be quarantined in Phase 2. This keeps
    # a failed transcode from ever moving the original out from under the user.
    transcoded_ok = set()
    outputs = []  # (output path, source filename) for the provenance note below
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
                outputs.append((out_path, filename))
            else:
                print(f"Transcode of {src} produced no output — will not quarantine")
        except Exception as e:
            print(f"Error transcoding {src} with preset '{preset_name}': {e} — will not quarantine")

        time.sleep(sleep_time)

    # Reload assets in case the transcode triggered a check_assets
    assets = get_json_file(ASSETS_JSON)

    # Park "created from <source>" for each output, on the freshly read copy, so
    # the next scan can stamp it onto the asset it discovers. Written to disk by
    # Phase 2's write below.
    for out_path, source_name in outputs:
        record_transcode_output(assets, out_path, source_name, preset_name)

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
            try:
                move_files(asset_id, src, dest)
            except OSError as err:
                assets["unreviewed_flags"][asset_id] = assets["unreviewed_assets"].pop(asset_id)
                assets["unreviewed_flags"][asset_id]["note"] = f"transcoded, but quarantine failed and the original is still in place: {err}"
                assets["unreviewed_flags"][asset_id]["severity"] = "warn"
                time.sleep(sleep_time)
                continue
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
    assets = get_json_file(ASSETS_JSON)
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
    assets = get_json_file(ASSETS_JSON)
    i = 0
    for asset in assets_to_quarantine:
        i = i+1
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_quarantine), 'status': asset})
        folder = assets["unreviewed_assets"][asset]["folder"]
        filename = assets["unreviewed_assets"][asset]["name"]
        src = os.path.join(folder, filename)
        dest = os.path.join(cn4m_quarantine, filename)

        if os.path.isfile(src):
            try:
                move_files(asset, src, dest)
            except OSError as err:
                # Leave it unreviewed and say so, rather than recording a
                # quarantine that never happened.
                assets["unreviewed_flags"][asset] = assets["unreviewed_assets"].pop(asset, None)
                assets["unreviewed_flags"][asset]["note"] = f"quarantine failed, file left in place: {err}"
                assets["unreviewed_flags"][asset]["severity"] = "warn"
                time.sleep(sleep_time)
                continue
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
    assets = get_json_file(ASSETS_JSON)

    tracked_repo_assets = assets["tracked_repo_assets"]
    tracked_quar_assets = assets["tracked_quar_assets"]
    untracked_repo_assets = assets["untracked_repo_assets"]
    untracked_quar_assets = assets["untracked_quar_assets"]
    unreviewed_assets = {}  # fresh dict — new discoveries only; existing unreviewed assets are merged in later

    # Build the set of already-known file IDs so we don't re-scan them.
    # Quarantined assets count as known. Their fileid is hash(original folder +
    # filename) and quarantining deliberately keeps that original folder, so a
    # file still sitting in repo/ under the same name would otherwise be
    # rediscovered as new — putting one fileid in two buckets at once and
    # listing the asset under both NEW and QUARANTINED.
    current_fileids = set().union(
        tracked_repo_assets.keys(), untracked_repo_assets.keys(),
        tracked_quar_assets.keys(), untracked_quar_assets.keys(),
    )

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

    # Hand each newly discovered file the "created from" note parked for it when
    # it was transcoded. Done before validation so a corrupt output still claims
    # its record rather than leaving it behind in the bucket.
    claim_transcode_notes(assets, unreviewed_assets)

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

    # ── Version-up and version conflict detection ─────────────────────────────
    # Both flags look at the approved repo assets we already hold. ☝️/🆕 also
    # counts the rest of this batch; the version conflict caution deliberately
    # does not, so two versions arriving in the same dump — alternates nobody
    # has ruled on yet — don't flag each other. Quarantined assets are peers for
    # neither: they were rejected, so a redelivery is the expected fix.
    apply_version_flags(unreviewed_assets, (tracked_repo_assets, untracked_repo_assets))

    # Sort valid new assets alphabetically by dumbpath (case-insensitive parent.filename)
    unreviewed_assets = dict(
        sorted(unreviewed_assets.items(), key=lambda item: item[1]["dumbpath"])
    )

    # Final safety net: purge any excluded filenames that slipped through
    purge_exclude_files(unreviewed_assets)

    # Unreviewed fileids are deliberately absent from current_fileids, so every
    # unreviewed file is re-read on each check and its entry rebuilt from the
    # file. That refresh is wanted for metadata, but the fresh entry knows
    # nothing of the notes recorded against the old one — where it was renamed
    # from, what it was transcoded from — so carry those across before the merge
    # below overwrites it. Without this, checking twice before approving would
    # quietly drop the note.
    for fileid, asset in unreviewed_assets.items():
        carry_provenance(asset, assets["unreviewed_assets"].get(fileid))

    # Merge new discoveries into existing unreviewed_assets (preserves any not yet reviewed)
    assets["unreviewed_assets"].update(unreviewed_assets)

    # ── Sweep assets whose file has gone ──────────────────────────────────────
    # The merge above only ever adds and overwrites, so an unreviewed asset
    # whose file was deleted or moved out of the repo between checks would sit
    # in the review list forever, pointing at nothing. Flagged rather than
    # dropped in silence, so the disappearance is reported under the table once
    # (clear_flags archives it straight after).
    #
    # Skipped entirely if the repo folder isn't there: a workspace mount that
    # dropped out makes every file look deleted, and quietly emptying the review
    # list is far worse than leaving a stale entry until the next check.
    # Unreviewed assets are always in the repo — quarantining moves them to
    # another bucket — so folder + name is where the file should be.
    if os.path.isdir(cn4m_repo):
        missing = [fileid for fileid, asset in assets["unreviewed_assets"].items()
                   if not (asset and os.path.isfile(os.path.join(asset.get("folder") or "",
                                                                 asset.get("name") or "")))]
        for fileid in missing:
            gone = assets["unreviewed_assets"].pop(fileid) or {}
            gone["note"] = "no longer in the repo, dropped from the review list"
            gone["severity"] = "warn"
            assets["unreviewed_flags"][fileid] = gone
            print(f"Sweeping unreviewed asset that is no longer on disk: {gone.get('name')}")

    write_json_file(assets, "assets.json")

    result = {
        "assets": unreviewed_assets,
        "flags": assets["unreviewed_flags"]
    }
    return {"current": progress_qty, "total": progress_qty, "status": "COMPLETE", "result": result}


# ── Rename asset ──────────────────────────────────────────────────────────────

@celery.task(bind=True)
def rename_asset(self, fileid, new_name):
    """
    Rename one unreviewed asset in place, in its own folder, and re-scan it.

    For deliveries that arrive with a repurposed or lower version number, so the
    file can be fixed from the review pane instead of over SMB and a re-scan.
    Only unreviewed assets are renameable: once something is approved or
    quarantined its name is recorded in the Google Sheet, and renaming it here
    would silently diverge from that.

    Runs in the worker rather than the web container because that's the only one
    with the workspace mounted writable — see the volumes in docker-compose.yaml.

    Refusals (name taken, file gone, invalid characters) come back as
    result.error rather than as a task failure, so the rename dialog can show
    the reason and let the user correct the name. A refusal never touches disk.
    """
    new_name = (new_name or "").strip()

    def refuse(message):
        return {"current": 1, "total": 1, "status": "COMPLETE", "result": {"error": message}}

    assets = get_json_file(ASSETS_JSON)
    unreviewed = assets["unreviewed_assets"]
    asset = unreviewed.get(fileid)

    if not asset:
        return refuse("That asset is no longer in the review list — run the check again.")

    problem = validate_asset_filename(new_name)
    if problem:
        return refuse(problem)

    old_name = asset.get("name") or ""
    folder = asset.get("folder") or ""
    if new_name == old_name:
        return refuse("That is already the filename.")

    src = os.path.join(folder, old_name)
    dst = os.path.join(folder, new_name)

    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 1, 'status': f"renaming {old_name}"})

    if not os.path.isfile(src):
        return refuse(f"{old_name} is no longer in {folder} — run the check again.")
    # A case-only rename ('..._V2.mov' -> '..._v2.mov') is legitimate, and on a
    # case-insensitive share the destination "already exists" because it *is*
    # the source. Anything else that exists is a genuine collision.
    if os.path.exists(dst) and not os.path.samefile(src, dst):
        return refuse(f"{new_name} already exists in that folder.")

    try:
        os.rename(src, dst)
    except OSError as err:
        return refuse(f"Rename failed: {err}")

    # fileid is a hash of folder + filename, so the file has a new one now.
    del unreviewed[fileid]

    rescanned = {}
    try:
        check_asset(rescanned, dst, new_name)
    except Exception as err:
        # Renamed on disk but unreadable afterwards. The entry just dropped
        # described a filename that no longer exists, so save without it and let
        # the next check pick the file up fresh, rather than leaving assets.json
        # describing a ghost.
        write_json_file(assets, "assets.json")
        return refuse(f"Renamed to {new_name}, but reading it back failed: {err}. Run the check again.")

    # Record where the file came from, so the rename is visible in assets.json
    # and travels with the asset into the Google Sheet's NOTES column. A second
    # rename keeps pointing at the name the file actually arrived under rather
    # than at the intermediate one, and renaming back to that clears the note.
    original = asset.get("renamed_from") or old_name
    for renamed in rescanned.values():
        if renamed["name"] != original:
            renamed["renamed_from"] = original
        # renamed_from is decided just above — including the case where renaming
        # back to the original name clears it — so only the transcode note is
        # carried over from the entry check_asset just rebuilt.
        carry_provenance(renamed, asset, keys=("created_from",))

    unreviewed.update(rescanned)

    # Re-flag the whole review list, not just the renamed file — a rename
    # changes which approved asset the row collides with. Same buckets as
    # check_assets. Note this is a wider net than the scan casts, which only
    # ever flags its own batch.
    apply_version_flags(unreviewed, (assets["tracked_repo_assets"], assets["untracked_repo_assets"]))

    # Keep the file sorted the way check_assets leaves it (case-insensitive
    # parent.filename), so the renamed entry doesn't just land at the end.
    assets["unreviewed_assets"] = dict(
        sorted(unreviewed.items(), key=lambda item: item[1].get("dumbpath", ""))
    )
    write_json_file(assets, "assets.json")

    return {"current": 1, "total": 1, "status": "COMPLETE", "result": {
        "fileid": next(iter(rescanned)),   # the renamed asset's new fileid
        "old_fileid": fileid,
        "name": new_name,
        "old_name": old_name,
        "assets": assets["unreviewed_assets"],
    }}


# ── Track assets ──────────────────────────────────────────────────────────────

@celery.task(bind=True)
def track_assets(self):
    """
    Push approved (untracked) assets to Google Sheets and move them to the tracked buckets.
    Handles both repo and quarantine assets in one call.
    Does nothing if there are no untracked assets.
    """
    assets = get_json_file(ASSETS_JSON)
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
    assets = get_json_file(ASSETS_JSON)
    total = len(assets["unreviewed_flags"])

    if total > 0:
        assets["untracked_flags"] = assets["unreviewed_flags"].copy()
        assets["unreviewed_flags"] = {}
        write_json_file(assets, "assets.json")
        return {"current": total, "total": total, "status": "COMPLETE", "result": "flags cleared"}
    else:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": "no flags to clear"}


# Explicitly define what gets imported when using `from app.tasks import *`
__all__ = ["check_assets", "approve_assets", "quarantine_assets", "track_assets", "clear_flags", "transcode_assets", "quarantine_and_transcode", "rename_asset"]
