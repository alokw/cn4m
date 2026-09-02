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

    # Recompile templates when they change on disk. Flask normally ties this to
    # debug mode, but FLASK_ENV=development (set in docker-compose) has been a
    # no-op since Flask 2.3, so debug is off and templates would otherwise be
    # compiled once and cached for the life of the process — meaning edits to
    # index.html only appear after a container restart. Static files (js/css)
    # are unaffected; they are read from disk per request.
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Store celery as a module-level global so tasks.py and routes.py can import it
    global celery
    celery = make_celery(app)

    from app.routes import main
    app.register_blueprint(main)

    return app


# Create the app (and celery) at module level so the Celery worker can import them
app = create_app()
