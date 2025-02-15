from flask import Flask
from celery import Celery
from dotenv import load_dotenv

load_dotenv("settings.env")

def make_celery(app):
    """Initialize Celery with Flask context."""
    celery = Celery(
        app.import_name,
        broker=app.config["CELERY_BROKER_URL"],
        backend=app.config["CELERY_RESULT_BACKEND"],
        include=["app.tasks"]  # ✅ Ensures tasks are auto-discovered
    )
    celery.conf.update(app.config)
    return celery

def create_app():
    """Create Flask app and initialize Celery."""
    app = Flask(__name__)
    app.config.from_mapping(
        CELERY_BROKER_URL="redis://redis:6379/0",
        CELERY_RESULT_BACKEND="redis://redis:6379/0"
    )

    global celery
    celery = make_celery(app)

    from app.routes import main
    app.register_blueprint(main)

    return app

# Explicitly expose Celery for worker command
app = create_app()
celery = make_celery(app)