# routes.py
# HTTP endpoints for the cn4m web UI.
# All action routes return a 202 Accepted with a Location header pointing to the
# task status endpoint — the frontend polls that URL to track progress.

from flask import Blueprint, jsonify, render_template, url_for, request
from app.tasks import *
from app import celery
from app.helpers import (get_ffmpeg_presets, parse_qc_codecs, parse_qc_resolutions,
                         parse_qc_fps, get_json_file, ASSETS_JSON)

main = Blueprint("main", __name__)


# ── UI ────────────────────────────────────────────────────────────────────────

@main.route('/')
def index():
    """Serve the single-page UI."""
    return render_template('index.html')


# ── Asset actions ─────────────────────────────────────────────────────────────

@main.route('/ffmpeg_presets', methods=['GET'])
def ffmpeg_presets():
    """Return the list of available ffmpeg presets for the dropdown."""
    return jsonify(get_ffmpeg_presets())

@main.route('/qc_config', methods=['GET'])
def qc_config():
    """Return QC rules parsed from .env: allowed codecs and per-screen resolutions."""
    return jsonify({
        "codecs": parse_qc_codecs(),
        "resolutions": parse_qc_resolutions(),
        "fps": parse_qc_fps()
    })

# Buckets backing the REPO and QUARANTINE browse tabs. Each pair is
# (untracked, tracked) — "tracked" meaning already pushed to the Google Sheet.
BROWSE_BUCKETS = {
    "repo": ("untracked_repo_assets", "tracked_repo_assets"),
    "quarantine": ("untracked_quar_assets", "tracked_quar_assets"),
}


@main.route('/assets/<bucket>', methods=['GET'])
def browse_assets(bucket):
    """
    Return every asset currently in the repo or quarantine, keyed by fileid, for
    the read-only browse tabs. Read straight from assets.json — no Celery task,
    since this is just a local file read.
    """
    if bucket not in BROWSE_BUCKETS:
        return jsonify({"error": "unknown bucket"}), 404

    assets = get_json_file(ASSETS_JSON)
    result = {}
    for key, tracked in zip(BROWSE_BUCKETS[bucket], (False, True)):
        for fileid, asset in (assets.get(key) or {}).items():
            # The move tasks use .pop(asset, None), so a bucket can legitimately
            # hold a None where an asset went missing mid-operation.
            if not asset:
                continue
            result[fileid] = dict(asset, tracked=tracked)
    return jsonify(result)


@main.route('/untracked_count', methods=['GET'])
def untracked_count():
    """
    How many approved assets are still waiting to be pushed to the Google Sheet.
    Used on page load to decide whether the TRACK ASSETS pane should already be
    open — otherwise a session that approved nothing new could never reach it.
    """
    assets = get_json_file(ASSETS_JSON)
    count = sum(1 for key in ("untracked_repo_assets", "untracked_quar_assets")
                for asset in (assets.get(key) or {}).values() if asset)
    return jsonify({"count": count})


@main.route('/transcode_assets', methods=['POST'])
def run_transcode_assets():
    """Transcode selected assets using the chosen ffmpeg preset."""
    assets = request.form.get('javascript_data')
    preset_name = request.form.get('preset_name')
    task = transcode_assets.delay(assets, preset_name)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/quarantine_and_transcode', methods=['POST'])
def run_quarantine_and_transcode():
    """Transcode selected assets, then quarantine the originals."""
    assets = request.form.get('javascript_data')
    preset_name = request.form.get('preset_name')
    task = quarantine_and_transcode.delay(assets, preset_name)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/check_assets', methods=['POST'])
def run_check_assets():
    """Scan the repo folder for new files and extract their metadata."""
    task = check_assets.delay()
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/quarantine_assets', methods=['POST'])
def run_quarantine_assets():
    """Move the selected assets to the quarantine folder."""
    assets = request.form.get('javascript_data')
    task = quarantine_assets.delay(assets)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/approve_assets', methods=['POST'])
def run_approve_assets():
    """Mark the selected assets as approved (ready to push to Google Sheets)."""
    assets = request.form.get('javascript_data')
    task = approve_assets.delay(assets)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/track_assets', methods=['POST'])
def run_track_assets():
    """Push all approved (untracked) assets to Google Sheets."""
    task = track_assets.delay()
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/rename_asset', methods=['POST'])
def run_rename_asset():
    """
    Rename a single unreviewed asset in place and re-scan it. Goes through the
    worker like every other mutation — the web container's workspace mount is
    read-only.
    """
    task = rename_asset.delay(request.form.get('fileid'), request.form.get('new_name'))
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/clear_flags', methods=['POST'])
def run_clear_flags():
    """Archive the current unreviewed flags so the panel resets for the next scan."""
    task = clear_flags.delay()
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}


# ── Task status polling ───────────────────────────────────────────────────────

@main.route('/status/<task_id>')
def taskstatus(task_id):
    """
    Return the current state/progress of a Celery task as JSON.
    The frontend polls this endpoint until state == 'COMPLETE' or a failure occurs.
    """
    task = celery.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'current': 0,
            'total': 0,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # Task raised an exception — surface the error message
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),
        }

    return jsonify(response)
