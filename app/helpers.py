from os.path import join, getsize
from pathlib import Path
import os
import json

#repo_folder = "/cn4m_assets/repo"
#quar_folder = "/cn4m_assets/quarantine"

def get_files_from_folder(folder):
    files = [os.path.join(dp, f) for dp, dn, fn in os.walk(os.path.expanduser(folder)) for f in fn]
    return files

def get_folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

def get_json_file(file):
    # check for assets.json - if invalid or doesn't exist, create empty object
    json_file = Path(file)
    if json_file.is_file():
        with open(json_file) as f:
            # make sure file contains valid json
            try:
                json_data = json.load(f)
            except ValueError as e:
                json_data = {}
    else:
        json_data = {}
    return json_data

__all__ = ["get_folder", "get_json_file", "get_files_from_folder"]