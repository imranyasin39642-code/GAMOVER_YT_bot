FROM python:3.10-slim

# Install system dependencies (FFmpeg, git, curl, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements & install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps || true

# Copy all application code
COPY . .

# Expose port 7860 for Hugging Face Spaces health check
EXPOSE 7860

# Run the Telegram Music Bot
CMD ["python3", "bot.py"]
