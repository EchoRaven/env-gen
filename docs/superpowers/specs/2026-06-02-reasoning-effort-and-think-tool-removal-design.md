# Design — Per-agent `reasoning_effort` + live-adjust + remove the `think` tool

**Date:** 2026-06-02
**Author:** reviewer/supervisor (implementing per user direction)
**Status:** approved (design), pre-implementation

## Goal
Use the LLM providers' **native reasoning** instead of a custom reasoning-externalizer tool.
Concretely: (1) set OpenAI gpt-5 `reasoning_effort` per agent lane at project setup, (2) allow
live (mid-run) adjustment from live_monitor like Claude Code's reasoning control, (3) delete the
redundant custom `think` tool. The configured model is `gpt-5.4` (a reasoning model); today we set
no `reasoning_effort` (only the `max_completion_tokens` param-name switch at `llm.py:784`) and every
agent carries a pure-echo `think` tool — so we neither tune native reasoning nor avoid the wasted
tool-call round-trip. This fixes both.

## Non-goals (YAGNI)
- Anthropic extended-thinking / Gemini `thinking_config` enablement — out of scope; the per-call
  param plumbing is built provider-extensibly but only gpt-5 `reasoning_effort` is wired now.
- Removing `plan` / `get_time` / `wait` — only `think` is the redundant reasoning-externalizer.

## Components

### 1. Config home (project setup)
- New per-profile field `reasoning_effort` in `agents_config.yaml`. Defaults (tunable live):
  orchestrator=`high`, design=`high`, debugger=`high`, backend=`medium`, frontend=`medium`,
  verifier=`medium`, knowledge=`low`. Worker/ephemeral profiles inherit `medium` unless set.
- Allowed values: `minimal` | `low` | `medium` | `high` (gpt-5 set). Unknown → fall back to `medium`
  with a logged warning (fail-soft, never break agent init).

### 2. Per-call threading (one shared LLM instance)
- The LLM is a single shared instance; agents call `self.llm.chat_messages(messages, tools=...)`
  (base.py:760/763). So effort rides **per call**:
  - Agent resolves its current effort (see §3) and passes `reasoning_effort=<effort>` to
    `chat_messages`.
  - `chat_messages` → `chat` forwards it into `request_params["reasoning_effort"]` **only when**
    `model_name.startswith("gpt-5")` (reuse the existing reasoning-model gate near llm.py:783-784).
    Non-gpt-5 / Anthropic / Gemini: param omitted (safe no-op, extensible later).

### 3. Live-adjust control channel
- The generation process and live_monitor are **separate processes sharing the run filesystem**, so
  the control channel is a per-run **`<workspace>/reasoning_effort.json`** (`{lane: effort}`):
  - **Startup:** orchestrator writes profile defaults into this file once.
  - **Read:** each agent, before an LLM call, resolves effort = `file[lane]` (mtime-cached read;
    re-read only when mtime changes) → falls back to its profile default → `medium`.
  - **Write (the "button"):** live_monitor gains `POST /api/projects/<id>/reasoning_effort`
    (body `{lane: effort}` or `{all: effort}`) that writes the file; a small panel renders per-lane
    dropdowns + a global setter. The running gen picks it up on its next LLM call.
  - No IPC / no HTTP server on the gen; fits the existing live_monitor POST-control pattern.

### 4. Remove the `think` tool
- Delete `ThinkTool` from `reasoning_tools.py` + its factory/bundle registration + references in v3
  prompts (orchestrator ×6, design) + its tests. No back-compat shim (delete-don't-skip).

## Testing (closed-by-construction)
1. gpt-5 chat call includes `reasoning_effort` resolved from the lane's config; a non-gpt-5 model
   omits it.
2. Writing `reasoning_effort.json` mid-run changes the effort a lane sends on its next call
   (mtime re-read works).
3. Unknown effort value → falls back to `medium` + warns (no crash).
4. `think`-absence pin: no `ThinkTool` symbol, no `think` in any tool bundle, no `think(` in v3
   prompts.
5. Roster-consistency invariant + full suite stay green.

## Sequencing & coordination
- Lands in the same uncommitted working tree the implementer uses for 8d (rounds 5–8c +
  orphaned facilitate.py all uncommitted). Per user choice, this lands **before 8d**, so the 8d M1
  smoke runs on the intended reasoning config (no point baselining the `think` tool we're deleting).
- The existing uncommitted pile is NOT committed by this work (user's explicit call); recommend
  committing soon — the pile is large and at-risk.
- The supervision loop will verify this change like any round; the orphaned-facilitate watch stays.

## Files touched (estimate)
- `agent/utils/llm.py` (chat/chat_messages: thread + gate reasoning_effort)
- `multi_agent/agents/agents_config.yaml` (per-profile reasoning_effort)
- `multi_agent/agents/base.py` (+ runtime/messaging.py): resolve effort, pass per call
- new `multi_agent/runtime/reasoning_effort.py` (or similar): read/write the per-run file + resolution
- `live_monitor_server.py` (POST endpoint) + `live_monitor/src/*` (panel)
- `tools/reasoning_tools.py` + `tool_bundles.py` + v3 prompts + tests (delete think)
- new tests (5 above)
