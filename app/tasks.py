from celery import shared_task
from app import celery
from app.helpers import *
import os
import time
import json

exclude_files = os.getenv("EXCLUDE_FILES").split(", ")
sleep_time = float(os.getenv("TIME_BETWEEN_CHECKS"))

@celery.task(bind=True)
def approve_assets(self, assets):
    assets_to_approve = json.loads(assets)
    assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    i = 0
    # move approved assets from unreviewed to untracked
    for asset in assets_to_approve:
        i = i+1
        assets["untracked_repo_assets"][asset] = assets["unreviewed_assets"].pop(asset, None)
        self.update_state(state='PROGRESS', meta={'current': i, 'total': len(assets_to_approve), 'status': asset})
        time.sleep(sleep_time)

    write_json_file(assets, "assets.json")
    return {"current": len(assets_to_approve), "total": len(assets_to_approve), "status": "COMPLETE", "result": assets_to_approve}


#@shared_task(name="app.tasks.check_assets")
@celery.task(bind=True)
#@shared_task
def check_assets(self):
    repo_folder = get_folder("/cn4m_assets/repo")           # create folder if doesnt exist
    quar_folder = get_folder("/cn4m_assets/quarantine")     # create folder if doesnt exist
    repo_files = get_files_from_folder(repo_folder)         # get files from repo
    assets = get_json_file("/cn4m_assets/assets.json")      # load file or create object if doesnt exist
    tracked_repo_assets = assets["tracked_repo_assets"]
    tracked_quar_assets = assets["tracked_quar_assets"]
    untracked_repo_assets = assets["untracked_repo_assets"]
    untracked_quar_assets = assets["untracked_quar_assets"]
    unreviewed_assets = assets["unreviewed_assets"]
    current_fileids = all_keys = set(tracked_repo_assets.keys()).union(tracked_quar_assets.keys(), untracked_repo_assets.keys(), untracked_quar_assets.keys(), unreviewed_assets.keys())

    # iterate through each file
    i = 0
    repo_files_qty = len(repo_files)
    for file in repo_files:
        i = i+1
        filename = os.path.basename(file)
        folder = str(os.path.normpath(os.path.dirname(file)))
        fileid = fast_hash(folder + "|" + filename)

        # only work on files that aren't excluded and arent already in assets.json
        if filename[0:2] != '._' and filename not in exclude_files and fileid not in current_fileids:
            unreviewed_assets = check_asset(unreviewed_assets, file, filename)
        
        # progress = int((i / repo_files_qty) * 100)
        self.update_state(state='PROGRESS', meta={'current': i, 'total': repo_files_qty, 'status': filename})
        #print(f"Processing... {progress}%")
        time.sleep(sleep_time)

    assets["unreviewed_assets"].update(unreviewed_assets)
    write_json_file(assets, "assets.json")

    return {"current": repo_files_qty, "total": repo_files_qty, "status": "COMPLETE", "result": unreviewed_assets}
    #return {"status": "Task completed!"}
    #return unreviewed_assets

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
__all__ = ["check_assets", "add_numbers", "long_task", "approve_assets"]





