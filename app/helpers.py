# restart celery_worker to check changes from this file

from os.path import join, getsize, isfile
from pathlib import Path
from time import strftime, localtime
from datetime import datetime
from pymediainfo import MediaInfo
from gspread_formatting import *
import os
import sys
import json
import time
import xxhash
import gspread
import errno
import ffmpeg
import argparse
import subprocess


#cn4m_assets = "/cn4m_assets"
#repo_folder = "/cn4m_assets/repo"
#quar_folder = "/cn4m_assets/quarantine"

google_creds = os.getenv("GOOGLE_CREDS")
google_sheet = os.getenv("GOOGLE_SHEET")
sleep_time = float(os.getenv("TIME_BETWEEN_CHECKS"))
exclude_files = os.getenv("EXCLUDE_FILES").split(", ")

cn4m_folder = "/cn4m_assets"
cn4m_quarantine = os.path.join(cn4m_folder, "quarantine")
cn4m_repo = os.path.join(cn4m_folder, "repo")

def ffmpeg_extract_audio(in_filename):
    # subprocess.run(["ffmpeg", "-formats"])      
    #print("in_filename:", in_filename)

    #out_filename = str(Path(in_filename).with_suffix(".wav"))
    p = Path(in_filename)
    out_filename = str(p.parent / (p.stem + "_hapaudio.mov"))
    #print("out_filename:", out_filename)

    #.output(out_filename, **{'acodec': 'pcm_s16le', 'ar': 48000, 'ac': 2})

    # color=c=black:s=16x16 -i %%A -map 0:v -map 1:a -c:v hap -format hap -vf "fps=30" -c:a pcm_s16le -ar 48000 -tune stillimage -shortest "%%~dA%%~pA%%~nA_hapaudio.mov"

    #   start cmd /k ffmpeg.exe -f lavfi -i color=c=black:s=16x16 -i %%A -map 0:v -map 1:a -c:v hap -format hap -vf "fps=30" -c:a pcm_s16le -ar 48000 -tune stillimage -shortest "%%~dA%%~pA%%~nA_hapaudio.mov"


    try:
        status = (
            ffmpeg
            .input('color=c=black:s=16x16', f='lavfi')   # color first! input 0 (video)
            .input(in_filename)                          # real file second! input 1 (audio)
            .output(
                out_filename,
                vcodec='hap',
                acodec='pcm_s16le',
                format='mov',
                vf='fps=30',
                ar=48000,
                tune='stillimage',
                shortest=None
            )
            .global_args(
                '-map', '0:v',    # take video from color
                '-map', '1:a'     # take audio from real file
            )
            .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        )
        print(stderr)
    except:
        status = ("error processing:", in_filename)

    # print(status)
    #return status
    
    '''
    print(out_filename)
    probe = (
        ffmpeg
        .input(in_filename, vn=None)
        .output(out_filename)
        .global_args('-acodec pcm_s16le')
        .global_args('-ar 48000')
        .global_args('-ac 2')
        .run()
        )
    #probe = ffmpeg.probe(in_filename)
    return probe
    '''
    return in_filename


def connect_to_google_sheet():
    gc = gspread.service_account_from_dict(json.loads(google_creds))
    sheet = gc.open_by_key(google_sheet)
    return sheet

def build_google_row(asset):
    row = []
    row.append("received")
    row.append(asset["parent"])
    row.append(asset["name"])
    row.append(asset["duration"]) if "duration" in asset else row.append("")
    row.append("")
    row.append(asset["video_codec"]) if "video_codec" in asset else row.append("")
    row.append(asset["width"]) if "width" in asset else row.append("")
    row.append(asset["height"]) if "height" in asset else row.append("")
    row.append(asset["framerate"]) if "framerate" in asset else row.append("")
    row.append(asset["audio"]) if "audio" in asset else row.append("")
    row.append(asset["audio_rate"]) if "audio_rate" in asset else row.append("")
    row.append(asset["audio_bits"]) if "audio_bits" in asset else row.append("")
    row.append(asset["audio_channels"]) if "audio_channels" in asset else row.append("")
    row.append(asset["size"]) if "size" in asset else row.append("")
    row.append(asset["created"]) if "created" in asset else row.append("")
    row.append(asset["modified"]) if "modified" in asset else row.append("")
    row.append(asset["processed"]) if "processed" in asset else row.append("")
    row.append(asset["folder"]) if "folder" in asset else row.append("")
    return row

def update_google_sheet(sheet, worksheet, new_rows):
    selected_worksheet = sheet.worksheet(worksheet)
    selected_worksheet.insert_rows(new_rows, row=2, value_input_option='RAW', inherit_from_before=False)
    if len(new_rows) >= 1:
        row_range = '2:' + str(len(new_rows)+1)        
        formatting = cellFormat(
            backgroundColor=color(1, 1, 1),
            textFormat=textFormat(bold=False, foregroundColor=color(0, 0, 0)),
            horizontalAlignment='LEFT'
            )
        format_cell_range(selected_worksheet, row_range, formatting)

