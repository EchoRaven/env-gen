# Target Environment Architecture (forgingground / agentsuite-red)

> **Single source of truth** for what the env-gen pipeline must generate.
> The generator's purpose is to produce **sandbox environments consumable by
> agentsuite-red's `env_server` pool** (`forgingground-env/src/envs/<env>/` +
> `forgingground-env/src/mcp_server/<env>/`). Every lane (orchestrator,
> backend, frontend, verifier, debugger) targets THIS contract. Derived from a
> deep read of the real reference envs (calendar, zoom, googledocs, gmail) on
> 2026-06-05.
>
> **Reference repo:** `/data/common/haibotong/agentsuite-red/forgingground-env/src`
> **Canonical clone targets:** `calendar` (backend/compose/DB/tenancy, modular
> FastAPI), `zoom` (embedded OAuth AS), `googledocs/ui` (Vite+Tailwind UI),
> `mcp_server/gmail` + `mcp_server/calendar` (MCP). **Anti-pattern: do NOT clone
> `googledocs`'s api service shape** (inline `python:3.12-slim` + apt/pip/migrations
> in `command:` — slow, fragile).

---

## 0. Tech stack (LOCKED)

| Layer | Choice |
|---|---|
| Backend | **Python 3.11 + FastAPI** (uvicorn, SQLAlchemy 2.x ORM, Pydantic v2, **psycopg3**) |
| Database | **stock `postgres:16` image** + `./init/01_init.sql` mounted into `/docker-entrypoint-initdb.d` (NO custom-built db image) |
| Frontend | **React 18 + Vite 5 + Tailwind 3** → multi-stage `node:20-alpine` build → `nginx:alpine` serve |
| Auth | **Embedded OAuth2 AS** (default, standalone envs) OR **central google-idp** resource-server (google-family only). RS256 JWT, JWKS. |
| MCP | **FastMCP** server in a SEPARATE tree `mcp_server/<env>/` (+ optional `injection_mcp_server/<env>/` for red-team) |
| Multi-tenancy | per-task **JWT `tenant_id` claim** in one shared process (native pool); business tables carry NO `tenant_id` (see §5) |
| Orchestration | per-env `docker-compose.yml`, 3 services, `network_mode: host` |

This **supersedes** the generator's current Express/JS + custom-postgres-image +
`app/{backend,frontend,database}` output. See §11 for the migration of prior work.

---

## 1. Directory layout (what the generator emits)

```
envs/<env>/                          # the ENV (backend + db + ui + compose)
├── docker-compose.yml               # 3 services: <env>-pg, <env>-api, <env>-ui (§9)
├── README.md
├── BASELINE.md                      # lifecycle doc (per-tenant / per-user / container-start) — §6
├── init/
│   └── 01_init.sql                  # Postgres DDL (tenancy spine + business tables) — §4
│   └── 0N_*.sql                     # optional, lexical-order initdb scripts (e.g. 02_seed_demo.sql)
├── migrations/                      # optional; idempotent ALTERs applied every boot — §4
├── init_examples/
│   └── basic_scenario.json          # dev/UI seed fixtures (default tenant only)
├── api/                             # FastAPI backend  (build context ./api ; service <env>-api)
│   ├── main.py                      # app + /health + control surface + business endpoints — §2,§7
│   ├── models.py                    # SQLAlchemy ORM (calendar style)
│   ├── schemas.py                   # Pydantic v2 (Base/Create/Update/Response/ListResponse)
│   ├── database.py                  # engine + SessionLocal + get_db()
│   ├── auth.py                      # JWT verify + get_current_user  (resource-server)  — §3
│   ├── oauth_routes.py              # EMBEDDED-AS only: the OAuth2 AS router  — §3
│   ├── oauth_store.py               # EMBEDDED-AS only: pg-backed client/code/user store
│   ├── jwt_manager.py               # EMBEDDED-AS only: RSA keypair + RS256 sign + JWKS
│   ├── sandbox_init.py              # CLI seeder: python sandbox_init.py <json> [tenant]
│   ├── reset.sh                     # docker exec <env>-api /reset.sh  (hard reset)
│   ├── pyproject.toml               # uv deps
│   └── Dockerfile                   # uv slim base → CMD python main.py
└── ui/                              # React+Vite+Tailwind  (build context ./ui ; service <env>-ui)
    ├── index.html                   # Vite root, <script type=module src=/src/main.jsx>
    ├── src/{main.jsx, App.jsx, api.js, index.css, components/{LoginPage,TenantPicker,...}.jsx}
    ├── vite.config.js, tailwind.config.js, postcss.config.js, package.json
    ├── nginx.conf.template, start.sh, Dockerfile, .dockerignore

mcp_server/<env>/                    # the MCP server (SEPARATE tree — NOT inside envs/<env>/) — §8
├── main.py                          # FastMCP + RemoteAuthProvider + @mcp.tool() per API op
├── pyproject.toml, uv.lock, start.sh, README.md

injection_mcp_server/<env>/          # optional red-team injection MCP — §8
├── env_injection.py, env_start.sh
```

