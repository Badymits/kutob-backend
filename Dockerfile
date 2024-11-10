# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED 1
ENV LANG C.UTF-8

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (for example, for psycopg2 or Redis)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file first to leverage Docker caching
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY . /app/

# Expose ports
# Django backend will typically run on 8000, Daphne on 8001, and Celery doesn't need a port
EXPOSE 8000
EXPOSE 8001

# Default command - this can be overridden based on the service
CMD ["gunicorn", "--workers", "4", "--timeout", "120", "kutob_backend.wsgi:application", "--bind", "0.0.0.0:8000"]
