# helpers.py
# Utility functions shared across Celery tasks.
# Covers: media metadata extraction, Google Sheets integration,
# file operations, JSON state management, and hashing.

from pathlib import Path
from time import strftime, localtime
from datetime import datetime
from pymediainfo import MediaInfo
from gspread_formatting import *
import os
import re
import json
import fnmatch
import xxhash
import gspread
import errno
import ffmpeg
import yaml
import shutil


# ── Environment config ────────────────────────────────────────────────────────
# These are read from the .env file at startup via python-dotenv.
google_creds = os.getenv("GOOGLE_CREDS")          # JSON string for the Google service account
google_sheet = os.getenv("GOOGLE_SHEET")          # Google Sheets document ID
sleep_time = float(os.getenv("TIME_BETWEEN_CHECKS"))  # Small delay between file ops to keep Celery progress updates responsive
exclude_files = os.getenv("EXCLUDE_FILES").split(", ")  # Filenames to skip during scanning
# Folder names to skip entirely during scanning. Robust to missing/empty env var.
_exclude_folders_raw = os.getenv("EXCLUDE_FOLDERS", "")
exclude_folders = [p.strip() for p in _exclude_folders_raw.split(",") if p.strip()]


def parse_qc_codecs():
    """
    Parse QC_CODEC env var into a list of lowercase codec names.
    e.g. 'NotchLC, Hap' -> ['notchlc', 'hap']
    Returns an empty list if not set.
    """
    raw = os.getenv("QC_CODEC", "")
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


def parse_qc_fps():
    """
    Parse QC_FPS env var into a list of floats, or an empty list if not set.
    e.g. '29.97, 30' -> [29.97, 30.0]
    Framerate must match one of the listed values exactly (within 0.001 for float precision).
    """
    raw = os.getenv("QC_FPS", "").strip()
    if not raw:
        return []
    result = []
    for entry in raw.split(","):
        try:
            result.append(float(entry.strip()))
        except ValueError:
            pass
    return result


def parse_qc_resolutions():
    """
    Parse QC_RESOLUTION env var into screen-tagged and global resolution rules.
    'SCREEN@WxH' entries apply to files whose screen field matches; bare 'WxH'
    entries apply to every file, including files with no screen field.
    e.g. 'A1@112x336, 1920x1080' ->
        {'screens': {'a1': {'w': 112, 'h': 336}}, 'global': [{'w': 1920, 'h': 1080}]}
    Malformed entries are skipped; both parts are empty if the var is unset.
    """
    raw = os.getenv("QC_RESOLUTION", "")
    result = {"screens": {}, "global": []}
    for entry in raw.split(","):
        entry = entry.strip()
        if "x" not in entry:
            continue
        screen, _, dims = entry.rpartition("@")
        parts = dims.split("x", 1)
        try:
            res = {"w": int(parts[0].strip()), "h": int(parts[1].strip())}
        except (ValueError, IndexError):
            continue
        if screen.strip():
            result["screens"][screen.strip().lower()] = res
        else:
            result["global"].append(res)
    if not result["screens"] and not result["global"]:
        return {}
    return result


def qc_resolution_rules(qc_resolutions, screen):
    """
    Return the list of resolution rules that apply to a file on the given screen:
    the global (untagged) rules plus this screen's rule, if one is configured.
    """
    if not qc_resolutions:
        return []
    rules = list(qc_resolutions.get("global", []))
    screen_rule = qc_resolutions.get("screens", {}).get((screen or "").strip().lower())
    if screen_rule:
        rules.append(screen_rule)
    return rules


