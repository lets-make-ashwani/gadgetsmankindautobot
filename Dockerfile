FROM python:3.11-slim

# Set timezone to Asia/Kolkata (Indian Standard Time)
ENV TZ="Asia/Kolkata"

# Install system dependencies including FFmpeg and tzdata
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose Render default port
EXPOSE 10000

# Start FastAPI server with background 3-hour scheduler
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
