#!/usr/bin/env bash
# Full Instagram via MULTI-MILESTONE: M1 (core 1.0.0) → M2 (social 1.1.0) → M3 (media+DMs 1.2.0).
# Each milestone is a fresh lane-set implementing a ~12-endpoint slice on the growing app, so no
# single lane saturates (the ~25-endpoint wall). Slices in instagram_milestones.json.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
AGENT_DIR="${REPO_ROOT}/agent"
PYTHON_BIN="${PYTHON_BIN:-/home/haibotong/miniconda3/envs/dt/bin/python}"
PROJECT_NAME="${PROJECT_NAME:-instagram}"
MODEL="${MODEL:-gpt-5.4}"
PROVIDER="${PROVIDER:-openai}"
OUTPUT_BASE="${OUTPUT_BASE:-${REPO_ROOT}/generated}"
REF_DIR="${REF_DIR:-${REPO_ROOT}/reference_images/instagram}"
MILESTONES="${MILESTONES:-${REPO_ROOT}/instagram_milestones.json}"

[ -f /tmp/envgen_key.sh ] && . /tmp/envgen_key.sh
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set" >&2; exit 1
fi

read -r -d '' DESCRIPTION <<'EOF' || true
Build a complete Instagram-style photo & video sharing social network (web app, dark theme) with a
left vertical navigation rail (Home, Search/Explore, Reels, Messages, Create, Profile) and a centered
content column. Match the supplied reference screenshots. The app is delivered across milestones — the
endpoint/page surface for the CURRENT milestone is supplied separately; build that slice on top of the
already-delivered prior milestones.
EOF

# buildkit on this host degrades after heavy build churn ("can't start new
# thread" inside the executor while plain containers are fine, 2026-06-11);
# the legacy builder is unaffected. All compose builds (validation, visual
# gate, agents) inherit these.
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-10800}"   # per-milestone wall-clock
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-1200}"
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
mkdir -p "${OUTPUT_BASE}"
cd "${AGENT_DIR}"

echo "Instagram MULTI-MILESTONE: ${PROJECT_NAME}  model=${MODEL}  milestones=${MILESTONES}"
echo

exec "${PYTHON_BIN}" -m env_generator.llm_generator.main \
  --name "${PROJECT_NAME}" \
  --description "${DESCRIPTION}" \
  ${MILESTONES:+$( [ "${MILESTONES}" != "none" ] && echo --milestones "${MILESTONES}" )} \
  --output "${OUTPUT_BASE}" \
  --reference-dir "${REF_DIR}" \
  --provider "${PROVIDER}" \
  --model "${MODEL}" \
  --fresh \
  --log \
  --verbose
