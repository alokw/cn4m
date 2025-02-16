from os.path import join, getsize
from pathlib import Path
from time import strftime, localtime
from pymediainfo import MediaInfo
import os
import json
import time
import xxhash
import gspread

cn4m_assets = "/cn4m_assets"
repo_folder = "/cn4m_assets/repo"
#quar_folder = "/cn4m_assets/quarantine"

google_creds = os.getenv("GOOGLE_CREDS")
google_sheet = os.getenv("GOOGLE_SHEET")
sleep_time = float(os.getenv("TIME_BETWEEN_CHECKS"))

def connect_to_google_sheet():
    gc = gspread.service_account_from_dict(json.loads(google_creds))
    sheet = gc.open_by_key(google_sheet)
    return sheet

def update_google_sheet(sheet, worksheet, assets, total, i, self):
    selected_worksheet = sheet.worksheet(worksheet)
    new_items = []
    for asset in assets:
        i = i+1
        item = []
        item.append(assets[asset]["parent"])
        item.append(assets[asset]["name"])
        self.update_state(state='PROGRESS', meta={'current': i, 'total': total, 'status': assets[asset]["name"]})
        item.append(assets[asset]["duration"]) if "duration" in assets[asset] else item.append("")
        item.append("")
        item.append(assets[asset]["video_codec"]) if "video_codec" in assets[asset] else item.append("")
        item.append(assets[asset]["width"]) if "width" in assets[asset] else item.append("")
        item.append(assets[asset]["height"]) if "height" in assets[asset] else item.append("")
        item.append(assets[asset]["framerate"]) if "framerate" in assets[asset] else item.append("")
        item.append(assets[asset]["audio"]) if "audio" in assets[asset] else item.append("")
        item.append(assets[asset]["audio_rate"]) if "audio_rate" in assets[asset] else item.append("")
        item.append(assets[asset]["audio_bits"]) if "audio_bits" in assets[asset] else item.append("")
        item.append(assets[asset]["audio_channels"]) if "audio_channels" in assets[asset] else item.append("")
        item.append(assets[asset]["size"]) if "size" in assets[asset] else item.append("")
        item.append(assets[asset]["created"]) if "created" in assets[asset] else item.append("")
        item.append(assets[asset]["modified"]) if "modified" in assets[asset] else item.append("")
        item.append(assets[asset]["processed"]) if "processed" in assets[asset] else item.append("")
        item.append(assets[asset]["folder"]) if "folder" in assets[asset] else item.append("")
        new_items.append(item)
        time.sleep(sleep_time)

    selected_worksheet.insert_rows(new_items, row=2, value_input_option='RAW', inherit_from_before=False)
    return i


def setup_google_sheet(sheet):
    headers = [ "PARENT", "NAME", "DURATION", "NOTES", "CODEC", "WIDTH", "HEIGHT", "FRAMERATE", "AUDIO", "RATE", "BITS", "CHANNELS", "SIZE", "CREATED", "MODIFIED", "PROCESSED", "FOLDER" ]
    header_formatting = {
          "backgroundColor": { "red": 0.0, "green": 0.0, "blue": 0.0 },
          "textFormat": {
            "foregroundColor": { "red": 1.0, "green": 1.0, "blue": 1.0 },
            "bold": True
          }
        }

    # get list of worksheets and check if ingest sheet is setup
    worksheet_objs = sheet.worksheets()
    worksheets_list = []
    for worksheet in worksheet_objs:
        worksheets_list.append(worksheet.title)
    
    if "repository" in worksheets_list:
        repo_worksheet = sheet.worksheet("repository")
    else:
        # setup worksheet and headers
        repo_worksheet = sheet.add_worksheet(title="repository", rows=100, cols=16)
        repo_worksheet.update(range_name='1:1', values=[headers])
        repo_worksheet.format('1:1', header_formatting)

    if "quarantine" in worksheets_list:
        quarantine_worksheet = sheet.worksheet("quarantine")
    else:
        # setup worksheet and headers
        quarantine_worksheet = sheet.add_worksheet(title="quarantine", rows=100, cols=16)
        quarantine_worksheet.update(range_name='1:1', values=[headers])
        quarantine_worksheet.format('1:1', header_formatting)

def move_files(uid, src, dst):
    try:
        os.renames(src, dst)
    except OSError as err:
        if err.errno == errno.EXDEV:
            #copy_id = uuid.uuid4()
            tmp_dst = "%s.%s.tmp" % (dst, uid)
            shutil.copyfile(src, tmp_dst)
            os.renames(tmp_dst, dst)
            os.unlink(src)
        else:
            raise

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


__all__ = ["get_folder", "get_json_file", "get_files_from_folder", "check_asset", "write_json_file", "fast_hash", "move_files", "connect_to_google_sheet", "setup_google_sheet", "update_google_sheet"]



