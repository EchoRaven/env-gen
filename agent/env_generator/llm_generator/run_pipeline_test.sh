#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end pipeline smoke test for the multi-agent env-gen orchestrator.
#
# Runs the FULL pipeline (main.py -> Orchestrator.run) directly, with verbose
# logging to both console and file. You supply the API key; everything else
# has sane defaults you can override with env vars.
#
# USAGE (pick ONE provider, export its key, then run):
#
#   # OpenAI
#   export OPENAI_API_KEY=sk-...
#   PROVIDER=openai MODEL=gpt-4o-mini ./run_pipeline_test.sh
#
#   # Google Gemini
#   export GOOGLE_API_KEY=...            # (or GEMINI_API_KEY)
#   PROVIDER=google MODEL=gemini-2.0-flash ./run_pipeline_test.sh
#
#   # Anthropic
#   export ANTHROPIC_API_KEY=sk-ant-...
#   PROVIDER=anthropic MODEL=claude-3-sonnet ./run_pipeline_test.sh
#
# Other overridable vars:
#   NAME         project name           (default: pipeline_smoke)
#   DESCRIPTION  what to build          (default: a tiny todo app, kept small on purpose)
#   OUTPUT       output root dir        (default: ./generated)
#
# COST/SAFETY NOTES:
#   * There is NO built-in token/wall-clock budget cap (see review item #8).
#     If it looks stuck or runaway, just Ctrl-C — it's safe to kill.
#   * Defaults use a cheap/fast model + a small app to keep the first run cheap.
#   * Docker daemon must be running (it is, on this host) for the smoke-test
#     stage; otherwise that stage warns and the gate will likely fail — which
#     is itself useful signal for a first run.
# ---------------------------------------------------------------------------
set -uo pipefail

# --- Resolve paths (script lives in the llm_generator dir) ----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY="${PY:-/home/haibotong/miniconda3/envs/dt/bin/python}"

# --- Config (override via env) --------------------------------------------
PROVIDER="${PROVIDER:-openai}"
MODEL="${MODEL:-gpt-4o-mini}"
NAME="${NAME:-pipeline_smoke}"
DESCRIPTION="${DESCRIPTION:-A minimal todo web app: list todos, add a todo, mark complete. Keep it intentionally small.}"
OUTPUT="${OUTPUT:-./generated}"
API_BASE="${API_BASE:-}"        # optional: gateway / OpenAI-compatible base URL

# --- Map provider -> required key env var ---------------------------------
case "$PROVIDER" in
  openai)     KEYVAR=OPENAI_API_KEY ;;
  openrouter) KEYVAR=OPENROUTER_API_KEY ;;
  google)     KEYVAR=GOOGLE_API_KEY ;;
  anthropic)  KEYVAR=ANTHROPIC_API_KEY ;;
  azure)      KEYVAR=AZURE_OPENAI_API_KEY ;;
  local)      KEYVAR="" ;;
  *) echo "Unknown PROVIDER='$PROVIDER' (use openai|openrouter|google|anthropic|azure|local)"; exit 2 ;;
esac

# google accepts GEMINI_API_KEY as a fallback (main.py does this too)
if [ -n "$KEYVAR" ]; then
  KEYVAL="${!KEYVAR:-}"
  if [ -z "$KEYVAL" ] && [ "$PROVIDER" = "google" ]; then KEYVAL="${GEMINI_API_KEY:-}"; fi
  if [ -z "$KEYVAL" ]; then
    echo "ERROR: \$$KEYVAR is not set. Export your key first, e.g.:"
    echo "    export $KEYVAR=...your-key..."
    exit 1
  fi
fi

# --- Preflight echo --------------------------------------------------------
echo "============================================================"
echo " env-gen pipeline smoke test"
echo "------------------------------------------------------------"
echo "  python      : $PY"
echo "  provider    : $PROVIDER"
echo "  model       : $MODEL"
echo "  key var     : ${KEYVAR:-<none (local)>}  $( [ -n "${KEYVAR:-}" ] && echo "(set)" )"
echo "  project name: $NAME"
echo "  output dir  : $OUTPUT/$NAME"
echo "  description : $DESCRIPTION"
echo "  docker      : $(docker info >/dev/null 2>&1 && echo running || echo 'NOT running')"
echo "  node        : $(node --version 2>/dev/null || echo missing)"
echo "------------------------------------------------------------"
echo "  Ctrl-C anytime to abort (safe). Full log also written to:"
echo "    $OUTPUT/$NAME/logs/generation_*.log"
echo "============================================================"
echo

# --- Run -------------------------------------------------------------------
# --fresh wipes any prior output for this NAME so it's a clean run.
# --log writes a timestamped log file under <output>/<name>/logs/.
# --verbose gives DEBUG-level detail (useful for tracing the concurrency in #1).
API_BASE_ARGS=()
[ -n "$API_BASE" ] && API_BASE_ARGS=(--api-base "$API_BASE")

exec "$PY" main.py \
  --name "$NAME" \
  --description "$DESCRIPTION" \
  --output "$OUTPUT" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  "${API_BASE_ARGS[@]}" \
  --fresh \
  --log \
  --verbose
