---
name: new-env-bootstrap
description: Use when the orchestrator lane is standing up a brand-new sandbox env from scratch — the request implies the whole stack (API + DB + OAuth + multi-tenancy + MCP + UI), not one piece. Triggers on "add a new env called X", "scaffold env from scratch", "create a Stripe/Notion/Linear env", "add an env for service Y", "new sandbox env end to end". This is the orchestrator/sequencing skill: it does not replace the component skills (env-oauth-blueprint, multi-tenancy-pattern, mcp-server-bootstrap, ui-bootstrap, frontend-design) — it orders them, owns the cross-cutting integration glue, and drives the build through workhub tasks to the delivery gate. Don't use when the env already exists and you're adding one piece — go to the component skill directly. Do use first whenever a request implies all the pieces, even if the user names only one; they almost always need the rest.
---

# Bootstrapping a brand-new sandbox env, end to end

Adding a new env (say, "linear" or "stripe" or "notion") means wiring
five things that have to agree on contracts: an API + DB, an OAuth AS,
multi-tenancy, an MCP server, and a UI. Each piece has its own skill
with the deep details — this skill is the **map** that says what order
to do them in and where the integration glue lives.

> **How this maps to the run loop.** You are the **orchestrator** lane. You don't hand-run `start_all.sh` and `pytest` yourself — you decompose this build order into **workhub** tasks for the backend / frontend / verifier lanes, watch **eventhub** for `agent_status` and `bug_create`, and bring the env up via **runhub** (`docker compose up`, api/ui probes). The smoke commands below are what the **verifier** records as `build:*` / `validation:*` checks via `codehub_record_check`; the env ships through `deliver_project` only once `_validate_delivery_gate` sees them all green — see `release-readiness` for the gate and `verification-before-completion` for the evidence-before-claim discipline. UI work is `ui-bootstrap` (skeleton) + `frontend-design` (look / clone-fidelity under the visual gate). A check failing mid-build is `systematic-debugging`, not a step you skip.

## The four component skills (read these first if relevant)

| Skill | What it covers |
|---|---|
| `env-oauth-blueprint` | AS topology choice (embedded vs separate), `/oauth/authorize`, `/oauth/token`, JWT claim contract, RS/JWKS option |
| `multi-tenancy-pattern` | `(email, tenant_id)` composite uniqueness, `X-Tenant-ID` header, tenant CRUD, cascade delete |
| `mcp-server-bootstrap` | FastMCP scaffold, RemoteAuthProvider, `host=0.0.0.0` + `MCP_RESOURCE_URL=host.docker.internal` |
| `ui-bootstrap` | React + Vite skeleton, api.js, TenantPicker, nginx.conf.template, gateway-proxy route |

The orchestrator (this skill) sequences them and fills in the
integration glue: `start_all.sh` wiring, the cross-tenant test adapter,
the e2e OAuth dance row, the docker-compose service block.

## Phase 0 — Research the real service before writing any code

Every env in this repo is a sandbox version of a real product (Linear,
Stripe, Notion, Slack, etc.). Before scaffolding, **web-search the real
target** so the sandbox's tool surface and entity model mirror what an
agent encountering the real service would see. Skipping this step has
shipped envs whose MCP tools don't line up with the real product's API,
forcing dataset judges to work around the mismatch.

### What to research (six items)

Use `WebSearch` and where useful `WebFetch` against:

| # | Item | Why it matters |
|---|---|---|
| 1 | **Frontend stack** of the real service | Pick visuals + IA cues so the sandbox UI looks plausible. We always implement in React+Vite, but visual choices come from this |
| 2 | **Backend stack / API shape** (REST vs GraphQL, naming, pagination) | If real service is GraphQL-first (Linear) vs REST-first (Stripe), the sandbox's HTTP surface should match the canonical operation names |
| 3 | **Datastore choice the real service exposes** (e.g. Slack channels vs Linear issues vs Notion blocks) | Shapes the schema — see also Step 1 |
| 4 | **Public API → MCP tool list** | This is the *primary* output of research. Enumerate the real service's documented endpoints / operations; each turns into one or more `@mcp.tool()` |
| 5 | **OAuth flow specifics** (scopes, grant types, special quirks like PKCE-only) | Sandbox AS will be embedded (see next section), but the surface contract — scope names, grant types accepted — should reflect what an agent that learned on the real product would attempt |
| 6 | **Core entity model** (Linear has Issue/Project/Cycle/Team; Stripe has Customer/Charge/PaymentIntent; …) | This becomes the schema + module list |

