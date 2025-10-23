FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create instance directory for database
RUN mkdir -p /app/instance

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app

# Initialize database as root (before switching to app user)
RUN python init_db.py

# Switch to app user
USER app

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run the application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
