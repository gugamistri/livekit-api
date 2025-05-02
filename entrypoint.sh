#!/usr/bin/env sh
set -e

# Start FastAPI server in the background
uvicorn server:app --host 0.0.0.0 --port 8000 &

# Then start your worker in the foreground
python agent_worker.py