# syntax=docker/dockerfile:1

# Use Python 3.12 slim (compatible with Python 3.10+ requirement)
FROM python:3.12-slim

# Set envs for Python behavior
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system deps (for building some wheels and SSL/certs)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (leverage Docker layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py ./

# The bot reads configuration from environment variables (.env can be mounted at runtime)
# Example run:
#   docker run --env-file ./.env --name jobformbot ghcr.io/your/image:tag

# Default command: start the bot
CMD ["python", "bot.py"]