**Dir-name decision:** use generic **`api/`** + **`ui/`** (googledocs precedent —
the env name is already known, no need to prefix). The **compose service names
MUST be `<env>-pg` / `<env>-api` / `<env>-ui`** regardless of dir name —
`gen_compose` prefix-rewrites by exact service-name match. (calendar uses
`<env>_api`/`<env>_ui` dirs; either is fine, service names are what matter.)

---

## 2. Backend (FastAPI `api/`)

Clone **calendar/calendar_api** structure (modular ORM split). `main.py` order:

1. **threadpool monkeypatch (MANDATORY, before app creation):**
   ```python
   async def _run_without_threadpool(func, *a, **k): return func(*a, **k)
   ```
   assigned to `starlette.concurrency.run_in_threadpool`,
   `fastapi.routing.run_in_threadpool`, `fastapi.dependencies.utils.run_in_threadpool`.
   *Sandbox hosts block new pthread creation — without this, FastAPI's default
   threadpool dispatch crashes.*
2. `app = FastAPI(title="<Env> API", version="1.0.0")`
3. `app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)`
4. `GET /` (banner) + `GET /health` → `{"status":"healthy"}`
5. control surface (§7): `/api/v1/reset`, `/api/v1/admin/init-tenant`, `/api/v1/tenants` (GET/POST), `/api/v1/tenants/{id}` (DELETE), `/api/v1/seed-user`
6. business endpoints — plain **sync `def`** functions, `Depends(get_db)` + `Depends(get_current_user)`, `HTTPException` on errors
7. ```python
   if __name__ == "__main__":
       uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("<ENV>_API_PORT","<default>")),
                   loop="asyncio", http="h11")   # loop/http pins MANDATORY (uvloop/httptools spawn threads → fail)
   ```

- **database.py:** `_database_url()` reads `DATABASE_URL` then `<ENV>_PG_{HOST,PORT,DB,USER,PASSWORD}` (defaults `127.0.0.1` / `<unique>` / `<env>_sandbox` / `sandbox` / `sandbox`), builds `postgresql+psycopg://...` (psycopg3!), `create_engine(url, echo=False, pool_pre_ping=True)`, `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`, `async def get_db()` yields+closes a sync Session (intentional — works with the monkeypatch).
- **models.py:** `Base = declarative_base()`; the **tenancy spine** (§5) + domain tables. String/UUID PKs for resources, Integer SERIAL for the user mirror; `ForeignKey`, `relationship(back_populates, cascade="all, delete-orphan")`, JSON(B) for nested blobs, `default/onupdate=datetime.utcnow`, `UniqueConstraint`. Use `flag_modified(obj, "col")` when mutating JSON columns in place.
- **schemas.py:** `<Obj>Base→Create/Update(all Optional)/Response/ListResponse`, `class Config: from_attributes = True` (+ `populate_by_name=True` + `Field(alias="camelCase")` when mirroring an external API).
- **Dockerfile:** `FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, WORKDIR /app, COPY pyproject.toml, `uv pip install --system -r pyproject.toml`, COPY *.py + reset.sh (+ chmod), `EXPOSE <internal_port>` (= uvicorn bind port, NOT host port), `CMD ["python","main.py"]`. No `pip install -e .`.
- **pyproject.toml deps (calendar superset, trim per imports):** fastapi>=0.115, uvicorn>=0.30, pydantic[email]>=2, pydantic-settings>=2, sqlalchemy>=2, **psycopg[binary]>=3.1**, python-jose[cryptography]>=3.3, bcrypt>=4 (google-idp only), python-multipart, python-dateutil, pytz, httpx. `requires-python>=3.11`, hatchling build-backend.
- **reset.sh:** `#!/bin/sh`, `set -e`, inline `python3 -c` deleting business tables **child-first FK order, PRESERVING `tenants`**, then `rm -f /tmp/<env>_*`.

---

## 3. Auth / OAuth

