#!/bin/bash
# Local test env (no docker): venv + pgserver Postgres + backend :8000 + vite preview :5173 + playwright.
set -e
python3.12 -m venv /tmp/venv && /tmp/venv/bin/pip install -q -r /workspace/app/backend/requirements.txt pgserver httpx 2>&1 | grep -v notice || true
/tmp/venv/bin/python -c "import pgserver; pgserver.get_server('/tmp/pgdata', cleanup_mode=None)" 2>/dev/null
PSQL=$(find /tmp/venv -name psql -type f | head -1)
$PSQL "postgresql://postgres:@/postgres?host=/tmp/pgdata" -c "CREATE ROLE netflix LOGIN PASSWORD 'netflix' SUPERUSER;" -c "CREATE DATABASE netflix OWNER netflix;" >/dev/null 2>&1 || true
PSQL=$(find /tmp/venv -name psql -type f | head -1)
for f in /workspace/app/database/init/*.sql; do $PSQL "postgresql://netflix:netflix@/netflix?host=/tmp/pgdata" -q -v ON_ERROR_STOP=1 -f $f >/dev/null; done
cd /workspace/app/backend && (DATABASE_URL="postgresql://netflix:netflix@/netflix?host=/tmp/pgdata" JWT_SECRET=dev nohup /tmp/venv/bin/uvicorn app.main:app --port 8000 > /tmp/backend.log 2>&1 &)
cd /workspace/app/frontend && npx vite build >/dev/null 2>&1 && (nohup npx vite preview --port 5173 > /tmp/vite.log 2>&1 &)
mkdir -p /tmp/pw /tmp/shots && cd /tmp/pw && npm init -y >/dev/null && npm i playwright@1.49 >/dev/null 2>&1 && npx playwright install chromium >/dev/null 2>&1
cp /workspace/tools/tests/*.mjs /tmp/pw/
echo ready
