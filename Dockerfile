FROM python:3.11.2-alpine

# Set build arguments for Git information
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown

# Set labels for metadata
LABEL git_commit=$GIT_COMMIT
LABEL build_date=$BUILD_DATE

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set timezone
ENV TZ=Asia/Manila

# Install tzdata
RUN apk add --no-cache tzdata

# Set timezone
RUN cp /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install system dependencies
RUN apk add --no-cache \
    postgresql-dev \
    gcc \
    python3-dev \
    musl-dev \
    netcat-openbsd

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy project files
COPY . .

# Copy and make entrypoint executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]