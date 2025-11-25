# Use a slim Python 3.10 image
FROM python:3.10-slim-buster

WORKDIR /home/backend

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV GDAL_LIBRARY_PATH=/usr/lib/libgdal.so

# Install system dependencies
RUN apt-get update && apt-get install -y \
    netcat \
    postgis \
    curl \
    postgresql-client \
    build-essential \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    binutils \
    ca-certificates \
    gnupg \
    libproj-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /home/backend/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /home/backend/

# Copy and configure entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