Don't over-research. **One pass per item, ~5 minutes total.** You're
building a sandbox, not a clone — fidelity beyond "agent recognizes
this as Service X" is wasted effort.

### After research: present the comparison and ask the user per-item

The sandbox tech stack is **locked** for everything *except surface
contract with the real service*. Present a side-by-side table and
prompt the user per-row with `AskUserQuestion`:

```
| Component       | Real <service>         | Our default              | Pick? |
|-----------------|------------------------|--------------------------|-------|
| Backend         | (e.g. Node + GraphQL)  | FastAPI + REST           | ●     |
| DB              | (e.g. Postgres)        | Postgres                 | ●     |
| Auth            | OAuth 2.0 + PKCE       | Embedded FastAPI AS      | ●     |
| Frontend        | React + custom         | React + Vite + nginx     | ●     |
| MCP tools       | <list from research>   | snake_case mirror of (1) | ?     |
| Entity model    | <list from research>   | <subset chosen by you>   | ?     |
```

Locked rows (Backend / DB / Auth / Frontend) get a brief confirmation
prompt only if real service significantly differs (e.g. GraphQL-first):
"Real <X> uses GraphQL; we'd still emit REST endpoints + translate
operations. OK?" The "?" rows are the actual decisions — the user
picks tool scope and entity subset.

Once locked, those choices feed:
- the schema (Step 1) → entity model
- the auth posture (next section) → always embedded
- the MCP tool list (Step 6) → from research item 4
- the visual style of the UI (per `ui-bootstrap`) → from research item 1

## Auth posture: ALWAYS embedded for a new env

*(Concrete `src/envs/...` paths below are reference examples from the product these envs ship into — they do NOT exist in your workspace, which holds `app/`, `design/`, `shared/` and your worktree. Treat them as shape, not as files to open.)*

For a new env you're scaffolding here, there is one supported answer:
**Topology A — embedded AS in the same FastAPI app as the business
endpoints.** Don't deliberate, don't explore alternatives.

```
EMBEDDED (Topology A): one container holds AS + RS  ← default + only
  ├─ /auth/login, /auth/register, /oauth/token       (AS endpoints)
  ├─ /api/v1/*                                       (RS endpoints)
  └─ users table (single source)
```

The other topologies exist in the repo but **are not for new envs**:

| Topology | Where it lives | Why not for new envs |
|---|---|---|
| **B — separate centralized AS** | `src/google-idp/` serves the 5 google envs | Justified historically because Google's real-world SSO across products is the modeled behavior. Spinning up another centralized AS for one new env is wasted infrastructure |
| **C — bridge AS in front of vendor IdP** | `src/envs/salesforce/` (legacy SuiteCRM bridge era) | Only useful when wrapping an opaque external IdP. New envs don't have that constraint |

If you have an unusual reason to want B/C, push back to the user before
proceeding — they probably haven't thought it through. Migrating A → B
later is a one-week job; you'd lose nothing starting embedded.

`env-oauth-blueprint` keeps the B/C templates available as reference
material for maintaining google-idp / salesforce. Don't read those
sections when scaffolding a new env.

## End-to-end build order

Each step links to the component skill that owns the details. Don't
re-derive — read the skill, copy its template, then come back here for
the next step.

```
0.  Pick a name and a port range
1.  Schema + tenants table          ← multi-tenancy-pattern
2.  Auth endpoints (register/login) ← env-oauth-blueprint
3.  OAuth AS endpoints              ← env-oauth-blueprint
4.  Business endpoints + tenant_id  ← multi-tenancy-pattern
4a. BASELINE.md (lifecycle doc)     ← multi-tenancy-pattern
4b. POST /api/v1/admin/init-tenant  ← multi-tenancy-pattern
5.  start_all.sh wiring             ← (here)
6.  MCP server                      ← mcp-server-bootstrap
7.  start_all_mcps.sh wiring        ← mcp-server-bootstrap
8.  UI                              ← ui-bootstrap
9.  gateway-proxy route             ← ui-bootstrap
10. Cross-tenant tests              ← multi-tenancy-pattern
11. mcp-gateway OAuth e2e row       ← (here)
12. Smoke run                       ← (here)
```

