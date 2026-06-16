---
name: multi-tenancy-pattern
description: Use when a backend lane adds multi-tenancy to a sandbox env, or designs an env that needs (a) the same email to be a different identity per tenant, (b) tenant-scoped reads/writes/deletes/lists, (c) cascading tenant teardown, or (d) the standard X-Tenant-ID header + JWT tenant_id claim contract. Also for the verifier lane writing cross-tenant isolation tests. Triggers on "add multi-tenancy to", "make X tenant-aware", "tenant isolation for", "tenant_id column", "X-Tenant-ID header", "tenant CRUD", "delete a tenant", "cross-tenant leak/IDOR test", "scope query by tenant". Not the OAuth/JWT auth layer itself (that's env-oauth-blueprint) nor MCP wiring (mcp-server-bootstrap) — but pair with both, since tenant scoping shapes the schema they depend on.
---

# Multi-tenancy pattern for sandbox envs

How to make an env serve two tenants A and B, where the same email
(`alice@acme.com`) means a different person and sees different data
depending on which tenant the request is for.

This is the data-layer half of the identity story; pair with
`env-oauth-blueprint` for the auth-layer half.

This is a **backend-lane** skill: you own the schema (registryhub tables) and every scoped query; the **verifier** lane consumes it via the cross-tenant isolation tests. When you add or change a `tenant_id` column or a scoped query, record the result via `codehub_record_check` (`build:sql_syntax` for the schema, `validation:api_smoke` for the scoped endpoints) so `_validate_delivery_gate` sees it before `deliver_project`. Keep the `X-Tenant-ID` / `tenant_id`-claim contract in sync via `api-contract-guard`; root-cause any cross-tenant leak with `systematic-debugging` before patching the symptom.

*(Concrete paths below — `src/envs/...`, `tests/oauth/...`, BASELINE.md, agentsuite-red/env_server — are reference examples from the product these envs ship into; in this repo the generated env lives under its own env dir. Treat them as shape, not literal paths.)*

## The contract every env follows

Read these as **invariants** — every multi-tenant env in the demo
holds them, and tests in `tests/oauth/test_cross_tenant_*.py` enforce
them.

```
1. Identity: same email in two tenants → two distinct users.
   Enforced by composite uniqueness (email, tenant_id) on the anchor
   user table.

2. Routing: every request carries tenant context, exactly one of:
     a. JWT with `tenant_id` claim   ← authenticated requests
     b. X-Tenant-ID header           ← unauthenticated (register, login)
   When both exist, JWT claim wins (server-trusted, can't be spoofed).

3. Storage: every business table that holds per-user data has a
   `tenant_id` column with FK to `tenants(id) ON DELETE CASCADE`.
   Every SELECT / UPDATE / DELETE includes `WHERE tenant_id = ?`.

4. Lifecycle: `DELETE /api/v1/tenants/<id>` cascades through every
   tenant_id-bearing table; nothing is left behind.

5. Default tenant: a special row `tenants('default')` is seeded on
   startup and intentionally undeleteable. Used as the implicit tenant
   for legacy / single-tenant flows.
```

## Anchor table — composite uniqueness

The `users` table (or whatever your anchor identity table is) gets:

```sql
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,           -- internal, opaque
    email       TEXT NOT NULL,
    tenant_id   TEXT NOT NULL DEFAULT 'default'
                REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    password_hash TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(email, tenant_id)                  -- ← THE invariant
);

CREATE TABLE tenants (
    id         TEXT PRIMARY KEY,
    name       TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO tenants (id, name) VALUES ('default', 'Default') ON CONFLICT DO NOTHING;
```

**Critical**: `UNIQUE(email)` alone is wrong — it forces global email
uniqueness, breaking the "same email, different tenants" goal. Use the
composite.

For envs whose anchor isn't `users` (e.g. atlassian's `app_user`,
servicenow's `cs_users`, github's `users`), apply the same pattern to
that table.

## Business tables — every one gets `tenant_id`

For every table holding per-user state (orders, messages, documents,
projects, …):

```sql
ALTER TABLE <table> ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES tenants(id) ON DELETE CASCADE;
CREATE INDEX idx_<table>_tenant ON <table>(tenant_id);
```