def qc_resolution_fails(qc_resolutions, screen, width, height):
    """
    Check a file's dimensions against the applicable resolution rules and return
    (width_fails, height_fails). Passing any one rule outright passes the file;
    otherwise the closest rule decides which dimension(s) are flagged, so a
    1920x1920 file checked against 1920x1080 flags only the height.
    """
    rules = qc_resolution_rules(qc_resolutions, screen)
    if not rules:
        return False, False
    try:
        w = int(width) if width != "" and width is not None else None
        h = int(height) if height != "" and height is not None else None
    except (ValueError, TypeError):
        return False, False
    if w is None and h is None:
        return False, False

    best = (True, True)
    for rule in rules:
        w_fail = w is not None and w != rule["w"]
        h_fail = h is not None and h != rule["h"]
        if not w_fail and not h_fail:
            return False, False
        if (w_fail + h_fail) < (best[0] + best[1]):
            best = (w_fail, h_fail)
    return best
# Docker container paths (the host folders are mounted here via docker-compose volumes)
cn4m_folder = "/cn4m_assets"
cn4m_quarantine = os.path.join(cn4m_folder, "quarantine")
cn4m_repo = os.path.join(cn4m_folder, "repo")
ffmpeg_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'ffmpeg_config.yaml')
project_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'project_config.yaml')


# ── FFmpeg presets ────────────────────────────────────────────────────────────

def load_ffmpeg_config():
    """Load and return the ffmpeg config YAML as a dict."""
    with open(ffmpeg_config_path, 'r') as f:
        return yaml.safe_load(f)


def load_project_config():
    """Load and return the project config YAML as a dict."""
    if os.path.isfile(project_config_path):
        with open(project_config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}


def ffmpeg_framerate(fps):
    """Convert a decimal framerate to ffmpeg's rational form where applicable."""
    if fps is None:
        return "24"
    fps = float(fps)
    fractional = {
        23.976: "24000/1001",
        29.97: "30000/1001",
        59.94: "60000/1001",
        14.985: "15000/1001",
    }
    for key, value in fractional.items():
        if abs(fps - key) < 0.015:
            return value
    return str(int(fps)) if fps == int(fps) else str(fps)


def get_ffmpeg_presets():
    """Return a list of {name, label, description} dicts for all presets in the config."""
    config = load_ffmpeg_config()
    return [{"name": p["name"], "label": p["label"], "description": p["description"]} for p in config.get("presets", [])]


def run_ffmpeg_preset(preset, src_path, asset_data=None):
    """
    Build and execute an ffmpeg command from a preset config dict against a source file.
    Config values may contain {field} tokens (e.g. {framerate}, {width}) which are
    replaced from project_config.yaml first, then asset_data as fallback.
    Returns the output file path on success, or raises on failure.
    """
    inputs = []
    for inp in preset['inputs']:
        file = inp['file'] if inp['file'] is not None else src_path
        kwargs = {}
        if inp.get('format'):
            kwargs['f'] = inp['format']
        inputs.append(ffmpeg.input(file, **kwargs))

    output_config = preset['outputs'][0]
    p = Path(src_path)
    out_path = str(p.parent / (p.stem + output_config['suffix'] + '.' + output_config['extension']))

    options = {}
    project_config = load_project_config()
    for key, value in output_config['options'].items():
        if isinstance(value, str):
            subs = {}
            if asset_data:
                subs.update({k: v for k, v in asset_data.items() if v is not None})
            subs.update({k: v for k, v in project_config.items() if v is not None})
            if 'framerate' in subs:
                subs['framerate'] = ffmpeg_framerate(subs['framerate'])
            value = value.format(**subs)
        options[key] = value

    stream = ffmpeg.output(*inputs, out_path, **options)

    global_args = preset.get('global_args') or []
    if global_args:
        stream = stream.global_args(*global_args)

    stream = stream.overwrite_output()
    print(f"ffmpeg command: {' '.join(stream.compile())}")
    try:
        stdout, stderr = stream.run(capture_stdout=True, capture_stderr=True)
        print(stderr)
    except ffmpeg.Error as e:
        print(f"ffmpeg stderr: {e.stderr.decode()}")
        raise
    return out_path


# ── Google Sheets ─────────────────────────────────────────────────────────────