Steps 4a + 4b are the **per-tenant baseline lifecycle hook** — every
env that ships into agentsuite-red's per-task pool needs both. See
`multi-tenancy-pattern` for the full spec; the short version is that
`env_server` POSTs to `/api/v1/admin/init-tenant` after creating each
test's tenant, and `BASELINE.md` is the authoritative doc for what
that endpoint materializes.

### Step 0 — Name + port budget

Pick three free ports. Look at `start_all.sh` and `gateway-proxy/nginx.conf`
to see what's taken; current high-water marks live in the 22000s.

```
ENV_API_PORT=22XXX        # backend API
ENV_FRONTEND_PORT=22YYY   # UI nginx
MCP_PORT=22ZZZ            # MCP server (HTTP transport)
```

If your env also needs Postgres (most do), pick a 4th port and **verify
it's actually free with `ss -tlnp | grep ':54..'`** — the 5470s range is
densely packed (google-idp at 5475, whatsapp at 22941, etc.), so just
"reading start_all.sh" isn't enough. Trying to bind a taken PG port
fails the container with `could not bind IPv4 address: Address already
in use` — checking up front saves the round trip.

Avoid 8043, 8080, 5432, 6379 — those clash with other dev tooling.

**Naming collision check**: if your new env has the same name root as
an existing env (e.g. you're adding `salesforce` while `salesforce_crm`
exists), `start_all.sh` may already export `<ENV>_API_PORT` for the
old env. Two options:

1. Rename the old env's vars first (e.g. `SALESFORCE_API_PORT` →
   `SALESFORCE_CRM_API_PORT`) and grep the codebase for stragglers.
2. Use a distinct prefix for your new env (e.g. `SF_API_PORT`).

Option 1 is cleaner long-term — the new env should own the canonical
name. Don't skip this; an env-var collision means *both* envs end up
on the same port, both fail, and the failure mode is non-obvious.

### Step 1 — Schema with tenants from day one

Don't ship single-tenant first and bolt multi-tenancy on later. The
single-tenant migration was painful enough across the existing 14 envs
that we never want to repeat it. Read `multi-tenancy-pattern` and copy
whatsapp's `01_init.sql` as the baseline. Key invariants:

- `users` table has `UNIQUE(email, tenant_id)`, NOT `UNIQUE(email)`.
- Every business table has `tenant_id TEXT NOT NULL DEFAULT 'default' REFERENCES tenants(id) ON DELETE CASCADE`.
- `tenants` table seeded with `('default', 'Default')` row, undeleteable.

### Step 2–3 — Auth + OAuth endpoints

Read `env-oauth-blueprint`. For Topology A, the AS endpoints
(`/auth/register`, `/auth/login`, `/oauth/authorize`, `/oauth/token`)
live in the same FastAPI app as the business endpoints. Slack
(`src/envs/slack/slack_api/`) is the cleanest reference — it doesn't
have legacy cruft.

The JWT claim contract is non-negotiable across the demo:

```python
{
    "sub": str,           # opaque user id (use the SERIAL from users.id)
    "email": str,
    "tenant_id": str,     # MUST be present; tests assert this
    "aud": "<env-name>",  # for cross-aud rejection (test_audience_confusion)
    "iss": "<env-name>-as",
    "scope": "...",
    "exp": int,
    "iat": int,
}
```

### Step 4 — Business endpoints

