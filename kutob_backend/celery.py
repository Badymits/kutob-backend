import os
from celery import Celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kutob_backend.settings')

app = Celery('kutob_backend')

app.conf.update(
    timezone = 'Asia/Manila',  # Correct timezone format
    enable_utc = True,
)

app.config_from_object('django.conf:settings', namespace='CELERY')

# this will find tasks in the django project with the decorator "shared tasks"
app.autodiscover_tasks()