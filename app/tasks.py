from celery import shared_task
from app.helpers import *
import os

#@shared_task(name="app.tasks.check_assets")
@shared_task
def check_assets():

    # check for quarantine and repo folders
    repo_folder = get_folder("/cn4m_assets/repo")
    quar_folder = get_folder("/cn4m_assets/quarantine")

    # check for assets.json
    assets = get_json_file("/cn4m_assets/assets.json")
    assets_new = get_json_file("/cn4m_assets/assets_new.json")
    
    # get files from repo
    repo_files = get_files_from_folder(repo_folder)

    print(repo_files)
    return repo_files

@shared_task
def add_numbers(x, y):
    """Simple Celery task that adds two numbers."""
    return x + y

# Explicitly define what gets imported when using `from app.tasks import *`
__all__ = ["check_assets", "add_numbers"]