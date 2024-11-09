#!/bin/sh

python manage.py makemigrations
python manage.py migrate --no-input
python manage.py collectstatic --no-input

# Start Gunicorn
echo "Starting Gunicorn..."
exec gunicorn --workers 3 kutob_backend.wsgi:application --bind 0.0.0.0:8000