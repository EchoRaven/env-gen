# forgingground-gen

Backend service for **env-gen** — the multi-agent pipeline that generates sandbox
environments for the **agentsuite-red** red-teaming platform. Generated envs land
in the `forgingground-env` `env_server` pool
(`forgingground-env/src/envs/<env>/` + `mcp_server/<env>/`).

Wraps the generation pipeline (extracted from `env-gen`'s `llm_generator/`) as a
**FastAPI service**: start/monitor generation runs, stream live progress over SSE,
and deliver finished environments into the pool. Built on the existing
`live_monitor_server.py` (HTTP + SSE + job model) seed.

- Sibling: **forgingground-gen-frontend** (the driver UI).
- Consumed by the platform as a **git submodule of `agentsuite-red`**.
- Integration plan: `ENVGEN_PLATFORM_INTEGRATION_PLAN.md`.

## Status

Scaffold — pipeline extraction + FastAPI service wrapping pending (plan §1, §5).
