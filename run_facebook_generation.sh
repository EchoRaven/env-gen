#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
AGENT_DIR="${REPO_ROOT}/agent"
REF_DIR_DEFAULT="${REPO_ROOT}/reference_images/facebook"
OUTPUT_BASE_DEFAULT="${REPO_ROOT}/generated"
MONITOR_PORT_DEFAULT=4211

PROJECT_NAME="${PROJECT_NAME:-facebook-web}"
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
Build a Facebook-inspired social networking application using the provided Facebook reference screenshots.

The app should reproduce the core product experience and visual structure of a modern social platform: authenticated entry, a personalized home feed, people discovery, reels/video browsing, marketplace listings, post details, and account/settings flows. Use the reference images in `reference_images/facebook` as primary visual guidance for layout, spacing, navigation hierarchy, cards, dialogs, and interaction states.

Mandatory reference-image workflow for the design stage:
1. Before writing `design/spec.ui.json`, the Design Agent must call `list_reference_images()` and inspect every provided Facebook screenshot with `view_image()` or `analyze_image()`.
2. Treat user-provided reference materials as authoritative visual inputs, not optional inspiration.
3. `design/spec.ui.json` must include a `visual_reference_analysis` section with one entry per screenshot: `image`, `screen`, `layout`, `navigation`, `components`, `colors`, `spacing`, and `implementation_notes`.
4. The UI page/component spec must explicitly map each generated page to the relevant reference image, for example login -> `login.png`, register -> `create_account.png`, home feed -> `home.png`, people -> `people.png`, reels -> `reals.png`, marketplace -> `marketplace.png`, post detail -> `post_details.png`, settings -> `settings.png`.
5. Frontend implementation should follow the design spec's visual reference analysis before writing page code.

Core features:
1. Login and create-account pages with realistic validation, password visibility controls, and authentication.
2. Responsive social home feed with left navigation, central posts, stories/reels entry points, right-side contacts/suggestions, composer, reactions, comments, shares, and saved/bookmarked posts.
3. Post detail page with full post content, media preview, reaction summary, threaded comments, activity history, and related posts.
4. People page for friend suggestions, search, friend requests, mutual friends, profiles, and follow/add/remove friend actions.
5. Reels page with short-form video cards, reactions, comments, captions, creator metadata, and vertical browsing behavior.
6. Marketplace page with listing grid, category filters, price/location filters, listing detail drawer/page, seller profile, save/contact seller actions, and mock inventory data.
7. Settings page with profile/account preferences, privacy controls, notifications, security/session settings, blocking, and appearance options.
8. Mock users, friendships, posts, comments, reactions, reels, marketplace listings, notifications, messages, and settings/preferences.
9. Role-based behavior for Admin, Member, and Viewer, including permissions around moderation, listing management, comments, and privacy-sensitive fields.
10. Clean, polished, Facebook-like SaaS/social UI with desktop and mobile responsive layouts, skeleton/loading states, empty states, and accessible controls.

The generated app should include frontend, backend APIs, database schema, realistic seed data (will better if directly user data from huggingface), and basic tests for authentication, post creation, reactions/comments, filtering/search, marketplace listing flows, and permission checks.
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

echo "Starting Facebook generation"
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
    --port "${MONITOR_PORT}" >/tmp/env-gen-live-monitor-facebook.log 2>&1 &
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
