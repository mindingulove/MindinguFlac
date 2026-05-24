#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PYTHON="${VENV_PYTHON:-python3.12}"

if [ ! -d "$DIR/venv" ]; then
  echo "Creating venv..."
  "$PYTHON" -m venv "$DIR/venv"
  "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"
fi

export PORT=8888
export HOST=0.0.0.0
export PYTHONUNBUFFERED=1

# Find and kill any process listening on the specified port
echo "Freeing up port $PORT..."
lsof -t -i:"$PORT" | xargs kill -9 2>/dev/null || true

exec "$DIR/venv/bin/python" app.py "$@"