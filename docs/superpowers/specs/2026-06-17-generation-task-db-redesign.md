# Spec — Generation-Task DB redesign (forgingground-gen Env Forge registry)

**Date:** 2026-06-17
**Repo:** `forgingground-gen` · **DB module:** `app/db.py`, `app/models.py` · **Writer:** the Env Forge server (`app/main.py`)
**Status:** design approved (brainstorming) — pending user spec review → writing-plans

## 1. Context & problem

The Env Forge backend keeps a **registry** of every environment the generator produces. Today (`app/models.py`):
- `Environment` — `id == name == generated dir` (PK is the slug; `generated_dir = ENVS_ROOT/<name>`). One row per env *name*.
- `Run` — 1:N per env (run_id, env_id, status, ticks, wallclock) but underused (the server reads runs live from the tree via `hub_reader`, not this table).
- `ChatMessage` — per-env chat.

The db is a **registry of pointers**: heavy per-env state (hubs, checkpoint) is read live from the generated tree (`db.py` docstring; `hub_reader`). Migrations are hand-rolled (`create_all` + idempotent `ALTER TABLE` helpers); SQLite default, Postgres-ready.

**Problem:** because `env = name = dir`, regenerating an env (e.g. running `youtube` again) **overwrites** `generated/youtube` — no history, no per-attempt record, no resume metadata. The registry can't answer "show me every generation attempt, who owns it, where its output + resumable state live, and its lifecycle/cost."

## 2. Goals (all four required)

1. **Resume/recovery** — a killed/crashed task can be resumed from its `state_path` (the engine already supports this: `CheckpointManager(output_dir/".checkpoint")`, `load()→can_resume()→resume_generation()`, orchestrator.py:396/752-763).
2. **Multi-user dashboard** — list/filter tasks & envs by owner / status / name, with strict per-tenant isolation.
3. **Full audit / observability** — every generation attempt is a durable row with resource/cost (ticks, wallclock, $, tokens) and a status-transition history.
4. **Lifecycle state machine** — explicit task states + error/failure detail.

## 3. Entity model (approved: option B — two tables)

