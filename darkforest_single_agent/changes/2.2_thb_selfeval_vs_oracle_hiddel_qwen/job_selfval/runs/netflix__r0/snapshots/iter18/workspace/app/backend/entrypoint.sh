#!/bin/sh
set -e
# Wait for Postgres before starting uvicorn
i=0
until python - <<'PY'
import os, socket, sys
host = os.getenv("NETFLIX_PG_HOST", "127.0.0.1")
port = int(os.getenv("NETFLIX_PG_PORT", "5432"))
try:
    socket.create_connection((host, port), timeout=2).close()
except OSError:
    sys.exit(1)
PY
do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "postgres did not come up in time" >&2
    exit 1
  fi
  sleep 2
done
exec python main.py
