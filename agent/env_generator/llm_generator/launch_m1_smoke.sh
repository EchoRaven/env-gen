#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Round-8b: M1 walking-skeleton smoke launcher.
# Per pipeline_supervision_charter.md §3:
#   M1 = auth + 1 core entity + 1 CRUD flow + docker boot + 1 smoke test.
# Minimal scope on purpose — the goal is to prove the kickoff-driven flow
# survives a real LLM run, NOT to ship a featureful product.
#
# This wraps the same /api/runs POST as launch_facebook_v3_repilot.sh,
# but with a thin M1 description so the first real end-to-end run has the
# smallest possible blast radius.
# ---------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source the local env file with the OpenAI key (gitignored).
if [ -f .env.local ]; then
  set +u; . .env.local; set -u
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set (expected via .env.local or shell export)." >&2
  exit 1
fi

MONITOR_URL="${MONITOR_URL:-http://127.0.0.1:4500}"
if ! curl -sf "$MONITOR_URL/api/ping" >/dev/null 2>&1; then
  echo "ERROR: live_monitor not reachable at $MONITOR_URL" >&2
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
export PROJECT_NAME="${PROJECT_NAME:-Minimal Blog M1 (round-8b ${TIMESTAMP})}"
export PROVIDER=openai
export MODEL="${MODEL:-gpt-5.4}"
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-cg_vJvy0RGkl}"
export CREATE_GATES="${CREATE_GATES:-1}"
export MONITOR_URL
export LLM_API_KEY="$OPENAI_API_KEY"

echo
echo "============================================================"
echo " M1 walking-skeleton smoke — round 8b — $(date +'%Y-%m-%d %H:%M:%S')"
echo "------------------------------------------------------------"
echo "  branch head : $(git -C /data/common/haibotong/env-gen rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "  project     : $PROJECT_NAME"
echo "  provider    : $PROVIDER"
echo "  model       : $MODEL"
echo "  monitor     : $MONITOR_URL"
echo "  spec        : MINIMAL blog (auth + posts + GET/POST + docker)"
echo
echo "  This is the first real end-to-end run of the kickoff-driven flow."
echo "  Watch for: kickoff_request reaching all 4 attendees, decisions arriving,"
echo "  synthesis passing roadmap_validator + cross_check_suite, normalizer"
echo "  surviving real LLM artifacts, contract registering to APIHub BEFORE"
echo "  any task_ready dispatch."
echo "============================================================"
echo

# Minimal admin login → unlimited budget.
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT
LOGIN_PAYLOAD=$(printf '{"username":"%s","password":"%s"}' "$ADMIN_USER" "$ADMIN_PASSWORD")
LOGIN_RESP=$(curl -s -c "$COOKIE_JAR" -X POST "$MONITOR_URL/api/auth/login" \
  -H "Content-Type: application/json" -d "$LOGIN_PAYLOAD")
echo "  -> login: $(echo "$LOGIN_RESP" | head -c 200)"

# Build the POST body. M1 minimal description.
RUN_PAYLOAD=$(/home/haibotong/miniconda3/envs/dt/bin/python <<'PY'
import json, os
description = """Build a MINIMAL blog application (M1 walking skeleton).

Scope is intentionally narrow — this is the thinnest end-to-end slice that
proves the whole stack wires up and runs. Do NOT add features beyond the
list below. Each line is a hard constraint.

AUTH (1 method, JWT bearer):
- POST /api/auth/register {email, password} -> {token}
- POST /api/auth/login {email, password} -> {token}
- All protected endpoints require Authorization: Bearer <jwt>

ONE ENTITY (posts):
- Table posts: id (BIGSERIAL PK), author_id (BIGINT REFERENCES users.id),
  body (TEXT), created_at (TIMESTAMP DEFAULT NOW())
- Table users: id (BIGSERIAL PK), email (VARCHAR UNIQUE), password_hash (VARCHAR)

ONE CRUD FLOW (posts):
- POST /api/posts {body} -> creates post, response_key='item' returns
  {item: {id, author_id, body, created_at}}
- GET /api/posts -> response_key='items' returns {items: [...], total: N}

ONE UI PAGE (post list + login):
- A single-page React app with two views: login form, post list
- On login success, fetch GET /api/posts and render the list
- A compose box on the post-list view to create a new post via POST /api/posts

DELIVERY:
- docker-compose.yml with postgres + express + react (3 services)
- Frontend renders on port 3000; backend on 8000; database internal
- One smoke test (Node or Python) that exercises:
  register -> login -> POST /api/posts -> GET /api/posts -> assert the post
  appears in the list

ACCEPTANCE PREDICATES (verifier authors at kickoff):
- api_smoke: POST /api/auth/register returns 200 + a non-empty token
- api_smoke: POST /api/posts with the token returns 200 + item.id present
- api_smoke: GET /api/posts returns 200 + items contains the post we just created
- ui_flow: docker compose up && curl :3000 returns 200 (frontend renders)

Prioritize a working end-to-end vertical slice. Do NOT add: comments, likes,
profile pages, search, admin UI, password reset, emails, OAuth, anything not
in the list above. If you find yourself thinking "I should also add X" — STOP
and ship only what's listed."""

body = {
    "name": os.environ["PROJECT_NAME"],
    "description": description,
    "model": os.environ["MODEL"],
    "provider": os.environ["PROVIDER"],
    "api_key": os.environ["LLM_API_KEY"],
    "reference_images": [],
    "verbose": True,
    "max_wall_sec": 1800,   # 30 min hard cap for M1 smoke
    "max_ticks": 200,
}
print(json.dumps(body))
PY
)

echo "  -> POST /api/runs (M1 minimal payload, ~$(echo "$RUN_PAYLOAD" | wc -c) bytes)"
START_RESP=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST "$MONITOR_URL/api/runs" \
  -H "Content-Type: application/json" -d "$RUN_PAYLOAD")
echo "  -> response: $(echo "$START_RESP" | head -c 300)"

PROJECT_ID=$(echo "$START_RESP" | /home/haibotong/miniconda3/envs/dt/bin/python -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('project_id',''))" 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  echo "FAILED to start run." >&2
  exit 1
fi
echo
echo "  project_id : $PROJECT_ID"
echo "  monitor    : $MONITOR_URL/project/$PROJECT_ID"
echo "  workspace  : (use monitor or the tail-log instructions printed below)"
echo
echo "  Tail logs:"
echo "    ls /tmp/envgen_demo/$PROJECT_ID/.agent_logs/ 2>/dev/null"
echo
