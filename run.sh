#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PYTHON="${VENV_PYTHON:-python3.12}"

# macOS uses its own venv (venv-macos) so it never collides with the Windows
# build venv (venv-windows) when the project folder is shared (e.g. Parallels).
VENV="$DIR/venv-macos"

if [ ! -d "$VENV" ]; then
  echo "Creating venv-macos..."
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install -r "$DIR/requirements.txt"
fi

export PORT=8888
export HOST=0.0.0.0
export PYTHONUNBUFFERED=1

# Find and kill any process listening on the specified port
echo "Freeing up port $PORT..."
PIDS="$(lsof -t -i:"$PORT" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  kill "$PIDS" 2>/dev/null || true
  sleep 1
  lsof -t -i:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
fi

exec "$VENV/bin/python" app.py "$@"
