from celery import shared_task
from app import celery
from app.helpers import *
import os
import time
import json

exclude_files = os.getenv("EXCLUDE_FILES").split(", ")
# print("exclude:" + str(exclude_files))
sleep_time = float(os.getenv("TIME_BETWEEN_CHECKS"))
cn4m_folder = "/cn4m_assets"
cn4m_quarantine = os.path.join(cn4m_folder, "quarantine")
cn4m_repo = os.path.join(cn4m_folder, "repo")

print("settings.env google_sheet = " + str(os.getenv("GOOGLE_SHEET")))
print("settings.env exclude_files = " + str(exclude_files))
print("settings.env sleep_time = " + str(os.getenv("TIME_BETWEEN_CHECKS")))
print("docker project_folder = " + str(cn4m_folder))
print("quarantine folder = " + str(cn4m_quarantine))
print("repo folder = " + str(cn4m_repo))

@celery.task(bind=True)
def extract_audio(self, asset):
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    folder = assets["unreviewed_assets"][asset]["folder"]
    filename = assets["unreviewed_assets"][asset]["name"]
    src = os.path.join(folder, filename)
    # print("extracting audio for" + str(asset))
    probe = ffmpeg_extract_audio(src)
    print("return from helper:")
    print(json.dumps(probe, indent = 4))
    self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_approve), 'status': asset})
    return {"current": 1, "total": 1, "status": "COMPLETE", "result": asset}


@celery.task(bind=True)
def approve_assets(self, assets):
    assets_to_approve = json.loads(assets)
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    # src = os.path.join(folder, filename)
    # assets = get_json_file("/cn4m_assets/assets.json")                  # load file or create object if doesnt exist
    i = 0
    # move approved assets from unreviewed to untracked
    for asset in assets_to_approve:
        i = i+1
        assets["untracked_repo_assets"][asset] = assets["unreviewed_assets"].pop(asset, None)
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_approve), 'status': asset})
        time.sleep(sleep_time)

    write_json_file(assets, "assets.json")
    return {"current": len(assets_to_approve), "total": len(assets_to_approve), "status": "COMPLETE", "result": assets_to_approve}


@celery.task(bind=True)
def quarantine_assets(self, assets):
    assets_to_quarantine = json.loads(assets)
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    # assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    i = 0
    # move approved assets from unreviewed to untracked
    for asset in assets_to_quarantine:
        i = i+1
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_quarantine), 'status': asset})
        folder = assets["unreviewed_assets"][asset]["folder"]
        filename = assets["unreviewed_assets"][asset]["name"]
        src = os.path.join(folder, filename)
        dest = os.path.join(cn4m_quarantine, filename)

        # make sure file still exists and if so, move it
        if os.path.isfile(src):
            # move files from repo to quarantine and remove from unreviewed_assets
            move_files(asset, src, dest)
            assets["untracked_quar_assets"][asset] = assets["unreviewed_assets"].pop(asset, None)
        else:
            # flag file as no longer found and remove from unreviewed_assets
            assets["unreviewed_flags"][asset] = assets["unreviewed_assets"].pop(asset, None)
            assets["unreviewed_flags"][asset]["note"] = "marked for quarantine but no longer found"
            assets["unreviewed_flags"][asset]["severity"] = "warn"
        
        time.sleep(sleep_time)
            
    write_json_file(assets, "assets.json")
    return {"current": len(assets_to_quarantine), "total": len(assets_to_quarantine), "status": "COMPLETE", "result": assets_to_quarantine}
    #return "end"


