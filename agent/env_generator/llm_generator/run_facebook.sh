#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Launch a REAL, full-feature generation run: a Facebook-style social network.
#
# This drives the run THROUGH THE LIVE MONITOR (POST /api/runs) so the project
# shows up in the monitor UI immediately and is tracked (status, budget, hubs,
# Preview). The monitor spawns main.py under its own workspaces-root for you.
#
# WHY a Facebook clone: the 8 reference screenshots (login, create account,
# home feed, post details, people/friends, marketplace, reels, settings)
# exercise nearly every capability — multi-page frontend, auth/OAuth, a
# multi-tenant backend + DB, CRUD across many entities, media, search, MCP
# tools, visual-review, and the delivery-gate machinery.
#
# USAGE — export the key for whichever provider you pick, then run:
#   # Anthropic (default)
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./run_facebook.sh
#
#   # OpenAI
#   export OPENAI_API_KEY=sk-proj-...
#   PROVIDER=openai MODEL=gpt-5.4 ./run_facebook.sh
#
#   # Optional: admin login → unlimited budget
#   export ADMIN_PASSWORD=cg_vJvy0RGkl
#
# Overridable env vars (all optional):
#   MONITOR_URL     monitor base URL          (default: http://127.0.0.1:4500)
#   MODEL           generation model          (default: claude-opus-4-7)
#   PROVIDER        LLM provider              (default: anthropic)
#   PROJECT_NAME    human project name        (default: Facebook Clone)
#   ADMIN_USER      admin username for login  (default: admin)
#   ADMIN_PASSWORD  admin password            (if set -> unlimited run budget)
#   CREATE_GATES    1 to seed delivery gates  (default: 1)
#   REF_DIR         reference images dir      (default: .../reference_images/facebook)
#
# The API key is sent only in the POST body to localhost; the monitor injects
# it into the run's env and never writes it to argv or logs.
# ---------------------------------------------------------------------------
set -uo pipefail

MONITOR_URL="${MONITOR_URL:-http://127.0.0.1:4500}"
MODEL="${MODEL:-claude-opus-4-7}"
PROVIDER="${PROVIDER:-anthropic}"
PROJECT_NAME="${PROJECT_NAME:-Facebook Clone}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
CREATE_GATES="${CREATE_GATES:-1}"
REF_DIR="${REF_DIR:-/data/common/haibotong/env-gen/reference_images/facebook}"

# Pick the right key env var for the chosen provider — sending the wrong-family
# key (e.g. an sk-ant-... key into OpenAI's API) gets a 401 in a loop.
case "$PROVIDER" in
  openai)     KEY_VAR=OPENAI_API_KEY ;;
  openrouter) KEY_VAR=OPENROUTER_API_KEY ;;
  google)     KEY_VAR=GOOGLE_API_KEY ;;
  anthropic)  KEY_VAR=ANTHROPIC_API_KEY ;;
  azure)     KEY_VAR=AZURE_OPENAI_API_KEY ;;
  local)      KEY_VAR="" ;;
  *) echo "ERROR: unknown PROVIDER='$PROVIDER' (use openai|openrouter|google|anthropic|azure|local)" >&2; exit 2 ;;
esac
if [ -n "$KEY_VAR" ]; then
  KEY_VAL="${!KEY_VAR:-}"
  if [ -z "$KEY_VAL" ] && [ "$PROVIDER" = "google" ]; then KEY_VAL="${GEMINI_API_KEY:-}"; fi
  if [ -z "$KEY_VAL" ]; then
    echo "ERROR: $KEY_VAR is not set for provider=$PROVIDER. Run:  export $KEY_VAR=..." >&2
    exit 1
  fi
fi
# Soft sanity-check on the key family — catches the most common mistake
# (pasting an Anthropic key into OPENAI_API_KEY or vice versa).
case "$PROVIDER:$KEY_VAL" in
  openai:sk-ant-*)    echo "ERROR: OPENAI_API_KEY looks like an Anthropic key (sk-ant-…). Set the openai key instead." >&2; exit 1 ;;
  anthropic:sk-proj-*|anthropic:sk-svcacct-*) echo "ERROR: ANTHROPIC_API_KEY looks like an OpenAI key. Set the anthropic key (sk-ant-…) instead." >&2; exit 1 ;;
esac

# Preflight: monitor reachable?
if ! curl -sf "$MONITOR_URL/api/ping" >/dev/null 2>&1; then
  echo "ERROR: monitor not reachable at $MONITOR_URL (start live_monitor_server.py first)." >&2
  exit 1
fi

PY="${PY:-/home/haibotong/miniconda3/envs/dt/bin/python}"