def connect_to_google_sheet():
    """Authenticate with the Google Sheets API using the service account credentials from .env."""
    gc = gspread.service_account_from_dict(json.loads(google_creds))
    sheet = gc.open_by_key(google_sheet)
    return sheet

def _file_type_emoji(ext):
    if not ext:
        return ""
    lower = str(ext).lower().replace(".", "")
    audio = ["wav", "aiff", "aif", "mp3", "flac", "ogg", "m4a", "aac", "wma"]
    image = ["png", "jpeg", "jpg", "tiff", "tif", "tga", "exr", "bmp", "gif", "webp", "dpx", "heic"]
    video = ["mov", "mkv", "mp4", "avi", "webm", "m4v", "wmv", "flv", "mpg", "mpeg"]
    if lower in audio:
        return "🎵 "
    if lower in image:
        return "🖼️ "
    if lower in video:
        return "🎬 "
    return ""


def build_google_row(asset):
    """
    Convert an asset dict into a flat list of values matching the sheet column order:
    STATUS | PARENT | NAME | SCREEN | VERSION | NOTES | DURATION | EXT | CODEC |
    WIDTH | HEIGHT | FPS | AUDIO | RATE | BITS | CH | SIZE | CREATED | MODIFIED | PROCESSED | FOLDER | FILENAME
    """
    row = []
    row.append("received")                                                    # STATUS — default on arrival
    row.append(asset["parent"])
    # NAME shows the screen-less display name; assets.json entries written before
    # display_name existed fall back to basename, which still carries the screen.
    name = asset.get("display_name") or asset.get("basename") or asset["name"]
    ext = asset.get("extension", "")
    row.append(name)
    row.append(asset.get("screen", ""))
    version = asset.get("version", "")
    if version:
        prefix = "☝️ " if asset.get("is_version_up") else "🆕 "
        row.append(prefix + version)
    else:
        row.append("")
    row.append(_file_type_emoji(ext).strip())                                # NOTES — file type emoji (🎵 🖼️ 🎬)
    row.append(asset["duration"]) if "duration" in asset else row.append("")
    row.append(ext)
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
    row.append(asset.get("name", ""))                                         # FILENAME — full filename including extension
    return row

def update_google_sheet(sheet, worksheet, new_rows, qc_codecs=None, qc_resolutions=None, qc_fps=None):
    """
    Insert new rows at the top of a worksheet (below the header row).
    Formats inserted rows as plain black-on-white left-aligned text.
    If qc_codecs / qc_resolutions / qc_fps are provided, cells that fail QC get red text.
    Column layout (0-based): SCREEN=3, CODEC=8, WIDTH=9, HEIGHT=10, FPS=11 → D, I, J, K, L
    """
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

        if qc_codecs or qc_resolutions or qc_fps:
            red_fmt = cellFormat(textFormat=textFormat(foregroundColor=color(0.8, 0.0, 0.0)))
            fail_ranges = []
            for i, row in enumerate(new_rows):
                sheet_row = i + 2  # row 1 is the header
                codec  = row[8]  if len(row) > 8  else ""
                screen = (row[3] if len(row) > 3  else "").lower()
                w_val  = row[9]  if len(row) > 9  else ""
                h_val  = row[10] if len(row) > 10 else ""
                fps_val = row[11] if len(row) > 11 else ""

                if qc_codecs and codec and codec.lower() not in qc_codecs:
                    fail_ranges.append((f'I{sheet_row}', red_fmt))

                w_fail, h_fail = qc_resolution_fails(qc_resolutions, screen, w_val, h_val)
                if w_fail:
                    fail_ranges.append((f'J{sheet_row}', red_fmt))
                if h_fail:
                    fail_ranges.append((f'K{sheet_row}', red_fmt))

                if qc_fps and fps_val != "":
                    try:
                        asset_fps = float(fps_val)
                        if not any(abs(asset_fps - allowed) < 0.001 for allowed in qc_fps):
                            fail_ranges.append((f'L{sheet_row}', red_fmt))
                    except (ValueError, TypeError):
                        pass

            if fail_ranges:
                format_cell_ranges(selected_worksheet, fail_ranges)

