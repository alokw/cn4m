from flask import Blueprint, jsonify, render_template
from app.tasks import *
import os

main = Blueprint("main", __name__)

#ingest_folder = os.getenv("INGEST_FOLDER")

@main.route('/')
def index():
    return render_template('index.html')

@main.route('/check_assets', methods=['POST'])
def run_check_assets():
    task = check_assets.delay()
    #return jsonify({}), 202, {'Location': url_for('taskstatus', task_id=task.id)}
    return jsonify({"task_id": task.id, "status": task.status})

@main.route("/task")
def run_task():
    """Trigger a Celery task."""
    task = add_numbers.delay(10, 20)
    return jsonify({"task_id": task.id, "status": task.status})