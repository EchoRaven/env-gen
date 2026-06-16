# Per-agent reasoning_effort + live-adjust + remove `think` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Set OpenAI gpt-5 `reasoning_effort` per agent lane (configurable at setup + adjustable live from live_monitor), and delete the redundant custom `think` tool.

**Architecture:** A pure resolution module reads a per-run `reasoning_effort.json` (lane→effort), falling back to per-profile defaults from `agents_config.yaml`. Each agent resolves its effort and passes it per LLM call; the OpenAI client injects `reasoning_effort` into request params **only for gpt-5** (all clients pop the kwarg so non-gpt-5/Anthropic/Gemini never receive it). live_monitor writes the file via a POST endpoint + panel. The `think` tool is removed everywhere.

**Tech Stack:** Python (asyncio), pytest, OpenAI/Anthropic/Google SDK clients in `agent/utils/llm.py`, React live_monitor.

**Interpreter:** `/home/haibotong/miniconda3/envs/dt/bin/python` (alias `PY` below).

**Critical correctness note:** all three clients do `request_params.update(kwargs)` (llm.py:806/1174/1233) — a blind forward. Therefore `reasoning_effort` MUST be `kwargs.pop`'d in each client before that update, and only OpenAI-gpt-5 re-injects it. Never let it reach gpt-4 / Anthropic / Gemini request params.

---

### Task 1: Pure reasoning-effort resolution module

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/reasoning_effort.py`
- Test: `agent/tests/test_reasoning_effort.py`

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_reasoning_effort.py
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path: sys.path.insert(0, p)
from multi_agent.runtime.reasoning_effort import (
    normalize_effort, resolve_effort, read_effort_map, write_effort_map,
    VALID_EFFORTS, DEFAULT_EFFORT,
)

def test_normalize_known_and_unknown():
    assert normalize_effort("high") == "high"
    assert normalize_effort("HIGH") == "high"
    assert normalize_effort("bogus") == DEFAULT_EFFORT  # fail-soft
    assert normalize_effort(None) == DEFAULT_EFFORT
    assert set(VALID_EFFORTS) == {"minimal", "low", "medium", "high"}

def test_write_then_read_roundtrip(tmp_path):
    write_effort_map(tmp_path, {"orchestrator": "high", "knowledge": "low"})
    assert read_effort_map(tmp_path) == {"orchestrator": "high", "knowledge": "low"}

def test_read_missing_file_is_empty(tmp_path):
    assert read_effort_map(tmp_path) == {}

def test_resolve_precedence(tmp_path):
    # file > profile_default > DEFAULT
    write_effort_map(tmp_path, {"design": "minimal"})
    assert resolve_effort(tmp_path, "design", "high") == "minimal"      # file wins
    assert resolve_effort(tmp_path, "backend", "medium") == "medium"    # profile default
    assert resolve_effort(tmp_path, "backend", None) == DEFAULT_EFFORT  # global default
    write_effort_map(tmp_path, {"design": "bogus"})
    assert resolve_effort(tmp_path, "design", "high") == DEFAULT_EFFORT # file value normalized

def test_resolve_rereads_after_change(tmp_path):
    write_effort_map(tmp_path, {"backend": "low"})
    assert resolve_effort(tmp_path, "backend", "high") == "low"
    write_effort_map(tmp_path, {"backend": "high"})
    assert resolve_effort(tmp_path, "backend", "low") == "high"  # mtime re-read picks up change
```

- [ ] **Step 2: Run to verify fail**

Run: `PY -m pytest agent/tests/test_reasoning_effort.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module**

```python
# agent/env_generator/llm_generator/multi_agent/runtime/reasoning_effort.py
"""Pure per-agent reasoning_effort resolution (no LLM, no global state).

Source of truth at runtime: a per-run ``reasoning_effort.json`` (lane -> effort)
in the workspace base_dir, writable live by live_monitor. Falls back to the
agent's per-profile default, then the global DEFAULT_EFFORT.
"""
from __future__ import annotations
import json, logging, os, tempfile
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

VALID_EFFORTS = ("minimal", "low", "medium", "high")
DEFAULT_EFFORT = "medium"
_FILENAME = "reasoning_effort.json"
# mtime cache: {path_str: (mtime, parsed_map)}
_cache: Dict[str, tuple] = {}


