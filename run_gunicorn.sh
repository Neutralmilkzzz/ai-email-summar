#!/bin/bash
set -e

echo "🚀 Starting Gunicorn server..."
exec gunicorn app:app \
    --workers 4 \
    --bind 0.0.0.0:8000 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 30 \
    --log-level info \
    --name ai-email-summary-web
