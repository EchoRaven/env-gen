#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
AGENT_DIR="${REPO_ROOT}/agent"
REF_DIR_DEFAULT="${REPO_ROOT}/reference_images/plane"
OUTPUT_BASE_DEFAULT="${REPO_ROOT}/generated"
MONITOR_PORT_DEFAULT=4210

PROJECT_NAME="${PROJECT_NAME:-plane-web}"
MODEL="${MODEL:-gpt-5.4}"
PROVIDER="${PROVIDER:-openai}"
REF_DIR="${REF_DIR:-${REF_DIR_DEFAULT}}"
OUTPUT_BASE="${OUTPUT_BASE:-${OUTPUT_BASE_DEFAULT}}"
MONITOR_PORT="${MONITOR_PORT:-${MONITOR_PORT_DEFAULT}}"
LAUNCH_MONITOR="${LAUNCH_MONITOR:-1}"
MONITOR_PID=""

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3.11}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

USE_UV=0
if command -v uv >/dev/null 2>&1; then
  USE_UV=1
fi

UV_EXTRA_DEPS=(
  "--with-requirements" "${AGENT_DIR}/utils/requirements.txt"
  "--with" "jinja2"
  "--with" "aiohttp"
  "--with" "pillow"
  "--with" "numpy"
)

DESCRIPTION="$(cat <<'EOF'
Build a Plane-inspired project management and issue tracking application.

The app should help software teams manage projects, issues, cycles, modules, and team collaboration. It should include a modern workspace UI similar to Linear, Jira, and Plane.

Core features:
1. Workspace dashboard with project statistics, active cycles, recent issues, and team activity.
2. Project list and project detail pages.
3. Issue list page with filtering by status, priority, assignee, label, and project.
4. Kanban board with columns for Backlog, Todo, In Progress, In Review, and Done.
5. Issue detail page with title, description, priority, status, assignee, labels, comments, related issues, and activity log.
6. Cycle/sprint page showing active cycle progress, completed issues, pending issues, and blocked issues.
7. Module/roadmap page grouping issues by product area.
8. Mock users, projects, issues, comments, labels, cycles, and activity logs.
9. Role-based behavior for Admin, Member, and Viewer.
10. Clean modern SaaS UI with responsive layout.

The generated app should include frontend, backend APIs, database schema, mock seed data, and basic tests for issue creation, status transitions, filtering, and permissions.
EOF
)"

if [[ ! -d "${AGENT_DIR}" ]]; then
  echo "ERROR: agent directory not found: ${AGENT_DIR}" >&2
  exit 1
fi

if [[ ! -d "${REF_DIR}" ]]; then
  echo "ERROR: reference image directory not found: ${REF_DIR}" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not set." >&2
  echo "Run: export OPENAI_API_KEY='your_key'" >&2
  exit 1
fi

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"

echo "Starting Plane generation"
echo "  project: ${PROJECT_NAME}"
echo "  python:  ${PYTHON_BIN}"
if [[ "${USE_UV}" == "1" ]]; then
  echo "  runner:  uv"
else
  echo "  runner:  direct"
fi
echo "  model:   ${MODEL} (${PROVIDER})"
echo "  refs:    ${REF_DIR}"
echo "  output:  ${OUTPUT_BASE}/${PROJECT_NAME}"
echo
cd "${AGENT_DIR}"

if [[ "${LAUNCH_MONITOR}" == "1" ]]; then
  "${PYTHON_BIN}" "${AGENT_DIR}/env_generator/llm_generator/live_monitor_server.py" \
    --project-dir "${OUTPUT_BASE}/${PROJECT_NAME}" \
    --port "${MONITOR_PORT}" >/tmp/env-gen-live-monitor.log 2>&1 &
  MONITOR_PID=$!
  echo "  monitor: http://127.0.0.1:${MONITOR_PORT}"
  echo
  trap 'if [[ -n "${MONITOR_PID:-}" ]]; then kill "${MONITOR_PID}" 2>/dev/null || true; fi' EXIT
fi

if [[ "${USE_UV}" == "1" ]]; then
  uv run --python "${PYTHON_BIN}" "${UV_EXTRA_DEPS[@]}" \
    -m env_generator.llm_generator.main \
    --name "${PROJECT_NAME}" \
    --description "${DESCRIPTION}" \
    --output "${OUTPUT_BASE}" \
    --provider "${PROVIDER}" \
    --model "${MODEL}" \
    --reference-dir "${REF_DIR}" \
    --fresh \
    --log \
    --verbose
else
  "${PYTHON_BIN}" -m env_generator.llm_generator.main \
    --name "${PROJECT_NAME}" \
    --description "${DESCRIPTION}" \
    --output "${OUTPUT_BASE}" \
    --provider "${PROVIDER}" \
    --model "${MODEL}" \
    --reference-dir "${REF_DIR}" \
    --fresh \
    --log \
    --verbose
fi