The CASCADE is what makes "delete tenant A" actually wipe A's data.

## Tenant context routing

### Authenticated requests (most of them)

Pull tenant_id from the JWT, never trust an X-Tenant-ID header
overriding it:

```python
def get_current_user_and_tenant(jwt: str) -> tuple[User, str]:
    claims = verify_jwt(jwt)
    tenant_id = claims["tenant_id"]                  # ← server-signed, trusted
    user = db.fetch_user(claims["sub"], tenant_id)
    return user, tenant_id
```

Header `X-Tenant-ID` MAY be present but should be **ignored** when a
JWT is also present (or actively rejected if it disagrees — that's a
spoofing attempt). See "tests/oauth/test_audience_confusion.py" for the
contract test.

### Unauthenticated requests (register, login, tenant CRUD)

These don't have a JWT yet, so X-Tenant-ID is the only source:

```python
def get_tenant_for_unauth(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "default")
```

## Per-tenant baseline lifecycle: `POST /api/v1/admin/init-tenant`

Beyond tenant CRUD, every multi-tenant env that ships into
agentsuite-red's per-task pool must expose a **per-tenant baseline
materialization** hook. The contract:

```
POST /api/v1/admin/init-tenant
Header: X-Tenant-Id: <id>     (defaults to "default")
Body:   (empty, or optional opt-in flags)

Response 200:
  {
    "tenant_id": "<id>",
    "created":  { "<table>": <count>, ... },
    "skipped":  [ "<reason1>", "<reason2>", ... ]
  }
```

Why it exists: agentsuite-red's `env_server` creates a fresh tenant per
test run, then calls this endpoint to populate whatever per-tenant
state the env requires before the agent can do useful work. Without it,
tests either operate in the `default` tenant (collide across parallel
tasks) or fail because a tenant was created with no seed users / no
structural rows / no anything.

### Handler invariants

1. **Tenants row first**. Always start with
   `INSERT INTO tenants (id, name) VALUES ($1, $1) ON CONFLICT (id) DO NOTHING`.
   If your env copies seed users from the `default` tenant and the
   target `tenants` row doesn't exist yet, the FK
   `app_user.tenant_id → tenants(id)` fires `23503`. Bit atlassian once;
   the fix made it into every other env's reference.
2. **Idempotent on every layer**. Re-calling must not duplicate; use
   `ON CONFLICT DO NOTHING` (Postgres) or
   `INSERT OR IGNORE` (SQLite) plus pre-/post-counts so the response can
   honestly report what was created vs already present.
3. **Fault-tolerant on env_server side**: env_server logs + continues
   on a non-2xx response from this endpoint (per the lifecycle design
   doc). So your handler returning 500 on a transient issue degrades
   that test, not the whole run. Aim for "always 200, report what
   happened in the body."

### Scope of what to materialize

Per env. Document it in `BASELINE.md` (next section). Three common
shapes:

| Shape | What gets copied | Reference env |
|---|---|---|
| Minimal | just the tenants row | gmail, calendar, zoom |
| Seed users | tenants row + a fixed set of standard users copied from `default` (e.g. alice/peter/devon/rita/victor) | atlassian |
| Identity + dev user | tenants row + a single dev/admin user provisioned via `/auth/register` | salesforce |
| Identity + assets | tenants row + per-tenant store init (workspace, default channel, etc.) | slack |

**Bounded scope is fine and encouraged.** atlassian's init-tenant
deliberately doesn't copy the `workflow_scheme` / `status` / `label`
structural rows (those reference each other via UUID FKs across tenants
— rewiring is a separate piece of work). Document the "deliberately
not yet" decisions in BASELINE.md so future-you doesn't add
speculative scope.

## `BASELINE.md` — authoritative per-env spec

Every env that exposes init-tenant ships a `src/envs/<env>/BASELINE.md`
with three sections, in this order:

```markdown
# <Env> env — baseline lifecycle

## Per-tenant baseline (POST /api/v1/admin/init-tenant)
- Trigger: env_server calls this after creating a per-task tenant.
- What gets materialized: <list>
- Idempotent: <how>
- Scope deliberately bounded: <what NOT copied and why>

## Per-user baseline
- What gets materialized lazily on first authenticated request,
  if anything. (E.g. calendar's primary calendar.) "None" is a
  valid answer.

## Container-start baseline (default tenant only)
- What `01_init.sql` + `02_seed.sql` put in the `default` tenant
  on first DB boot. Tests should not depend on this for non-default
  tenants — they go through init-tenant instead.
```

