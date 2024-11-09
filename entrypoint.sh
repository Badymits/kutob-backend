#!/bin/sh

python manage.py makemigrations
python manage.py migrate --no-input

# Start Gunicorn
echo "Starting Gunicorn..."
exec gunicorn kutob_backend.wsgi:application --bind 0.0.0.0:8080