# forgingground-gen

The **Forgingground environment generator** — the multi-agent pipeline that
generates sandbox environments (FastAPI + React/Vite/Tailwind + Postgres +
OAuth2 AS + FastMCP) for the **agentsuite-red** red-teaming platform.

This repo is the canonical home for the generator (migrated out of the upstream
`env-gen` research monorepo). It holds two things:

| Path | What |
|------|------|
| `agent/env_generator/` | The generation **engine** — the multi-agent LLM pipeline (kickoff → impl → docker → validation), runtime contract-projection layers, templates, and the legacy live monitor. |
| `agent/tests/` | The engine's test suite (~2,900 tests). |
| `agent/utils/` | Engine support utilities (LLM provider clients, config). |
| `app/` | The **Env Forge API** — a FastAPI service: env/run registry (DB) + live collaboration-hub state read from each generated env, serving the Env Forge UI under `/env-forge/*`. |
| `run_*.sh` | Generation entry points (instagram / facebook / plane / github-clone / smoke). |
| `reference_images/` | Reference screenshots used as visual-fidelity targets. |

Sibling repo: **forgingground-gen-frontend** (the React Env Forge UI), consumed
by the platform as a git submodule of `agentsuite-red-frontend`.

## Run the generator

```sh
# deps live in your env (see pyproject.toml); GOOGLE_API_KEY / provider keys as needed
PROVIDER=google MODEL=gemini-3.1-pro-preview ./run_instagram.sh
```

Each script derives `REPO_ROOT` from its own location; generated envs land in
`./generated/<project>`.

## Run the Env Forge API

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8095
# env: DATABASE_URL (default sqlite), ENVS_ROOT (default ./generated)
```

## Test the engine

```sh
cd agent && python -m pytest tests/ -q
```

> The apps this engine **generates** carry their own dependency manifests
> (python-jose / bcrypt / cryptography / psycopg for the embedded OAuth2 AS,
> etc.) — those are emitted into each generated env and are not engine deps.
