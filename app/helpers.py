from os.path import join, getsize
from pathlib import Path
from time import strftime, localtime
from pymediainfo import MediaInfo
import os
import json
import time
import xxhash

cn4m_assets = "/cn4m_assets"
repo_folder = "/cn4m_assets/repo"
#quar_folder = "/cn4m_assets/quarantine"

def get_files_from_folder(folder):
    files = [os.path.join(dp, f) for dp, dn, fn in os.walk(os.path.expanduser(folder)) for f in fn]
    return files

def get_folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

def get_json_file(file):
    # first check for assets.json - if invalid or doesn't exist, create empty object
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

    # then check if the right keys exist, and if they don't, add them
    if "tracked_repo_assets" not in json_data:
        json_data["tracked_repo_assets"] = {}
    if "tracked_quar_assets" not in json_data:
        json_data["tracked_quar_assets"] = {}
    if "untracked_repo_assets" not in json_data:
        json_data["untracked_repo_assets"] = {}
    if "untracked_quar_assets" not in json_data:
        json_data["untracked_quar_assets"] = {}
    if "unreviewed_assets" not in json_data:
        json_data["unreviewed_assets"] = {}

    return json_data

def check_asset(assets, file, filename):
    #parent = str(os.path.basename(os.path.dirname(file)))
    folder = str(os.path.normpath(os.path.dirname(file)))
    parent = str(os.path.relpath(folder, repo_folder))
    fileid = fast_hash(folder + "|" + filename)
    assets[fileid] = {}
    assets[fileid]["name"] = filename
    assets[fileid]["parent"] = parent
    assets[fileid]["folder"] = folder
    assets[fileid]["modified"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getmtime(file)))
    assets[fileid]["processed"] = strftime('%Y-%m-%d %H:%M:%S', localtime(int(time.time())))
    # try to get creation and modification time (creation time only works in windows)
    try:
        assets[fileid]["created"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getctime(file)))
    except AttributeError:
        assets[fileid]["created"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getmtime(file)))

    media_info = MediaInfo.parse(file)
    for track in media_info.tracks:
        if track.track_type == "General":
            assets[fileid]["extension"] = track.file_extension
            assets[fileid]["size"] = track.other_file_size[4]

        elif track.track_type == "Video":
            assets[fileid]["duration"] = track.other_duration[4]
            assets[fileid]["framerate"] = track.frame_rate
            assets[fileid]["width"] = track.width
            assets[fileid]["height"] = track.height
            
            video_codec_id = track.codec_id
            if video_codec_id == "ap4x":
                video_codec = "ProRes 4444 XQ"
            elif video_codec_id == "ap4h":
                video_codec = "ProRes 4444"
            elif video_codec_id == "apch":
                video_codec = "ProRes 422 High Quality"
            elif video_codec_id == "apcn":
                video_codec = "ProRes 422"
            elif video_codec_id == "apcs":
                video_codec = "ProRes 422 LT"
            elif video_codec_id == "apco":
                video_codec = "ProRes 422 Proxy"
            elif video_codec_id == "Hap1":
                video_codec = "Hap"
            elif video_codec_id == "Hap5":
                video_codec = "Hap Alpha"
            elif video_codec_id == "HapY":
                video_codec = "Hap Q"
            elif video_codec_id == "HapM":
                video_codec = "Hap Q Alpha"
            elif video_codec_id == "Hap7":
                video_codec = "Hap R"
            elif video_codec_id == "nclc":
                video_codec = "NotchLC"
            elif video_codec_id == "avc1":
                video_codec = "H.264"
            else:
                video_codec = video_codec_id

            assets[fileid]["video_codec"] = video_codec
            
        elif track.track_type == "Audio":
            assets[fileid]["duration"] = track.other_duration[4]
            assets[fileid]["audio"] = track.commercial_name
            #assets[file]["audio_codec"] = track.codec_id
            assets[fileid]["audio_channels"] = track.channel_s
            assets[fileid]["audio_rate"] = track.sampling_rate

            if track.bit_depth:
                assets[fileid]["audio_bits"] = track.bit_depth
            #assets[file]["audio_layout"] = track.channel_layout

        elif track.track_type == "Image":
            assets[fileid]["width"] = track.width
            assets[fileid]["height"] = track.height

    return assets

def write_json_file(json_data, json_filename):
    json_file = Path(os.path.join(cn4m_assets, json_filename))
    with open(json_file, 'w') as f:
        json.dump(json_data, f, indent=4, sort_keys=True)

def fast_hash(input_string, length=32):
    #h = xxhash.xxh64(input_string).hexdigest()  # 64-bit hash
    h = xxhash.xxh128(input_string).hexdigest()  # Use xxh128 for 32-char output
    return h[:length]  # Trim hash if needed


__all__ = ["get_folder", "get_json_file", "get_files_from_folder", "check_asset", "write_json_file", "fast_hash"]