def normalize_effort(value: Optional[str]) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_EFFORTS:
        return value.strip().lower()
    if value is not None:
        logger.warning("reasoning_effort: unknown value %r -> %s", value, DEFAULT_EFFORT)
    return DEFAULT_EFFORT


def _path(base_dir) -> Path:
    return Path(base_dir) / _FILENAME


def read_effort_map(base_dir) -> Dict[str, str]:
    path = _path(base_dir)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = str(path)
    cached = _cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    _cache[key] = (mtime, data)
    return data


def write_effort_map(base_dir, mapping: Dict[str, str]) -> None:
    path = _path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({k: str(v) for k, v in mapping.items()}, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def resolve_effort(base_dir, lane: str, profile_default: Optional[str]) -> str:
    file_map = read_effort_map(base_dir)
    if lane in file_map:
        return normalize_effort(file_map[lane])
    if profile_default is not None:
        return normalize_effort(profile_default)
    return DEFAULT_EFFORT
```

- [ ] **Step 4: Run to verify pass**

Run: `PY -m pytest agent/tests/test_reasoning_effort.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/reasoning_effort.py agent/tests/test_reasoning_effort.py
git commit -m "feat(kickoff): pure reasoning_effort resolution module"
```

---

### Task 2: Thread + gate reasoning_effort in the LLM clients

**Files:**
- Modify: `agent/utils/llm.py` (OpenAIClient.chat ~759-806; AnthropicClient.chat ~1142-1174; GoogleClient.chat ~1212-1233)
- Test: `agent/tests/test_llm_reasoning_effort.py`

- [ ] **Step 1: Write the failing test** (inspect built request params without a live API call)

```python
# agent/tests/test_llm_reasoning_effort.py
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "env_generator" / "llm_generator"), str(ROOT.parent)):
    if p not in sys.path: sys.path.insert(0, p)
import importlib
llm = importlib.import_module("agent.utils.llm")

def _params(model, **kw):
    # build_openai_request_params is a pure helper extracted in Step 3
    return llm.build_openai_request_params(model_name=model, messages=[], **kw)

def test_gpt5_gets_reasoning_effort():
    p = _params("gpt-5.4", reasoning_effort="high")
    assert p.get("reasoning_effort") == "high"

def test_non_gpt5_omits_reasoning_effort():
    p = _params("gpt-4.1", reasoning_effort="high")
    assert "reasoning_effort" not in p

def test_gpt5_without_effort_omits_param():
    p = _params("gpt-5.4", reasoning_effort=None)
    assert "reasoning_effort" not in p
```

- [ ] **Step 2: Run to verify fail**

Run: `PY -m pytest agent/tests/test_llm_reasoning_effort.py -q`
Expected: FAIL (`build_openai_request_params` not defined).

- [ ] **Step 3: Implement** — extract a pure param-builder + pop/gate in each client.

In `OpenAIClient.chat`, BEFORE `request_params.update(kwargs)` (llm.py:806), add:
```python
        reasoning_effort = kwargs.pop("reasoning_effort", None)
```
and AFTER the existing param assembly, gate-inject:
```python
        if reasoning_effort and str(self.config.model_name).startswith("gpt-5"):
            request_params["reasoning_effort"] = str(reasoning_effort)
```
Extract the gate into a module-level pure helper (so it is unit-testable without an API client):
```python
def build_openai_request_params(*, model_name, messages, reasoning_effort=None, **rest):
    params = {"model": model_name, "messages": messages}
    params.update(rest)
    if reasoning_effort and str(model_name).startswith("gpt-5"):
        params["reasoning_effort"] = str(reasoning_effort)
    return params
```
(Use this helper inside `OpenAIClient.chat` to assemble params, or at minimum mirror its gate.)

In `AnthropicClient.chat` and `GoogleClient.chat`, add BEFORE their `request_params.update(kwargs)`:
```python
        kwargs.pop("reasoning_effort", None)  # native thinking not wired for this provider yet
