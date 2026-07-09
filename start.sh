#!/usr/bin/env bash
# One-command local launch: backend API on :8000, web portal on :8090.
set -euo pipefail
cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_PORT=8090

if ! pg_isready -q; then
  echo "PostgreSQL is not running. Start it first (e.g. brew services start postgresql@16)." >&2
  exit 1
fi

cd backend
# The venv is only created (and dependencies installed) once; delete backend/.venv
# to force a clean reinstall after requirements.txt changes.
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
cd ..

# Build the web bundle only if it doesn't exist yet; delete frontend/build/web
# (or run `flutter build web` yourself) to pick up frontend code changes.
if [ ! -f frontend/build/web/index.html ]; then
  if ! command -v flutter >/dev/null 2>&1; then
    echo "Flutter SDK not found on PATH and no prebuilt frontend/build/web exists." >&2
    echo "Install Flutter (stable) or build the web bundle on another machine first." >&2
    kill "$BACKEND_PID" 2>/dev/null
    exit 1
  fi
  (cd frontend && flutter build web --release --dart-define=API_BASE_URL=http://localhost:$BACKEND_PORT/api)
fi
(cd frontend/build/web && python3 -m http.server "$FRONTEND_PORT" --bind 127.0.0.1) &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null' EXIT INT TERM
echo
echo "Portal:      http://127.0.0.1:$FRONTEND_PORT"
echo "API docs:    http://127.0.0.1:$BACKEND_PORT/docs"
echo "Admin login: admin@example.com / Admin123!"
echo "Press Ctrl+C to stop both servers."
wait
