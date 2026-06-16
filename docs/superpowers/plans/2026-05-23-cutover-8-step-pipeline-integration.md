# Cutover 8 — Step Pipeline Integration (`hub_pulse` + `hub_commit_gate`)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Wire two new code-forced stages into every agent's step pipeline. `hub_pulse` at step START pulls each agent's view of the 4 hubs + MessageBus and injects it into the LLM prompt. `hub_commit_gate` at step END scans for loose ends (uncommitted edits, stale claimed tasks, unhandled breaking changes) and rolls them forward to the next step. Both stages cannot be disabled via `agents_config.yaml` — the engine forces them.

**Architecture:** Two new modules (`hub_pulse.py`, `commit_gate.py`) + new CodeHub helpers (`get_branch_status`, `list_prs_needing_review`, `get_pending_reviews_for`, `get_my_branch_loose_ends`) + step_runner integration. Replaces the dead `inbox_status` / `crdt_changes` / `crdt_sync` stages whose CRDT references were stripped in Cutovers 4-5.

**Tech Stack:** Python 3.11 (`dt` conda env), unittest, existing HubRegistry + step_pipeline infrastructure.

**Source spec:** `docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md` §5 (hub_pulse) + §6 (hub_commit_gate) + §10 (step pipeline changes).

**Out of scope:**
- Real LLM E2E test (defer — requires API keys, separate verification)
- Pulse-stage caching across consecutive steps (YAGNI for now)
- AST-based registration auto-detection (deferred per Cutover 7 notes)

---

## Pre-Reading

- `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py` lines 79-260 — existing stage loop with `_stage_enabled` gate
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/sync.py:202-260` — `_build_inbox_status_snapshot` / `_build_inbox_status_prompt` pattern to follow
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — existing CodeHub methods
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — `HubRegistry` ctor (used in all test fixtures)
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` lines 21-40 (execution_pipeline_defaults), 110, 146, 187, 235, 282, 343, 376, 419 (per-profile stage lists)

## File Map

**Create:**
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py` — pulse module (~180 LoC)
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/commit_gate.py` — gate module (~150 LoC)
- `agent/tests/test_hub_pulse.py` — pulse tests (~200 LoC)
- `agent/tests/test_commit_gate.py` — gate tests (~180 LoC)
- `agent/tests/test_codehub_branch_helpers.py` — new CodeHub helpers tests (~120 LoC)
- `docs/superpowers/migration-logs/09-step-pipeline-integration.md` — cutover log

**Modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — add 4 new helpers: `get_branch_status`, `list_prs_needing_review`, `get_pending_reviews_for`, `get_my_branch_loose_ends`
- `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py` — replace `inbox_status` + `crdt_changes` with `hub_pulse`; replace `crdt_sync` with `hub_commit_gate`; engine-force both regardless of yaml
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — update 8 profiles' stage lists + `execution_pipeline_defaults.stages` + add `commit_gate:` config section
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — explain pulse + gate
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2`

---

## Phase 0 — Pre-flight

### Task 1: Branch + baseline

- [ ] **Step 1:** Worktree from parent tip

```bash
cd /data/common/haibotong/env-gen
git fetch red-env-gen
git worktree add .worktrees/haibotong-cutover-8-step-pipeline -b haibotong-cutover-8-step-pipeline red-env-gen/haibotong-0521-pipeline-web-tools
cd .worktrees/haibotong-cutover-8-step-pipeline
```

- [ ] **Step 2:** Baseline tests + discover count

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: regressions 7 OK; discover ~312 OK.

- [ ] **Step 3:** Verify current dead-stage references that need removal

```bash
grep -nE "inbox_status|crdt_changes|crdt_sync" agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py | head
```

Note all line numbers — Task 5/6 will rewrite those blocks.

---

## Phase A — New CodeHub Branch / Review Helpers (TDD)

### Task 2: TDD `get_branch_status`, `list_prs_needing_review`, `get_pending_reviews_for`, `get_my_branch_loose_ends`

**Files:**
- Create: `agent/tests/test_codehub_branch_helpers.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1:** Write failing tests

Create `agent/tests/test_codehub_branch_helpers.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CodeHubBranchHelpersTests(unittest.TestCase):
    def _setup_repo(self, td):
        """Real git repo with one agent worktree."""
        hubs = HubRegistry(Path(td))
        ch = hubs.codehub
        ch.ensure_repo()
        ch.register_agent_worktree("backend")
        return hubs, ch

    def test_get_branch_status_returns_clean_for_fresh_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            status = ch.get_branch_status("backend")
            self.assertTrue(status["clean"])
            self.assertEqual(status["dirty_files"], [])
            self.assertEqual(status["commits_ahead_of_main"], 0)

    def test_get_branch_status_detects_dirty(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            wt = ch.repo_root / "workspaces" / "backend"
            (wt / "feature.py").write_text("x = 1\n")
            status = ch.get_branch_status("backend")
            self.assertFalse(status["clean"])
            self.assertIn("feature.py", status["dirty_files"])

    def test_get_branch_status_detects_ahead_count(self):
        with tempfile.TemporaryDirectory() as td:
            _, ch = self._setup_repo(td)
            wt = ch.repo_root / "workspaces" / "backend"
            (wt / "f1.py").write_text("x=1\n")
            ch.commit("backend", message="add f1", files=["f1.py"])
            (wt / "f2.py").write_text("x=2\n")
            ch.commit("backend", message="add f2", files=["f2.py"])
            status = ch.get_branch_status("backend")
            self.assertGreaterEqual(status["commits_ahead_of_main"], 2)
            self.assertTrue(status["clean"])

    def test_get_branch_status_handles_no_repo_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            # No ensure_repo, no worktree
            status = hubs.codehub.get_branch_status("backend")
            self.assertIsInstance(status, dict)
            self.assertIn("clean", status)
            # When no repo, treat as clean / 0 ahead (defensive default)
            self.assertTrue(status["clean"])

    def test_list_prs_needing_review_filters_by_reviewer(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            need_fe = ch.list_prs_needing_review("frontend")
            self.assertEqual(len(need_fe), 1)
            self.assertEqual(need_fe[0]["id"], pr["id"])
            need_db = ch.list_prs_needing_review("database")
            self.assertEqual(need_db, [])

    def test_list_prs_needing_review_excludes_already_decided(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            pr = ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            ch.submit_review(pr["id"], "frontend", "approve")
            # frontend already decided
            need_fe = ch.list_prs_needing_review("frontend")
            self.assertEqual(need_fe, [])
            need_orch = ch.list_prs_needing_review("orchestrator")
            self.assertEqual(len(need_orch), 1)

    def test_get_pending_reviews_for_with_step_age(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            result = ch.get_pending_reviews_for("frontend", since_steps=0)
            self.assertEqual(len(result), 1)
            self.assertIn("pr_id", result[0])

    def test_get_my_branch_loose_ends_aggregates_state(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, ch = self._setup_repo(td)
            wt = ch.repo_root / "workspaces" / "backend"
            (wt / "f1.py").write_text("x=1\n")
            ch.commit("backend", message="add f1", files=["f1.py"])
            loose = ch.get_my_branch_loose_ends("backend")
            self.assertIn("dirty", loose)
            self.assertIn("ahead", loose)
            self.assertIn("has_open_pr", loose)
            self.assertIn("conflict_prs", loose)
            self.assertGreaterEqual(loose["ahead"], 1)
            self.assertFalse(loose["has_open_pr"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm 8 tests FAIL

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_branch_helpers -v 2>&1 | tail -15
```

Expected: failures with `AttributeError: 'CodeHub' object has no attribute 'get_branch_status'` (and similar).

