from celery import Celery
import os

celery = Celery('tasks', broker=os.environ.get('CELERY_BROKER_URL'), backend=os.environ.get('CELERY_RESULT_BACKEND'))

@celery.task
def add(x, y):
    return x + y