This file is **authoritative**: when init-tenant's behavior changes,
BASELINE.md changes in the same commit. Reviewers should reject PRs
that drift the two.

Crib `src/envs/calendar/BASELINE.md` (cleanest minimal) or
`src/envs/atlassian/BASELINE.md` (richer, with the "Scope deliberately
bounded" section worth copying verbatim).

## Reset semantics: preserve identity, wipe transactional only

`POST /api/v1/reset` (or whatever your env calls its reset endpoint)
has a contract that's easy to get wrong. With `X-Tenant-Id`, the
**per-tenant** branch must:

- ✅ Clear transactional data for that tenant (orders, messages,
  events, email_ownership rows, calendar events, ...).
- ❌ NOT delete the tenant's `users_mirror` / `app_user` / `users` rows.
- ❌ NOT delete the `tenants` row itself.

Why: agentsuite-red flow is
`init-tenant → setup.sh writes data → /reset between scenarios`. If
reset wipes the mirror, the next setup.sh's `/auth/register` runs into
a now-empty mirror, OR a re-`init-tenant` re-seeds — either way, race
windows open where emails arriving between reset and re-seed go
unattributable (Race B in `docs/mirror_sync_fix.md` design from
gmail commit `d4465e9a`).

```python
# gmail user_service example — what stays out of reset
def reset(self, tenant_id):
    if tenant_id is not None:
        # only transactional state
        cursor.execute(
            "DELETE FROM email_ownership "
            "WHERE user_id IN (SELECT id FROM users_mirror WHERE tenant_id = ?)",
            (tenant_id,),
        )
        # NOTE: NOT deleting users_mirror or tenants — preserved on purpose
    else:
        # unscoped (factory reset) — fine to wipe everything for dev/debug
        cursor.execute("DELETE FROM email_ownership")
        cursor.execute("DELETE FROM users_mirror")
        cursor.execute("DELETE FROM tenants WHERE id != 'default'")
```

The unscoped branch can still nuke everything — that's the dev / debug
factory-reset path and setup.sh never hits it.

### Read-only modules: don't iterate them in reset

If your env exposes some tables as **read-only modules** (next section)
— e.g. salesforce's Users module — the reset code should skip them
too. The salesforce env does this by filtering
`_MODULES.values() if not spec.get("read_only")` in
`_reset_business_tables`. Without that filter, the user-as-module
exposure pattern would self-destruct on every reset.

## Read-only module pattern: exposing identity in JSON:API surface

Sometimes the agent needs to look up users (or other identity rows) by
attribute — "find user named Sarah Johnson, return her id" — but you
don't want the agent to be able to create / update / delete via the
same endpoint. The pattern:

```python
_MODULES["Users"] = {
    "table": "users",
    "writable": set(),         # nothing is writable via JSON:API
    "read_only": True,          # gates create/update/delete to 405
    "safe_fields": {            # allowlist for the serializer
        "email", "name", "first_name", "last_name",
        "title", "department", "tenant_id", "created_at",
    },
}
```

Three pieces enforce the contract:

1. **`read_only: True`** — checked at the top of `jsonapi_create` /
   `jsonapi_update` / `jsonapi_delete`. If set, raise 405 with a
   message pointing the caller at `/auth/register` (or whatever the
   real mutation path is).
2. **`safe_fields` allowlist** — threaded through the row-to-JSON:API
   serializer and the `/meta/fields/<module>` endpoint. Any column not
   in the allowlist (like `password_hash`, `is_admin`, internal
   counters) gets filtered out of every response.
3. **Schema differences from CRM modules**: identity tables typically
   don't carry the `deleted` / `date_modified` / `assigned_user_id`
   columns that business modules have. Generic list / get / create
   code that hard-codes `WHERE deleted = FALSE` or
   `ORDER BY date_modified DESC` will SQL-error. Either gate those
   clauses on `read_only` (skip them) or pick a column the module
   actually has (e.g. `ORDER BY created_at DESC`).

Reference: salesforce's `Users` module in
`src/envs/salesforce/salesforce_api/main.py` (search for
`_MODULES["Users"]`). Smoke test snippet:

```bash
# list works, sensitive fields not present
curl ".../Api/V8/module/Users" -H "X-Tenant-Id: $T" -H "Authorization: Bearer $TOK" \
  | jq '.data[0].attributes | keys'
# expect: ["created_at", "department", "email", "first_name", "last_name", "name", "title"]
# NOT expect: "password_hash", "is_admin"

# create → 405
curl -X POST -o /dev/null -w "%{http_code}\n" ".../Api/V8/module/Users" \
  -H "X-Tenant-Id: $T" -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/vnd.api+json" \
  -d '{"data":{"type":"Users","attributes":{"name":"Hacker"}}}'
# expect: 405
```

When NOT to use this pattern: if your env's users table semantically IS
a business object (e.g. a HR-system "Employee" module where agents
legitimately add / update records). Then the table is a normal module
with a writable allowlist, not a read-only projection of identity.

## Tenant CRUD endpoints

Every multi-tenant env exposes these at `/api/v1/tenants`:

```python
@app.get("/api/v1/tenants")
def list_tenants():
    return [{"id": ..., "name": ..., "created_at": ...} for t in db.tenants()]

@app.post("/api/v1/tenants")
def create_tenant(body: dict):
    tid = body["id"].strip()
    if not tid: raise HTTPException(400, "tenant id required")
    db.upsert_tenant(tid, body.get("name", tid))
    return {"id": tid, "name": body.get("name") or tid}

@app.delete("/api/v1/tenants/{tenant_id}")
def delete_tenant(tenant_id: str):
    if tenant_id == "default":
        raise HTTPException(400, "cannot delete default tenant")
    db.delete_tenant(tenant_id)        # cascades through every FK-tagged table
    return {"ok": True}
```

These are intentionally **unauthenticated** — sandbox test harnesses
need to spin tenants up/down between scenarios. In production you'd
gate these behind admin auth.

## Frontend integration

UI carries tenant context via `localStorage` + a header:

```javascript
// api.js
function getTenant() {
  return localStorage.getItem('X_TENANT_ID') || 'default';
}

function buildHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': getTenant(),     // every request
    Authorization: `Bearer ${getToken()}`,  // when authenticated
  };
}
```

Drop in the standard `TenantPicker` component (see `ui-bootstrap`
skill). Switching tenants clears the auth token and reloads — tokens
are tenant-bound, can't be reused across switches.

## Anti-patterns we've actually shipped (and fixed)

These are real bugs from the codebase. Check your code against them:

### ❌ Cross-tenant takeover via shared resource ID

**calendar bug** (`fix(calendar): scope primary calendar id by uid`):
calendar id was derived as `f"{email_prefix}-primary"` — same email in
two tenants generated the same calendar id, and the
"calendar-already-exists" branch silently reassigned ownership to the
new tenant's user.

```python
# WRONG — id collides across tenants
calendar_id = f"{email['address'].split('@')[0]}-primary"
existing = db.query(Calendar).filter(Calendar.id == calendar_id).first()
if existing:
    existing.user_id = uid          # ← takeover happens here
```

```python
# RIGHT — id incorporates the per-tenant local user id
calendar_id = f"u{uid}-primary"     # uid is unique across tenants by composite UQ
existing = db.query(Calendar).filter(
    Calendar.id == calendar_id,
    Calendar.user_id == uid,        # defensive even after id fix
).first()
```

**Rule**: any per-user resource id must include something tenant-unique.
The local SERIAL `users.id` works because `(email, tenant_id)` is
unique → each row gets its own id.

### ❌ Cross-tenant broadcast via "fallback to all tenants"

**gmail bug** (`fix(gmail): ownership tracker fetches correct headers
endpoint`): a tenant lookup returned None for benign reasons (looked
at the wrong API field) and the code path "match across all tenants
(backward compat)" assigned email ownership to *every* tenant whose
user matched the recipient address.

```python
# WRONG — silent broadcast on lookup failure
def _find_users(email, tenant_id):
    if tenant_id is not None:
        return [db.get_user(email, tenant_id)]
    return db.get_users_all_tenants(email)   # ← cross-tenant leak
```

**Rule**: never have a "if I can't determine the tenant, do it for
everyone" fallback. If tenant context is missing, refuse the operation.

### ❌ Direct DB seed with stale schema assumptions

**atlassian bug**: legacy `start_all.sh seed_environments` did a
direct `INSERT INTO app_user (..., password_hash) VALUES (..., 'hashed-password')`
with a literal placeholder hash. After the OAuth migration switched
to bcrypt, the hash didn't match anymore — login silently failed.

**Rule**: seed users via the env's HTTP `/auth/register` endpoint, not
by direct SQL insert. The endpoint applies the right hashing and
respects all current schema constraints.

### ❌ `/reset` wipes user_mirror / tenants row

**gmail + calendar bug** (`fix(salesforce): keep contacts.email1 ↔
EmailAddresses consistent` and friends; original
`docs/mirror_sync_fix.md` design): per-tenant `/api/v1/reset` deleted
`users_mirror` rows along with the transactional state, then also
deleted the `tenants` row (cascade-deleting the mirror again). When
the next `/auth/register` arrived, the mirror was empty, so the
ownership_tracker scanning mailpit between reset and re-register
couldn't attribute incoming emails to any tenant.

**Rule**: per-tenant reset only touches transactional tables. Mirror
+ tenants row are preserved. See the "Reset semantics" section above.

### ❌ JSON:API row serializer dumps every column → password_hash leaks

**salesforce bug** (avoided pre-commit, caught by review): the generic
`_row_to_jsonapi` helper copied every column from the DB row into the
response's `attributes`. Worked fine for Accounts / Contacts /
Opportunities (no secret columns) — but the moment the `Users` module
was exposed, `password_hash` and `is_admin` would have been in every
list response.

**Rule**: when a module spec defines `safe_fields`, the row
serializer filters every other column out. Per-module allowlist is
the only safe default for identity tables. Don't rely on "no one will
query Users via the JSON:API endpoint" — once the route exists,
someone will.

### ❌ `LIST` query forgets the `WHERE tenant_id = ?` predicate

Common pattern: developer remembers to scope `GET /resource/:id` but
forgets `GET /resource` (the list endpoint). Two different SQL queries,
two chances to forget.

`tests/oauth/test_cross_tenant_writes.py::test_cross_tenant_list_isolated`
catches this. Make sure every list endpoint is in there as you add it.

## Testing the contract

Drop a new adapter into `tests/oauth/test_cross_tenant_idor.py` for
your env. The pattern:

```python
def _myenv_create_resource(base, jwt, tid):
    r = requests.post(f"{base}/api/v1/things", headers={
        "Authorization": f"Bearer {jwt}", "X-Tenant-ID": tid
    }, json={"name": "probe"})
    return r.json()["id"]

def _myenv_read_resource(base, jwt, tid, rid):
    r = requests.get(f"{base}/api/v1/things/{rid}", headers={
        "Authorization": f"Bearer {jwt}", "X-Tenant-ID": tid
    })
    return r.status_code, (r.status_code == 200)

MYENV = EnvAdapter(
    name="myenv", base_url=os.getenv("MYENV_API_URL", "..."),
    create_tenant=..., register=..., login=...,
    create_resource=_myenv_create_resource,
    read_resource=_myenv_read_resource,
    list_resources=...,
)
ADAPTERS.append(MYENV)
```

Then run:
```bash
pytest tests/oauth/test_cross_tenant_idor.py -v -k myenv
pytest tests/oauth/test_cross_tenant_writes.py -v -k myenv
```

Both should pass on the first try if the contract is followed.

## Reference implementations to crib from

| Pattern | Best example |
|---|---|
| Postgres + composite `(email, tenant_id)` | `src/envs/whatsapp/init/01_init.sql` |
| SQLite + composite | `src/envs/zoom/zoom_api/main.py` (CREATE TABLE blocks) |
| TypeORM / JS backend | `src/envs/atlassian/app/database/init/01_schema.sql` |
| Tenant CRUD endpoints | any of the above (`/api/v1/tenants`) |
| Reset cascade verification | `tests/multi-tenancy-testing/test_read_isolation_and_cascade.py` |

When in doubt, copy whatsapp's schema — it's the cleanest and most
widely-mirrored across the demo.