- **`Environment`** = the stable thing a user *owns and uses* (serves, chats with, gates). First-class so the user↔env relationship (the db's purpose) stays clean. Lean: identity + ownership + a pointer to the task currently being served.
- **`GenerationTask`** = one row per generation **attempt** (PK = `task_id`), 1:N per env. Holds all per-attempt data (paths, lifecycle, config snapshot, resources, result).

`Run` is superseded by `GenerationTask` → removed. `ChatMessage` kept, `env_id` re-pointed to the new `environments.id`.

## 4. Schema

### `environments`
| field | type | notes |
|---|---|---|
| `id` | str, **PK** | stable uuid (decouples identity from name/dir) |
| `tenant_id` | str, index | owner tenant |
| `created_by` | str | owner user |
| `name` | str | label, e.g. `youtube`; **unique(`tenant_id`, `name`)** |
| `current_task_id` | str, FK→`generation_tasks.task_id`, nullable | the delivered task currently served (the env's "live" version) |
| `archived` | bool, default false | soft-hide from dashboard |
| `created_at` / `updated_at` | datetime(tz) | `updated_at` on-update |

### `generation_tasks`
| group | field | type | notes |
|---|---|---|---|
| identity | `task_id` | str, **PK** | the generation-task id |
| | `env_id` | str, FK→`environments.id`, index | |
| | `tenant_id`, `created_by` | str, index | denormalized for fast per-owner queries + isolation (no join needed) |
| | `name` | str | denormalized env name (display) |
| paths | `project_path` | str | **this attempt's own output dir** (not shared per name) |
| | `state_path` | str | `project_path/.checkpoint` — the resumable state |
| lifecycle | `status` | str enum | see §5 |
| | `status_history_json` | str (JSON) | `[{status, at, reason?}, …]` — audit/lifecycle, no 3rd table |
| | `error` | str, nullable | failure message |
| | `failure_phase` | str, nullable | phase at failure |
| config snapshot | `reference`, `model`, `provider`, `scope`, `requirements` | str | config used for THIS attempt |
| | `gates_json` | str (JSON) | |
| | `max_wallclock_min`, `max_ticks` | int | caps used |
| resources (audit) | `coordination_ticks` | int | |
| | `wallclock_sec` | float | |
| | `cost_usd` | float | |
| | `tokens` | int | |
| result | `delivered` | bool | |
| | `release_version` | str, nullable | |
| time | `created_at` | datetime(tz) | |
| | `started_at`, `finished_at` | datetime(tz), nullable | |
| | `updated_at` | datetime(tz) | on-update |

### Indexes
- `generation_tasks`: `(tenant_id, status)`, `(env_id)`, `(created_by)`, `(created_at)` — dashboard filters + audit scans.
- `environments`: `(tenant_id)`, unique `(tenant_id, name)`.

### `chat_messages`
Unchanged shape; `env_id` now references `environments.id` (uuid) instead of the name.

## 5. Lifecycle state machine

```
queued ──▶ generating ──▶ delivered                  (terminal — success; delivered=true, release_version set)
              │  ├──────▶ failed                       (terminal — error + failure_phase set)
              │  ├──────▶ killed                        (terminal — terminated, checkpoint NOT resumable)
              │  └──────▶ resumable ──▶ generating      (killed/crashed but checkpoint.can_resume())
```
Mapping to the engine (`CheckpointManager`): `running`→`generating`; `complete_generation(success)`→`delivered`; `fail_generation`→`failed`; process killed + `can_resume()`→`resumable`; killed + not resumable→`killed`. Every transition appends `{status, at, reason}` to `status_history_json`.

`Environment.current_task_id` is set to a task only when it reaches `delivered` (the served/live version); a new attempt does not change `current_task_id` until it too delivers.

## 6. Migration (chosen: convert-existing, non-destructive)

The change alters the `Environment` PK type (name→uuid), adds a table, and re-keys FKs — SQLite cannot `ALTER` these in place, so it is a **rebuild + data copy**, run idempotently at `init_db()` (same spirit as today's `_ensure_tenant_columns`):
1. Create new `environments` (new shape) + `generation_tasks`.
2. For each legacy `environments` row: insert a new env (fresh uuid `id`, carry `tenant_id`/`created_by`/`name`) **and** one `generation_tasks` row (`project_path` = legacy `generated_dir`, `state_path` = `generated_dir/.checkpoint`, carry `status`/config/`delivered`); set the env's `current_task_id` to that task iff `delivered`.
3. Re-point `chat_messages.env_id` (legacy name → new uuid).
4. Drop `runs`.
5. Guard idempotently (skip if already migrated, e.g. a `schema_version` marker).

**Fallback (one-line switch):** wipe-and-recreate — the server already rebuilds `environments` by rescanning `ENVS_ROOT` (`app/main.py:80-84`); acceptable since the legacy registry is a small dev artifact with no per-attempt history to lose.

## 7. Population contract (what the writer must do)

The Env Forge server (`app/main.py`) owns writes. On a generate request it MUST:
- allocate a **per-task output dir** (e.g. `ENVS_ROOT/<name>/<task_id>/` or `ENVS_ROOT/<task_id>/`) — **not** the shared `ENVS_ROOT/<name>` — and record it as `project_path` (+ `state_path = project_path/.checkpoint`);
- insert the `generation_tasks` row `status=queued`, spawn the engine with `--output <project_path>`, flip `status=generating`;
- drive `status`/`resources`/`finished_at`/`error` from the engine's checkpoint + process exit; on `delivered`, set `Environment.current_task_id`.

The engine writes state into its `--output` dir (`.checkpoint`, `project.json`, `run_budget.json`, the git tree); the db only stores pointers + metadata (registry-of-pointers principle preserved).

## 8. Scope & downstream impact

**In scope (this spec → its plan):** `app/models.py` (2 tables + ChatMessage re-key, Run removal), `app/db.py` (migration + indexes), and the **population contract** as a requirement.

**Dependent follow-up (separate plan — NOT this spec):** the server/engine rewiring that the per-task-dir convention forces —
- the `env = name = dir` create logic (`app/main.py:144`) and the rescan-sync (`:80-84`) must change to per-task dirs;
- read endpoints that resolve by `generated_dir` must resolve via `current_task.project_path`;
- per-task `--output` wiring on spawn.
These consume the new schema; they are tracked as a follow-up so this change stays reviewable.

**Out of scope:** the `task_events` audit table (deferred — `status_history_json` + resource fields suffice; revisit if per-tick timelines are needed); resume *triggering* UX (the engine already supports resume; surfacing a "resume" action is follow-up).

## 9. Open items
- Per-task dir layout: `ENVS_ROOT/<name>/<task_id>/` (groups by name, nice for the dashboard) vs `ENVS_ROOT/<task_id>/` (flat). Lean: nested-by-name. Decide in the follow-up plan.
