#!/usr/bin/env bash
# Idempotent setup: install deps, seed Mongo, start the server.
# Reads ONLY MONGODB_URI from .env; everything else is in-process defaults.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-./venv/bin/python}
PIP=${PIP:-./venv/bin/pip}
PORT=${API_PORT:-8088}

if [[ ! -x "$PY" ]]; then
  echo "==> Creating venv at ./venv"
  python3 -m venv venv
  PY=./venv/bin/python
  PIP=./venv/bin/pip
fi

echo "==> Installing dependencies"
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -e .

echo "==> Seeding csx_demo database"
"$PY" -m app.seed

echo "==> Starting uvicorn on http://localhost:${PORT}"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --reload