For every list/get/create/update/delete: include `WHERE tenant_id = ?`.
The most common bug is forgetting it on the LIST endpoint (the GET-by-id
gets remembered, the bare GET doesn't). See `multi-tenancy-pattern`'s
"LIST query forgets the WHERE predicate" anti-pattern.

### Step 4a — `BASELINE.md` (lifecycle doc)

Create `src/envs/<env>/BASELINE.md`. Three sections, no exceptions:

- **Per-tenant baseline** — what `POST /api/v1/admin/init-tenant`
  materializes (seed users? structural rows? nothing beyond a tenants
  row?).
- **Per-user baseline** — what gets created lazily on first
  authenticated request, if anything (e.g. calendar's "primary"
  calendar).
- **Container-start baseline** — what `01_init.sql` + `02_seed.sql`
  put in the `default` tenant only.

Crib `src/envs/calendar/BASELINE.md` as the cleanest minimal template,
or `src/envs/atlassian/BASELINE.md` for a richer example (which
includes the "deliberately bounded scope" pattern). The doc lives in
the env directory because it has to stay in sync with that env's code
— treat it as authoritative spec, not a README.

### Step 4b — `POST /api/v1/admin/init-tenant`

Add the endpoint. Contract:

- Reads `X-Tenant-Id` header (defaults to `default` if missing).
- Ensures the `tenants` row exists for that id (idempotent INSERT
  with `ON CONFLICT DO NOTHING`).
- Materializes any per-tenant baseline data documented in
  `BASELINE.md` — seed users copied from `default`, shared structural
  rows, etc.
- Idempotent on every layer; re-calling returns 200 with everything
  marked skipped.
- Response shape: `{tenant_id, created: {<table>: <count>}, skipped: [...]}`.

If the env has no per-tenant assets beyond identity (gmail / calendar /
zoom shape — users come via google-idp, no env-side seed users to copy),
the body shrinks to "ensure tenants row, return shape". Reference
implementations across the existing envs:

| Env | Complexity | Reference |
|---|---|---|
| gmail / calendar / zoom | minimal (ensure tenants row only) | `src/envs/gmail/user_service/auth_api.py` |
| slack | medium (tenants + workspace store init) | `src/envs/slack/slack_api/main.py` |
| atlassian | medium (5 standard seed users copied from `default`) | `src/envs/atlassian/app/backend/src/controllers/adminController.js` |
| salesforce | complex (tenants + dev user, demo data flag deferred) | `src/envs/salesforce/salesforce_api/main.py` |

**Critical sequencing inside the handler**: if you copy seed users from
the `default` tenant, ensure the new `tenants` row exists FIRST
(`ON CONFLICT DO NOTHING`), THEN insert into `app_user` / equivalent.
Otherwise the FK `tenant_id → tenants(id)` fires `23503`. This bit
atlassian once — fix is in the reference above.

### Step 5 — start_all.sh

Add a block to `src/envs/<env>/start_all.sh` (or to the top-level
`start_all.sh` if the env is single-container). The block must:

- export the three port env vars
- `docker compose -f src/envs/<env>/docker-compose.yml up -d`
- wait for `/health` to return 200 before continuing
- on the `seed` subcommand, register the dev user via the HTTP
  `/auth/register` endpoint — **not** by direct SQL insert (see
  `multi-tenancy-pattern` "Direct DB seed with stale schema" anti-pattern)

```bash
# in start_all.sh
seed_<env>() {
  curl -fsS -X POST "http://localhost:${ENV_API_PORT}/auth/register" \
    -H "Content-Type: application/json" \
    -H "X-Tenant-ID: default" \
    -d '{"email":"dev@<env>.local","password":"dev-local-password","name":"Dev User"}' \
    || echo "<env> dev user already exists, skipping"
}
```

### Step 6–7 — MCP server

Read `mcp-server-bootstrap`. Copy slack's `src/mcp_server/slack/main.py`
as the skeleton. Don't forget:

- `host="0.0.0.0"` in `mcp.run()` (without it, mcp-gateway in Docker
  can't reach it)
- `MCP_RESOURCE_URL=http://host.docker.internal:<MCP_PORT>/mcp` in env vars
- `auth=` parameter in `FastMCP(...)` constructor pointing at
  `_build_auth_provider()` — without this, the server boots but rejects
  every authenticated request

Add the MCP launch line to `start_all_mcps.sh` following the existing
pattern (export resource URL, source venv, nohup the python entrypoint,
write logs to `/tmp/<env>-mcp.log`).

### Step 8–9 — UI

Read `ui-bootstrap`. Crib slack-ui or zoom-ui — they have the cleanest
nginx + api.js pair. The two integration points easy to forget:

1. **gateway-proxy route**: add a `location /<env>/ { ... }` block in
   `src/gateway-proxy/nginx.conf`. Without this, browser-level SSO
   doesn't work (each UI on its own port = different origin).
2. **`/api/v1/` proxy ordering**: in the env's UI nginx, the
   `location /api/v1/` block must come **before** `location /api/`,
   otherwise the rewrite eats the `/v1/` prefix and `/api/v1/tenants`
   404s. (Real bug: see `ui-bootstrap` paypal anti-pattern.)

### Step 10 — Cross-tenant tests

Add an adapter to `tests/oauth/test_cross_tenant_idor.py`,
`test_cross_tenant_writes.py`, and `test_audience_confusion.py`.
Pattern from `multi-tenancy-pattern`:

```python
MYENV = EnvAdapter(
    name="<env>", base_url=os.getenv("<ENV>_API_URL", "..."),
    create_tenant=..., register=..., login=...,
    create_resource=..., read_resource=..., list_resources=...,
)
ADAPTERS.append(MYENV)
```

Run `pytest tests/oauth/test_cross_tenant_*.py -v -k <env>`. Both files
should pass on the first run if you followed the contract — if they
don't, that's almost always a missing `WHERE tenant_id = ?`.

### Step 11 — mcp-gateway OAuth e2e row

Add an `OAuthEnv(...)` row to `tests/oauth/test_mcp_gateway_oauth_e2e.py`'s
`ENVS` list:

```python
OAuthEnv("<env>", <MCP_PORT>, "dev@<env>.local", "dev-local-password",
         ("<expected_tool_keyword_1>", "<keyword_2>", "<keyword_3>"),
         "<env>.read <env>.write"),
```

Run `pytest tests/oauth/test_mcp_gateway_oauth_e2e.py -v -k <env>` —
this is the smoke that proves the full OAuth dance (DCR → authorize →
token exchange → MCP discovery) works end to end. If it fails the
breakage is somewhere between the env's AS and the MCP, and the assert
message points at exactly which step.

### Step 12 — Smoke run

Final pre-PR checklist. All must be green:

```bash
# env up, health green
./start_all.sh start
curl -fsS http://localhost:${ENV_API_PORT}/health

# OAuth metadata reachable
curl -fsS http://localhost:${ENV_API_PORT}/.well-known/oauth-authorization-server | jq .

# RS metadata on MCP reachable
curl -fsS http://localhost:${MCP_PORT}/.well-known/oauth-protected-resource | jq .

# Tenant CRUD works
curl -fsS -X POST http://localhost:${ENV_API_PORT}/api/v1/tenants \
  -H "Content-Type: application/json" -d '{"id":"smoke","name":"Smoke"}'

# UI loads via gateway-proxy
curl -fsS http://localhost:22050/<env>/ | grep -q "<title>"

# init-tenant lifecycle hook works (Step 4b)
T=smoke-$(date +%s)
curl -fsS -X POST "http://localhost:${ENV_API_PORT}/api/v1/admin/init-tenant" \
  -H "X-Tenant-Id: $T"
# → should return JSON with {tenant_id: $T, created: {...}, skipped: [...]}

# Tests pass
pytest tests/oauth/test_cross_tenant_idor.py -v -k <env>
pytest tests/oauth/test_cross_tenant_writes.py -v -k <env>
pytest tests/oauth/test_audience_confusion.py -v -k <env>
pytest tests/oauth/test_mcp_gateway_oauth_e2e.py -v -k <env>
```

If all six pass, the env is shipped.

## Bind-mount vs Dockerfile-built: pick consciously

Two ops postures are in use across the repo. The one you pick affects
how dev iteration works (restart vs rebuild) and how agentsuite-red's
per-task pool refreshes the env to a new code version.

```
┌──────────────────────────────────────────────────────────────┐
│ BIND-MOUNT (default for new envs)                            │
│  image: python:3.12-slim                                     │
│  volumes: - ./api:/app:ro                                    │
│  command: sh -c "pip install ... && uvicorn main:app ..."    │
│                                                              │
│  Source change → docker restart picks it up.                 │
│  Pip install change → still restart (command reruns).        │
│  No image to build; nothing to push.                         │
│                                                              │
│  Used by: google-idp, salesforce.                            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ DOCKERFILE-BUILT                                             │
│  build: ./api  (or build: { context: ..., dockerfile: ... }) │
│  image: <env>:<svc>   (optional tag for sharing)             │
│                                                              │
│  Source change → docker compose build + force-recreate.      │
│  Same applies to requirements.txt / Dockerfile changes.      │
│                                                              │
│  Used by: gmail user-service, calendar-api, atlassian        │
│  backend.                                                    │
└──────────────────────────────────────────────────────────────┘
```

**Pick bind-mount unless you have a reason not to.** Reasons to go
Dockerfile-built: env needs system packages beyond a base image's apt
defaults, env ships UI assets compiled in (the React+nginx ones), or
env's runtime is non-Python (Node, Go). For a typical FastAPI+Postgres
env, bind-mount is faster to iterate and trivially picks up code
changes from a `git pull`.

Quick decision-table for restart/rebuild after changes (also see the
"common ops" section in `mcp-server-bootstrap`):

| Change | Bind-mount | Dockerfile-built |
|---|---|---|
| Python source | `docker restart <c>` | rebuild + recreate |
| Dependencies in `pip install` line / requirements.txt | `docker restart <c>` (command reruns pip) | rebuild + recreate |
| Dockerfile content | n/a (no Dockerfile) | rebuild + recreate |
| Compose env / volumes | `docker compose ... up -d --no-deps --force-recreate <svc>` | same |

## Reference envs to crib from (ranked)

When in doubt, copy from these in this order:

| Need | Best reference | Why |
|---|---|---|
| Overall env structure | `src/envs/slack/` | Cleanest end-to-end, no legacy cruft |
| SQL schema | `src/envs/whatsapp/init/01_init.sql` | Most-mirrored, simplest |
| MCP server | `src/mcp_server/slack/main.py` | Has `host=0.0.0.0` and auth provider correct |
| UI nginx | `src/envs/zoom/zoom_ui/nginx.conf.template` | Correct `/api/v1/` ordering |
| start_all.sh block | `src/envs/whatsapp/start_all.sh` | Health-check + HTTP seed pattern |
| docker-compose | `src/envs/slack/docker-compose.yml` | Minimal, no dev-only services |

Avoid copying from atlassian (legacy schema), paypal (legacy nginx),
gmail (red-data-specific helpers), or customer_service (port-conflict
workarounds baked in).

## Common integration bugs (the glue, not the components)

These bite when the components are individually correct but don't
agree on a contract:

- **`aud` claim mismatch**: env signs JWT with `aud="myenv"` but MCP's
  RemoteAuthProvider configured with `audience="myenv-mcp"` →
  every authenticated MCP call returns 401. Match them.
- **Gateway-proxy route name vs UI base path**: `location /myenv/`
  in gateway-proxy strips `/myenv/` before forwarding, but the UI's
  Vite `base` config is set to `/`. Either set Vite `base: '/myenv/'`
  *or* configure the gateway-proxy to keep the prefix. (Match what
  slack does.)
- **MCP_RESOURCE_URL mismatch**: env's PRM advertises
  `http://localhost:<port>/mcp` as the resource, but mcp-gateway
  (running in Docker) can only reach `http://host.docker.internal:<port>/mcp`.
  See the `host.docker.internal` section in `mcp-server-bootstrap`.
- **Forgot to seed `tenants('default')`**: register endpoint silently
  fails with FK violation on first call. Always seed the default tenant
  in `01_init.sql`.

## When to NOT use this skill

- Adding only OAuth to an existing env → use `env-oauth-blueprint` directly.
- Adding only multi-tenancy to an existing env → use `multi-tenancy-pattern`.
- Adding only an MCP for an existing env → use `mcp-server-bootstrap`.
- Adding only a UI to an existing env → use `ui-bootstrap`.

This skill is for the **all-of-it** case. If the user has an existing
env and is asking to add one piece, the right move is to delegate to
the focused skill — re-running the full orchestrator on a partial
build will fight the existing structure.
