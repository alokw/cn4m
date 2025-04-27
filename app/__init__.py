from flask import Flask
from celery import Celery
from dotenv import load_dotenv
import os

load_dotenv(".env")

def make_celery(app):
    """Initialize Celery with Flask context."""
    celery = Celery(
        app.import_name,
        broker=os.getenv("CELERY_BROKER_URL"),  # ✅ Still correct
        backend=os.getenv("RESULT_BACKEND"),  # ✅ Updated key
        broker_connection_retry_on_startup=True  # ✅ Fixes the warning
    )
    #celery = Celery(
    #    app.import_name,
    #    broker=app.config["CELERY_BROKER_URL"],
    #    backend=app.config["CELERY_RESULT_BACKEND"],
    #    include=["app.tasks"]  # ✅ Ensures tasks are auto-discovered
    #)
    celery.conf.update(app.config)
    return celery

def create_app():
    """Create Flask app and initialize Celery."""
    app = Flask(__name__)
    app.config["CELERY_BROKER_URL"] = os.getenv("CELERY_BROKER_URL")
    app.config["result_backend"] = os.getenv("RESULT_BACKEND")  # ✅ Updated key
    #app.config.from_mapping(
    #    CELERY_BROKER_URL="redis://redis:6379/0",
    #    CELERY_RESULT_BACKEND="redis://redis:6379/0"
    #)

    global celery
    celery = make_celery(app)

    from app.routes import main
    app.register_blueprint(main)

    return app

# Explicitly expose Celery for worker command
app = create_app()
celery = make_celery(app)