def setup_google_sheet(sheet):
    """
    Ensure the 'repository' and 'quarantine' worksheets exist with the correct
    headers, formatting, frozen header row, column widths, and a STATUS dropdown.
    Safe to call repeatedly — only creates sheets that are missing.
    """
    headers = [ "STATUS", "PARENT", "NAME", "SCREEN", "VERSION", "NOTES", "DURATION", "EXT", "CODEC", "WIDTH", "HEIGHT", "FPS", "AUDIO", "RATE", "BITS", "CH", "SIZE", "CREATED", "MODIFIED", "PROCESSED", "FOLDER", "FILENAME" ]

    worksheet_objs = sheet.worksheets()
    worksheets_list = [w.title for w in worksheet_objs]

    needed_worksheets = ["repository", "quarantine"]
    for w in needed_worksheets:
        if w in worksheets_list:
            current_worksheet = sheet.worksheet(w)
        else:
            # Sheet doesn't exist — create it and apply all formatting
            current_worksheet = sheet.add_worksheet(title=w, rows=100, cols=22)
            current_worksheet.update(range_name='1:1', values=[headers])
            current_worksheet.format('1:1', {
                "backgroundColor": { "red": 0.0, "green": 0.0, "blue": 0.0 },
                "textFormat": {
                    "foregroundColor": { "red": 1.0, "green": 1.0, "blue": 1.0 },
                    "bold": True
                    }
                })
            general_formatting = cellFormat(horizontalAlignment='LEFT')
            validation_rule = DataValidationRule(
                BooleanCondition('ONE_OF_LIST', ['received', 'ingested', 'programmed', 'waiting', 'problem']),
                showCustomUi=True
            )
            format_cell_range(current_worksheet, 'A:V', general_formatting)
            set_frozen(current_worksheet, rows=1)
            # Widths follow the header order above: D is now SCREEN, E VERSION, F NOTES, G DURATION
            set_column_widths(current_worksheet, [
                ('A', 100), ('B', 175), ('C', 400), ('D', 90),
                ('E', 100), ('F', 175), ('G', 90), ('H', 75), ('I', 90),
                ('J', 65), ('K', 65), ('L', 55), ('M', 55), ('N', 55),
                ('O', 55), ('P', 55), ('Q', 75), ('R', 135), ('S', 135),
                ('T', 135), ('U', 265), ('V', 400)
            ])
            set_data_validation_for_cell_range(current_worksheet, 'A2:A2000', validation_rule)


# ── File operations ───────────────────────────────────────────────────────────

def move_files(uid, src, dst):
    """
    Move a file from src to dst, creating any missing parent directories.
    Handles cross-device moves (EXDEV) by copying then deleting the original.
    uid is the asset's fileid hash, used to name the temporary file during cross-device copies.
    """
    try:
        os.renames(src, dst)
    except OSError as err:
        if err.errno == errno.EXDEV:
            # Cross-device move: copy to a temp file at the destination, then remove the source
            tmp_dst = "%s.%s.tmp" % (dst, uid)
            shutil.copyfile(src, tmp_dst)
            os.renames(tmp_dst, dst)
            os.unlink(src)
        else:
            raise
    except PermissionError:
        print(f"Permission error moving {src} → {dst}")

def get_files_from_folder(folder):
    """
    Return a sorted list of all file paths found recursively under folder.
    Skips any subdirectory whose name matches an EXCLUDE_FOLDERS pattern —
    pruned in-place during os.walk so excluded trees aren't descended into at all.
    """
    files = []
    for dp, dn, fn in os.walk(os.path.expanduser(folder)):
        # Modify dn in-place so os.walk skips these subdirectories entirely
        dn[:] = [d for d in dn if not is_folder_excluded(d)]
        for f in fn:
            files.append(os.path.join(dp, f))
    return sorted(files)

def get_folder(folder):
    """Return folder path, creating it if it doesn't already exist."""
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder


