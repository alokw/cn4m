from flask import Blueprint, jsonify, render_template, url_for, request
from app.tasks import *
import os

main = Blueprint("main", __name__)

#ingest_folder = os.getenv("INGEST_FOLDER")

@main.route('/')
def index():
    return render_template('index.html')

@main.route('/extract_audio/<id>', methods=['POST'])  # /landingpage/A
def run_extract_audio(id):
    task = extract_audio.delay(id)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/check_assets', methods=['POST'])
def run_check_assets():
    task = check_assets.delay()
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/quarantine_assets', methods=['POST'])
def run_quarantine_assets():
    assets = request.form.get('javascript_data')
    task = quarantine_assets.delay(assets)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}
    #return "done"

@main.route('/approve_assets', methods=['POST'])
def run_approve_assets():
    assets = request.form.get('javascript_data')
    task = approve_assets.delay(assets)
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/track_assets', methods=['POST'])
def run_track_assets():
    task = track_assets.delay()
    #return "done"
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}

@main.route('/clear_flags', methods=['POST'])
def run_clear_flags():
    task = clear_flags.delay()
    #return "done"
    return jsonify({}), 202, {'Location': url_for('main.taskstatus', task_id=task.id)}






'''
@main.route("/task")
def run_task():
    """Trigger a Celery task."""
    task = add_numbers.delay(10, 20)
    return jsonify({"task_id": task.id, "status": task.status})
'''

@main.route('/status/<task_id>')
def taskstatus(task_id):
    task = long_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        #print(task.info)
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
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }

    return jsonify(response)
