# routes.py
# HTTP endpoints for the cn4m web UI.
# All action routes return a 202 Accepted with a Location header pointing to the
# task status endpoint — the frontend polls that URL to track progress.

from flask import Blueprint, jsonify, render_template, url_for, request
from app.tasks import *
from app import celery
from app.helpers import (get_ffmpeg_presets, parse_qc_codecs, parse_qc_resolutions,
                         parse_qc_fps, get_json_file, ASSETS_JSON)
from app.suite_status import push_status, read_status, read_log
import os
import requests

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


# ── Suite status feed ─────────────────────────────────────────────────────────
# The other cn4m suite tools POST short status lines here and they surface in
# the rail at the top of the UI. Documented under "Suite status feed" in the
# README — that's the contract those tools are written against, so think twice
# before changing the shape of what's accepted or returned.

def _suite_token_ok():
    """
    SUITE_STATUS_TOKEN in .env turns on a shared secret for pushes. Left unset
    the endpoint is open, matching the rest of cn4m, which assumes a trusted
    LAN. It's worth setting once anything outside that LAN can reach the port.
    """
    expected = (os.getenv("SUITE_STATUS_TOKEN") or "").strip()
    if not expected:
        return True
    supplied = (request.headers.get("X-CN4M-Token")
                or (request.get_json(silent=True) or {}).get("token")
                or request.form.get("token") or "").strip()
    return supplied == expected


@main.route('/suite/status', methods=['GET'])
def get_suite_status():
    """
    The feed, newest first. Pass ?since=<id> to get only what's arrived since —
    the UI polls this way so a message is never shown twice.
    """
    try:
        since = int(request.args.get('since', 0))
    except (TypeError, ValueError):
        since = 0

    entries = read_status(since)
    latest = entries[0]["id"] if entries else since
    return jsonify({"entries": entries, "latest_id": latest})


@main.route('/suite/status', methods=['POST'])
def post_suite_status():
    """
    Push one status line. Accepts JSON or form fields:
      app      required — which tool it came from, shown as a prefix
      message  required — one short line; longer than 160 chars is trimmed
      level    optional — idle (default) | ok | working | warning | blocked |
                          error, colours the dot
    """
    if not _suite_token_ok():
        return jsonify({"error": "invalid or missing token"}), 403

    data = request.get_json(silent=True) or request.form
    try:
        entry = push_status(data.get('app'), data.get('message'), data.get('level'))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        # Redis down, most likely. Say so plainly rather than 500-ing blank: the
        # caller is another program and its author has to debug this remotely.
        return jsonify({"error": "could not reach the status feed: %s" % err}), 503

    return jsonify(entry), 201


# ── Log ───────────────────────────────────────────────────────────────────────
# The full record behind the rail. Everything pushed to the feed above is in
# here too; the extra route is for cn4m's own outcomes, which the browser
# paints on its rail itself and sends here just to be kept.

@main.route('/log')
def log_page():
    """The log page, linked from the bottom of the rail's status tray."""
    return render_template('log.html')


@main.route('/log/entries', methods=['GET'])
def get_log():
    """The log, newest first. ?since=<id> works exactly as it does on the feed."""
    try:
        since = int(request.args.get('since', 0))
    except (TypeError, ValueError):
        since = 0

    entries = read_log(since)
    latest = entries[0]["id"] if entries else since
    return jsonify({"entries": entries, "latest_id": latest})


@main.route('/log', methods=['POST'])
def post_log():
    """
    Record one of cn4m's own outcomes ("Approved 5 assets"). Log only — the
    browser that sent it has already painted it, and the rail is per-browser.

    No token: this is the UI talking to its own server, and the page can't be
    given the suite secret without publishing it. The app name is pinned to
    cn4m rather than read from the request, so the most this route can be
    misused for is a cn4m-tagged line in the log, never a message in the rail.
    """
    data = request.get_json(silent=True) or request.form
    try:
        entry = push_status("cn4m", data.get('message'), data.get('level'), feed=False)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        return jsonify({"error": "could not reach the log: %s" % err}), 503
    return jsonify(entry), 201


# ── Cascade sync ──────────────────────────────────────────────────────────────
# The SYNC button in the suite rail fires a job hook in cn4m-cascade. The
# outbound request is made here, not from the browser, because it carries a
# bearer token — putting that in cn4m.js would hand it to anyone who opens the
# page or reads the served JavaScript.
#
# Both halves come from .env so the target can be repointed without a code
# change: CASCADE_SYNC_URL is the hook, CASCADE_SYNC_TOKEN the bearer token
# (optional — omit it for a hook that doesn't want one).

# A job hook only has to accept the request, not run the job, so this is a
# generous ceiling rather than an expected wait.
CASCADE_SYNC_TIMEOUT = 15


@main.route('/cascade/sync', methods=['GET'])
def cascade_sync_configured():
    """
    Whether a sync target is set. The rail asks before showing the button, so an
    install that doesn't use cascade gets no button rather than one that always
    fails.
    """
    return jsonify({"configured": bool((os.getenv("CASCADE_SYNC_URL") or "").strip())})


@main.route('/cascade/sync', methods=['POST'])
def cascade_sync():
    """
    Fire the configured cn4m-cascade job hook.

    Says only whether cascade accepted the request. What the job then does is
    cascade's to report, through /suite/status — the rail deliberately says
    nothing on cn4m's behalf about a sync it only started.
    """
    url = (os.getenv("CASCADE_SYNC_URL") or "").strip()
    if not url:
        return jsonify({"error": "CASCADE_SYNC_URL is not set in .env"}), 501

    token = (os.getenv("CASCADE_SYNC_TOKEN") or "").strip()
    headers = {"Authorization": "Bearer " + token} if token else {}

    try:
        response = requests.post(url, headers=headers, timeout=CASCADE_SYNC_TIMEOUT)
    except requests.RequestException as err:
        # Nearly always either cascade being down or CASCADE_SYNC_URL pointing at
        # 127.0.0.1, which inside this container means the container itself.
        return jsonify({"error": "could not reach cascade: %s" % err}), 502

    if not response.ok:
        detail = " ".join((response.text or "").split())[:200]
        return jsonify({"error": "cascade returned %d%s"
                                 % (response.status_code, ": " + detail if detail else "")}), 502

    return jsonify({"ok": True, "status": response.status_code})


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
