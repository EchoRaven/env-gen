# Hub-Consistency Finish-Gate Implementation Plan (Phase A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (this plan is single-developer inline). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `finish()` refuse to succeed when an agent has written code but failed to register the corresponding entries in APIHub/CodeHub — closing the loop between "wrote a route file" and "the rest of the team can see this endpoint exists."

**Architecture:** Add a new `BaseWorkflowPolicy` subclass `HubConsistencyPolicy` that runs at `finish()` time. The policy compares two things: (a) what the agent has materially changed this session — counted from `files_created` + `files_modified` already passed to `handle_finish` — and (b) what is registered in the relevant hubs (apihub_endpoints, apihub_tables, workhub_pages, codehub_commits). If a gap exists, the policy intercepts the finish, injects a structured "blocked" message listing exactly which calls are missing, and returns `{"action": "continue"}` so the agent runs again. No prompt rewording, no soft instructions — a hard gate at the only point that matters (the agent's attempted exit).

**Tech Stack:** Python `BaseWorkflowPolicy` (multi_agent/workflow_policies.py), yaml profile config (multi_agent/agents/agents_config.yaml), existing apihub/codehub stores via `agent._hubs`.

**Non-goals (Phase A):** pre-write declaration tools, peer review on declarations, automatic PR creation, write-tool decoration. Those are Phase B+C — proven design but bigger scope, deferred until Phase A behavior is validated on a real run.

**Why finish() is the right insertion point:**
1. It's the agent's natural exit boundary — the moment they commit (mentally) to "I'm done."
2. The existing `FinishContinuePolicy` already proves the pattern: intercept `finish`, push a follow-up message, return `continue`.
3. The agent's most recent context will be the **policy's rejection message** — a much stronger signal than a system-prompt mention buried 20k tokens up.
4. Once the loop runs once with the gate biting, the agent learns the pattern for the rest of the session (and across sessions if knowledge agent stores it).

---

## File Structure

**Modify:**
- `multi_agent/workflow_policies.py` — add `HubConsistencyPolicy` class + factory branch
- `multi_agent/agents/agents_config.yaml` — add `workflow_policies` entries for design, database, backend, frontend
- `multi_agent/agents/runtime/messaging.py` — track session-start timestamp (used to count "commits since session started") if not already tracked

**Create:**
- `agent/tests/test_hub_consistency_policy.py` — TDD coverage for each gate

**Don't touch:** the hub stores themselves, the existing apihub/codehub tools, the FinishTool implementation. The gate sits cleanly above them.

---

## Decisions locked in

| Decision | Value | Rationale |
|---|---|---|
| Where the gate lives | `BaseWorkflowPolicy.handle_finish` (existing extension point) | Pattern already exists, matches `FinishContinuePolicy` |
| When the gate fires | `finish` tool only | `deliver_project` already has its own end-of-line gates |
| Gate decision shape | `{"action": "continue"}` + injected user message | Same shape as `FinishContinuePolicy`, agent loops back |
| What counts as "evidence of code change" | `files_created` + `files_modified` (already passed) | Avoids re-scanning filesystem; uses existing book-keeping |
| Per-agent expectations | YAML-driven (`expect_hub_kinds`) | Different roles care about different hubs |
| Failure verbosity | Up to 12 missing items listed in the message | Long enough to be useful, short enough not to balloon context |
| Codehub commit threshold | `commits_seen_session_start <= 0 AND modifications > 5` → block | Allows the very first session step to finish; bites after real work |

## Per-agent gate matrix

| Agent profile | `expect_hub_kinds` | Block when |
|---|---|---|
| `design` | `apihub_endpoints, apihub_tables, workhub_pages` | wrote `design/spec.*.json` but corresponding hub count is 0 |
| `database` | `apihub_tables, codehub_commits` | wrote `*.sql` or migration files but 0 tables registered, OR 0 commits |
| `backend` | `apihub_endpoints, codehub_commits` | wrote files under `*/routes/`, `*/controllers/`, `*/handlers/` but 0 endpoints registered, OR 0 commits |
| `frontend` | `workhub_pages, codehub_commits` | wrote `*.jsx`/`*.tsx`/`*.vue` page files but 0 pages registered, OR 0 commits |
| `verifier` | `codehub_commits` (all upstream) | tries to finish but any upstream agent has uncommitted work |
| `orchestrator` | — | no consistency block (orchestrator finishes when delivery is done) |

---

### Task 1: `HubConsistencyPolicy` skeleton + dataclass

**Files:**
- Modify: `multi_agent/workflow_policies.py` (append after `FinishContinuePolicy`)
- Test: `agent/tests/test_hub_consistency_policy.py` (new)

- [ ] **Step 1: Write the failing test for the no-op case**

Save as `agent/tests/test_hub_consistency_policy.py`:

```python
"""HubConsistencyPolicy — Phase A finish-gate tests."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class _StubAgent:
    """Minimal agent stand-in: agent_id, workspace.base_dir, _hubs, _logger."""

    def __init__(self, agent_id, reg, workspace_dir):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self.workspace = MagicMock()
        self.workspace.base_dir = Path(workspace_dir)
        self._hubs = reg
        self._logger = MagicMock()


class TestHubConsistencyPolicyShape(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_returns_none_when_tool_is_not_finish(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(expect_hub_kinds=["apihub_endpoints"], file_patterns=["routes/"])
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="write",  # not finish
                tool_args={},
                tool_call=None,
                tool_call_id="",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(outcome)

    def test_returns_none_when_no_code_evidence(self):
        """If the agent didn't write anything that looks like the gate
        target, the policy must not block."""
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["apihub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p2", project_name="P2")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=None,
                tool_call_id="",
                messages=[],
                files_created=["docs/notes.md"],   # not a route file
                files_modified=[],
            ))
            self.assertIsNone(outcome)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — should fail with ImportError**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py -v`

Expected: FAIL — `ImportError: cannot import name 'HubConsistencyPolicy' from 'multi_agent.workflow_policies'`

- [ ] **Step 3: Add the policy class skeleton**

Append to `multi_agent/workflow_policies.py`:

```python
class HubConsistencyPolicy(BaseWorkflowPolicy):
    """Block ``finish()`` when the agent has written code without
    registering the corresponding entries in the relevant hubs.

    Parameters
    ----------
    expect_hub_kinds:
        Which hub stores the agent is expected to populate. Each entry
        is one of the strings checked by :meth:`_count_hub_entries`:
        ``apihub_endpoints``, ``apihub_tables``, ``workhub_pages``,
        ``codehub_commits``.
    file_patterns:
        Substrings that, if present in a created/modified file path,
        count as "evidence the agent wrote code in the relevant area".
        E.g. ``["routes/", "controllers/", "handlers/"]`` for backend.
        At least one match → the hub-count check must pass; zero
        matches → the gate is a no-op for this finish.
    min_modifications_for_codehub:
        Threshold for the ``codehub_commits`` check — we don't punish
        an agent for finishing after a single trivial write. Default
        5 (matches "real work happened" heuristic).
    """

    def __init__(
        self,
        *,
        expect_hub_kinds: List[str],
        file_patterns: List[str],
        min_modifications_for_codehub: int = 5,
    ):
        self.expect_hub_kinds = [str(k).strip() for k in (expect_hub_kinds or []) if str(k).strip()]
        self.file_patterns = [str(p).strip() for p in (file_patterns or []) if str(p).strip()]
        self.min_modifications_for_codehub = int(min_modifications_for_codehub)

    async def handle_finish(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call: Any,
        tool_call_id: str,
        messages: List[Any],
        files_created: List[str],
        files_modified: List[str],
    ) -> Optional[Dict[str, Any]]:
        # Only intercept finish (deliver_project has its own pipeline).
        if tool_name != "finish":
            return None

        touched = list(files_created or []) + list(files_modified or [])
        # No code-area evidence → don't block.
        relevant = [p for p in touched if self._path_matches(p)]
        if not relevant and not files_modified and not files_created:
            return None
        if self.file_patterns and not relevant:
            return None

        # Sample current hub counts for each expected kind.
        gaps: List[str] = []
        for kind in self.expect_hub_kinds:
            count, gap_msg = self._check_hub_kind(
                agent=agent,
                kind=kind,
                touched=touched,
                relevant=relevant,
                modifications=len(files_modified or []) + len(files_created or []),
            )
            if gap_msg:
                gaps.append(gap_msg)

        if not gaps:
            return None

        # Build the rejection message — short, structured, actionable.
        bullet = "\n".join(f"- {g}" for g in gaps[:12])
        block_text = (
            "🚫 finish() blocked by hub-consistency gate.\n\n"
            "Before you can finish, the following must be reconciled:\n"
            f"{bullet}\n\n"
            "Take the listed actions, then call finish() again."
        )
        messages.append(Message.assistant(tool_calls=[tool_call]))
        messages.append(Message.tool(block_text, tool_call_id))
        messages.append(Message.user(
            "Hub-consistency gate fired. Address every item above. "
            "Do not summarize — execute the missing register/commit calls."
        ))
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] finish blocked by hub-consistency: {len(gaps)} gap(s)"
            )
        except Exception:
            pass
        return {"action": "continue"}

    def _path_matches(self, path: str) -> bool:
        if not self.file_patterns:
            return True
        p = str(path or "")
        return any(pat in p for pat in self.file_patterns)

    def _check_hub_kind(
        self,
        *,
        agent: Any,
        kind: str,
        touched: List[str],
        relevant: List[str],
        modifications: int,
    ) -> Tuple[int, Optional[str]]:
        """Return (current_count, gap_message_or_None)."""
        hubs = getattr(agent, "_hubs", None)
        if hubs is None:
            return 0, None

        if kind == "apihub_endpoints":
            store = getattr(hubs.apihub, "_endpoints", None)
            count = self._store_count(store)
            if relevant and count == 0:
                return 0, (
                    f"APIHub has 0 endpoints registered, but you've written "
                    f"{len(relevant)} route/controller file(s). Call "
                    f"`apihub_register_endpoint(method=..., path=..., schema=..., status='implemented')` "
                    f"for each route you implemented."
                )
            return count, None

        if kind == "apihub_tables":
            store = getattr(hubs.apihub, "_tables", None)
            count = self._store_count(store)
            if relevant and count == 0:
                return 0, (
                    f"APIHub has 0 tables registered, but you've written "
                    f"{len(relevant)} schema/migration file(s). Call "
                    f"`apihub_register_table(name=..., columns=...)` for "
                    f"each table you created."
                )
            return count, None

        if kind == "workhub_pages":
            store = getattr(hubs.workhub, "_pages", None)
            count = self._store_count(store)
            if relevant and count == 0:
                return 0, (
                    f"WorkHub has 0 pages registered, but you've written "
                    f"{len(relevant)} page file(s). Call "
                    f"`workhub_update_page(name=..., path=..., status='defined', components=[...])` "
                    f"for each page."
                )
            return count, None

        if kind == "codehub_commits":
            store = getattr(hubs.codehub, "_commits", None)
            count = self._store_count(store)
            if modifications >= self.min_modifications_for_codehub and count == 0:
                return 0, (
                    f"CodeHub shows 0 commits, but you've changed "
                    f"{modifications} file(s) this session. Call "
                    f"`codehub_commit(message=..., files=[...])` to record "
                    f"your work so other agents (and the verifier) can see it."
                )
            return count, None

        # Unknown kind — silently ignore so misconfig in yaml doesn't crash finish.
        return 0, None

    @staticmethod
    def _store_count(store: Any) -> int:
        """Count non-bookkeeping entries in a JsonStore-backed dict."""
        if store is None:
            return 0
        try:
            value = store.value() if hasattr(store, "value") else dict(store)
        except Exception:
            return 0
        if not isinstance(value, dict):
            return 0
        return sum(1 for k in value if not str(k).startswith("_"))
```

- [ ] **Step 4: Run test — should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py -v`

Expected: PASS — both no-op tests green.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/workflow_policies.py agent/tests/test_hub_consistency_policy.py
git commit -m "workflow_policies: add HubConsistencyPolicy skeleton (no-op cases)"
```

---

### Task 2: APIHub endpoints gate

**Files:**
- Test: `agent/tests/test_hub_consistency_policy.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `test_hub_consistency_policy.py`:

```python
class TestApihubEndpointsGate(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_when_routes_written_but_no_endpoints_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        from utils.llm import Message
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["apihub_endpoints"],
            file_patterns=["routes/", "controllers/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            tool_call = MagicMock()
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "all routes done"},
                tool_call=tool_call,
                tool_call_id="tc1",
                messages=messages,
                files_created=["app/backend/src/routes/auth.js", "app/backend/src/routes/feed.js"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            # Messages list should now have: assistant-toolcall, tool-result (block text), user follow-up
            self.assertEqual(len(messages), 3)
            tool_msg_text = str(messages[1].content)
            self.assertIn("apihub_register_endpoint", tool_msg_text)
            self.assertIn("0 endpoints registered", tool_msg_text)

    def test_passes_when_at_least_one_endpoint_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["apihub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # Manually seed one endpoint so the gate sees > 0.
            reg.apihub._endpoints.set(
                "POST /api/auth/login",
                {"method": "POST", "path": "/api/auth/login", "status": "implemented"},
                agent="backend",
            )
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "ok"},
                tool_call=MagicMock(),
                tool_call_id="tc1",
                messages=[],
                files_created=["app/backend/src/routes/auth.js"],
                files_modified=[],
            ))
            self.assertIsNone(outcome)
```

- [ ] **Step 2: Run — should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py::TestApihubEndpointsGate -v`

Expected: PASS — both endpoint tests green. (The implementation from Task 1 already handles `apihub_endpoints`; Task 2's only purpose is to *prove* it with tests.)

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_hub_consistency_policy.py
git commit -m "tests: cover HubConsistencyPolicy apihub_endpoints gate"
```

---

### Task 3: APIHub tables + WorkHub pages gates

**Files:**
- Test: `agent/tests/test_hub_consistency_policy.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestApihubTablesAndPagesGates(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_when_schema_written_but_no_tables_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["apihub_tables"],
            file_patterns=[".sql", "migration"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("database", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "schema in"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=["app/database/init/01_schema.sql"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("apihub_register_table", str(messages[1].content))

    def test_blocks_when_pages_written_but_workhub_pages_empty(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["workhub_pages"],
            file_patterns=[".jsx", ".tsx", ".vue"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("frontend", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "ui done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=[
                    "app/frontend/src/pages/Login.jsx",
                    "app/frontend/src/pages/Home.jsx",
                ],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("workhub_update_page", str(messages[1].content))
```

- [ ] **Step 2: Run — should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py::TestApihubTablesAndPagesGates -v`

Expected: PASS — both pass (Task 1's implementation already handles `apihub_tables` and `workhub_pages`).

If FAIL with `'HubRegistry' object has no attribute 'workhub' / '_pages'` — read `hub_registry.py` and update the policy's attribute path to the real one (search for `pages` in workhub service). The plan binds to whatever name the existing store uses; do not invent a new one.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_hub_consistency_policy.py
git commit -m "tests: cover HubConsistencyPolicy tables + pages gates"
```

---

### Task 4: CodeHub commits gate

**Files:**
- Test: `agent/tests/test_hub_consistency_policy.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestCodehubCommitsGate(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_finish_when_many_writes_zero_commits(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["codehub_commits"],
            file_patterns=[],   # any file counts
            min_modifications_for_codehub=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=[f"app/backend/file{i}.js" for i in range(6)],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("codehub_commit", str(messages[1].content))

    def test_passes_below_threshold_even_with_zero_commits(self):
        """Three trivial edits and finish() shouldn't trigger the gate."""
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["codehub_commits"],
            file_patterns=[],
            min_modifications_for_codehub=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "tiny tweak"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["a", "b"],
                files_modified=["c"],
            ))
            self.assertIsNone(outcome)
```

- [ ] **Step 2: Run — should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py::TestCodehubCommitsGate -v`

Expected: PASS — both green.

Common failure: `'HubRegistry' has no attribute 'codehub'` or `codehub` exposes commits under a different attribute. Read `multi_agent/runtime/hubs/codehub/` and bind to the real name (e.g. `_commits` vs `commits` vs `commit_store`). Update both the policy and the test fixture accordingly.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_hub_consistency_policy.py
git commit -m "tests: cover HubConsistencyPolicy codehub_commits gate"
```

---

### Task 5: Factory wiring in `create_workflow_policies`

**Files:**
- Modify: `multi_agent/workflow_policies.py:152-189` (factory function)
- Test: `agent/tests/test_hub_consistency_policy.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestHubConsistencyFactoryWiring(unittest.TestCase):
    def test_factory_builds_policy_from_yaml_shaped_dict(self):
        from multi_agent.workflow_policies import (
            create_workflow_policies,
            HubConsistencyPolicy,
        )
        cfg = {
            "workflow_policies": [
                {
                    "kind": "hub_consistency_gate",
                    "expect_hub_kinds": ["apihub_endpoints", "codehub_commits"],
                    "file_patterns": ["routes/", "controllers/"],
                    "min_modifications_for_codehub": 5,
                },
            ],
        }
        policies = create_workflow_policies(cfg)
        matching = [p for p in policies if isinstance(p, HubConsistencyPolicy)]
        self.assertEqual(len(matching), 1)
        p = matching[0]
        self.assertEqual(p.expect_hub_kinds, ["apihub_endpoints", "codehub_commits"])
        self.assertIn("routes/", p.file_patterns)
        self.assertEqual(p.min_modifications_for_codehub, 5)

    def test_factory_raises_on_unknown_kind(self):
        from multi_agent.workflow_policies import create_workflow_policies
        with self.assertRaises(ValueError):
            create_workflow_policies({
                "workflow_policies": [{"kind": "nonsense_gate"}],
            })
```

- [ ] **Step 2: Run — should fail**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py::TestHubConsistencyFactoryWiring -v`

Expected: FAIL on first test — `ValueError: Unknown workflow policy kind: hub_consistency_gate` (the factory rejects unknown kinds; until we add the branch, this is the failure mode).

- [ ] **Step 3: Add the factory branch**

In `multi_agent/workflow_policies.py`, locate the `elif kind == "finish_continue":` block (~line 175) and add directly after:

```python
        elif kind == "hub_consistency_gate":
            policies.append(
                HubConsistencyPolicy(
                    expect_hub_kinds=list(raw.get("expect_hub_kinds") or []),
                    file_patterns=list(raw.get("file_patterns") or []),
                    min_modifications_for_codehub=int(
                        raw.get("min_modifications_for_codehub", 5)
                    ),
                )
            )
```

(Order matters only for readability — keep it next to the other policy branches. The terminal `elif kind:` raise-on-unknown stays unchanged.)

- [ ] **Step 4: Run — should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_policy.py -v`

Expected: PASS — all tests across the file green.

- [ ] **Step 5: Commit**

```bash
git add multi_agent/workflow_policies.py agent/tests/test_hub_consistency_policy.py
git commit -m "workflow_policies: wire hub_consistency_gate kind into factory"
```

---

### Task 6: YAML — attach gates to design/database/backend/frontend

**Files:**
- Modify: `multi_agent/agents/agents_config.yaml`
- Test: `agent/tests/test_agents_config_stages.py` (extend with a quick assertion)

- [ ] **Step 1: Write the failing test**

Append at the bottom of `agent/tests/test_agents_config_stages.py`:

```python
class TestHubConsistencyGatesInConfig(unittest.TestCase):
    def test_each_implementer_profile_has_hub_consistency_gate(self):
        import yaml
        from pathlib import Path
        cfg_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        cfg = yaml.safe_load(cfg_path.read_text())
        profiles = cfg["profiles"]
        for role in ("design", "database", "backend", "frontend"):
            kinds = [
                str((p or {}).get("kind", ""))
                for p in (profiles[role].get("workflow_policies") or [])
            ]
            self.assertIn(
                "hub_consistency_gate", kinds,
                f"{role} profile is missing hub_consistency_gate "
                f"(workflow_policies={kinds})",
            )
```

- [ ] **Step 2: Run — should fail**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_agents_config_stages.py::TestHubConsistencyGatesInConfig -v`

Expected: FAIL — every implementer role missing the new policy.

- [ ] **Step 3: Add the gates to yaml**

In `multi_agent/agents/agents_config.yaml`, add a `workflow_policies` entry to each of the four roles. For each role, locate the existing `workflow_policies:` line (or create one immediately before `execution_pipeline:`). Append the gate config:

**design**: insert these lines under `design:` (after the existing `skills:` line, before `execution_pipeline:`):

```yaml
    workflow_policies:
      - kind: hub_consistency_gate
        expect_hub_kinds: [apihub_endpoints, apihub_tables, workhub_pages]
        file_patterns: ["design/spec.api.json", "design/spec.database.json", "design/spec.ui.json"]
        min_modifications_for_codehub: 5
```

**database**: extend its existing `workflow_policies:` (which currently has `implementation_bootstrap`):

```yaml
    workflow_policies:
      - kind: implementation_bootstrap
        allowed_starters: [design, orchestrator]
        required_files:
          - design/spec.database.json
          - design/spec.api.json
          - design/spec.ui.json
      - kind: hub_consistency_gate
        expect_hub_kinds: [apihub_tables, codehub_commits]
        file_patterns: [".sql", "migration", "schema"]
        min_modifications_for_codehub: 3
```

**backend**: append a new `workflow_policies:` block (search for "backend:" header; ensure the entry comes after `skills:` and before `execution_pipeline:`):

```yaml
    workflow_policies:
      - kind: hub_consistency_gate
        expect_hub_kinds: [apihub_endpoints, codehub_commits]
        file_patterns: ["routes/", "controllers/", "handlers/", "src/api/"]
        min_modifications_for_codehub: 5
```

**frontend**: same shape:

```yaml
    workflow_policies:
      - kind: hub_consistency_gate
        expect_hub_kinds: [workhub_pages, codehub_commits]
        file_patterns: [".jsx", ".tsx", ".vue", "pages/", "components/"]
        min_modifications_for_codehub: 5
```

- [ ] **Step 4: Run — yaml-shape test should pass**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_agents_config_stages.py -q`

Expected: PASS — every test in the file green.

- [ ] **Step 5: Smoke — full yaml still parses and policies build**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -c "
import yaml
from multi_agent.workflow_policies import create_workflow_policies
cfg = yaml.safe_load(open('agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml'))
for name in ('design','database','backend','frontend'):
    profile = cfg['profiles'][name]
    ps = create_workflow_policies(profile)
    print(name, ':', [type(p).__name__ for p in ps])
"`

Expected:
```
design : [HubConsistencyPolicy]
database : [ImplementationBootstrapPolicy, HubConsistencyPolicy]
backend : [HubConsistencyPolicy]
frontend : [HubConsistencyPolicy]
```

- [ ] **Step 6: Commit**

```bash
git add multi_agent/agents/agents_config.yaml agent/tests/test_agents_config_stages.py
git commit -m "agents_config: attach hub_consistency_gate to design/database/backend/frontend"
```

---

### Task 7: End-to-end gate integration test

**Files:**
- Test: `agent/tests/test_hub_consistency_finish_e2e.py` (new)

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_hub_consistency_finish_e2e.py`:

```python
"""End-to-end: a real ConfigurableAgent with the backend profile gets its
finish() blocked when the apihub is empty after writing route files."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import (              # noqa: E402
    create_workflow_policies,
    HubConsistencyPolicy,
)


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestBackendProfileBlocksFinishWithEmptyApihub(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_backend_finish_blocked_when_apihub_empty(self):
        import yaml
        cfg_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        cfg = yaml.safe_load(cfg_path.read_text())
        backend_cfg = cfg["profiles"]["backend"]
        policies = create_workflow_policies(backend_cfg)
        gate = next(p for p in policies if isinstance(p, HubConsistencyPolicy))

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")

            class Stub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _logger = MagicMock()
                def __init__(self):
                    self.workspace = MagicMock()
                    self.workspace.base_dir = Path(tmp)

            agent = Stub()
            messages = []
            outcome = asyncio.run(gate.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "backend done"},
                tool_call=MagicMock(),
                tool_call_id="tc1",
                messages=messages,
                files_created=[
                    "app/backend/src/routes/auth.js",
                    "app/backend/src/routes/posts.js",
                    "app/backend/src/routes/feed.js",
                ],
                files_modified=[
                    "app/backend/src/routes/users.js",
                    "app/backend/src/routes/social.js",
                    "app/backend/src/server.js",
                ],
            ))
            # Must be blocked
            self.assertEqual(outcome, {"action": "continue"})
            block_text = str(messages[1].content)
            # Both gaps surface
            self.assertIn("apihub_register_endpoint", block_text)
            self.assertIn("codehub_commit", block_text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — should pass (or surface real hub-attribute issues)**

Run: `cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_consistency_finish_e2e.py -v`

Expected: PASS.

If the test surfaces `AttributeError` on a real hub attribute name (e.g. `_pages` doesn't exist on workhub) — fix the policy's binding to the real attribute and re-run. This is exactly what an integration test is for; do NOT skip the failure.

- [ ] **Step 3: Run the entire chat/hub test suite as a regression sweep**

Run:
```bash
cd /data/common/haibotong/env-gen && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
  agent/tests/test_hub_consistency_policy.py \
  agent/tests/test_hub_consistency_finish_e2e.py \
  agent/tests/test_agents_config_stages.py \
  agent/tests/test_human_chat_mini_loop.py \
  agent/tests/test_human_chat_compression.py \
  agent/tests/test_human_chat_directive_injection.py \
  agent/tests/test_workspace_scoped_agent_logs.py \
  agent/tests/test_eventhub_completeness.py \
  agent/tests/test_human_console.py \
  agent/tests/test_human_console_excludes_chat_steps.py \
  -q
```

Expected: every test passes.

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_hub_consistency_finish_e2e.py
git commit -m "tests: e2e HubConsistencyPolicy gate on backend profile"
```

---

### Task 8: Live-run smoke test

- [ ] **Step 1: Kill the running agent + restart**

```bash
pkill -f "main.py.*facebook-clone"
# Wait ~2 seconds for graceful exit then start a fresh run from the monitor UI.
# (Use the standard run_facebook.sh flow.)
```

- [ ] **Step 2: Drive the run to a finish attempt**

Let the run proceed until backend reaches `finish()`. Watch its log file at
`/tmp/envgen_demo/facebook-clone/.agent_logs/Backend Lead Agent/<latest>.jsonl`.

Expected behaviour: the **first** `finish` attempt by backend should produce a tool result containing the string `🚫 finish() blocked by hub-consistency gate.` and the agent should resume (loop continues), then call `apihub_register_endpoint` for each route and `codehub_commit` for the file changes, then call `finish` again successfully.

- [ ] **Step 3: Verify APIHub populated**

```bash
python3 -c "import json; d=json.load(open('/tmp/envgen_demo/facebook-clone/shared/hubs/apihub_endpoints.json')); print(sum(1 for k in d if not k.startswith('_')), 'endpoints registered')"
```

Expected: > 0 (was 0 before the gate).

- [ ] **Step 4: Verify CodeHub commits exist**

```bash
python3 -c "import json; d=json.load(open('/tmp/envgen_demo/facebook-clone/shared/hubs/codehub_commits.json')); print(sum(1 for k in d if not k.startswith('_')), 'commits recorded')"
```

Expected: > 0.

- [ ] **Step 5: Verify UI shows them**

Refresh the live monitor → APIHub page should list the registered endpoints. CodeHub page should show the commits.

- [ ] **Step 6: Final commit + plan close-out**

If everything is green:

```bash
git add docs/superpowers/plans/2026-05-28-hub-consistency-finish-gate.md
git commit -m "docs: hub-consistency finish-gate plan (Phase A complete)"
```

---

## Self-review

**Spec coverage** (against the user's request):
- ✅ "Hard rule, not prompt" — finish() interception
- ✅ "register API after write" — apihub_endpoints / apihub_tables / workhub_pages gates
- ✅ "Can't see commits/PR in CodeHub" — codehub_commits gate (Phase A); PR gate deferred to Phase B
- ⚠️ "Before-write declaration + peer review" — DEFERRED to Phase B (explicitly out of scope, noted in non-goals)
- ⚠️ "agents see merged code instead of stale worktree" — DEFERRED to Phase B/C

This matches the user's "Phase A first" instruction; Phase B will build on the gates the user has actually seen work.

**Placeholder scan:**
- No "TBD", "implement later", "appropriate error handling" — every step has runnable code
- Every test case includes the actual assertions
- Every code block is the literal text to add

**Type consistency:**
- `expect_hub_kinds: List[str]`, `file_patterns: List[str]`, `min_modifications_for_codehub: int` — same in test, class, factory, yaml
- `handle_finish` return type matches `BaseWorkflowPolicy`'s contract (`Optional[Dict[str, Any]]`)
- Hub store access via `hubs.apihub._endpoints`, `.tables`, `hubs.workhub._pages`, `hubs.codehub._commits` — to be verified against real attribute names in Task 3/4 (the plan notes both: "if the test fails on attribute name, read the hub service to bind to the real name")

**Known risk:** The exact attribute names on `apihub`, `workhub`, `codehub` services (`_endpoints` vs `endpoints` vs `_endpoint_store`) are something the test will surface. The plan explicitly notes this and points the engineer at how to fix.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-hub-consistency-finish-gate.md`. Two execution options:

1. **Subagent-Driven (recommended for fresh agents)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute tasks in this session with checkpoints

Which approach?
