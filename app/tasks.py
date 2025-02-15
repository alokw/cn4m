from celery import shared_task

@shared_task
def add_numbers(x, y):
    """Simple Celery task that adds two numbers."""
    return x + y