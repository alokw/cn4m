# __init__.py
# Flask application factory and Celery initialization.
# This module is the entry point for both the web server (gunicorn/flask) and
# the Celery worker — both import `app` and `celery` from here.

from flask import Flask
from celery import Celery
from dotenv import load_dotenv
import os

load_dotenv(".env")


def make_celery(app):
    """
    Create a Celery instance configured to use the same broker/backend as Flask.
    broker_connection_retry_on_startup=True suppresses a deprecation warning in
    newer versions of Celery when the broker isn't immediately available.
    """
    celery = Celery(
        app.import_name,
        broker=os.getenv("CELERY_BROKER_URL"),
        backend=os.getenv("RESULT_BACKEND"),
        broker_connection_retry_on_startup=True
    )
    celery.conf.update(app.config)
    return celery


def create_app():
    """Create and configure the Flask app, then initialize Celery."""
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY")
    app.config["CELERY_BROKER_URL"] = os.getenv("CELERY_BROKER_URL")
    app.config["result_backend"] = os.getenv("RESULT_BACKEND")

    # Store celery as a module-level global so tasks.py and routes.py can import it
    global celery
    celery = make_celery(app)

    from app.routes import main
    app.register_blueprint(main)

    return app


# Create the app (and celery) at module level so the Celery worker can import them
app = create_app()