def ensure_workspace_folders():
    """
    Make sure the 'repo' and 'quarantine' subdirectories exist inside
    WORKSPACE_FOLDER (mounted at /cn4m_assets in the container). Called at
    worker startup so the app is usable on a fresh workspace without the user
    needing to manually create the subdirs.
    """
    for path in (cn4m_repo, cn4m_quarantine):
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            print(f"Created workspace folder: {path}")


# ── JSON state file ───────────────────────────────────────────────────────────

def get_json_file(file):
    """
    Load assets.json from disk. If the file is missing or contains invalid JSON,
    returns an empty dict. Also ensures all expected top-level keys exist so the
    rest of the code can safely read/write each bucket without key errors.
    """
    json_file = Path(file)
    if json_file.is_file():
        with open(json_file) as f:
            try:
                json_data = json.load(f)
            except ValueError:
                json_data = {}
    else:
        json_data = {}

    # Ensure all asset buckets exist (safe to call on a fresh or partial file)
    for key in ["tracked_flags", "tracked_repo_assets", "tracked_quar_assets",
                "untracked_flags", "untracked_repo_assets", "untracked_quar_assets",
                "unreviewed_assets", "unreviewed_flags"]:
        if key not in json_data:
            json_data[key] = {}

    return json_data

def write_json_file(json_data, json_filename):
    """Serialize json_data and write it to assets.json in the repo folder."""
    json_file = Path(os.path.join(cn4m_repo, json_filename))
    with open(json_file, 'w') as f:
        json.dump(json_data, f, indent=4)


# ── Media metadata extraction ─────────────────────────────────────────────────

def check_asset(assets, file, filename):
    """
    Parse a single media file with pymediainfo and extract all relevant metadata.
    Populates an entry in the assets dict keyed by the file's xxhash fileid.

    Extracts: folder path, parent folder name, timestamps, file size, video codec,
    resolution, framerate, duration, audio format, sample rate, bit depth, channels.
    Also handles still-image tracks (width/height only, no video codec).
    """
    folder = str(os.path.normpath(os.path.dirname(file)))
    parent = str(os.path.relpath(folder, cn4m_repo))  # folder name relative to the repo root
    fileid = fast_hash(folder + "|" + filename)        # unique ID for this file at this path

    assets[fileid] = {}
    assets[fileid]["name"] = filename

    # Parse structured fields out of the filename (id, desc, screen, version, basename, display_name)
    parsed = parse_asset_filename(filename)
    assets[fileid]["id"] = parsed["id"]
    assets[fileid]["desc"] = parsed["desc"]
    assets[fileid]["screen"] = parsed["screen"]
    assets[fileid]["version"] = parsed["version"]
    assets[fileid]["basename"] = parsed["basename"]
    assets[fileid]["display_name"] = parsed["display_name"]

    assets[fileid]["parent"] = parent
    assets[fileid]["folder"] = folder
    assets[fileid]["dumbpath"] = str(parent + "." + filename).casefold()  # used for case-insensitive sorting
    assets[fileid]["modified"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getmtime(file)))
    assets[fileid]["processed"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # creation time is only reliable on Windows; fall back to mtime on Linux/Mac
    try:
        assets[fileid]["created"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getctime(file)))
    except AttributeError:
        assets[fileid]["created"] = strftime('%Y-%m-%d %H:%M:%S', localtime(os.path.getmtime(file)))

    media_info = MediaInfo.parse(file)
    for track in media_info.tracks:
        if track.track_type == "General":
            assets[fileid]["extension"] = track.file_extension
            assets[fileid]["size"] = track.other_file_size[4]  # human-readable size (e.g. "1.2 GiB")

        elif track.track_type == "Video":
            assets[fileid]["duration"] = track.other_duration[4]  # human-readable (e.g. "00:01:30:00")
            assets[fileid]["framerate"] = track.frame_rate
            assets[fileid]["width"] = track.width
            assets[fileid]["height"] = track.height

            # Map codec IDs to human-readable names for display in the UI and Google Sheet.
            # codec_id comes from the container's FourCC / codec tag.
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
            elif video_codec_id in ("hvc1", "hev1"):
                video_codec = "H.265"
            else:
                video_codec = video_codec_id  # fall back to raw codec ID if unrecognized

            assets[fileid]["video_codec"] = video_codec

        elif track.track_type == "Audio":
            assets[fileid]["duration"] = track.other_duration[4]
            assets[fileid]["audio"] = track.commercial_name         # e.g. "PCM", "AAC"
            assets[fileid]["audio_channels"] = track.channel_s
            assets[fileid]["audio_rate"] = track.sampling_rate
            if track.bit_depth:
                assets[fileid]["audio_bits"] = track.bit_depth

        elif track.track_type == "Image":
            # Still-image files (e.g. PNG/JPEG) report dimensions under an Image track
            assets[fileid]["width"] = track.width
            assets[fileid]["height"] = track.height

    return assets