echo "============================================================"
echo " env-gen — Facebook clone (full-feature real run)"
echo "------------------------------------------------------------"
echo "  monitor     : $MONITOR_URL"
echo "  provider    : $PROVIDER"
echo "  model       : $MODEL"
echo "  key var     : ${KEY_VAR:-<none (local)>}  $( [ -n "${KEY_VAR:-}" ] && [ -n "${KEY_VAL:-}" ] && echo "(set)" )"
echo "  project     : $PROJECT_NAME"
echo "  reference   : $REF_DIR"
echo "  admin login : $( [ -n "$ADMIN_PASSWORD" ] && echo 'yes (unlimited budget)' || echo 'no (guest budget caps)')"
echo "  seed gates  : $( [ "$CREATE_GATES" = "1" ] && echo yes || echo no)"
echo "============================================================"

# Everything else (cookies, JSON, parsing) is done in Python for robustness.
# The API key + admin password are passed via env, never on the command line.
LLM_API_KEY="${KEY_VAL:-}" \
ADMIN_PASSWORD="$ADMIN_PASSWORD" \
MONITOR_URL="$MONITOR_URL" MODEL="$MODEL" PROVIDER="$PROVIDER" \
PROJECT_NAME="$PROJECT_NAME" ADMIN_USER="$ADMIN_USER" \
CREATE_GATES="$CREATE_GATES" REF_DIR="$REF_DIR" \
"$PY" - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error, http.cookiejar, glob