#@shared_task(name="app.tasks.check_assets")
@celery.task(bind=True)
#@shared_task
def check_assets(self):
    repo_folder = get_folder(cn4m_repo)           # create folder if doesnt exist
    quar_folder = get_folder(cn4m_quarantine)     # create folder if doesnt exist
    # repo_folder = get_folder("/cn4m_assets/repo")           # create folder if doesnt exist
    # quar_folder = get_folder("/cn4m_assets/quarantine")     # create folder if doesnt exist
    repo_files = get_files_from_folder(repo_folder)         # get files from repo
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    # assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    tracked_repo_assets = assets["tracked_repo_assets"]
    tracked_quar_assets = assets["tracked_quar_assets"]
    untracked_repo_assets = assets["untracked_repo_assets"]
    untracked_quar_assets = assets["untracked_quar_assets"]
    unreviewed_assets = assets["unreviewed_assets"]
    # get all repo and reviewed assets so we dont recheck them (but okay to recheck quarantined ones)
    current_fileids = all_keys = set(tracked_repo_assets.keys()).union(untracked_repo_assets.keys(), unreviewed_assets.keys())

    #print("repo_files" + str(repo_files))

    # iterate through each file
    i = 0
    progress_qty = len(repo_files) * 2     # multiplying by 2 since we are checking then validating
    for file in repo_files:
        
        filename = os.path.basename(file)
        folder = str(os.path.normpath(os.path.dirname(file)))
        fileid = fast_hash(folder + "|" + filename)

        # check assets
        # only work on files that aren't excluded and arent already in assets.json
        if filename[0:2] != '._' and filename not in exclude_files and fileid not in current_fileids:
            unreviewed_assets = check_asset(unreviewed_assets, file, filename)
            
            #print(f"Processing... {progress}%")
            i = i+1
            self.update_state(state='PROGRESS', meta={'current': i, 'total': progress_qty, 'status': str("analyzing " + str(filename)) })
            time.sleep(sleep_time)

    # validate assets
    invalid_assets = {}
    for asset in unreviewed_assets:
        if "width" not in unreviewed_assets[asset] and "audio" not in unreviewed_assets[asset]:
            invalid_assets[asset] = unreviewed_assets[asset]
            invalid_assets[asset]["note"] = "invalid or corrupt, ignoring"
            invalid_assets[asset]["severity"] = "warn"
            #assets["unreviewed_flags"][asset] = invalid_assets[asset].pop(asset, None)
        i = i+1
        self.update_state(state='PROGRESS', meta={'current': i, 'total': progress_qty, 'status': str("validating " + str(unreviewed_assets[asset]["name"])) })
        time.sleep(sleep_time)

    # move invalid assets to flagged assets
    assets["unreviewed_flags"].update(invalid_assets)
    for asset in invalid_assets:
        del unreviewed_assets[asset]

    # sort assets by dumbpath
    unreviewed_assets = dict(
        sorted(unreviewed_assets.items(), key=lambda item: item[1]["dumbpath"])
    )

    # check unreviewed_assets in case sync.ffs_lock if it somehow sneaks in there
    purge_exclude_files(unreviewed_assets)

    assets["unreviewed_assets"].update(unreviewed_assets)
    write_json_file(assets, "assets.json")

    result = {
        "assets": unreviewed_assets,
        "flags": assets["unreviewed_flags"]
        }

    return {"current": progress_qty, "total": progress_qty, "status": "COMPLETE", "result": result}



@celery.task(bind=True)
def track_assets(self):
    # assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    total = len(assets["untracked_repo_assets"]) + len(assets["untracked_quar_assets"])
    
    # only bother tracking if there are untracked assets
    if total > 0:
        sheet = connect_to_google_sheet()
        setup_google_sheet(sheet)
        i = 0
        repo_rows = []
        repo_assets_to_move = []
        for asset in assets["untracked_repo_assets"]:
            i = i+1
            repo_assets_to_move.append(asset)
            asset = assets["untracked_repo_assets"][asset]
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': asset["name"]})
            row = build_google_row(asset)
            repo_rows.append(row)
            time.sleep(sleep_time)

        update_google_sheet(sheet, "repository", repo_rows)
        # move assets from untracked to tracked
        for asset in repo_assets_to_move:
            assets["tracked_repo_assets"][asset] = assets["untracked_repo_assets"].pop(asset, None)

        quar_rows = []
        quar_assets_to_move = []
        for asset in assets["untracked_quar_assets"]:
            i = i+1
            quar_assets_to_move.append(asset)
            asset = assets["untracked_quar_assets"][asset]
            self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': asset["name"]})
            row = build_google_row(asset)
            quar_rows.append(row)
            time.sleep(sleep_time)

        update_google_sheet(sheet, "quarantine", quar_rows)
        # move assets from untracked to tracked
        for asset in quar_assets_to_move:
            assets["tracked_quar_assets"][asset] = assets["untracked_quar_assets"].pop(asset, None)

        write_json_file(assets, "assets.json")
        return {"current": total, "total": total, "status": "COMPLETE", "result": "untracked items tracked"}

    else:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": "no assets to track"}



@celery.task(bind=True)
def clear_flags(self):
    # assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    assets = get_json_file(os.path.join(cn4m_folder, "assets.json"))      # load file or create object if doesnt exist
    total = len(assets["unreviewed_flags"])
    i = 0
    # only bother tracking if there are untracked assets
    if total > 0:
        assets["untracked_flags"] = assets["unreviewed_flags"].copy()
        assets["unreviewed_flags"] = {}

        write_json_file(assets, "assets.json")
        return {"current": total, "total": total, "status": "COMPLETE", "result": "flags cleared"}

    else:
        return {"current": 0, "total": 0, "status": "COMPLETE", "result": "no flags to clear"}




@shared_task
def add_numbers(x, y):
    """Simple Celery task that adds two numbers."""
    return x + y



@celery.task(bind=True)
def long_task(self):
    """Background task that runs a long function with progress reports."""
    verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
    adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
    noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
    message = ''
    total = random.randint(10, 50)
    for i in range(total):
        if not message or random.random() < 0.25:
            message = '{0} {1} {2}...'.format(random.choice(verb),
                                              random.choice(adjective),
                                              random.choice(noun))
        self.update_state(state='PROGRESS',
                          meta={'current': i, 'total': total,
                                'status': message})
        time.sleep(1)
    return {'current': 100, 'total': 100, 'status': 'Task completed!',
            'result': 42}



# Explicitly define what gets imported when using `from app.tasks import *`
__all__ = ["check_assets", "add_numbers", "long_task", "approve_assets", "quarantine_assets", "track_assets", "clear_flags", "extract_audio"]





