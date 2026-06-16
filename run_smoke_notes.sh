#!/usr/bin/env bash
# Minimal smoke for the forgingground retarget (Phase 3b/3c + ⚠1/⚠2).
# Exercises: kickoff → spine + embedded OAuth2 AS + MCP projection →
# backend/frontend lanes → verifier (impl-completion self-trigger) → docker.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
AGENT_DIR="${REPO_ROOT}/agent"
PYTHON_BIN="${PYTHON_BIN:-/home/haibotong/miniconda3/envs/dt/bin/python}"
PROJECT_NAME="${PROJECT_NAME:-smoke-notes}"
MODEL="${MODEL:-gpt-5.4}"
PROVIDER="${PROVIDER:-openai}"
OUTPUT_BASE="${OUTPUT_BASE:-${REPO_ROOT}/generated}"

# Source the API key if dropped at /tmp/envgen_key.sh (export OPENAI_API_KEY=...).
[ -f /tmp/envgen_key.sh ] && . /tmp/envgen_key.sh
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set (export it or put it in /tmp/envgen_key.sh)" >&2
  exit 1
fi

read -r -d '' DESCRIPTION <<'EOF' || true
Build a minimal multi-tenant "Notes" web application.

Core features:
1. Authenticated entry: register + login pages (email/password). Each user only sees their own notes.
2. A notes list page: the signed-in user's notes (title + snippet + tags + updated time), newest first, with a "New note" action and an empty state.
3. A note editor/detail page: create, view, edit, and delete a note (title, body, optional comma-separated tags).
4. Filter the notes list by a tag.

Data model (keep it small):
- notes: id, user_id (owner), title, body, tags (text), created_at, updated_at.
Business rows are owned per user; every query is scoped to the authenticated user.

The generated app should include the FastAPI backend (CRUD endpoints for notes + the
auth/tenant control surface), the React/Vite frontend (login + notes list + note editor +
tag filter), the database schema, and a little seed data. Keep the scope tight — this is a
smoke test of the pipeline, not a full product.
EOF

# Budget backstop (2026-06-06): orchestrator default caps are 7200s/240 ticks
# (2h). A stalled run (verifier never validates -> orchestrator spins) otherwise
# burns ~6800 gpt-5.4 calls before aborting (smoke #7). Cap the SMOKE tighter so
# an unattended spin self-aborts at ~30min; a healthy notes app delivers in
# 15-20min. Override-able from the environment.
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-1800}"
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-90}"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"
cd "${AGENT_DIR}"

echo "Smoke generation: ${PROJECT_NAME}  model=${MODEL} (${PROVIDER})  output=${OUTPUT_BASE}/${PROJECT_NAME}"
echo "Monitor already running at http://127.0.0.1:4505 (workspaces-root=${OUTPUT_BASE})"
echo

exec "${PYTHON_BIN}" -m env_generator.llm_generator.main \
  --name "${PROJECT_NAME}" \
  --description "${DESCRIPTION}" \
  --output "${OUTPUT_BASE}" \
  --provider "${PROVIDER}" \
  --model "${MODEL}" \
  --fresh \
  --log \
  --verbose