BASE   = os.environ["MONITOR_URL"].rstrip("/")
MODEL  = os.environ["MODEL"]
PROV   = os.environ["PROVIDER"]
NAME   = os.environ["PROJECT_NAME"]
KEY    = os.environ.get("LLM_API_KEY", "")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PW   = os.environ.get("ADMIN_PASSWORD", "")
REF_DIR    = os.environ["REF_DIR"]
MAKE_GATES = os.environ.get("CREATE_GATES", "1") == "1"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def call(path, body=None, method=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {"error": raw[:300]}
    except Exception as e:
        return 0, {"error": str(e)}

# --- Optional admin login (unlocks unlimited run budget) -------------------
if ADMIN_PW:
    st, res = call("/api/auth/login", {"username": ADMIN_USER, "password": ADMIN_PW})
    if st == 200 and res.get("role") == "admin":
        print(f"  -> logged in as {res.get('username')} ({res.get('role')}) — budget unlimited")
    else:
        print(f"  !! admin login failed ({st}: {res.get('error','?')}); continuing as guest", file=sys.stderr)

# --- Reference images ------------------------------------------------------
refs = sorted(glob.glob(os.path.join(REF_DIR, "*.png")))
print(f"  -> {len(refs)} reference images: " + ", ".join(os.path.basename(p) for p in refs))

# --- The task: a Facebook-style social network, exercising everything ------
DESCRIPTION = """Build "Facebook Clone" — a production-style, multi-tenant social-network web app
that closely matches the 8 provided reference screenshots. The goal is BREADTH:
implement every page and feature below as a coherent, runnable full-stack app.

PAGES (each must match its reference screenshot in layout, color, and components):
1. Login (login.png) — email/password login, "forgot password" link, social-login buttons.
2. Create account (create_account.png) — signup form (name, email, password, birthday, gender) with validation.
3. Home feed (home.png) — left nav rail, center news feed (create-post composer; posts with
   author, text, image, like/comment/share counts), a stories/reels strip on top, and a right
   rail of contacts/suggestions.
4. Post details (post_details.png) — single post with full reactions bar and a threaded comment
   list; add a comment; like a comment.
5. People / Friends (people.png) — friend suggestions and incoming requests; add friend / confirm /
   remove; see mutual friends.
6. Marketplace (marketplace.png) — category sidebar, a responsive grid of listings (photo, title,
   price, location), listing detail view, and a "create new listing" form with image upload.
7. Reels (reals.png) — vertical full-screen video/reel feed with like + comment + share overlay.
8. Settings (settings.png) — tabbed settings (profile, account, privacy, notifications); edit and
   persist profile fields and privacy toggles.

BACKEND (REST API + relational DB, containerized):
- Multi-tenant: every row is scoped to its owning user; users can only read/write their own data
  or data shared with them (friends' posts, public listings). Enforce this at the data layer.
- Auth: register, login (issue a session/JWT token), logout, "me" endpoint; protect all private
  routes; hash passwords. Provide an OAuth-style token flow (Authorization: Bearer ...).
- Entities & CRUD: users, sessions, posts, comments, reactions, friendships, friend_requests,
  marketplace_listings, reels, notifications, user_settings.
- Endpoints (at minimum): POST /api/auth/register, POST /api/auth/login, POST /api/auth/logout,
  GET /api/me, GET /api/feed, POST /api/posts, GET /api/posts/:id, POST /api/posts/:id/comments,
  POST /api/posts/:id/reactions, GET /api/friends, POST /api/friends/requests,
  POST /api/friends/requests/:id/accept, GET /api/marketplace/listings,
  POST /api/marketplace/listings, GET /api/reels, GET /api/settings, PUT /api/settings.
- DB migrations + a seed script that creates a few demo users, friendships, posts, comments,
  listings, and reels so the UI is populated on first load.

DELIVERY:
- A docker-compose that brings up frontend + backend + database with one command.
- The frontend must render (no blank screen / no console errors) and the core flows must work:
  sign up, log in, see a populated feed, create a post, open a post and comment, send/accept a
  friend request, browse the marketplace, open settings and save a change.
- Expose the most important operations as MCP tools as well.

Prioritize a working end-to-end vertical slice (auth -> feed -> post -> comment) first, then
broaden to friends, marketplace, reels, and settings."""

# --- Spawn the run via the monitor ----------------------------------------
body = {
    "name": NAME,
    "description": DESCRIPTION,
    "model": MODEL,
    "provider": PROV,
    "api_key": KEY,
    "reference_images": refs,
    "verbose": True,
    # No caps. Admin login sets ENVGEN_BUDGET_UNLIMITED (the orchestrator then
    # never aborts on budget regardless of numbers); these effectively-infinite
    # values are the belt-and-suspenders fallback for the guest case.
    "max_wall_sec": 10**9,   # ~31 years — i.e. unlimited duration
    "max_ticks": 10**9,      # unlimited ticks
}
st, res = call("/api/runs", body)
if st != 200 or res.get("error"):
    print(f"\nFAILED to start run ({st}): {res.get('error', res)}", file=sys.stderr)
    sys.exit(1)

pid = res.get("project_id")
rid = res.get("run_id")
log = res.get("log_path")
print(f"\n  RUN STARTED")
print(f"    project_id : {pid}")
print(f"    run_id     : {rid}")
print(f"    log        : {log}")

# --- Seed delivery gates (exercise every gate type) ------------------------
if MAKE_GATES and pid:
    gates = [
        {"name": "POST /api/auth/login", "type": "endpoint_exists",
         "params": {"method": "POST", "path": "/api/auth/login"}},
        {"name": "GET /api/feed", "type": "endpoint_exists",
         "params": {"method": "GET", "path": "/api/feed"}},
        {"name": "POST /api/posts", "type": "endpoint_exists",
         "params": {"method": "POST", "path": "/api/posts"}},
        {"name": "GET /api/marketplace/listings", "type": "endpoint_exists",
         "params": {"method": "GET", "path": "/api/marketplace/listings"}},
        {"name": "compose file present", "type": "file_exists",
         "params": {"path": "docker-compose.yml"}},
        {"name": "home visually matches", "type": "visual_similarity",
         "params": {"page_id": "home", "min_similarity": 0.7}},
        {"name": "login visually matches", "type": "visual_similarity",
         "params": {"page_id": "login", "min_similarity": 0.7}},
        # code_check: prove the backend is multi-tenant-ish by grepping for a
        # tenant/owner scoping column in the schema (illustrative; tune in the UI).
        {"name": "schema scopes rows by owner", "type": "code_check",
         "params": {"command": "grep -RniE 'user_id|owner_id|tenant' . --include=*.sql --include=*.js --include=*.ts --include=*.py -l | head -1",
                    "expect_exit": 0, "timeout": 60}},
    ]
    # ---- Optional: OAuth contract gates (from env-factory's 8-test minimum) ----
    # When the project IS an OAuth sandbox env (slack / paypal / atlassian / …),
    # uncomment + adjust the lines below. The helper turns the bundled test
    # script into a ``code_check`` gate that runs against the live env.
    # See: multi_agent/bundled_tests/oauth_contract/test_<env>.py
    #
    # try:
    #     from multi_agent.bundled_tests.gate_templates import oauth_contract_gate, list_supported_envs
    #     # Pick the env name that matches your project + the URL the env exposes.
    #     gates.append(oauth_contract_gate(env="slack", api_url="http://localhost:8034"))
    #     # Repeat per env, e.g.:
    #     # gates.append(oauth_contract_gate(env="paypal", api_url="http://localhost:8036"))
    # except Exception as e:
    #     print(f"    oauth_contract_gate skipped: {e}", file=sys.stderr)
    ok = 0
    for g in gates:
        s, r = call(f"/api/projects/{pid}/user_gates", g)
        if s == 200 and not r.get("error"):
            ok += 1
        else:
            print(f"    gate '{g['name']}' rejected ({s}): {r.get('error','?')}", file=sys.stderr)
    print(f"    gates      : {ok}/{len(gates)} seeded")

# --- Where to watch --------------------------------------------------------
print("\n  WATCH IT:")
print(f"    Monitor    : {BASE}/#/projects/{pid}/overview")
print(f"    Preview    : {BASE}/#/projects/{pid}/preview")
print(f"    Gates      : {BASE}/#/projects/{pid}/gates")
print(f"    Tail log   : tail -f {log}")
PYEOF
