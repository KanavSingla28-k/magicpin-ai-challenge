# Render deployment Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py composer.py server.py handlers.py store.py ./
COPY dataset/ ./dataset/

# Expose port (Render uses PORT env var)
EXPOSE 8080

# Run with gunicorn for production (or uvicorn directly)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]