# ── Filename parsing ──────────────────────────────────────────────────────────

# Matches asset filenames in the convention: {id}_{desc}_{screen}_{vVERSION}.{ext}
#   id      — starts and ends with a letter or digit; may contain _ . - between (e.g. 1000, shrm26, 1000-1005)
#   desc    — any chars; may contain underscores (greedy match)
#   screen  — any chars EXCEPT underscores (this is the boundary that makes parsing unambiguous)
#   version — starts with 'v' or 'V' followed by at least one digit, then any chars up to the file extension
#             (the required digit prevents a screen tag that happens to start with 'v' from being misread as a version)
ASSET_FILENAME_PATTERN = re.compile(
    r'^(?P<id>[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9]|[A-Za-z0-9])'
    r'_(?P<desc>.+)'
    r'_(?P<screen>[^_]+)'
    r'_(?P<version>v[0-9][^.]*)'
    r'\.[^.]+$',
    re.IGNORECASE
)

# Fallback for filenames with no screen designation: {id}_{desc}_{vVERSION}.{ext}
# Only tried when the full pattern above fails.
ASSET_FILENAME_PATTERN_NO_SCREEN = re.compile(
    r'^(?P<id>[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9]|[A-Za-z0-9])'
    r'_(?P<desc>.+)'
    r'_(?P<version>v[0-9][^.]*)'
    r'\.[^.]+$',
    re.IGNORECASE
)

def parse_asset_filename(filename):
    """
    Parse a filename like '1000_prestige_segment_trans_ab_v01_nlc.mov' into:
      id           = '1000'
      desc         = 'prestige_segment_trans'
      screen       = 'ab'
      version      = 'v01_nlc'
      basename     = '1000_prestige_segment_trans_ab'  (everything except version and extension)
      display_name = '1000_prestige_segment_trans'     (basename minus the screen)

    Also handles screenless filenames like '4050_PESGVideo_V0.mov':
      id           = '4050'
      desc         = 'PESGVideo'
      screen       = ''
      version      = 'v0'
      basename     = '4050_PESGVideo'
      display_name = '4050_PESGVideo'

    basename and display_name differ only when a screen is present, and they are
    not interchangeable: basename is the version-up matching key, so it must keep
    the screen to stop two screens' deliveries of the same content from looking
    like versions of each other. display_name is what the NAME column shows.

    Returns a dict with all six keys. If the filename doesn't match either
    convention, the four parsed fields default to empty strings, while basename
    and display_name fall back to the full filename minus the extension (so
    there's always something usable as a display label).
    """
    m = ASSET_FILENAME_PATTERN.match(filename)
    if m:
        asset_id = m.group("id")
        desc = m.group("desc")
        screen = m.group("screen")
        return {
            "id": asset_id,
            "desc": desc,
            "screen": screen,
            "version": m.group("version").lower(),
            "basename": f"{asset_id}_{desc}_{screen}",
            "display_name": f"{asset_id}_{desc}",
        }
    m = ASSET_FILENAME_PATTERN_NO_SCREEN.match(filename)
    if m:
        asset_id = m.group("id")
        desc = m.group("desc")
        return {
            "id": asset_id,
            "desc": desc,
            "screen": "",
            "version": m.group("version").lower(),
            "basename": f"{asset_id}_{desc}",
        }
    # Non-conforming filename: fall back to filename-without-extension
    stem = Path(filename).stem
    return {"id": "", "desc": "", "screen": "", "version": "", "basename": stem, "display_name": stem}


