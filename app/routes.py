# routes.py
# HTTP endpoints for the cn4m web UI.
# All action routes return a 202 Accepted with a Location header pointing to the
# task status endpoint — the frontend polls that URL to track progress.

from flask import Blueprint, jsonify, render_template, url_for, request
from app.tasks import *
from app import celery
import os

main = Blueprint("main", __name__)


# ── UI ────────────────────────────────────────────────────────────────────────

@main.route('/')
def index():
    """Serve the single-page UI."""
    return render_template('index.html')


# ── Asset actions ─────────────────────────────────────────────────────────────

@main.route('/extract_audio/<id>', methods=['POST'])
def run_extract_audio(id):
    """Kick off audio extraction for a single asset by its fileid."""
    task = extract_audio.delay(id)
    print(id)
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