def setup_google_sheet(sheet):
    headers = [ "STATUS", "PARENT", "NAME", "DURATION", "NOTES", "CODEC", "WIDTH", "HEIGHT", "FPS", "AUDIO", "RATE", "BITS", "CH", "SIZE", "CREATED", "MODIFIED", "PROCESSED", "FOLDER" ]

    # get list of worksheets and check if ingest sheet is setup
    worksheet_objs = sheet.worksheets()
    worksheets_list = []
    for worksheet in worksheet_objs:
        worksheets_list.append(worksheet.title)
    
    needed_worksheets = ["repository","quarantine"]
    for w in needed_worksheets:
        if w in worksheets_list:
            current_worksheet = sheet.worksheet(w)
        else:
            # setup worksheet and headers
            # gspread formatting: https://github.com/robin900/gspread-formatting
            current_worksheet = sheet.add_worksheet(title=w, rows=100, cols=16)
            current_worksheet.update(range_name='1:1', values=[headers])
            current_worksheet.format('1:1', {
                "backgroundColor": { "red": 0.0, "green": 0.0, "blue": 0.0 },
                "textFormat": {
                    "foregroundColor": { "red": 1.0, "green": 1.0, "blue": 1.0 },
                    "bold": True
                    }
                })
            general_formatting = cellFormat(
                horizontalAlignment='LEFT'
                )
            validation_rule = DataValidationRule(
                BooleanCondition('ONE_OF_LIST', ['received', 'ingested', 'programmed', 'waiting', 'problem']),
                showCustomUi=True
            )

            format_cell_range(current_worksheet, 'A:Q', general_formatting)
            set_frozen(current_worksheet, rows=1)
            set_column_widths(current_worksheet, [ ('A', 100), ('B', 175), ('C', 400), ('D', 90), ('E', 175), ('F', 90), ('G', 65), ('H', 65), ('I', 55), ('J', 55), ('K', 55), ('L', 55), ('M', 55), ('N', 75), ('O', 135), ('P', 135), ('Q', 135), ('R', 265) ])
            set_data_validation_for_cell_range(current_worksheet, 'A2:A2000', validation_rule)

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
    except PermissionError:
        print(f"Permission error: {file_path}")    
#        assets["unreviewed_flags"][asset] = assets["unreviewed_assets"].pop(asset, None)
#        assets["unreviewed_flags"][asset]["note"] = "marked for quarantine but no longer found"
#        assets["unreviewed_flags"][asset]["severity"] = "warn"

def get_files_from_folder(folder):
    files = [os.path.join(dp, f) for dp, dn, fn in os.walk(os.path.expanduser(folder)) for f in fn]
    sorted_files = sorted(files)
    return sorted_files

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
    if "tracked_flags" not in json_data:
        json_data["tracked_flags"] = {}
    if "tracked_repo_assets" not in json_data:
        json_data["tracked_repo_assets"] = {}
    if "tracked_quar_assets" not in json_data:
        json_data["tracked_quar_assets"] = {}
    if "untracked_flags" not in json_data:
        json_data["untracked_flags"] = {}
    if "untracked_repo_assets" not in json_data:
        json_data["untracked_repo_assets"] = {}
    if "untracked_quar_assets" not in json_data:
        json_data["untracked_quar_assets"] = {}
    if "unreviewed_assets" not in json_data:
        json_data["unreviewed_assets"] = {}
    if "unreviewed_flags" not in json_data:
        json_data["unreviewed_flags"] = {}
    return json_data

def check_asset(assets, file, filename):
    #parent = str(os.path.basename(os.path.dirname(file)))
    folder = str(os.path.normpath(os.path.dirname(file)))
    parent = str(os.path.relpath(folder, cn4m_repo))
    fileid = fast_hash(folder + "|" + filename)
    assets[fileid] = {}
    assets[fileid]["name"] = filename
    assets[fileid]["parent"] = parent
    assets[fileid]["folder"] = folder
    assets[fileid]["dumbpath"] = str(parent + "." + filename).casefold()
    assets[fileid]["modified"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getmtime(file)))
    assets[fileid]["processed"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    #assets[fileid]["processed"] = strftime('%Y-%m-%d %H:%M:%S', localtime(int(time.time())))
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
                video_codec = "ProRes 422 HQ"
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
    #json_file = Path(os.path.join(cn4m_folder, json_filename))
    cn4m_repo = os.path.join(cn4m_folder, "repo")
    json_file = Path(os.path.join(cn4m_repo, json_filename))
    with open(json_file, 'w') as f:
        #json.dump(json_data, f, indent=4, sort_keys=False)
        json.dump(json_data, f, indent=4)

def fast_hash(input_string, length=32):
    #h = xxhash.xxh64(input_string).hexdigest()  # 64-bit hash
    h = xxhash.xxh128(input_string).hexdigest()  # Use xxh128 for 32-char output
    return h[:length]  # Trim hash if needed

# remove any files that should have been excluded but may have snuck in
def purge_exclude_files(assets):
    for f in exclude_files:
        folder = str(cn4m_repo)
        fileid = fast_hash(folder + "|" + f)
        if fileid in assets:
            del assets[fileid]
            print(f"Key '{fileid}' removed successfully.")
    return assets

'''
def unlock_file(file_path):
    # Unlocks a file on macOS using chflags.
    # added due to finding locked files copied from google drive
    print("---- trying to unlock file -----")
    print(file_path)
    print(sys.platform)
    #if sys.platform == 'darwin':
    if sys.platform == 'linux':
        try:
            print("system darin")
            print("chflags in progress")
            os.system(f'whoami')
            os.system(f'id -g -n')
            os.system(f'chmod 777 "{file_path}"')
            os.system(f'ls -l /cn4m_assets/repo/1001_sat_am_sizzle')
            #os.system(f'chflags nouchg {file_path}')
        except PermissionError:
            print(f"Permission error: {file_path}")
        except FileNotFoundError:
            print(f"File not found: {file_path}")
'''

def cn4m_note(assets, note):
    print(note)
    



__all__ = ["get_folder", "get_json_file", "get_files_from_folder", "check_asset", "write_json_file", "fast_hash", "move_files", "connect_to_google_sheet", "setup_google_sheet", "update_google_sheet", "build_google_row", "purge_exclude_files", "cn4m_note", "ffmpeg_extract_audio"]