- [ ] **Step 3:** Implement 4 helpers in `runtime/hubs/codehub/service.py`

Find the last method in `CodeHub` (likely `force_merge_pull_request` from Cutover 7). Add these methods after it:

```python
    def get_branch_status(self, agent_id: str) -> dict:
        """Wraps git status + rev-list for the agent's worktree."""
        wt_path = self.repo_root / "workspaces" / agent_id
        if not wt_path.exists() or not (self.repo_root / ".git").exists():
            return {"clean": True, "dirty_files": [],
                    "commits_ahead_of_main": 0, "unpushed_commits": 0}
        try:
            status_out = self.git._run(["status", "--porcelain"], cwd=wt_path)
            dirty_files = []
            for line in (status_out or "").splitlines():
                # Each line is "XY <path>"; we strip the 3-char prefix.
                if len(line) > 3:
                    dirty_files.append(line[3:].strip())
            ahead_out = self.git._run(
                ["rev-list", "--count", "main..HEAD"], cwd=wt_path, check=False
            ).strip() or "0"
            try:
                ahead = int(ahead_out)
            except ValueError:
                ahead = 0
            return {
                "clean": not dirty_files,
                "dirty_files": dirty_files,
                "commits_ahead_of_main": ahead,
                "unpushed_commits": ahead,
            }
        except Exception:
            return {"clean": True, "dirty_files": [],
                    "commits_ahead_of_main": 0, "unpushed_commits": 0}

    def list_prs_needing_review(self, reviewer: str) -> list:
        """PRs where `reviewer` is in pr.reviewers and has not yet submitted a decision."""
        out = []
        reviews = list(self.stores.code_reviews.value().values())
        for pr in self.stores.pull_requests.value().values():
            if pr.get("status") not in (None, "open"):
                continue
            if reviewer not in (pr.get("reviewers") or []):
                continue
            decided = any(
                r.get("reviewer") == reviewer and r.get("pr_id") == pr.get("id")
                for r in reviews
            )
            if decided:
                continue
            out.append(pr)
        return out

    def get_pending_reviews_for(self, agent_id: str, since_steps: int = 0) -> list:
        """Same as list_prs_needing_review but returns lightweight {pr_id, author, files_changed_count, step_age} entries."""
        prs = self.list_prs_needing_review(agent_id)
        result = []
        for pr in prs:
            result.append({
                "pr_id": pr.get("id"),
                "author": pr.get("author"),
                "files_changed_count": len((pr.get("files_changed") or [])),
                "step_age": since_steps,
            })
        return result

    def get_my_branch_loose_ends(self, agent_id: str) -> dict:
        """Compact dict for hub_commit_gate. {dirty, ahead, has_open_pr, conflict_prs}."""
        status = self.get_branch_status(agent_id)
        branch = f"agent/{agent_id}"
        my_open_prs = [
            pr for pr in self.stores.pull_requests.value().values()
            if pr.get("author") == agent_id
            and pr.get("status") in (None, "open")
            and pr.get("source_branch") == branch
        ]
        conflict_prs = [
            pr.get("id") for pr in self.stores.pull_requests.value().values()
            if pr.get("author") == agent_id and pr.get("status") == "conflict"
        ]
        return {
            "dirty": not status["clean"],
            "ahead": status["commits_ahead_of_main"],
            "has_open_pr": bool(my_open_prs),
            "conflict_prs": conflict_prs,
        }
```

- [ ] **Step 4:** Run tests, confirm 8 PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_branch_helpers -v 2>&1 | tail -15
```

- [ ] **Step 5:** Run regressions to ensure nothing else broke

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_git_ops agent.tests.test_codehub_worktree agent.tests.test_hub_architecture 2>&1 | tail -3
```

- [ ] **Step 6:** Commit

```bash
git add agent/tests/test_codehub_branch_helpers.py \
        agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
git commit -m "CodeHub: add get_branch_status / list_prs_needing_review / get_pending_reviews_for / get_my_branch_loose_ends"
```

---

## Phase B — `hub_pulse` Module (TDD)

### Task 3: TDD `hub_pulse.collect` + `build_prompt` + `should_render`

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`
- Create: `agent/tests/test_hub_pulse.py`

- [ ] **Step 1:** Write failing tests

Create `agent/tests/test_hub_pulse.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import (  # noqa: E402
    collect_hub_pulse,
    build_hub_pulse_prompt,
    should_render,
)