**JWT claim contract (LOCKED, identical across both patterns):**
`iss`, `sub`(str), `aud`(**array**, even for one audience), `tenant_id`, `email`,
`scope`, `jti`, `iat`, `exp`, `client_id` (+ optional `name`). RS256 only, verified via JWKS.

### 3a. Embedded OAuth2 AS — **default for standalone envs** (clone zoom)
Emit `jwt_manager.py` + `oauth_store.py` + `oauth_routes.py`, wired in `main.py`:
- `jwt_manager.JWTManager(data_dir=JWT_DATA_DIR)`: loads/creates `<data_dir>/jwt_private.pem` (RSA-2048, PKCS8, NoEncryption, **chmod 0600**), `KEY_ID="<env>-oauth-key-1"`, `sign_access_token(...)`, `jwks()`.
- `oauth_store`: pg-backed, password hash `sha256(password + "<env>_sandbox_salt_2024")` — **the same salt must appear in `main._hash_password`** (they must agree or logins fail).
- `oauth_routes.build_router(db, jwt_manager)`: mounts `GET /.well-known/oauth-authorization-server`, `GET /.well-known/jwks.json`, `POST /oauth/register` (RFC 7591), `GET/POST /oauth/authorize` (**PKCE S256 required**), `POST /oauth/token` (authorization_code). Scopes `<env>.read/<env>.write/<env>.admin`.
- `main.py` also serves first-party `POST /auth/{login,register}` (JSON) + `POST /api/v1/auth/{login,register}` (form) all minting the same RS256 token; `get_current_user` verifies against the in-process public PEM with **`options={"verify_aud": False}`** (aud enforced at the MCP layer).
- **compose:** `OAUTH_DEFAULT_AUDIENCE=<env>-api`, `OAUTH_ACCESS_TOKEN_TTL`, `JWT_DATA_DIR=/var/lib/<env>-auth`, **named volume `<env>_jwt_data:/var/lib/<env>-auth` (REQUIRED — else tokens die on restart)**. OAuth tables (`oauth_clients`, `oauth_authorization_codes`) live in `init/01_init.sql`.
- Read `OAUTH_ISSUER` **from env** (gen_compose pins it to `http://127.0.0.1:<allocated_API_PORT>`); never hardcode the port.

### 3b. google-idp resource-server — **google-family only** (clone calendar `auth.py`)
Pure verifier, **no minting, no `/oauth/*`**: `_fetch_jwks()` from `GOOGLE_IDP_URL/.well-known/jwks.json` (300s cache) + HS256 fallback on `OAUTH_JWT_SECRET`; `_check_iss_aud` (`iss==OAUTH_ISSUER`, `MY_AUDIENCE in aud`); `get_current_user` lazy-upserts `users_mirror` on `(sub, tenant_id)`. Must expose `POST /api/v1/seed-user` (idempotent mirror receiver — the IdP fans out to it on register). compose vars: `OAUTH_JWT_SECRET`, `OAUTH_ISSUER=google-idp`, `MY_AUDIENCE=<env>-api`, `GOOGLE_IDP_URL=http://127.0.0.1:8050`. Hashing is **bcrypt** here (not the embedded salt). Register the env in `google-idp/seed/clients.json` + the IdP's mirror fan-out list. Identity/passwords/users live ONLY in google-idp.

---

## 4. Database + seeding