```
This guarantees `reasoning_effort` never reaches a non-gpt-5/Anthropic/Gemini request.

- [ ] **Step 4: Run to verify pass**

Run: `PY -m pytest agent/tests/test_llm_reasoning_effort.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/utils/llm.py agent/tests/test_llm_reasoning_effort.py
git commit -m "feat(llm): thread + gpt-5-gate reasoning_effort; pop it for other providers"
```

---

### Task 3: Per-profile reasoning_effort in agents_config.yaml + agent exposes it

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` (each profile)
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/configurable_agent.py` (read profile → `self.reasoning_effort`)
- Test: `agent/tests/test_profile_reasoning_effort.py`

- [ ] **Step 1: Failing test**

```python
# asserts ConfigurableAgent exposes reasoning_effort from its profile, default 'medium' if absent
# (load orchestrator profile -> 'high'; a profile w/o the field -> 'medium')
```
(Write a test that builds the agent config for `orchestrator` and asserts `agent.reasoning_effort == "high"`, and for a profile without the key asserts `"medium"`, using the existing ConfigurableAgent construction path used by other config tests.)

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Add `reasoning_effort:` to each profile in `agents_config.yaml`:
orchestrator/design/debugger → `high`; backend/frontend/verifier → `medium`; knowledge → `low`;
worker/ephemeral profiles → `medium`. In `configurable_agent.py`, read it:
```python
from ..runtime.reasoning_effort import normalize_effort
self.reasoning_effort = normalize_effort(profile.get("reasoning_effort"))
```
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(config): per-profile reasoning_effort defaults`.

---

### Task 4: Agent resolves + passes effort per LLM call; startup seeds the file

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/base.py` (calls at 760/763)
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/messaging.py:481`
- Modify: orchestrator boot (write defaults file once at startup)
- Test: `agent/tests/test_agent_passes_reasoning_effort.py`

- [ ] **Step 1: Failing test** — with a mock `self.llm.chat_messages`, assert the agent passes
`reasoning_effort` equal to `resolve_effort(base_dir, agent_id, profile_default)`. Construct an agent
with a tmp workspace base_dir, set `self.reasoning_effort="high"`, write `{agent_id:"low"}` to the
file, call the agentic step, assert `chat_messages` received `reasoning_effort="low"` (file wins).

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** At each `self.llm.chat_messages(...)` site, resolve + pass:
```python
from ..runtime.reasoning_effort import resolve_effort
_effort = resolve_effort(self.workspace.base_dir, self.agent_id, getattr(self, "reasoning_effort", None))
response = await self.llm.chat_messages(messages, tools=tools, reasoning_effort=_effort)
```
At orchestrator boot (where `start_kickoff` is invoked / agents spawned), seed defaults once:
```python
from .runtime.reasoning_effort import write_effort_map, read_effort_map
if not read_effort_map(base_dir):
    write_effort_map(base_dir, {lane: spec.reasoning_effort for lane, spec in resident_specs.items()})
```
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(agents): resolve + pass per-call reasoning_effort; seed defaults at boot`.

---

### Task 5: live_monitor POST endpoint + panel ("the button")

**Files:**
- Modify: `agent/env_generator/llm_generator/live_monitor_server.py` (POST `/api/projects/<id>/reasoning_effort`)
- Modify: `agent/env_generator/llm_generator/live_monitor/src/` (panel: per-lane dropdowns + global setter → POST)
- Test: `agent/tests/test_live_monitor_reasoning_effort_endpoint.py`

- [ ] **Step 1: Failing test (server-side)** — POST body `{"backend":"high"}` to the handler →
`reasoning_effort.json` in the project workspace now has `backend=high`; body `{"all":"low"}` sets every
resident lane to low. Use the existing live_monitor endpoint test pattern (call the handler function
directly with a tmp workspace, like `set_project_status_call` tests).

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Add `set_reasoning_effort_call(workspaces_root, project_id, body)` mirroring
`set_project_status_call` (llm.py live_monitor_server.py:1758): resolve workspace base_dir, then
`write_effort_map(base_dir, merged)` where `{"all": e}` expands to every resident lane and `{lane: e}`
merges into the current map (read-modify-write via `read_effort_map`). Wire the route. Add the React panel:
a small control listing lanes with a `<select>` (minimal/low/medium/high) each + a global "set all",
POSTing to the endpoint. Follow the existing hub_panels.jsx control/POST conventions.

- [ ] **Step 4:** Run → PASS (server test). Babel-parse the jsx (`npx babel --presets ... hub_panels.jsx` or the repo's existing parse check) to confirm no syntax error.
- [ ] **Step 5:** Commit `feat(live_monitor): live reasoning_effort control endpoint + panel`.

---

### Task 6: Remove the `think` tool everywhere (no shim)

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/reasoning_tools.py` (delete `ThinkTool` class :23, export :2631)
- Modify: `agent/env_generator/llm_generator/tools/__init__.py` (imports :20,:102; instance :402; export :525)
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/tooling.py` (:510 special-case, :614 quiet_tools)
- Modify: v3 prompts referencing `think` (orchestrator ×6, design)
- Delete/adjust: any test asserting `think` presence
- Test: `agent/tests/test_think_tool_removed.py`

- [ ] **Step 1: Failing absence-pin test**

```python
# agent/tests/test_think_tool_removed.py
import sys, glob
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path: sys.path.insert(0, p)