class HubPulseCollectTests(unittest.TestCase):
    def test_collect_empty_state_returns_dict_with_4_hubs(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertIn("codehub", pulse)
            self.assertIn("apihub", pulse)
            self.assertIn("workhub", pulse)
            self.assertIn("eventhub", pulse)

    def test_collect_codehub_my_open_prs(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend", agent="orchestrator")
            ch.open_pull_request(
                branch="agent/backend",
                reviewers=["frontend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="backend",
            )
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertGreaterEqual(len(pulse["codehub"]["my_open_prs"]), 1)

    def test_collect_codehub_branch_status_present(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            self.assertIn("branch_status", pulse["codehub"])
            self.assertIn("clean", pulse["codehub"]["branch_status"])

    def test_collect_apihub_my_endpoints_failed_tests(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.apihub.register_endpoint("POST", "/api/posts", schema={},
                                          provider="backend", agent="design")
            hubs.apihub.record_api_test("POST /api/posts",
                                        {"passed": False},
                                        evidence={"status": 422}, agent="verifier")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            failed = pulse["apihub"]["my_endpoints_with_failed_tests"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["id"], "POST /api/posts")

    def test_collect_apihub_breaking_changes_for_my_consumed_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.apihub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="design",
            )
            hubs.apihub.register_consumer("GET /api/feed", "src/Feed.jsx", "frontend")
            hubs.apihub.update_schema("GET /api/feed",
                                     response={"items": []}, agent="backend")
            pulse = collect_hub_pulse(hubs, agent_id="frontend", step_num=1)
            breaking = pulse["apihub"]["my_consumed_endpoints_with_breaking_changes"]
            self.assertGreaterEqual(len(breaking), 1)
            self.assertEqual(breaking[0]["endpoint_id"], "GET /api/feed")

    def test_collect_workhub_tasks_assigned_to_me(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.workhub.create_task(title="task1", assignee="backend",
                                     agent="orchestrator")
            hubs.workhub.create_task(title="task2", assignee="frontend",
                                     agent="orchestrator")
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            pending = pulse["workhub"]["tasks_assigned_to_me_pending"]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["title"], "task1")

    def test_collect_eventhub_unread_count(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.eventhub.publish_event(
                source_hub="apihub", event_type="x", payload={},
                recipients=["backend"], priority="urgent",
            )
            hubs.eventhub.publish_event(
                source_hub="apihub", event_type="y", payload={},
                recipients=["backend"], priority="normal",
            )
            pulse = collect_hub_pulse(hubs, agent_id="backend", step_num=1)
            counts = pulse["eventhub"]["unread_count_by_priority"]
            self.assertEqual(counts.get("urgent", 0), 1)
            self.assertEqual(counts.get("normal", 0), 1)


class HubPulseBuildPromptTests(unittest.TestCase):
    def test_build_prompt_renders_codehub_section_when_dirty(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": False, "dirty_files": ["x.py"],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "apihub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        prompt = build_hub_pulse_prompt(pulse)
        self.assertIsNotNone(prompt)
        self.assertIn("CodeHub", prompt)
        self.assertIn("dirty", prompt.lower())
        self.assertIn("x.py", prompt)

    def test_build_prompt_omits_apihub_when_empty(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": False, "dirty_files": ["x.py"],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "apihub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        prompt = build_hub_pulse_prompt(pulse)
        # APIHub section should not be rendered because all fields empty
        self.assertNotIn("APIHub", prompt)

    def test_should_render_returns_false_when_all_empty(self):
        empty = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": True, "dirty_files": [],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "apihub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        self.assertFalse(should_render(empty))

    def test_should_render_returns_true_with_any_content(self):
        pulse = {
            "codehub": {"branch": "agent/backend",
                        "branch_status": {"clean": True, "dirty_files": [],
                                          "commits_ahead_of_main": 0, "unpushed_commits": 0},
                        "my_open_prs": [], "prs_needing_my_review": []},
            "apihub": {"my_endpoints_with_failed_tests": [],
                       "my_consumed_endpoints_with_breaking_changes": [],
                       "api_reviews_pending_my_decision": []},
            "workhub": {"tasks_assigned_to_me_pending": [
                            {"id": "t1", "title": "x", "priority": "normal"}],
                        "tasks_in_progress_by_me": [],
                        "mentions_unread": [], "plans_i_own": []},
            "eventhub": {"unread_count_by_priority": {},
                         "top_unread": [], "active_subscriptions": 0},
        }
        self.assertTrue(should_render(pulse))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm 11 tests FAIL (`ImportError: hub_pulse module`).

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse -v 2>&1 | tail -15
```

- [ ] **Step 3:** Implement `hub_pulse.py`

Create `agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py`:

```python
"""hub_pulse — step-start stage that pulls each agent's view of the 4 hubs + MessageBus."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def collect_hub_pulse(hubs: Any, agent_id: str, step_num: int = 0) -> Dict[str, Any]:
    """Collect the agent's view across 4 hubs. Top-K bounded to control token usage."""
    return {
        "codehub": _pulse_codehub(hubs, agent_id, step_num),
        "apihub": _pulse_apihub(hubs, agent_id),
        "workhub": _pulse_workhub(hubs, agent_id),
        "eventhub": _pulse_eventhub(hubs, agent_id),
    }


def _pulse_codehub(hubs: Any, agent_id: str, step_num: int) -> Dict[str, Any]:
    ch = getattr(hubs, "codehub", None)
    if ch is None:
        return {"branch": "", "branch_status": {"clean": True, "dirty_files": [],
                                                  "commits_ahead_of_main": 0, "unpushed_commits": 0},
                "my_open_prs": [], "prs_needing_my_review": []}
    branch_status = ch.get_branch_status(agent_id) if hasattr(ch, "get_branch_status") else {
        "clean": True, "dirty_files": [], "commits_ahead_of_main": 0, "unpushed_commits": 0}
    branch = f"agent/{agent_id}"
    my_open_prs = []
    for pr in ch.stores.pull_requests.value().values():
        if pr.get("author") != agent_id:
            continue
        if pr.get("status") not in (None, "open"):
            continue
        reviews = [r for r in ch.stores.code_reviews.value().values()
                   if r.get("pr_id") == pr.get("id") and r.get("state") == "approve"]
        approvals_received = len({r.get("reviewer") for r in reviews})
        approvals_needed = len(pr.get("reviewers") or [])
        my_open_prs.append({
            "id": pr.get("id"),
            "merge_state": pr.get("merge_state"),
            "approvals_received": approvals_received,
            "approvals_needed": approvals_needed,
            "linked_apis": pr.get("linked_apis") or [],
            "linked_tasks": pr.get("linked_tasks") or [],
        })
    prs_needing_my_review = []
    if hasattr(ch, "get_pending_reviews_for"):
        prs_needing_my_review = ch.get_pending_reviews_for(agent_id, since_steps=0)
    return {
        "branch": branch,
        "branch_status": branch_status,
        "my_open_prs": my_open_prs[:5],
        "prs_needing_my_review": prs_needing_my_review[:5],
    }


def _pulse_apihub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    ah = getattr(hubs, "apihub", None)
    if ah is None:
        return {"my_endpoints_with_failed_tests": [],
                "my_consumed_endpoints_with_breaking_changes": [],
                "api_reviews_pending_my_decision": []}
    failed = []
    for ep_id, ep in ah.get_endpoints().items():
        if ep.get("provider") != agent_id:
            continue
        tests = ah.get_contract_test_results(ep_id)
        if not tests:
            continue
        latest = max(tests, key=lambda t: t.get("created_at", 0))
        if not latest.get("result", {}).get("passed"):
            failed.append({"id": ep_id,
                            "last_contract_test_status": "failed",
                            "evidence": latest.get("evidence", {})})

    breaking_for_me = []
    consumers = ah._consumers.value()
    my_consumer_endpoints = {(c.get("endpoint_id"), c.get("file_path"))
                              for c in consumers.values()
                              if c.get("agent") == agent_id}
    recent_breaking = ah.get_breaking_changes(since_ts=None)
    for change in recent_breaking[:20]:
        ep_id = change.get("endpoint_id")
        for (consumed_ep, my_file) in my_consumer_endpoints:
            if consumed_ep == ep_id:
                breaking_for_me.append({
                    "endpoint_id": ep_id,
                    "my_file": my_file,
                    **(change.get("breaking") or {}),
                })
                break

    reviews_pending = []
    for r in ah._api_reviews.value().values():
        if agent_id in (r.get("reviewers") or []) and r.get("status") == "pending":
            reviews_pending.append({
                "review_id": r.get("id"),
                "endpoint_id": r.get("endpoint_id"),
                "requested_by": r.get("created_by"),
            })
    return {
        "my_endpoints_with_failed_tests": failed[:5],
        "my_consumed_endpoints_with_breaking_changes": breaking_for_me[:5],
        "api_reviews_pending_my_decision": reviews_pending[:5],
    }


def _pulse_workhub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    wh = getattr(hubs, "workhub", None)
    if wh is None:
        return {"tasks_assigned_to_me_pending": [],
                "tasks_in_progress_by_me": [],
                "mentions_unread": [], "plans_i_own": []}
    pending = wh.list_tasks(assignee=agent_id, status="pending")[:5] if hasattr(wh, "list_tasks") else []
    in_progress = wh.list_tasks(assignee=agent_id, status="in_progress")[:5] if hasattr(wh, "list_tasks") else []
    mentions = []
    if hasattr(wh, "stores"):
        for c in wh.stores.comments.value().values():
            if agent_id in (c.get("mentions") or []):
                mentions.append({
                    "comment_id": c.get("id"),
                    "resource_id": c.get("resource_id"),
                    "from": c.get("agent"),
                    "body": c.get("body", "")[:200],
                })
    plans_owned = wh.list_plans() if hasattr(wh, "list_plans") else []
    plans_owned = [p for p in plans_owned if p.get("owner") == agent_id][:3]
    enriched_plans = []
    for p in plans_owned:
        tasks = wh.list_tasks(plan_id=p.get("id")) if hasattr(wh, "list_tasks") else []
        enriched_plans.append({
            "id": p.get("id"),
            "tasks_total": len(tasks),
            "tasks_completed": sum(1 for t in tasks if t.get("status") == "completed"),
        })
    return {
        "tasks_assigned_to_me_pending": pending,
        "tasks_in_progress_by_me": in_progress,
        "mentions_unread": mentions[:5],
        "plans_i_own": enriched_plans,
    }


def _pulse_eventhub(hubs: Any, agent_id: str) -> Dict[str, Any]:
    eh = getattr(hubs, "eventhub", None)
    if eh is None:
        return {"unread_count_by_priority": {},
                "top_unread": [], "active_subscriptions": 0}
    unread = eh.list_inbox(agent_id, unread_only=True) if hasattr(eh, "list_inbox") else []
    counts = {"urgent": 0, "high": 0, "normal": 0, "low": 0}
    for e in unread:
        p = e.get("priority", "normal")
        counts[p] = counts.get(p, 0) + 1
    sorted_unread = sorted(
        unread,
        key=lambda e: ({"urgent": 0, "high": 1, "normal": 2, "low": 3}.get(e.get("priority", "normal"), 2),
                       -float(e.get("created_at", 0))),
    )
    top = []
    for e in sorted_unread[:3]:
        top.append({
            "event_id": e.get("id"),
            "source_hub": e.get("source_hub"),
            "event_type": e.get("event_type"),
            "resource_id": e.get("resource_id"),
        })
    subs = eh.get_subscriptions(agent=agent_id) if hasattr(eh, "get_subscriptions") else []
    return {
        "unread_count_by_priority": counts,
        "top_unread": top,
        "active_subscriptions": len(subs),
    }


def should_render(pulse: Dict[str, Any]) -> bool:
    """Return True if any section has content worth showing."""
    ch = pulse.get("codehub") or {}
    bs = ch.get("branch_status") or {}
    if not bs.get("clean", True):
        return True
    if bs.get("commits_ahead_of_main", 0) > 0:
        return True
    if ch.get("my_open_prs") or ch.get("prs_needing_my_review"):
        return True
    ah = pulse.get("apihub") or {}
    if (ah.get("my_endpoints_with_failed_tests")
        or ah.get("my_consumed_endpoints_with_breaking_changes")
        or ah.get("api_reviews_pending_my_decision")):
        return True
    wh = pulse.get("workhub") or {}
    if (wh.get("tasks_assigned_to_me_pending")
        or wh.get("tasks_in_progress_by_me")
        or wh.get("mentions_unread")
        or wh.get("plans_i_own")):
        return True
    eh = pulse.get("eventhub") or {}
    if eh.get("top_unread") or any((eh.get("unread_count_by_priority") or {}).values()):
        return True
    return False


def build_hub_pulse_prompt(pulse: Dict[str, Any]) -> Optional[str]:
    """Render the pulse dict as a markdown block. Returns None if all sections empty."""
    if not should_render(pulse):
        return None
    lines: List[str] = ["### 🔄 HUB PULSE"]

    ch = pulse.get("codehub") or {}
    bs = ch.get("branch_status") or {}
    ch_has_content = (not bs.get("clean", True)
                       or bs.get("commits_ahead_of_main", 0) > 0
                       or ch.get("my_open_prs") or ch.get("prs_needing_my_review"))
    if ch_has_content:
        lines.append("")
        lines.append(f"🌳 **CodeHub** — branch `{ch.get('branch', '')}`")
        if not bs.get("clean", True):
            files = bs.get("dirty_files") or []
            lines.append(f"  • Working tree: **dirty** ({len(files)} file(s): {', '.join(files[:3])}{'…' if len(files) > 3 else ''})")
        if bs.get("commits_ahead_of_main", 0) > 0 and not ch.get("my_open_prs"):
            lines.append(f"  • {bs['commits_ahead_of_main']} commits ahead of main, NO PR open")
            lines.append("    → consider `codehub_commit(...)` then `codehub_open_pr(...)`")
        for pr in ch.get("my_open_prs") or []:
            lines.append(f"  • Your open PR {pr['id']} — {pr.get('merge_state', 'unknown')} ({pr.get('approvals_received', 0)}/{pr.get('approvals_needed', 0)} approvals)")
        if ch.get("prs_needing_my_review"):
            lines.append(f"  • PRs needing your review ({len(ch['prs_needing_my_review'])}):")
            for pr in ch["prs_needing_my_review"]:
                lines.append(f"    - {pr['pr_id']} by {pr.get('author', '?')} ({pr.get('files_changed_count', 0)} files)")
            lines.append(f"      → `codehub_get_diff(pr_id)` then `codehub_review_pr(...)`")

    ah = pulse.get("apihub") or {}
    ah_has_content = (ah.get("my_endpoints_with_failed_tests")
                       or ah.get("my_consumed_endpoints_with_breaking_changes")
                       or ah.get("api_reviews_pending_my_decision"))
    if ah_has_content:
        lines.append("")
        lines.append("🔌 **APIHub**")
        for ep in ah.get("my_endpoints_with_failed_tests") or []:
            ev = ep.get("evidence", {})
            lines.append(f"  • Your endpoint has **FAILED** contract test: {ep['id']} (evidence: {ev})")
        for br in ah.get("my_consumed_endpoints_with_breaking_changes") or []:
            removed = br.get("removed_response_fields") or []
            type_changed = br.get("type_changed_fields") or []
            details = []
            if removed:
                details.append(f"removed_response_fields={removed}")
            if type_changed:
                details.append(f"type_changed_fields={type_changed}")
            lines.append(f"  • ⚠️ BREAKING CHANGE on endpoint you consume: {br['endpoint_id']} ({'; '.join(details) or 'see details'}) — your file: {br.get('my_file', '?')}")
        for rv in ah.get("api_reviews_pending_my_decision") or []:
            lines.append(f"  • API review pending your decision: {rv['review_id']} for {rv['endpoint_id']}")

    wh = pulse.get("workhub") or {}
    wh_has_content = (wh.get("tasks_assigned_to_me_pending")
                       or wh.get("tasks_in_progress_by_me")
                       or wh.get("mentions_unread")
                       or wh.get("plans_i_own"))
    if wh_has_content:
        lines.append("")
        lines.append("📋 **WorkHub**")
        if wh.get("tasks_assigned_to_me_pending"):
            lines.append(f"  • {len(wh['tasks_assigned_to_me_pending'])} tasks pending assigned to you:")
            for t in wh["tasks_assigned_to_me_pending"]:
                lines.append(f"    - [{t.get('priority', 'normal').upper()}] {t.get('id', '?')} \"{t.get('title', '')}\"")
        if wh.get("tasks_in_progress_by_me"):
            lines.append(f"  • {len(wh['tasks_in_progress_by_me'])} tasks in progress")
        if wh.get("plans_i_own"):
            for p in wh["plans_i_own"]:
                lines.append(f"  • You own plan {p['id']} ({p.get('tasks_completed', 0)}/{p.get('tasks_total', 0)} done)")
        if wh.get("mentions_unread"):
            lines.append(f"  • {len(wh['mentions_unread'])} unread @mentions:")
            for m in wh["mentions_unread"]:
                lines.append(f"    - from {m.get('from', '?')} on {m.get('resource_id', '?')}: \"{m.get('body', '')[:60]}\"")

    eh = pulse.get("eventhub") or {}
    eh_has_content = eh.get("top_unread") or any((eh.get("unread_count_by_priority") or {}).values())
    if eh_has_content:
        lines.append("")
        counts = eh.get("unread_count_by_priority") or {}
        summary = " ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)
        lines.append(f"📬 **EventHub** — Inbox unread by priority ({summary or 'none'})")
        for e in eh.get("top_unread") or []:
            lines.append(f"  • Top: {e['source_hub']}/{e['event_type']} {e.get('resource_id', '')}")

    return "\n".join(lines)
```

- [ ] **Step 4:** Run, confirm 11 PASS

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse -v 2>&1 | tail -15
```

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_hub_pulse.py \
        agent/env_generator/llm_generator/multi_agent/agents/runtime/hub_pulse.py
git commit -m "Add hub_pulse module (collect + build_prompt + should_render)"
```

---

## Phase C — `hub_commit_gate` Module (TDD)

### Task 4: TDD `commit_gate.collect` + `build_prompt`

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/agents/runtime/commit_gate.py`
- Create: `agent/tests/test_commit_gate.py`

- [ ] **Step 1:** Write failing tests

Create `agent/tests/test_commit_gate.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.commit_gate import (  # noqa: E402
    collect_loose_ends,
    build_commit_gate_prompt,
)


THRESHOLDS = {"stale_task_steps": 5, "stale_review_steps": 3, "stale_pr_steps": 10}


class CommitGateCollectTests(unittest.TestCase):
    def test_collect_clean_state_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            for value in loose.values():
                self.assertFalse(value)

    def test_collect_detects_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            wt = hubs.codehub.repo_root / "workspaces" / "backend"
            (wt / "f.py").write_text("x=1\n")
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=1, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("dirty_worktree"))

    def test_collect_detects_unpushed_commits_no_open_pr(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            ch = hubs.codehub
            ch.ensure_repo()
            ch.register_agent_worktree("backend")
            wt = ch.repo_root / "workspaces" / "backend"
            (wt / "f.py").write_text("x=1\n")
            ch.commit("backend", message="add f", files=["f.py"])
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=1, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("unpushed_commits"))

    def test_collect_detects_stale_claimed_task(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            task = hubs.workhub.create_task(title="x", assignee="backend",
                                            agent="orchestrator")
            hubs.workhub.claim_task(task["id"], "backend")
            # step_num is 10 + threshold is 5 → assume task is stale
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=10, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("stale_claimed_tasks"))

    def test_collect_detects_forgotten_review(self):
        with tempfile.TemporaryDirectory() as td:
            hubs = HubRegistry(Path(td))
            hubs.codehub.ensure_repo()
            hubs.codehub.register_agent_worktree("backend")
            hubs.codehub.register_agent_worktree("frontend")
            task = hubs.workhub.create_task(title="x", assignee="frontend",
                                            agent="orchestrator")
            hubs.codehub.open_pull_request(
                branch="agent/frontend",
                reviewers=["backend", "orchestrator"],
                linked_tasks=[task["id"]],
                title="Test", author="frontend",
            )
            loose = collect_loose_ends(hubs, agent_id="backend",
                                        step_num=5, thresholds=THRESHOLDS)
            self.assertTrue(loose.get("forgotten_reviews"))


class CommitGateBuildPromptTests(unittest.TestCase):
    def test_build_prompt_returns_none_when_no_loose_ends(self):
        loose = {"dirty_worktree": False, "unpushed_commits": False,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        self.assertIsNone(build_commit_gate_prompt(loose, details={}))

    def test_build_prompt_renders_dirty_worktree_section(self):
        loose = {"dirty_worktree": True, "unpushed_commits": False,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        details = {"dirty_files": ["src/feed.py"]}
        prompt = build_commit_gate_prompt(loose, details=details)
        self.assertIsNotNone(prompt)
        self.assertIn("INTEGRITY CHECK", prompt)
        self.assertIn("src/feed.py", prompt)

    def test_build_prompt_renders_unpushed_commits_section(self):
        loose = {"dirty_worktree": False, "unpushed_commits": True,
                 "stale_claimed_tasks": False, "forgotten_reviews": False,
                 "unhandled_breaking_changes": False, "conflict_prs_unresolved": False}
        details = {"ahead": 3, "branch": "agent/backend"}
        prompt = build_commit_gate_prompt(loose, details=details)
        self.assertIsNotNone(prompt)
        self.assertIn("3 commits", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run, confirm 8 tests FAIL (`ImportError: commit_gate`).

- [ ] **Step 3:** Implement `commit_gate.py`

Create `agent/env_generator/llm_generator/multi_agent/agents/runtime/commit_gate.py`:

```python
"""commit_gate — step-end stage that scans for loose ends and reports to next step."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DEFAULT_THRESHOLDS = {
    "stale_task_steps": 5,
    "stale_review_steps": 3,
    "stale_pr_steps": 10,
}


def collect_loose_ends(hubs: Any, agent_id: str, step_num: int,
                        thresholds: Optional[Dict[str, int]] = None) -> Dict[str, bool]:
    """Return six-category boolean dict. Use collect_loose_ends_details for the data backing each flag."""
    t = thresholds or DEFAULT_THRESHOLDS
    details = collect_loose_ends_details(hubs, agent_id, step_num, t)
    return {
        "dirty_worktree": bool(details.get("dirty_files")),
        "unpushed_commits": details.get("ahead", 0) > 0 and not details.get("has_open_pr"),
        "stale_claimed_tasks": bool(details.get("stale_claimed_tasks")),
        "forgotten_reviews": bool(details.get("forgotten_reviews")),
        "unhandled_breaking_changes": bool(details.get("unhandled_breaking_changes")),
        "conflict_prs_unresolved": bool(details.get("conflict_prs_unresolved")),
    }


def collect_loose_ends_details(hubs: Any, agent_id: str, step_num: int,
                                thresholds: Dict[str, int]) -> Dict[str, Any]:
    """Return full details dict used by both the bool collect and the prompt renderer."""
    details: Dict[str, Any] = {
        "dirty_files": [], "ahead": 0, "branch": f"agent/{agent_id}",
        "has_open_pr": False, "stale_claimed_tasks": [],
        "forgotten_reviews": [], "unhandled_breaking_changes": [],
        "conflict_prs_unresolved": [],
    }
    ch = getattr(hubs, "codehub", None)
    if ch is not None and hasattr(ch, "get_my_branch_loose_ends"):
        bl = ch.get_my_branch_loose_ends(agent_id)
        details["dirty_files"] = []
        if hasattr(ch, "get_branch_status"):
            bs = ch.get_branch_status(agent_id)
            details["dirty_files"] = bs.get("dirty_files") or []
        details["ahead"] = bl.get("ahead", 0)
        details["has_open_pr"] = bl.get("has_open_pr", False)
        details["conflict_prs_unresolved"] = bl.get("conflict_prs") or []

    wh = getattr(hubs, "workhub", None)
    if wh is not None and hasattr(wh, "list_tasks"):
        stale_threshold = thresholds.get("stale_task_steps", 5)
        in_progress = wh.list_tasks(assignee=agent_id, status="in_progress") or []
        for t in in_progress:
            # We approximate step age — if claimed_at recorded, fall back to step_num
            # threshold comparison since we don't have step_num at claim time
            if step_num >= stale_threshold:
                details["stale_claimed_tasks"].append({
                    "id": t.get("id"), "title": t.get("title"),
                    "claimed_at": t.get("claimed_at"),
                })

    if ch is not None and hasattr(ch, "list_prs_needing_review"):
        forgotten = ch.list_prs_needing_review(agent_id)
        review_threshold = thresholds.get("stale_review_steps", 3)
        for pr in forgotten:
            if step_num >= review_threshold:
                details["forgotten_reviews"].append({
                    "pr_id": pr.get("id"), "author": pr.get("author"),
                })

    ah = getattr(hubs, "apihub", None)
    if ah is not None and hasattr(ah, "get_breaking_changes"):
        breaking = ah.get_breaking_changes(since_ts=None) or []
        consumers = ah._consumers.value() if hasattr(ah, "_consumers") else {}
        my_consumer_eps = {c.get("endpoint_id") for c in consumers.values()
                           if c.get("agent") == agent_id}
        for change in breaking:
            ep = change.get("endpoint_id")
            if ep in my_consumer_eps:
                handled = False
                if wh is not None and hasattr(wh, "list_tasks"):
                    related = [t for t in (wh.list_tasks(assignee=agent_id) or [])
                                if ep in (t.get("metadata", {}).get("linked_apis") or [])]
                    if any(t.get("status") in ("in_progress", "completed") for t in related):
                        handled = True
                if not handled:
                    details["unhandled_breaking_changes"].append({"endpoint_id": ep})

    return details


def build_commit_gate_prompt(loose: Dict[str, bool], details: Dict[str, Any]) -> Optional[str]:
    """Render an INTEGRITY CHECK markdown block. Returns None if no loose end is set."""
    if not any(loose.values()):
        return None
    lines: List[str] = ["### ⚠️ INTEGRITY CHECK"]
    lines.append("")
    lines.append("You finished this step with the following loose ends:")
    lines.append("")
    if loose.get("dirty_worktree"):
        files = details.get("dirty_files") or []
        lines.append(f"🔴 **Dirty work tree** (uncommitted changes)")
        lines.append(f"  - {len(files)} file(s): {', '.join(files[:5])}{'…' if len(files) > 5 else ''}")
        lines.append("  → next step: `codehub_commit(message=..., files=[...])`")
        lines.append("")
    if loose.get("unpushed_commits"):
        ahead = details.get("ahead", 0)
        branch = details.get("branch", "")
        lines.append(f"🟡 **Branch has {ahead} commits but NO open PR** (on {branch})")
        lines.append("  → consider: `codehub_open_pr(branch=..., reviewers=[...], linked_tasks=[...])`")
        lines.append("")
    if loose.get("stale_claimed_tasks"):
        tasks = details.get("stale_claimed_tasks") or []
        lines.append(f"🔴 **{len(tasks)} claimed task(s) with no progress this step**")
        for t in tasks[:3]:
            lines.append(f"  - {t.get('id', '?')} \"{t.get('title', '')}\"")
        lines.append("  → either `workhub_complete_task` / `workhub_fail_task` / `workhub_comment(body=\"progress: ...\")`")
        lines.append("")
    if loose.get("forgotten_reviews"):
        prs = details.get("forgotten_reviews") or []
        lines.append(f"🟡 **{len(prs)} PR(s) waiting on your review**")
        for pr in prs[:3]:
            lines.append(f"  - {pr.get('pr_id', '?')} by {pr.get('author', '?')}")
        lines.append("  → `codehub_review_pr(pr_id, state, inline_comments=[...])`")
        lines.append("")
    if loose.get("unhandled_breaking_changes"):
        bc = details.get("unhandled_breaking_changes") or []
        lines.append(f"🔴 **{len(bc)} unhandled breaking change(s) on endpoints you consume**")
        for c in bc[:3]:
            lines.append(f"  - {c.get('endpoint_id', '?')}")
        lines.append("")
    if loose.get("conflict_prs_unresolved"):
        prs = details.get("conflict_prs_unresolved") or []
        lines.append(f"🔴 **{len(prs)} of your PR(s) in conflict, unresolved**")
        for pid in prs[:3]:
            lines.append(f"  - {pid}")
        lines.append("  → `codehub_resolve_conflict(pr_id, resolution_files={...})`")
    return "\n".join(lines)
```

- [ ] **Step 4:** Run, confirm 8 PASS.

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_commit_gate -v 2>&1 | tail -15
```

- [ ] **Step 5:** Commit

```bash
git add agent/tests/test_commit_gate.py \
        agent/env_generator/llm_generator/multi_agent/agents/runtime/commit_gate.py
git commit -m "Add commit_gate module (loose-ends scanner + prompt renderer)"
```

---

## Phase D — step_runner Integration

### Task 5: Replace `inbox_status` + `crdt_changes` stages with `hub_pulse`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py`

- [ ] **Step 1:** Read current stage 1+2 implementation

```bash
sed -n '79,260p' agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py | head -90
```

Identify the block that handles `inbox_status` (lines ~193-234) and `crdt_changes` (lines ~236-259). The new `hub_pulse` stage replaces BOTH.

- [ ] **Step 2:** Modify `default_stage_order` in step_runner.py

Find around line 79:

```python
        default_stage_order = [
            "inbox_status",
            "crdt_changes",
            "runtime_team_status",
            ...
            "crdt_sync",
            "knowledge_sync",
        ]
```

Replace with:

```python
        default_stage_order = [
            "hub_pulse",
            "runtime_team_status",
            "planning",
            "retrieve_context",
            "action",
            "hub_commit_gate",
            "knowledge_sync",
        ]
```

- [ ] **Step 3:** Inject hub_pulse + hub_commit_gate at engine level

After the line that computes `enabled_stages = set(stage_order)`, add:

```python
        # Engine-forced stages: hub_pulse always first, hub_commit_gate always last.
        # Cannot be disabled via yaml — code-forced for invariants.
        if "hub_pulse" not in enabled_stages:
            enabled_stages.add("hub_pulse")
            stage_order = ["hub_pulse"] + [s for s in stage_order if s != "hub_pulse"]
        if "hub_commit_gate" not in enabled_stages:
            enabled_stages.add("hub_commit_gate")
            stage_order = [s for s in stage_order if s != "hub_commit_gate"] + ["hub_commit_gate"]
```

- [ ] **Step 4:** Replace `inbox_status` + `crdt_changes` block with `hub_pulse`

Find the block (around line 193):

```python
                if _stage_enabled("inbox_status"):
                    ...
                if _stage_enabled("crdt_changes"):
                    ...
```

Replace ENTIRE block with:

```python
                hub_pulse_prompt = None
                if _stage_enabled("hub_pulse"):
                    stage_start = loop_time()
                    self._active_stage = "hub_pulse"
                    try:
                        from .hub_pulse import collect_hub_pulse, build_hub_pulse_prompt
                        hubs = getattr(self, "_hubs", None)
                        if hubs is not None:
                            pulse = collect_hub_pulse(hubs, self.agent_id, step_num=step)
                            hub_pulse_prompt = build_hub_pulse_prompt(pulse)
                            if hub_pulse_prompt:
                                messages.append(Message.user(hub_pulse_prompt))
                        _mark_stage(
                            "hub_pulse", executed=True,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                        )
                    except Exception as e:
                        self._logger.warning(f"[{self.agent_id}] hub_pulse stage skipped: {e}")
                        _mark_stage(
                            "hub_pulse", executed=False, skip_reason="exception",
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            metadata={"error": str(e)},
                        )
                else:
                    _mark_stage("hub_pulse", executed=False, skip_reason="disabled_by_config")
```

Note: variable `hub_pulse_prompt` replaces `inbox_status_prompt` AND `crdt_changes_prompt` in any downstream uses. Search for `inbox_status_prompt` and `crdt_changes_prompt` later in the same file (around line 309-310) — replace them with `hub_pulse_prompt`:

```python
# OLD
                    inbox_status_prompt=inbox_status_prompt,
                    crdt_changes_prompt=crdt_changes_prompt,
# NEW
                    hub_pulse_prompt=hub_pulse_prompt,
```

If those parameters are unused downstream, just drop them. Search to confirm.

- [ ] **Step 5:** Run regressions to confirm step_runner still imports and runs

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse agent.tests.test_hub_architecture 2>&1 | tail -3
```

Expected: regressions 7 OK; hub_pulse 11 OK; hub_architecture passes.

If `inbox_status_prompt` / `crdt_changes_prompt` parameter mismatch breaks something downstream, fix the callers. The intent is: ONE prompt string (or None) replaces TWO.

- [ ] **Step 6:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py
git commit -m "Replace inbox_status + crdt_changes stages with hub_pulse (engine-forced)"
```

### Task 6: Replace `crdt_sync` stage with `hub_commit_gate`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py`

- [ ] **Step 1:** Find current `_run_crdt_sync_stage` call (around line 368)

```bash
grep -nE "_run_crdt_sync_stage|crdt_sync" agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py | head
```

- [ ] **Step 2:** Replace the `crdt_sync` block with `hub_commit_gate`

Find the call:

```python
                done = await self._run_crdt_sync_stage(
                    enabled=_stage_enabled("crdt_sync"),
                    ...
                )
```

Replace it (the entire call expression) with:

```python
                if _stage_enabled("hub_commit_gate"):
                    stage_start = loop_time()
                    self._active_stage = "hub_commit_gate"
                    try:
                        from .commit_gate import (
                            collect_loose_ends,
                            collect_loose_ends_details,
                            build_commit_gate_prompt,
                            DEFAULT_THRESHOLDS,
                        )
                        hubs = getattr(self, "_hubs", None)
                        if hubs is not None:
                            t = DEFAULT_THRESHOLDS
                            details = collect_loose_ends_details(hubs, self.agent_id, step, t)
                            loose = collect_loose_ends(hubs, self.agent_id, step, t)
                            gate_prompt = build_commit_gate_prompt(loose, details)
                            if gate_prompt:
                                # Roll forward to next step
                                self._pending_integrity_prompt = gate_prompt
                                try:
                                    hubs.eventhub.publish_event(
                                        source_hub="system",
                                        event_type="integrity_check",
                                        payload={"loose": loose, "details": details},
                                        recipients=[self.agent_id],
                                        priority="high",
                                    )
                                except Exception:
                                    pass
                        _mark_stage(
                            "hub_commit_gate", executed=True,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                        )
                    except Exception as e:
                        self._logger.warning(f"[{self.agent_id}] hub_commit_gate stage skipped: {e}")
                        _mark_stage(
                            "hub_commit_gate", executed=False, skip_reason="exception",
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            metadata={"error": str(e)},
                        )
                else:
                    _mark_stage("hub_commit_gate", executed=False, skip_reason="disabled_by_config")
                done = False
```

(Remove the entire previous `_run_crdt_sync_stage` invocation since CRDT is gone.)

- [ ] **Step 3:** Wire `_pending_integrity_prompt` into next step's pulse

Find where hub_pulse prepends the prompt (Task 5's block). Modify it so if `getattr(self, "_pending_integrity_prompt", None)` is set, prepend that BEFORE the new pulse and then clear it:

```python
                if _stage_enabled("hub_pulse"):
                    stage_start = loop_time()
                    self._active_stage = "hub_pulse"
                    try:
                        # Prepend any pending integrity prompt from previous step
                        pending = getattr(self, "_pending_integrity_prompt", None)
                        if pending:
                            messages.append(Message.user(pending))
                            self._pending_integrity_prompt = None
                        from .hub_pulse import collect_hub_pulse, build_hub_pulse_prompt
                        # ...rest of pulse code unchanged...
```

- [ ] **Step 4:** Run regressions

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_commit_gate agent.tests.test_hub_pulse 2>&1 | tail -3
```

- [ ] **Step 5:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py
git commit -m "Replace crdt_sync stage with hub_commit_gate (engine-forced, rolls forward to next pulse)"
```

---

## Phase E — Update `agents_config.yaml`

### Task 7: Update default stage list + per-profile stage lists + commit_gate config

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`

- [ ] **Step 1:** Update `execution_pipeline_defaults.stages`

Find (around line 21):

```yaml
execution_pipeline_defaults:
  stages:
    - inbox_status
    - crdt_changes
    - runtime_team_status
    - planning
    - retrieve_context
    - action
    - crdt_sync
    - knowledge_sync
```

Replace with:

```yaml
execution_pipeline_defaults:
  stages:
    - hub_pulse
    - runtime_team_status
    - planning
    - retrieve_context
    - action
    - hub_commit_gate
    - knowledge_sync
  commit_gate:
    stale_task_steps: 5
    stale_review_steps: 3
    stale_pr_steps: 10
    enabled: true
```

- [ ] **Step 2:** Update each profile's per-profile `stages:` list

Find every line `stages: [inbox_status, crdt_changes, ...]` (8 profiles) and replace with:

```yaml
      stages: [hub_pulse, runtime_team_status, planning, retrieve_context, action, hub_commit_gate, knowledge_sync]
```

Use sed or manual edit:

```bash
sed -i 's|stages: \[inbox_status, crdt_changes, runtime_team_status, planning, retrieve_context, action, crdt_sync, knowledge_sync\]|stages: [hub_pulse, runtime_team_status, planning, retrieve_context, action, hub_commit_gate, knowledge_sync]|g' agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml
```

Verify replacement:

```bash
grep -nE "stages:.*hub_pulse|stages:.*inbox_status" agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml
```

Expected: 9 matches with `hub_pulse`; 0 with `inbox_status`.

- [ ] **Step 3:** Update `max_tool_calls_per_stage`

Find (around line 33-40):

```yaml
  max_tool_calls_per_stage:
    planning: 1
    retrieve_context: 2
    crdt_sync: 4
    knowledge_sync: 1
```

Replace `crdt_sync: 4` with `hub_pulse: 0` and `hub_commit_gate: 0` (these stages collect data; no LLM tool calls):

```yaml
  max_tool_calls_per_stage:
    hub_pulse: 0
    planning: 1
    retrieve_context: 2
    hub_commit_gate: 0
    knowledge_sync: 1
```

Do the same for each per-profile `max_tool_calls_per_stage:` if present.

- [ ] **Step 4:** Regressions + smoke

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_hub_pulse agent.tests.test_commit_gate agent.tests.test_hub_architecture 2>&1 | tail -3
```

Expected: all OK.

- [ ] **Step 5:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml
git commit -m "agents_config: replace inbox_status/crdt_changes/crdt_sync with hub_pulse/hub_commit_gate"
```

---

## Phase F — Update Agent Prompts

### Task 8: Update 4 prompts (orchestrator, design, database, backend)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`

- [ ] **Step 1:** Audit current pulse / gate references

```bash
grep -lE "inbox_status|crdt_changes|crdt_sync|hub_pulse|hub_commit_gate" agent/env_generator/llm_generator/multi_agent/prompts/v2/*.j2
```

If any prompt explicitly mentions `inbox_status` or `crdt_changes`, replace with `hub_pulse`. None of them likely do — the stages run silently.

- [ ] **Step 2:** Add a "STEP PIPELINE" note section to each of the 4 prompts

In each `.j2` file, find an appropriate section (likely after "Workflow" or "Environment" — varies per prompt). Insert this fragment:

```jinja

## Step Pipeline

Every step you take runs through these stages automatically:

1. **🔄 HUB PULSE** (auto, start of every step): pulls your view of CodeHub /
   APIHub / WorkHub / EventHub and shows you: dirty work tree, open PRs needing
   your action, PRs needing your review, breaking changes on endpoints you
   consume, tasks assigned to you, unread @mentions, urgent inbox events.
   Read this section before deciding what to do.
2. **You decide and act** (planning / retrieve_context / action).
3. **⚠️ INTEGRITY CHECK** (auto, end of every step): if you finished with
   loose ends (uncommitted edits, branch has commits but no PR, claimed task
   with no progress, PRs waiting on your review, unhandled breaking changes,
   conflict PRs unresolved) the gate flags them and rolls them forward as a
   reminder at the start of your next step.

The gate does NOT auto-commit, auto-open-PR, or auto-review for you. It only
makes the loose ends visible so you can address them deliberately.
```

Apply the SAME fragment to all 4 prompts. Find the right insertion point per file:
- `orchestrator_agent.j2` — after the "Workflow" section
- `design_agent.j2` — after the "Environment" / "Workflow" section
- `database_agent.j2` — after the "Workflow" section
- `backend_agent.j2` — after the "Workflow" section

- [ ] **Step 3:** Jinja render smoke test

```bash
for prompt in orchestrator design database backend; do
  /home/haibotong/miniconda3/envs/dt/bin/python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('agent/env_generator/llm_generator/multi_agent/prompts'))
tpl = env.get_template('v2/${prompt}_agent.j2')
out = tpl.render(name='test', api_port=8000, ui_port=3000, db_port=5432, backend_internal_port=8080)
assert 'HUB PULSE' in out or 'hub_pulse' in out
print('${prompt}: render OK + pulse mention present')
"
done
```

If any prompt fails because a context variable is missing, add the variable to the test call.

- [ ] **Step 4:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2
git commit -m "Update 4 agent prompts to describe hub_pulse + integrity check pipeline"
```

### Task 9: Update 3 prompts (frontend, verifier, knowledge)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2`

- [ ] **Step 1:** Apply the SAME "Step Pipeline" fragment from Task 8 Step 2 to each of these 3 prompts. Pick the same kind of insertion point (after Workflow).

- [ ] **Step 2:** Jinja render smoke test

```bash
for prompt in frontend verifier knowledge; do
  /home/haibotong/miniconda3/envs/dt/bin/python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('agent/env_generator/llm_generator/multi_agent/prompts'))
tpl = env.get_template('v2/${prompt}_agent.j2')
out = tpl.render(name='test', api_port=8000, ui_port=3000, db_port=5432, backend_internal_port=8080)
assert 'HUB PULSE' in out or 'hub_pulse' in out
print('${prompt}: render OK')
"
done
```

- [ ] **Step 3:** Commit

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/verifier_agent.j2 \
        agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2
git commit -m "Update 3 agent prompts (frontend/verifier/knowledge) for step pipeline"
```

---

## Phase G — Ship

### Task 10: Discover + migration log + push

- [ ] **Step 1:** Full discover

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -3
```

Expected: discover ≥ 335 OK (was 312, +27 from new pulse/gate/branch-helper tests); regressions 7 OK.

- [ ] **Step 2:** Confirm zero Claude trailers

```bash
git log --pretty=%B red-env-gen/haibotong-0521-pipeline-web-tools..HEAD | grep -c "Co-Authored-By:"
```

Expected: 0.

- [ ] **Step 3:** Confirm hub_pulse/hub_commit_gate enforced even if config drops them

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -c "
import sys, ast
sys.path.insert(0, 'agent')
sys.path.insert(0, 'agent/env_generator/llm_generator')
# Manual inspection — confirm engine-force lines are present
src = open('agent/env_generator/llm_generator/multi_agent/agents/runtime/step_runner.py').read()
assert 'hub_pulse' in src and 'hub_commit_gate' in src
assert 'enabled_stages.add(\"hub_pulse\")' in src or 'enabled_stages.add(\\'hub_pulse\\')' in src
print('engine-force lines present')
"
```

- [ ] **Step 4:** Write migration log

Create `docs/superpowers/migration-logs/09-step-pipeline-integration.md`:

```markdown
# 09 — Step Pipeline Integration (hub_pulse + hub_commit_gate)

**Branch:** haibotong-cutover-8-step-pipeline
**Predecessor:** haibotong-cutover-7-schema-gates (merged into parent)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §5-6, §10
**Plan:** docs/superpowers/plans/2026-05-23-cutover-8-step-pipeline-integration.md

## Summary

Every agent step now runs `hub_pulse` (start, code-forced) and
`hub_commit_gate` (end, code-forced). Pulse pulls each agent's view of
the 4 hubs + MessageBus and injects it as a prompt block before the LLM
thinks. Gate scans 6 categories of loose ends and rolls them forward to
the next step's pulse. Both stages cannot be turned off via
`agents_config.yaml` — the engine injects them regardless.

The dead `inbox_status`, `crdt_changes`, `crdt_sync` stages — whose CRDT
backings were stripped in Cutovers 4-5 — are removed.

## Modules added

- `agents/runtime/hub_pulse.py` — `collect_hub_pulse`, `build_hub_pulse_prompt`, `should_render`
- `agents/runtime/commit_gate.py` — `collect_loose_ends`, `collect_loose_ends_details`, `build_commit_gate_prompt`, `DEFAULT_THRESHOLDS`

## CodeHub helpers added

- `get_branch_status(agent_id)` — git status + ahead/behind
- `list_prs_needing_review(reviewer)` — PRs needing reviewer decision
- `get_pending_reviews_for(agent_id, since_steps=0)` — light dict for pulse
- `get_my_branch_loose_ends(agent_id)` — gate aggregator

## Step pipeline changes

Before:
```
inbox_status → crdt_changes → runtime_team_status → planning → retrieve_context
            → action → crdt_sync → knowledge_sync
```

After:
```
hub_pulse → runtime_team_status → planning → retrieve_context → action
         → hub_commit_gate → knowledge_sync
```

Engine forces `hub_pulse` first and `hub_commit_gate` last regardless of
`agents_config.yaml`. Per-stage tool-call caps for both new stages set to 0
(they collect data via hub method calls, not LLM tools).

## Prompts updated

All 7 v2 agent prompts gained a "Step Pipeline" section explaining the
HUB PULSE + INTEGRITY CHECK auto-injected blocks.

## Test additions

- test_codehub_branch_helpers.py (8 tests)
- test_hub_pulse.py (11 tests)
- test_commit_gate.py (8 tests)

## Commits

<paste output of `git log --oneline red-env-gen/haibotong-0521-pipeline-web-tools..HEAD`>

## Regression evidence

<paste last 5 lines of run_regressions.py>

## Acceptance criteria from spec §13

- D. Every agent step first stage is `hub_pulse` ✓ (engine-forced)
- E. Every agent step last stage is `hub_commit_gate` ✓ (engine-forced)
- F. Frontend / consumer agents see breaking-change tasks in pulse ✓ (via `_pulse_apihub`)
- Loose ends roll forward to next step prompt ✓ (`_pending_integrity_prompt`)
```

Fill in actual values from Steps 1-2.

- [ ] **Step 5:** Commit + push

```bash
git add docs/superpowers/migration-logs/09-step-pipeline-integration.md
git commit -m "Add Cutover 8 migration log"
git push red-env-gen haibotong-cutover-8-step-pipeline -u 2>&1 | tail -3
```

- [ ] **Step 6:** Print PR compare URL

```bash
echo "PR compare: https://github.com/Virtue-AI/red-env-gen/compare/haibotong-0521-pipeline-web-tools...haibotong-cutover-8-step-pipeline"
```

---

## Constraints recap

- **No `Co-Authored-By: Claude` trailer on any commit.**
- Use `dt` conda env: `/home/haibotong/miniconda3/envs/dt/bin/python`.
- Branch from `red-env-gen/haibotong-0521-pipeline-web-tools` (post-Cutover-7 parent).
- Each task → 1 commit (10 tasks total).

## Recovery Notes

- If `step_runner.py` parameter signature changes (replacing `inbox_status_prompt` + `crdt_changes_prompt` with `hub_pulse_prompt`) break downstream code, fix the callers — don't add back the dead parameters.
- If a real LLM run is needed before merging, defer to a manual smoke (out of scope for this plan).
- `_pending_integrity_prompt` is a transient agent attribute (cleared after one consumption). It persists across steps within the same agent instance but does NOT persist across agent restarts. Acceptable for the gate's "roll forward to next step" semantics.

## Out of Scope (future)

- Pulse caching across consecutive steps within a single LLM turn (YAGNI)
- AST-based file scanning for unregistered endpoints / pages / consumers
- A "silenced" mechanism for the gate (user-explicit silence of an intentionally-unaddressed loose end)
