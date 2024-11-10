# Dockerfile for Django, Daphne, Celery, and Celery Beat

# Base image with Python
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# Copy the application code
COPY . /app/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=kutob_backend.settings
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0
ENV CELERY_TIMEZONE=Asia/Manila

# Install system dependencies (if needed for things like `gevent`, `psycopg2`, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Optionally, you can directly install gevent via pip here if it's not in your requirements.txt
RUN pip install gevent

# Expose the necessary ports (for Django, Daphne, Celery)
EXPOSE 8000 8001