def test_no_thinktool_symbol():
    import tools as tools_pkg
    assert not hasattr(tools_pkg, "ThinkTool")

def test_think_not_in_v3_prompts():
    bad = []
    for f in glob.glob(str(SRC / "multi_agent/prompts/v3/*.j2")):
        txt = Path(f).read_text()
        # the tool call/name, not the english word — match think( or "think"
        if "think(" in txt or '"think"' in txt or "'think'" in txt:
            bad.append(f)
    assert bad == [], f"stale think tool refs: {bad}"
```

- [ ] **Step 2:** Run → FAIL (ThinkTool still exported / prompts still ref think).

- [ ] **Step 3:** Delete `ThinkTool` class + its `__all__`/exports in `reasoning_tools.py`; remove the
import + the `ThinkTool()` instance + export in `tools/__init__.py:20,102,402,525`; remove the
`if tool_name == "think":` block in `tooling.py:510` and `"think"` from the `quiet_tools` set at :614;
remove `think` from the orchestrator + design v3 prompts (replace any "call think first" guidance with
nothing — the model reasons natively now). Delete any test asserting `think` is present.

- [ ] **Step 4:** Run → PASS. Then run the roster invariant + a smoke-import:
`PY -m pytest agent/tests/test_think_tool_removed.py agent/tests/test_roster_consistency_invariant.py -q`
Expected: PASS.

- [ ] **Step 5:** Commit `refactor: remove redundant think tool (native reasoning replaces it)`.

---

### Task 7: Full-suite + integration verification

- [ ] **Step 1:** `PY -m pytest agent/tests/ -q -p no:cacheprovider` — expect green (≈2110 + new tests, 0 failed).
- [ ] **Step 2:** Guardrail re-probe: inject a bare-form phantom into a throwaway tool, run the roster invariant, confirm RED, remove. Confirm git clean of probe files.
- [ ] **Step 3:** Sanity: grep the tree for any remaining `reasoning_effort` mis-wiring (it must NOT appear in Anthropic/Google request bodies) and any residual `think` tool reference outside docs/historical.
- [ ] **Step 4:** Hand back to the supervision loop (it will review this like any round; note the change in `docs/refactor_review.md`).

---

## Self-review
- **Spec coverage:** §1 config→Task 3; §2 threading→Task 2; §3 live-adjust file+endpoint→Tasks 1,4,5; §4 delete think→Task 6; §5 tests→each task + Task 7. ✓
- **Placeholder scan:** Tasks 3/4/5 describe tests in prose rather than full code (the construction path depends on existing config-test/endpoint-test helpers in the repo) — acceptable as they reference concrete existing patterns (`set_project_status_call` tests, ConfigurableAgent config tests); fill the exact harness from the sibling test when implementing. Tasks 1/2/6 (the tricky correctness) have complete code. ✓
- **Type consistency:** `resolve_effort(base_dir, lane, profile_default)`, `read_effort_map`/`write_effort_map(base_dir, map)`, `normalize_effort`, `VALID_EFFORTS`/`DEFAULT_EFFORT` used consistently across Tasks 1/4/5. `reasoning_effort` kwarg name consistent across Tasks 2/4. ✓
