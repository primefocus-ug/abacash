"""
config/celery.py
=================
Celery application configuration.

Start the worker on your VPS (run in a separate terminal / supervisor process):
    celery -A config worker --loglevel=info

Start the beat scheduler (sends periodic tasks):
    celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

On Windows (local dev) — use eventlet:
    pip install eventlet
    celery -A config worker --loglevel=info --pool=eventlet
"""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")

# Read config from Django settings, namespace="CELERY"
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in every installed app
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")