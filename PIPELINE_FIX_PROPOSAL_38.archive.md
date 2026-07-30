# PIPELINE FIX PROPOSAL #38 — app-correctness class (run #35 validation stall)

The STRUCTURAL pipeline is now solid: run #35 (full #35/#36/#37 stack) reached VALIDATION with a
clean build (CLASS B blocked the broken Dockerfile 75×; CLASS C: 0 merge-blocks; CLASS A surfaced
real build output) and 43 endpoints. It then STALLED in the validation remediation loop — the SAME
3 app-correctness failures repeat every attempt (1/6→3/6 across 3 rounds, never converging):
1. `business_chain: POST /api/notes → 401 "missing or invalid token"`  ← PRIMARY (breaks every authed endpoint)
2. `business_endpoints_implemented: GET /api/notes/:id → 405 (registered implemented)`
3. `frontend_dead_controls: interactive markup with NO bound handler/API call`

These are GENERATED-CODE-QUALITY bugs (the deepest layer, only reachable now the structural blockers
are fixed). Diagnosed from the generated app (generated/smoke-notes/app/backend/custom_routes.py):

## CLASS A1 (PRIMARY) — the backend REIMPLEMENTS auth instead of importing the framework's
- The framework PROVIDES `get_current_user` in `app/backend/auth_dependency.py:38`
  (`authorization: str = Header(...)`, validates the AS's tokens) — the correct dependency.
- The backend WROTE ITS OWN in `custom_routes.py:38`: `OAuth2PasswordBearer(tokenUrl="/auth/login")`
  + `jwt.decode(token, jwt_manager.public_pem, algorithms=[ALGORITHM], audience="app")`. This is
  subtly incompatible with the framework AS tokens (audience/claims/extraction) → every authed
  request → 401 → the whole business_chain fails.
- ROOT = a STALE PROMPT. `backend_agent.j2:128` still says: *"Embedded-AS wired into `main.py` per
  <auth_wiring> (import jwt_manager/oauth_store/oauth_routes, `get_current_user` verifies RS256 vs
  `_jwt_manager.public_pem`)"*. That is the OLD model where the backend authored main.py. Now main.py
  + auth_dependency are FRAMEWORK-GENERATED with get_current_user already defined — but the backend,
  needing the dependency for custom_routes, follows :128 and re-creates the RS256 verifier itself.

### Proposed fix (prompt + optional deterministic repair)
- PROMPT (`backend_agent.j2`): in custom_routes, **`from auth_dependency import get_current_user`** —
  the framework owns + generates the auth dependency; do NOT reimplement OAuth2PasswordBearer /
  jwt.decode / a get_current_user. Remove/replace the stale :128 "wire get_current_user into main.py
  verifies RS256" line (main.py + auth_dependency are framework-generated). Same for `get_db` (import
  the framework's `get_db`, not a hand-rolled psycopg2 connection — custom_routes also hand-rolled
  `get_db_connection`).
- DETERMINISTIC REPAIR (robust, FIX #48-style — recommend for the reviewer to weigh): at scaffold/heal
  time, if custom_routes.py defines its own `get_current_user`/`oauth2_scheme`/`get_db_connection`,
  rewrite to import the framework's (`from auth_dependency import get_current_user`,
  `from database import get_db`). This survives the model ignoring the prompt.

## CLASS A2 (secondary) — registered path style `:id` (Express) vs `{id}` (FastAPI) → 405/404
- The run log shows `/api/notes/:id` (Express) **44×** alongside `/api/notes/{id}` **79×**. The
  custom_routes ROUTE is correct (`@router.get("/api/notes/{id}")`), but a registration/test path
  still carries `:id` → the verifier tests the literal `:id` path → no match → 405.
- #29-P1 canonicalizes `:id`→`{id}` for endpoint_id; verify WHY `:id` still reaches the verifier's
  test path (the backend registering `:id`? a test-path derivation that skips canonicalization?).
  Fix at the registration/canonicalization boundary so the served route and the tested path agree.

## CLASS A3 (minor) — duplicate route decorator
- `custom_routes.py:48-49` has `@router.get("/api/notes/{id}")` TWICE on `get_note`. Harmless-ish but
  a codegen smell; a prompt nudge (one decorator per handler) or a lint catch.

## CLASS A4 (secondary) — frontend_dead_controls
- Interactive markup with no bound handler/API call. The frontend renders controls (buttons/forms)
  not wired to an apiPost/apiGet. Separate frontend-quality class; diagnose from the generated
  frontend pages (likely the lane stubs a control without wiring the action). Lower priority than the
  auth blocker (which fails the whole chain).

## Scope ask for the reviewer
Focus A1 (the auth reimplementation — the chain blocker): confirm the framework's
auth_dependency.get_current_user is the right import + that custom_routes importing it works (same
dir / sys.path), confirm the stale :128 prompt line is the driver, and weigh prompt-only vs the
deterministic import-repair (does any past run show the backend importing it correctly when told?).
Confirm A2's `:id` leakage point. A3/A4 lighter. Flag anything env-specific (must stay general).
