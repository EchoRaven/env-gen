#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# v3 re-pilot launcher — Facebook clone, OpenAI gpt-5.4, unlimited budget,
# via the live_monitor at :4500 (so the run appears in the UI).
#
# Per pilot_report_2026_06_01.md Option B: validate whether the v3 prompts
# + 3-bug runtime fixes + 23-mechanism phase ladder actually move the
# Backend-Lead 0-tool-calls bottleneck that killed take2.
#
# ─── PRE-RUN CHECKLIST (do this BEFORE you run this script) ────────────────
#
# 1. Export your OpenAI key in this shell:
#      export OPENAI_API_KEY=sk-proj-...
#    (Sanity check: `echo $OPENAI_API_KEY | head -c 8`  →  should print "sk-proj-")
#
# 2. Confirm the live_monitor is up at :4500 (the script will check too):
#      curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4500/api/ping
#    Expected: 200.  If 000 or anything else, see "Start the monitor" below.
#
# 3. Confirm Docker is up (the generated app needs `docker compose up`):
#      docker ps >/dev/null && echo "docker OK" || echo "DOCKER DOWN"
#
# 4. Confirm disk space (audit flagged 94% on /dev/sda2 as a sysadmin item):
#      df -h /data/common  # generated app + worktrees + .git can be GBs
#
# Once all four are green, just run:
#      ./launch_facebook_v3_repilot.sh
#
# ─── WHAT THIS SCRIPT DOES ─────────────────────────────────────────────────
#
# - Wraps run_facebook.sh with the v3-re-pilot env vars set (provider=openai,
#   model=gpt-5.4, admin login → unlimited budget, versioned project name).
# - run_facebook.sh handles cookies, admin login, run POST, gate seeding.
# - After launch, prints the monitor URLs and tail-log command so you can
#   watch progress.
#
# ─── START THE MONITOR (if step 2 above failed) ────────────────────────────
#
# In a SEPARATE shell (the monitor needs to stay running):
#   cd /data/common/haibotong/env-gen/agent/env_generator/llm_generator
#   /home/haibotong/miniconda3/envs/dt/bin/python live_monitor_server.py
# Then re-run this script.
#
# ─── WHAT TO WATCH FOR ─────────────────────────────────────────────────────
#
# A successful re-pilot moves past the take2 failure mode:
#   take2 died at tick=0, elapsed_sec=780 (~13 min), with empty app/ dirs.
#   The "agents stalled before producing output" pattern is exactly what the
#   3-bug runtime fixes (9a015dc7/48a1471a/2e518079) target.
#
# Specifically, watch for:
#   * ticks > 0  (orchestrator loop is iterating)
#   * app/backend/, app/frontend/, app/database/ getting actual code files
#     (not just empty subdirs)
#   * docker-compose.yml present in the project root
#   * Backend Lead agent calling tools (the 0-tool-calls bottleneck moved)
#
# If the run dies again at <30 min with 0-ish ticks and empty app/:
#   - Capture the .agent_logs/ dir before killing — that's the diagnostic gold
#   - Run-budget.json::usage.status will likely still say "running" (stale)
#   - Open the monitor's project overview to see which agent stalled
#
# ─── KILL SWITCH ───────────────────────────────────────────────────────────
#
#   curl -X POST http://127.0.0.1:4500/api/projects/<project_id>/abort
# (or just close the monitor UI's project tab and Ctrl-C this script —
#  the monitor will reap the run)
# ---------------------------------------------------------------------------

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Preflight: API key set? ---------------------------------------------
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set in this shell." >&2
  echo "Run:   export OPENAI_API_KEY=sk-proj-..." >&2
  echo "Then re-run this script." >&2
  exit 1
fi
case "$OPENAI_API_KEY" in
  sk-ant-*)  echo "ERROR: OPENAI_API_KEY looks like an Anthropic key (sk-ant-...)." >&2; exit 1 ;;
  AIza*)     echo "ERROR: OPENAI_API_KEY looks like a Google key (AIza...)." >&2; exit 1 ;;
esac

# --- Preflight: monitor reachable? ---------------------------------------
MONITOR_URL="${MONITOR_URL:-http://127.0.0.1:4500}"
if ! curl -sf "$MONITOR_URL/api/ping" >/dev/null 2>&1; then
  echo "ERROR: live_monitor not reachable at $MONITOR_URL" >&2
  echo "" >&2
  echo "In a SEPARATE shell, run:" >&2
  echo "  cd $SCRIPT_DIR" >&2
  echo "  /home/haibotong/miniconda3/envs/dt/bin/python live_monitor_server.py" >&2
  echo "" >&2
  echo "Then re-run this script." >&2
  exit 1
fi

# --- Preflight: docker daemon? -------------------------------------------
if ! docker ps >/dev/null 2>&1; then
  echo "WARN: docker daemon is not reachable. The generation can still run," >&2
  echo "      but the delivery-gate smoke-test stage will fail with no signal." >&2
  echo "      Start docker if you want the full feedback loop:" >&2
  echo "        sudo systemctl start docker" >&2
  echo "" >&2
  echo "Continuing in 5s — Ctrl-C to abort." >&2
  sleep 5
fi

# --- v3 re-pilot configuration --------------------------------------------
# Versioned project name so it doesn't collide with take1/take2 in the UI.
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
export PROJECT_NAME="${PROJECT_NAME:-Facebook Clone (v3 re-pilot ${TIMESTAMP})}"
export PROVIDER=openai
export MODEL="${MODEL:-gpt-5.4}"
# Admin login → unlimited budget (per pilot_report Option B "give it room").
# Default password sourced from run_facebook.sh comment. Override if your
# install has a different one:  export ADMIN_PASSWORD=...
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-cg_vJvy0RGkl}"
export CREATE_GATES="${CREATE_GATES:-1}"
export MONITOR_URL

echo
echo "============================================================"
echo " v3 re-pilot launch — $(date +'%Y-%m-%d %H:%M:%S')"
echo "------------------------------------------------------------"
echo "  branch head : $(git -C /data/common/haibotong/env-gen rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "  project     : $PROJECT_NAME"
echo "  provider    : $PROVIDER"
echo "  model       : $MODEL"
echo "  monitor     : $MONITOR_URL"
echo "  budget      : unlimited (admin login)"
echo "  references  : ${REF_DIR:-/data/common/haibotong/env-gen/reference_images/facebook}"
echo
echo "  This run will exercise:"
echo "    * v3 prompts (Knowledge d89d8c49, Backend 92d98837,"
echo "      Frontend 2eadf0c6, Design 911a6452)"
echo "    * 3-bug runtime fixes (9a015dc7, 48a1471a, 2e518079)"
echo "    * 23-mechanism phase ladder at head $(git -C /data/common/haibotong/env-gen rev-parse --short HEAD 2>/dev/null)"
echo "============================================================"
echo

# --- Hand off to run_facebook.sh (it does the actual POST) ---------------
exec ./run_facebook.sh
