from flask import Blueprint, jsonify
from app.tasks import add_numbers

main = Blueprint("main", __name__)

@main.route("/")
def home():
    return jsonify({"message": "Flask is running!"})

@main.route("/task")
def run_task():
    """Trigger a Celery task."""
    task = add_numbers.delay(10, 20)
    return jsonify({"task_id": task.id, "status": task.status})