- **Schema is DELIVERED, not built:** db service = stock `postgres:16`, mount `- ./init:/docker-entrypoint-initdb.d:ro` + named `<env>_pgdata` volume. The official entrypoint runs `init/*.sql` **once, on an empty volume**. **No custom db Dockerfile.**
- **`init/01_init.sql`** = self-contained CREATE-only DDL + the default-tenant INSERT. Ordering by zero-padded prefix (`01_init.sql` < `02_seed_demo.sql` < `03_*`).
- **DDL conventions:** `TEXT` ids/strings; opaque resource ids `TEXT PRIMARY KEY`; internal user key `SERIAL PRIMARY KEY`; `TIMESTAMP DEFAULT NOW()`; `JSONB` blobs; `CREATE TABLE/INDEX IF NOT EXISTS`. **FK syntax `<col> <type> NOT NULL REFERENCES <table>(<col>) ON DELETE CASCADE`** (paren'd column — *not* `REFERENCES table.col`, the bug fixed by `database_scaffold._normalize_inline_fk`). **Quote reserved words** (`"end"`, `"primary"`; `start` is fine).
- **Schema evolution** for existing volumes → `migrations/00N_*.sql` (idempotent: `ADD COLUMN IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, `pg_constraint` guards), applied by the api container on every boot via `psql -v ON_ERROR_STOP=1`. An empty `migrations/` dir is valid.
- **Seed data** flows via `init_examples/*.json` + `sandbox_init.py` (ORM loader). `sandbox_init.py` **looks up users in the mirror (raises if absent) — it does NOT create users** (identity is in the IdP/AS). `init_data.sh` seeds the **default tenant only**, for UI/dev — **never for tests** (tests provision their own tenant via `init-tenant`).

---

## 5. Multi-tenancy (the non-obvious model)

**Native pool = ONE shared backend process; per-task isolation is the JWT `tenant_id`
claim, NOT container isolation.** The single biggest correctness invariant:

- **Business tables carry NO `tenant_id` column.** Tenancy is enforced transitively:
  `business_row.user_id (local SERIAL) → users_mirror(sub, tenant_id)`. The local id
  is unique per tenant by construction, so **filtering every query by the
  authenticated `current_user["id"]` IS the tenant boundary.**
- **Tenancy spine in `init/01_init.sql`:**
  ```sql
  CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, created_at TIMESTAMP DEFAULT NOW());
  INSERT INTO tenants (id) VALUES ('default') ON CONFLICT (id) DO NOTHING;
  CREATE TABLE IF NOT EXISTS users (            -- a.k.a. users_mirror
    id SERIAL PRIMARY KEY,
    sub INTEGER NOT NULL,                       -- IdP/AS authoritative user id
    tenant_id TEXT NOT NULL DEFAULT 'default' REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT, name TEXT,
    UNIQUE (sub, tenant_id));
  ```
- Same `sub` (or `email`) in two tenants = **two distinct local ids**. `get_user_by_email` MUST include `tenant_id`. Never `existing.user_id = uid` to "adopt" a row.
- **PK-from-user-value collision:** any business PK derived from a user-stable value must be prefixed with the local uid (`u{uid}-primary`), never email — else two tenants sharing `dev@virtueai.com` collide.
- `tenant_id` resolution: **JWT `tenant_id` claim** for business calls; **`X-Tenant-Id` header** for admin/reset/seed; fallback literal `"default"`.
- **Never trust a client-supplied user/tenant id for business scoping** (cross-tenant IDOR). Generate a `tests/oauth/test_cross_tenant_idor` that mints two JWTs (same sub diff tenant; diff sub same email) and asserts isolation.
- `verify_aud=False` in the decode call is intentional — aud is checked manually in `_check_iss_aud` (or at the MCP layer). Keep the manual check.

---

## 6. BASELINE.md (mandatory per env)

Three baseline tiers + reset semantics:
- **Per-tenant** (`POST /api/v1/admin/init-tenant`): usually just the `tenants` row ("nothing else").
- **Per-user** (lazy on first JWT): mirror upsert (+ e.g. a primary calendar).
- **Container-start** (`init_data.sh`): default-tenant dev seed only, NOT for tests.
- **Reset:** tenant-scoped `/api/v1/reset` (X-Tenant-Id) deletes only that tenant's business rows and **preserves the mirror + tenants row**; header-less = factory reset (dev only). For native pools `env_server` never calls the header-less reset.

---

## 7. Required HTTP control surface (every env)

| Endpoint | Notes |
|---|---|
| `GET /health` | 200 = ready. Healthcheck target. |
| `POST /api/v1/reset` | `X-Tenant-Id` → tenant-scoped (preserve mirror+tenants); no header → factory. |
| `POST /api/v1/admin/init-tenant` | `X-Tenant-Id` (default `default`), idempotent. |
| `GET /api/v1/tenants` / `POST /api/v1/tenants` | list / create. |
| `DELETE /api/v1/tenants/{id}` | 400 on `default`, 404 if missing; CASCADE wipes the tenant. |
| `POST /api/v1/seed-user` | google-family only: idempotent mirror upsert on `(sub, tenant_id)`. |
| `/auth/login`, `/auth/register` | embedded-AS: local; google-family: in google-idp. Overridable via pool.yaml `auth_path_prefix`. |

These control endpoints are **unauthenticated** (the test harness drives them).

---

## 8. MCP server (`mcp_server/<env>/`, separate tree)

Clone **gmail/calendar** (google-family) or **atlassian** (self-AS). 4 files: `main.py`, `pyproject.toml` (`<env>-mcp`; fastmcp~=2.13, mcp[cli], httpx, uvicorn[standard], websockets), `start.sh`, `README.md`.
- Module scope: `mcp = FastMCP("<Env> Client", auth=_build_auth_provider())` where the provider = `RemoteAuthProvider(token_verifier=JWTVerifier(jwks_uri, issuer, audience, algorithm="RS256"), authorization_servers=[AS], base_url=MCP_RESOURCE_URL)`. Audience = `<env>-api` (google) or `{MCP_RESOURCE_URL}/mcp` (self-AS).
- One `@mcp.tool() async def` per env API operation: fresh `httpx.AsyncClient` per call (never cached), headers from `await _get_auth_headers()`, return `json.dumps(result, ensure_ascii=False)`, wrap in `try/except` → `{"error": str(e)}`. Rich docstrings (FastMCP → tool schemas).
- **Per-request JWT forwarding:** `_get_auth_headers()` pulls the caller token via `get_access_token()` and forwards `Authorization: Bearer <jwt>`. The JWT's `tenant_id` is the SOLE tenant source — **do NOT also send `X-Tenant-ID` in MT mode.** Fail-closed (PermissionError) if no per-request token. `DISABLE_OAUTH=1` (STDIO/dev) self-mints via the IdP authorize+PKCE flow.
- `mcp.run(transport="http", host="0.0.0.0", port=port)`; port = `PORT` env > `registry.yaml` (dir-name keyed) > per-env default.
- **Injection MCP** (optional red-team): `injection_mcp_server/<env>/env_injection.py` — UNAUTHENTICATED `FastMCP(name="<Env>EnvInjection")`, `inject_*` tools POST attacker-controlled fields into the env API with a fixed seed token, own port.

---

## 9. docker-compose contract

**Exactly 3 services, `network_mode: host`, no `ports:` mappings** (bind the pool-assigned `*_PORT` directly). Clone **calendar/docker-compose.yml** (search-replace identifiers); do NOT clone googledocs's api `command:` shape.

```yaml
services:
  <env>-pg:                         # image: postgres:16
    environment: { POSTGRES_DB: <env>_sandbox, POSTGRES_USER: sandbox, POSTGRES_PASSWORD: sandbox, PGPORT: ${<ENV>_PG_PORT:-<N>} }
    volumes: [ "./init:/docker-entrypoint-initdb.d:ro", "<env>_pgdata:/var/lib/postgresql/data" ]
    healthcheck: pg_isready -U sandbox -d <env>_sandbox -p ${<ENV>_PG_PORT:-<N>}   # CMD-SHELL
  <env>-api:                        # build: ./api
    depends_on: { <env>-pg: { condition: service_healthy } }
    environment: { <ENV>_PG_*, <ENV>_API_PORT, OAUTH_* / GOOGLE_IDP_URL }
    healthcheck: python -c "import urllib.request; urllib.request.urlopen('http://localhost:<API_PORT>/health', timeout=5)"   # NEVER curl
  <env>-ui:                         # build: ./ui
    depends_on: { <env>-api: { condition: service_healthy } }
    environment: { <ENV>_API_URL: http://127.0.0.1:${<ENV>_API_PORT}, <ENV>_UI_PORT }
volumes: { <env>_pgdata: {}, <env>_jwt_data: {} }   # jwt_data only for embedded-AS
```

- Parameterize every host port as `${<ENV>_<ROLE>_PORT:-<default>}`; defaults must be **globally unique** across env.yaml. Internal app port (uvicorn bind, EXPOSE, /health) ≠ host port.
- `network_mode: host` → **no docker-DNS**; api/ui env vars use `127.0.0.1`/`localhost`, never service names.
- Healthchecks use **python urllib, never curl** (slim/uv images have no curl).

---

## 10. Making an env "consumable" by env_server (registration)

A generated env is NOT poolable until registered in **3 places** (agentsuite-red side):
1. **`config/env.yaml :: environments.<env>`** — `docker_compose` path + `reset_endpoints.api.url` (`http://127.0.0.1:${<ENV>_API_PORT}/api/v1/reset`) + `ports` map (the `*_PORT` keys gen_compose allocates pool ports for, from `start_port: 61000`).
2. **`config/mcp.yaml :: servers[]`** — MCP entry whose `environment` names the env (BASE_URL/AUTH_URL/OAUTH_AUDIENCE).
3. **`env_server/pool.yaml :: pools.<env>`** — `tenant_mode`: `kind: native` (1 shared MCP, JWT routing) or `wrapped` (`pool_size` N); `api_base`/`idp_base` (`==api_base` if embedded AS; `http://127.0.0.1:8050` for google-family); `mcp_env.OAUTH_AUDIENCE=<env>-api`; `dev_user` (default `dev@virtueai.com`/`virtue`/`Dev User`); optional `auth_path_prefix`, `login_token_jsonpath`.

`gen_compose` allocates ports, reserves +2 (MCP, injection MCP) per instance, writes `env_server/instances/<rid>/.env`, brings the pool up as project `pool`. **Re-run `python -m env_server.gen_compose` after editing pool/env.yaml.** Bind = `POST idp /api/v1/tenants` → `POST idp/auth/register` → `POST api /api/v1/admin/init-tenant`; mint = `POST idp/auth/login` (token at `login_token_jsonpath`); unbind = `POST api /api/v1/reset` (X-Tenant-Id) → `DELETE idp /api/v1/tenants/{id}`.

---

## 11. Migration from the generator's current output

| Dimension | Generator now | Target | My recent work |
|---|---|---|---|
| Backend | Express/JS `app/backend/src/server.js` | FastAPI `api/main.py` (+models/schemas/database/auth) | `backend_agent.j2` **rewrite** |
| Layout | `app/{backend,frontend,database}` | `envs/<env>/{api,ui,init,...}` + `mcp_server/<env>/` | output contract **rewrite** |
| DB | custom `app/database/Dockerfile` build (B1) | stock `postgres:16` + `init/01_init.sql` mount | **drop the db Dockerfile**; keep init-SQL gen + relocate to `init/01_init.sql`; **FK normalization (`c58db847`) survives** |
| Schema | plain users/posts, no tenancy | tenancy spine (tenants + users_mirror, FK to local id) | new |
| B2 required-files | `Dockerfile,package.json,src/server.js` | `Dockerfile,pyproject.toml,main.py` | **update the file list** |
| restage backstop / B3 readiness gate | — | — | **stack-agnostic, survive as-is** |
| Frontend | React/Vite, no Tailwind | React/Vite/**Tailwind** + LoginPage + TenantPicker + nginx template | add conventions (largely additive) |
| Auth / tenancy / MCP | none | embedded OAuth AS + JWT tenancy + separate MCP | **new lanes/generators** |

Phased plan: **(1)** backend lane → FastAPI + fix B2 + db-as-stock-image; **(2)** frontend conventions; **(3)** embedded OAuth AS + tenancy spine; **(4)** MCP lane; **(5)** registration emit (env/mcp/pool.yaml); **(6)** translate the 4 domain skills (env-oauth-blueprint / multi-tenancy-pattern / mcp-server-bootstrap / new-env-bootstrap) to THIS `envs/<env>/` frame.

---

## 12. Invariant checklist (the things that silently break)

- [ ] threadpool monkeypatch applied to all 3 symbols **before** app creation
- [ ] `uvicorn.run(..., loop="asyncio", http="h11")` (never uvloop/httptools)
- [ ] EXPOSE / uvicorn bind / `/health` healthcheck all use the **internal** port; host port differs
- [ ] healthchecks use **python urllib, never curl**
- [ ] db = stock postgres image + `./init` mount; **no custom db Dockerfile**
- [ ] FK syntax `REFERENCES table(col)`; reserved words quoted
- [ ] **business tables have NO `tenant_id`**; tenancy via `users_mirror(sub, tenant_id)` + business FK to local SERIAL id
- [ ] every business route filters by `current_user["id"]`; never client-supplied id
- [ ] `verify_aud=False` in decode + manual `iss`/`aud` check
- [ ] embedded AS: `jwt_private.pem` on a **named volume**; password salt identical in `oauth_store` + `main`
- [ ] JWT claim set exactly `{iss,sub,aud[],tenant_id,email,scope,jti,iat,exp,client_id}`; `aud` is an array
- [ ] tenant-scoped `/reset` preserves mirror+tenants; refuse to delete `default`
- [ ] `OAUTH_ISSUER` read from env (gen_compose pins it)
- [ ] MCP under `mcp_server/<env>/` (NOT inside the env); per-request JWT forward, no cached httpx client, no `X-Tenant-ID` in MT mode
- [ ] `network_mode: host` → use `127.0.0.1`, not service names
- [ ] registered in env.yaml + mcp.yaml + pool.yaml; unique default ports

---
*Generated 2026-06-05 from a 7-dimension deep read of forgingground reference envs.
Reference files cited inline are under `agentsuite-red/forgingground-env/src/`.*