# Splits a version string into its leading number and whatever trails it,
# e.g. 'v01_nlc' -> num '01', rest '_nlc'. Mirrors the version group in the
# filename patterns above ('v' + at least one digit + anything).
VERSION_NUMBER_PATTERN = re.compile(r'^v(?P<num>[0-9]+)(?P<rest>.*)$', re.IGNORECASE)


def version_sort_key(version):
    """
    Sort key that orders version strings the way people expect: numerically on the
    leading digits, so v2 sorts before v10 (a plain string sort puts v10 first).
    The remainder breaks ties, so 'v01_hap' and 'v01_nlc' have a stable order.
    Versions that don't parse sort last, after every numbered version.
    """
    m = VERSION_NUMBER_PATTERN.match(version or "")
    if not m:
        return (1, 0, (version or "").casefold())
    return (0, int(m.group("num")), m.group("rest").casefold())


# ── Hashing ───────────────────────────────────────────────────────────────────

def fast_hash(input_string, length=32):
    """
    Generate a short unique ID for a file using xxhash-128.
    The hash is derived from the file's folder path + filename so the same
    filename in two different folders gets a different ID.
    """
    h = xxhash.xxh128(input_string).hexdigest()
    return h[:length]


# ── Exclude file matching ─────────────────────────────────────────────────────

def is_excluded(filename):
    """
    Return True if the filename should be skipped during scanning.

    Matches against the EXCLUDE_FILES list using glob-style wildcards via fnmatch,
    so patterns like 'videoin_*.mov' or '*.tmp' work as well as exact filenames.
    Comparison is case-insensitive (filenames coming from Windows/Aspera may have
    inconsistent case). Always excludes macOS resource fork files (._*).
    """
    if filename.startswith("._"):
        return True
    fname = filename.lower()
    return any(fnmatch.fnmatchcase(fname, pattern.lower()) for pattern in exclude_files)


def is_folder_excluded(folder_name):
    """
    Return True if a subdirectory name matches any pattern in EXCLUDE_FOLDERS.
    Supports glob wildcards (e.g. ~private-asp*, _archive_*) and matches case-insensitively.
    Returns False if EXCLUDE_FOLDERS is unset or empty.
    """
    if not exclude_folders:
        return False
    fname = folder_name.lower()
    return any(fnmatch.fnmatchcase(fname, pattern.lower()) for pattern in exclude_folders)


# Safety net: remove any excluded files that may have slipped through the primary check.
# Matches by filename (works at any subdirectory depth, unlike a hash-based check).
def purge_exclude_files(assets):
    to_delete = [
        fileid for fileid, asset in assets.items()
        if is_excluded(asset.get("name", ""))
    ]
    for fileid in to_delete:
        print(f"Purging excluded file: {assets[fileid].get('name')}")
        del assets[fileid]
    return assets


__all__ = ["get_folder", "ensure_workspace_folders", "get_json_file", "get_files_from_folder", "check_asset", "write_json_file", "fast_hash", "move_files", "connect_to_google_sheet", "setup_google_sheet", "update_google_sheet", "build_google_row", "purge_exclude_files", "is_excluded", "is_folder_excluded", "load_ffmpeg_config", "get_ffmpeg_presets", "run_ffmpeg_preset", "parse_asset_filename", "version_sort_key", "parse_qc_codecs", "parse_qc_resolutions", "parse_qc_fps", "qc_resolution_rules", "qc_resolution_fails"]
