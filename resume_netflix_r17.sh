#!/usr/bin/env bash
# Resume r17 instead of starting r18.
#
# r17 reached `{'ms_49bd6f21': 'delivered'}` and then FAILED the final delivery gate on a
# single check -- validation_ui_evidence_failed -- resting on ONE stale record:
#
#   validation:ui_smoke:landing_page   failure   written 03:10:14, never overwritten
#
# while 21 other UI records passed, validation:ui_flow:landing_page PASSED, and the page's
# real defect (a public landing page fetching an authed endpoint) was repaired at ~03:20.
# The record could not be refreshed: run_validation is api-only and does not drive a
# browser, and the remediation forbade re-recording it. That is #1177, now fixed.
#
# The checkpoint is status=failed, which can_resume() accepts, so this picks up the whole
# $336 of work -- hubs, worktrees, app code, the 21 passing records -- at the one blocker,
# with #1176 and #1177 loaded. A fresh run would redo design-prep and cost ~$400.
set -uo pipefail

REPO="${REPO:-/data/common/haibotong/forgingground-gen}"
PY="${PY:-/home/haibotong/miniconda3/envs/dt/bin/python}"
NAME="${NAME:-netflix-local-r17}"
DESIGN="${DESIGN:-$REPO/design_inputs/netflix}"

. /data/common/haibotong/.envgen_openai_key.sh
export OPENAI_API_KEY="${ENVGEN_LLM_KEY}"
PROVIDER="${ENVGEN_PROVIDER:-openai}"
MODEL="${MODEL:-${ENVGEN_MODEL:?ENVGEN_MODEL not set}}"
API_BASE="${ENVGEN_API_BASE:-https://api.openai.com/v1}"

# The work is done; this is a gate-clearing pass. Cap it so a wedge cannot run away:
# the spend counter is per-process, so this is $150 for the RESUME, not the total.
# Unconditional: the key file already exports ENVGEN_MAX_SPEND_USD=600 for a FULL run,
# and `${VAR:-150}` would keep that 600. A resume is a gate-clearing pass on work that
# is already paid for, so it gets its own, tighter ceiling.
export ENVGEN_MAX_SPEND_USD="${RESUME_CAP:-150}"
export ENVGEN_SINGLE_MILESTONE="${ENVGEN_SINGLE_MILESTONE:-1}"
export ENVGEN_MAX_WALLCLOCK_SEC="${ENVGEN_MAX_WALLCLOCK_SEC:-3600}"
export ENVGEN_MAX_TICKS="${ENVGEN_MAX_TICKS:-60}"
export PYTHONPATH="$REPO/agent:${PYTHONPATH:-}"

DESC="$(cat "$DESIGN/DESCRIPTION.txt")"

echo "RESUME: $NAME   model=$MODEL   cap=\$${ENVGEN_MAX_SPEND_USD}  wallclock<=${ENVGEN_MAX_WALLCLOCK_SEC}s"
cd "$REPO/agent" || exit 1
exec "$PY" -m env_generator.llm_generator.main \
  --name "$NAME" \
  --description "$DESC" \
  --output "$REPO/generated" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --api-base "$API_BASE" \
  --design-input "$DESIGN" \
  --resume --log --verbose
