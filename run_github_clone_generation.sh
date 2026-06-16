#!/usr/bin/env bash
set -euo pipefail
# ===== Config =====
REPO_ROOT="/Users/thb/Desktop/Gen-Env/openenv-gen-multi-agent"
AGENT_DIR="${REPO_ROOT}/agent"
REF_DIR="${AGENT_DIR}/env_generator/llm_generator/screenshot/notion"
OUTPUT_BASE="${REPO_ROOT}/demos"
PROJECT_NAME="notion-collab-web-test"
MODEL="gpt-5.2"
PROVIDER="openai"

export OPENAI_API_KEY=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

# Ensure repo-local packages (e.g. data_engine) are importable from agent runtime.
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

export HF_TOKEN="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"

DESCRIPTION="Build a production-grade Notion-like collaborative workspace app with highly similar information architecture, workflows, and UI design.
Core features: auth/login/register, multi-tenant workspaces, nested page tree, rich text block editing, slash commands, comments and @mentions, page sharing and role-based permissions (owner/editor/viewer), recent activity feed, notifications, and full-text search.
UI goal: closely match Notion layout and visual rhythm, including left sidebar navigation, top toolbar, page content canvas, block-level interactions, card/list hierarchy, spacing, and clean minimal styling.
Use reference screenshots from --reference-dir as primary UI baseline.
Deliver a runnable full-stack app with realistic seeded data and testable main flows."

# ===== Preflight =====
if [[ ! -d "${AGENT_DIR}" ]]; then
  echo "ERROR: agent directory not found: ${AGENT_DIR}" >&2
  exit 1
fi

if [[ ! -d "${REF_DIR}" ]]; then
  echo "ERROR: reference directory not found: ${REF_DIR}" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not set." >&2
  echo "Run: export OPENAI_API_KEY='your_key'" >&2
  exit 1
fi

mkdir -p "${OUTPUT_BASE}"

echo "Starting generation:"
echo "  project: ${PROJECT_NAME}"
echo "  model:   ${MODEL} (${PROVIDER})"
echo "  refs:    ${REF_DIR}"
echo "  output:  ${OUTPUT_BASE}/${PROJECT_NAME}"
echo

cd "${AGENT_DIR}"

python3 -m env_generator.llm_generator.main \
  --name "${PROJECT_NAME}" \
  --description "${DESCRIPTION}" \
  --output "${OUTPUT_BASE}" \
  --provider "${PROVIDER}" \
  --model "${MODEL}" \
  --reference-dir "${REF_DIR}" \
  --log
