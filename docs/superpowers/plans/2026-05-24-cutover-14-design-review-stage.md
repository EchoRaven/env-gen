# Cutover 14: Design Review Stage (Architect Reviewer)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a mandatory design-review hop between the Design agent producing a design doc and downstream agents (backend / database / frontend) acting on it. A new **Architect Reviewer** agent must submit a substantive design review challenging ≥3 design assumptions before approving. Downstream agents are structurally blocked from starting work on a design that isn't `approved`.

**Architecture:** Design docs ride on existing WorkHub `pages` with `kind="design"` and a new `status` lifecycle `draft → under_review → approved | needs_revision`. WorkHub gains `submit_design_review(page_id, reviewer, state, challenges)` enforcing ≥3 non-empty `challenges` for `state="approve"` (mirrors Cutover 13's substantive-review pattern). A new `runtime/design_gate.py` module provides `assert_design_approved(workhub, page_id)` for downstream agents to call at the top of their first step. New `architect_reviewer` agent profile + prompt + LLM tools (`design_submit_review`, `design_list_pending_review`, `design_get_status`). Design agent prompt updated to publish design pages with `kind="design"` and wait for approval before delivering; backend/database/frontend prompts updated to call `design_get_status` before acting.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Existing surfaces: WorkHub `create_page`, `list_pages` (Cutover 5), HubTool framework (Cutover 10), agent profile + prompt patterns (Cutovers 10-13).

---

## Context for Worker

### Why this cutover exists

Today, after Design agent emits a design doc, three downstream agents (backend / database / frontend) start building in parallel against it. The 4 hubs catch *implementation* drift via schema gates (Cutover 7) and registration discipline (Cutover 7), and Cutover 13 catches rubber-stamp PR reviews, but nothing catches **wrong design**. If the design itself is bad (wrong table partitioning, wrong API shape, missing a major flow), all three downstream agents build the wrong thing in parallel. Force-merge cleans the symptom; the root cause goes uncaught.

Real engineering inserts an **architect/staff-eng review** between design lock-in and implementation start. This cutover adds that hop as a hard structural gate.

### Lifecycle

```
Design agent creates page (kind="design", status="draft")
                           │
                           ▼
Design agent finishes editing -> sets status="under_review" via submit_design_for_review()
                           │
                           ▼
Architect Reviewer picks it up (via list_pending_design_reviews())
                           │
                           ▼
Architect reviews -> submit_design_review(page_id, state, challenges=[...])
   ├── state="approve" requires len(non_empty_challenges) >= 3 -> status="approved"
   ├── state="needs_revision" -> status="needs_revision"; design agent revises and re-submits
   └── state="comment" -> doesn't transition; informational
                           │
                           ▼
Downstream agents: assert_design_approved(workhub, page_id) at top of first step;
   raises DesignNotApprovedError if status != "approved"
```

### Why ≥3 challenges (not ≥1)

Design reviews exist to interrogate the design. Mirror's Cutover 13's "considered_alternatives" pattern: ≥1 was a weak floor for code reviews; design reviews carry higher stakes (three downstream agents depend on it). Three is the smallest number that forces the reviewer to actually structure their critique rather than dump one note and call it done. "Challenged the read path", "challenged the write path", "challenged the failure mode" — three orthogonal angles is the bar.

Each challenge must include `claim` (what the design says), `concern` (what could go wrong), and `recommendation` (what should change or what was decided). Empty / whitespace-only entries don't count.

### Why design docs live on WorkHub pages (not a new entity)

WorkHub already has pages with `kind` and `status` fields. Adding a `kind="design"` lifecycle is cheaper than introducing a new entity store. Design review history is appended to `metadata.review_history` on the page. The architecture mirrors the bug-on-task pattern from Cutover 10.

### Page schema after Cutover 14

```python
{
    "id": "page_<hex>",
    "title": "Feed page architecture",
    "kind": "design",
    "status": "approved",  # draft | under_review | approved | needs_revision
    "attendees": [...],
    "metadata": {
        "design_subject": "feed",
        "review_history": [
            {
                "at": <epoch>,
                "by": "architect_reviewer",
                "state": "approve",          # or "needs_revision" / "comment"
                "challenges": [
                    {"claim": "...", "concern": "...", "recommendation": "..."},
                    ...
                ],
                "review_id": "drev_<hex>",
            },
            ...
        ],
    },
    ...other existing page fields
}
```

### Downstream gating

`assert_design_approved(workhub, page_id)` raises `DesignNotApprovedError` if:
- Page doesn't exist
- Page's `kind` isn't `"design"`
- Page's `status` isn't `"approved"`

Downstream prompts (backend, database, frontend) get a hard rule: **at the top of any task that references a design page, call `design_get_status(page_id)` and refuse if not approved**. The orchestrator should not assign implementation tasks until the design is approved.

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (`dt` conda env)
- No Claude trailer on commits; no emojis in code or prompts
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 9
- Both baselines green at every task boundary: regressions 7 OK; discover 534 OK after Cutover 13
- Worktree path: `worktrees/<agent_id>`; default git branch: `master`

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/design_gate.py` — `assert_design_approved` + `DesignNotApprovedError`
- `agent/env_generator/llm_generator/tools/design_tools.py` — 4 LLM tools (`design_submit_for_review`, `design_submit_review`, `design_list_pending_review`, `design_get_status`)
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/architect_reviewer_agent.j2`
- `agent/tests/test_workhub_design_review.py`
- `agent/tests/test_design_gate.py`
- `agent/tests/test_design_tools.py`
- `agent/tests/test_architect_reviewer_config.py`
- `agent/tests/test_architect_reviewer_prompt.py`
- `agent/tests/test_design_review_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — add `submit_design_for_review`, `submit_design_review`, `is_design_approved`, `list_pending_design_reviews`, `get_design_page`
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `architect_reviewer` profile (12th); add `design_tools` bundle to design/architect_reviewer/backend/database/frontend
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `design_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2` — must publish kind="design", call submit_design_for_review, await approval
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2` — must check design status; refuse if not approved
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2` — same as backend
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2` — same as backend

---

## Task 1: Worktree setup + baseline

**Files:**
- Create: `docs/superpowers/cutover-14-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-14-design-review
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-14-design-review`. If missing: `git worktree add -b haibotong-cutover-14-design-review .worktrees/haibotong-cutover-14-design-review haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 534 OK.

- [ ] **Step 3: Inventory current WorkHub page surface**

```bash
grep -nE "def (create_page|list_pages|append_block)" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py | head -5
```

Confirm `create_page(title, parent, attendees, agent)` and `list_pages(kind, status)` exist as expected.

- [ ] **Step 4: Inventory current profile count**

```bash
grep -nE "^  [a-z_]+:$" agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml | head -15
```

Expected: 11 profiles (after Cutover 10's bug_triage_orchestrator). The 12th — `architect_reviewer` — is added in Task 5.

- [ ] **Step 5: Write baseline note**

Create `docs/superpowers/cutover-14-baseline.md`:

```markdown
# Cutover 14 Baseline (Design Review Stage)

## Test counts
- regressions: 7 OK
- discover: 534 OK

## Gap this cutover closes
Today nothing checks the *design* before backend/database/frontend start
implementing. Cutover 13 caught rubber-stamp PR reviews, but a wrong design
still makes it to three parallel implementations. This cutover adds a
mandatory architect-reviewer hop with >=3-challenge requirement, and a
structural gate that blocks downstream agents from starting on un-approved
designs.

## Existing surfaces we extend
- WorkHub.create_page(kind=, ...) and list_pages(kind=, status=) exist
- Page schema has kind + status fields
- HubTool framework + agent profile pattern reusable from Cutovers 10-13
- 11 existing profiles; adding 12th (architect_reviewer)

## Lifecycle
draft -> under_review -> approved | needs_revision
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/cutover-14-baseline.md
git commit -m "Cutover 14: record pre-flight baseline (regressions 7 OK, discover 534 OK)"
```

Verify no Claude trailer.

---

## Task 2: WorkHub design-review schema + helpers

Five new methods on `WorkHub`:
- `submit_design_for_review(page_id, agent)` — transitions `status: draft → under_review`
- `submit_design_review(page_id, reviewer, state, challenges)` — validates state + challenges, appends to history, transitions status
- `is_design_approved(page_id) -> bool` — convenience
- `list_pending_design_reviews() -> List[dict]` — design pages with status=="under_review"
- `get_design_page(page_id) -> Optional[dict]` — convenience (returns None if not a design page)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_design_review.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_workhub_design_review.py`:

```python
"""Tests for WorkHub design-review helpers (Cutover 14)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_CHALLENGES = [
    {"claim": "design says use Redis for cache",
     "concern": "Redis lacks user-scoped TTL",
     "recommendation": "use per-user namespaces or move to Memcached"},
    {"claim": "design says single-table feed",
     "concern": "single-table will hot-shard at >100k DAU",
     "recommendation": "partition by user_id mod 16"},
    {"claim": "design says client polls /api/feed",
     "concern": "polling wastes battery on mobile",
     "recommendation": "use SSE or WebSocket"},
]


def _make_design_page(reg, agent="design"):
    return reg.workhub.create_page(
        title="Feed architecture", agent=agent, attendees=["architect_reviewer"],
        kind="design", metadata={"design_subject": "feed"})


class WorkHubDesignLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="design_rev_"))
        self.reg = HubRegistry(self.tmp)
        self.page = _make_design_page(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_design_page_starts_as_draft(self) -> None:
        self.assertEqual(self.page["status"], "draft")
        self.assertEqual(self.page["kind"], "design")

    def test_get_design_page_returns_only_design_kind(self) -> None:
        page2 = self.reg.workhub.create_page(title="Sprint notes",
                                              agent="orch", kind="meeting")
        self.assertEqual(self.reg.workhub.get_design_page(self.page["id"])["id"], self.page["id"])
        self.assertIsNone(self.reg.workhub.get_design_page(page2["id"]))

    def test_submit_design_for_review_transitions_to_under_review(self) -> None:
        updated = self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.assertEqual(updated["status"], "under_review")

    def test_submit_design_for_review_rejects_non_draft(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        result = self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.assertIn("error", result)

    def test_list_pending_design_reviews_returns_under_review_pages(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        pending = self.reg.workhub.list_pending_design_reviews()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], self.page["id"])

    def test_list_pending_excludes_drafts_and_approved(self) -> None:
        # draft -> not pending
        self.assertEqual(self.reg.workhub.list_pending_design_reviews(), [])
        # under_review then approved -> not pending
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD_CHALLENGES)
        self.assertEqual(self.reg.workhub.list_pending_design_reviews(), [])


class WorkHubDesignReviewSubstantiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="design_subst_"))
        self.reg = HubRegistry(self.tmp)
        self.page = _make_design_page(self.reg)
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_approve_with_3_challenges_transitions_to_approved(self) -> None:
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD_CHALLENGES)
        self.assertEqual(result["status"], "approved")
        self.assertTrue(self.reg.workhub.is_design_approved(self.page["id"]))

    def test_approve_with_less_than_3_challenges_is_rejected(self) -> None:
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD_CHALLENGES[:2])
        self.assertIn("error", result)
        # Status should stay under_review
        page = self.reg.workhub.get_design_page(self.page["id"])
        self.assertEqual(page["status"], "under_review")

    def test_approve_with_3_but_one_empty_challenge_is_rejected(self) -> None:
        bad = list(_GOOD_CHALLENGES)
        bad[1] = {"claim": "", "concern": "", "recommendation": ""}
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=bad)
        self.assertIn("error", result)

    def test_approve_with_challenges_missing_required_keys_is_rejected(self) -> None:
        bad = [{"claim": "x"}, {"claim": "y"}, {"claim": "z"}]  # missing concern + rec
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=bad)
        self.assertIn("error", result)

    def test_needs_revision_with_zero_challenges_is_accepted(self) -> None:
        # Blocking the design doesn't need >=3 — same as Cutover 13
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="needs_revision", challenges=[])
        self.assertNotIn("error", result)
        page = self.reg.workhub.get_design_page(self.page["id"])
        self.assertEqual(page["status"], "needs_revision")

    def test_review_history_appended(self) -> None:
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD_CHALLENGES)
        page = self.reg.workhub.get_design_page(self.page["id"])
        hist = (page.get("metadata") or {}).get("review_history") or []
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["state"], "approve")
        self.assertEqual(len(hist[0]["challenges"]), 3)
        self.assertEqual(hist[0]["by"], "architect_reviewer")

    def test_is_design_approved_returns_false_when_under_review(self) -> None:
        self.assertFalse(self.reg.workhub.is_design_approved(self.page["id"]))

    def test_is_design_approved_returns_false_for_unknown_page(self) -> None:
        self.assertFalse(self.reg.workhub.is_design_approved("nope"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_design_review -v 2>&1 | tail -20
```

Expected: failures — methods don't exist; `create_page` likely doesn't accept `kind` kwarg either.

- [ ] **Step 3: Extend `create_page` to accept `kind` and `metadata`**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, find the `create_page` signature (line ~25) and extend:

```python
    def create_page(self, title: str, parent: str = None,
                    attendees: Optional[List[str]] = None, agent: str = "",
                    kind: str = "general", metadata: Optional[dict] = None) -> dict:
```

In the page dict assembly, add `"kind": kind` and `"metadata": metadata or {}`. Keep the existing default `status="active"`.

For `kind="design"`, override the default status to `"draft"` (the rest of the flow handles it). Add this inside `create_page` before the dict assembly:

```python
        default_status = "draft" if kind == "design" else "active"
```

Then `"status": default_status` in the page dict.

- [ ] **Step 4: Implement the 5 new methods**

Add these methods on `WorkHub` (near `create_page`):

```python
    _VALID_DESIGN_REVIEW_STATES = {"approve", "needs_revision", "comment"}

    def get_design_page(self, page_id: str) -> Optional[dict]:
        page = self.stores.pages.get(page_id)
        if not page or page.get("kind") != "design":
            return None
        return page

    def submit_design_for_review(self, page_id: str, agent: str = "") -> dict:
        page = self.get_design_page(page_id)
        if not page:
            return {"error": f"design page not found: {page_id}"}
        if page.get("status") != "draft":
            return {"error": f"cannot submit for review; status is {page.get('status')!r}, expected 'draft'"}
        updated = dict(page)
        updated["status"] = "under_review"
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        actor = agent or "workhub"
        self.stores.pages.update(lambda m: m.set(page_id, updated, actor),
                                  change_info={"agent": actor})
        self._emit("design_submitted_for_review", updated,
                    recipients=updated.get("attendees", []) or [],
                    priority="high")
        return updated

    def submit_design_review(self, page_id: str, reviewer: str, state: str,
                              challenges: Optional[List[dict]] = None) -> dict:
        page = self.get_design_page(page_id)
        if not page:
            return {"error": f"design page not found: {page_id}"}
        if state not in self._VALID_DESIGN_REVIEW_STATES:
            return {"error": f"invalid state: {state!r}"}

        # Substantive validation for approve only
        if state == "approve":
            challenges = challenges or []
            substantive = []
            for c in challenges:
                if not isinstance(c, dict):
                    continue
                claim = (c.get("claim") or "").strip()
                concern = (c.get("concern") or "").strip()
                rec = (c.get("recommendation") or "").strip()
                if claim and concern and rec:
                    substantive.append({"claim": claim, "concern": concern,
                                         "recommendation": rec})
            if len(substantive) < 3:
                return {"error": "design approve requires at least 3 substantive "
                                  "challenges, each with non-empty claim/concern/recommendation"}
            challenges = substantive

        import uuid
        review_id = f"drev_{uuid.uuid4().hex[:10]}"
        now = time.time()
        review = {
            "review_id": review_id, "at": now, "by": reviewer,
            "state": state, "challenges": challenges or [],
        }

        updated = dict(page)
        meta = dict(updated.get("metadata") or {})
        history = list(meta.get("review_history") or [])
        history.append(review)
        meta["review_history"] = history
        updated["metadata"] = meta

        if state == "approve":
            updated["status"] = "approved"
        elif state == "needs_revision":
            updated["status"] = "needs_revision"
        # comment: no transition

        updated["_updated_by"] = reviewer
        updated["_updated_at"] = now
        self.stores.pages.update(lambda m: m.set(page_id, updated, reviewer),
                                  change_info={"agent": reviewer})
        self._emit(f"design_review_{state}", updated,
                    recipients=updated.get("attendees", []) or [],
                    priority="high")
        return updated

    def is_design_approved(self, page_id: str) -> bool:
        page = self.get_design_page(page_id)
        return bool(page and page.get("status") == "approved")

    def list_pending_design_reviews(self) -> List[dict]:
        return [p for p in (self.stores.pages.value() or {}).values()
                if p.get("kind") == "design" and p.get("status") == "under_review"]
```

If `time` and `uuid` aren't already imported at the top of the file, they should be (the file uses them extensively for tasks already — verify; if not import them).

- [ ] **Step 5: Verify 14 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_design_review -v 2>&1 | tail -25
```

Expected: 14 tests OK.

- [ ] **Step 6: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 548 OK (534 + 14 new). If `create_page` extension breaks existing tests because they don't expect `kind` or `metadata` on the stored page, the new fields default to safe values — should not break. But if a test does deep equality on the page dict, update it minimally.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_design_review.py
git commit -m "WorkHub: add design-review lifecycle (>=3 substantive challenges for approve)"
```

---

## Task 3: `design_gate` module — `assert_design_approved`

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/design_gate.py`
- Create: `agent/tests/test_design_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_design_gate.py`:

```python
"""Tests for the design_gate helper (Cutover 14)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.design_gate import (  # noqa: E402
    DesignNotApprovedError, assert_design_approved, is_design_approved,
)


_GOOD = [
    {"claim": "a", "concern": "b", "recommendation": "c"},
    {"claim": "d", "concern": "e", "recommendation": "f"},
    {"claim": "g", "concern": "h", "recommendation": "i"},
]


class DesignGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="design_gate_"))
        self.reg = HubRegistry(self.tmp)
        self.page = self.reg.workhub.create_page(
            title="design", agent="design", kind="design")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assert_raises_for_unknown_page(self) -> None:
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, "nope")

    def test_assert_raises_for_non_design_page(self) -> None:
        other = self.reg.workhub.create_page(title="x", agent="orch", kind="meeting")
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, other["id"])

    def test_assert_raises_for_draft(self) -> None:
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])

    def test_assert_raises_for_under_review(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])

    def test_assert_passes_after_approval(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD)
        # No exception expected
        assert_design_approved(self.reg.workhub, self.page["id"])

    def test_is_design_approved_returns_bool(self) -> None:
        self.assertFalse(is_design_approved(self.reg.workhub, self.page["id"]))
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD)
        self.assertTrue(is_design_approved(self.reg.workhub, self.page["id"]))

    def test_error_message_includes_page_id_and_actual_status(self) -> None:
        try:
            assert_design_approved(self.reg.workhub, self.page["id"])
        except DesignNotApprovedError as e:
            msg = str(e)
            self.assertIn(self.page["id"], msg)
            self.assertIn("draft", msg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_gate -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the gate module**

Create `agent/env_generator/llm_generator/multi_agent/runtime/design_gate.py`:

```python
"""Design-approval gate (Cutover 14).

Downstream agents (backend/database/frontend) call `assert_design_approved`
at the top of any task that references a design page. The raise signals the
caller (and via prompt rules, the LLM) that work cannot start until the
Architect Reviewer has approved the design.
"""

from __future__ import annotations


class DesignNotApprovedError(RuntimeError):
    pass


def assert_design_approved(workhub, page_id: str) -> None:
    page = workhub.get_design_page(page_id) if hasattr(workhub, "get_design_page") else None
    if page is None:
        raise DesignNotApprovedError(
            f"design page {page_id!r} not found or not a design-kind page")
    status = page.get("status")
    if status != "approved":
        raise DesignNotApprovedError(
            f"design page {page_id!r} is not approved (current status: {status!r}); "
            "downstream implementation must wait until status='approved'")


def is_design_approved(workhub, page_id: str) -> bool:
    try:
        assert_design_approved(workhub, page_id)
        return True
    except DesignNotApprovedError:
        return False


__all__ = ["DesignNotApprovedError", "assert_design_approved", "is_design_approved"]
```

- [ ] **Step 4: Verify 7 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_gate -v 2>&1 | tail -15
```

Expected: 7 OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 555 OK (548 + 7 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/design_gate.py agent/tests/test_design_gate.py
git commit -m "Add design_gate: assert_design_approved raises DesignNotApprovedError if status != approved"
```

---

## Task 4: Design LLM tools

4 tools: `design_submit_for_review`, `design_submit_review`, `design_list_pending_review`, `design_get_status`.

**Files:**
- Create: `agent/env_generator/llm_generator/tools/design_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Create: `agent/tests/test_design_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_design_tools.py`:

```python
"""Tests for design LLM tools (Cutover 14)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.design_tools import (  # noqa: E402
    DesignSubmitForReviewTool, DesignSubmitReviewTool,
    DesignListPendingReviewTool, DesignGetStatusTool,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_GOOD = [
    {"claim": "a", "concern": "b", "recommendation": "c"},
    {"claim": "d", "concern": "e", "recommendation": "f"},
    {"claim": "g", "concern": "h", "recommendation": "i"},
]


class DesignToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="design_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.page = self.reg.workhub.create_page(
            title="x", agent="design", kind="design")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_submit_for_review_transitions_status(self) -> None:
        t = DesignSubmitForReviewTool(agent_id="design", hub_workspace=self.reg)
        result = _run_async(t._run(page_id=self.page["id"]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["status"], "under_review")

    def test_submit_review_with_3_challenges_approves(self) -> None:
        DesignSubmitForReviewTool(agent_id="design", hub_workspace=self.reg)
        # transition draft -> under_review via service so tool isn't required for setup
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        t = DesignSubmitReviewTool(agent_id="architect_reviewer", hub_workspace=self.reg)
        result = _run_async(t._run(page_id=self.page["id"], state="approve",
                                    challenges=_GOOD))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["status"], "approved")

    def test_submit_review_with_2_challenges_fails(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        t = DesignSubmitReviewTool(agent_id="architect_reviewer", hub_workspace=self.reg)
        result = _run_async(t._run(page_id=self.page["id"], state="approve",
                                    challenges=_GOOD[:2]))
        self.assertFalse(result.success)

    def test_list_pending_returns_under_review_pages(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        t = DesignListPendingReviewTool(agent_id="architect_reviewer",
                                         hub_workspace=self.reg)
        result = _run_async(t._run())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["pending"]), 1)

    def test_get_status_returns_current_status(self) -> None:
        t = DesignGetStatusTool(agent_id="backend", hub_workspace=self.reg)
        r = _run_async(t._run(page_id=self.page["id"]))
        self.assertTrue(r.success)
        self.assertEqual(r.data["status"], "draft")
        self.assertFalse(r.data["approved"])

    def test_get_status_unknown_page_fails(self) -> None:
        t = DesignGetStatusTool(agent_id="backend", hub_workspace=self.reg)
        r = _run_async(t._run(page_id="nope"))
        self.assertFalse(r.success)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_tools -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the tools**

Create `agent/env_generator/llm_generator/tools/design_tools.py`. Mirror the bug_tools / run_tools convention (HubTool base, NAME/DESCRIPTION/PARAMETERS, async `_run`, `_finalize_hub_tools`, `create_*_tools(agent_id, hub_workspace)` factory):

```python
"""Design-review LLM tools (Cutover 14)."""

from __future__ import annotations

from typing import Any

from .hub_tools import HubTool, _finalize_hub_tools
from ._base import ToolResult


class DesignSubmitForReviewTool(HubTool):
    NAME = "design_submit_for_review"
    DESCRIPTION = ("Design agent transitions a draft design page (kind='design') "
                    "to status='under_review'. Architect Reviewer will then pick it up.")
    PARAMETERS = {
        "type": "object",
        "properties": {"page_id": {"type": "string"}},
        "required": ["page_id"],
    }

    async def _run(self, *, page_id: str) -> ToolResult:
        result = self._hubs.workhub.submit_design_for_review(page_id, agent=self._agent_id)
        if isinstance(result, dict) and result.get("error"):
            return ToolResult(success=False, error_message=result["error"])
        return ToolResult(success=True, data={"page": result})


class DesignSubmitReviewTool(HubTool):
    NAME = "design_submit_review"
    DESCRIPTION = ("Architect Reviewer submits a design review. For state='approve' "
                    "you MUST supply at least 3 challenges, each with non-empty "
                    "claim/concern/recommendation. Rubber-stamp = rejected.")
    PARAMETERS = {
        "type": "object",
        "properties": {
            "page_id": {"type": "string"},
            "state": {"type": "string", "enum": ["approve", "needs_revision", "comment"]},
            "challenges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "concern": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["claim", "concern", "recommendation"],
                },
                "default": [],
            },
        },
        "required": ["page_id", "state"],
    }

    async def _run(self, *, page_id: str, state: str,
                    challenges: list = None) -> ToolResult:
        result = self._hubs.workhub.submit_design_review(
            page_id, reviewer=self._agent_id, state=state,
            challenges=challenges or [])
        if isinstance(result, dict) and result.get("error"):
            return ToolResult(success=False, error_message=result["error"])
        return ToolResult(success=True, data={"page": result})


class DesignListPendingReviewTool(HubTool):
    NAME = "design_list_pending_review"
    DESCRIPTION = "List design pages awaiting architect review (status='under_review')."
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        pending = self._hubs.workhub.list_pending_design_reviews()
        # Return small summaries
        summaries = [{
            "id": p["id"], "title": p.get("title"),
            "design_subject": (p.get("metadata") or {}).get("design_subject"),
            "submitted_at": p.get("_updated_at"),
        } for p in pending]
        return ToolResult(success=True, data={"pending": summaries})


class DesignGetStatusTool(HubTool):
    NAME = "design_get_status"
    DESCRIPTION = ("Get the current status of a design page. Used by downstream agents "
                    "(backend/database/frontend) BEFORE starting work: refuse if not "
                    "'approved'.")
    PARAMETERS = {
        "type": "object",
        "properties": {"page_id": {"type": "string"}},
        "required": ["page_id"],
    }

    async def _run(self, *, page_id: str) -> ToolResult:
        page = self._hubs.workhub.get_design_page(page_id)
        if page is None:
            return ToolResult(success=False,
                              error_message=f"design page not found: {page_id}")
        return ToolResult(success=True, data={
            "page_id": page_id,
            "status": page.get("status"),
            "approved": page.get("status") == "approved",
            "review_count": len((page.get("metadata") or {}).get("review_history") or []),
        })


_DESIGN_TOOLS = [
    DesignSubmitForReviewTool, DesignSubmitReviewTool,
    DesignListPendingReviewTool, DesignGetStatusTool,
]
_finalize_hub_tools(_DESIGN_TOOLS)


def create_design_tools(agent_id: str = "", hub_workspace: Any = None) -> list:
    return [cls(agent_id=agent_id, hub_workspace=hub_workspace) for cls in _DESIGN_TOOLS]


__all__ = [
    "DesignSubmitForReviewTool", "DesignSubmitReviewTool",
    "DesignListPendingReviewTool", "DesignGetStatusTool",
    "create_design_tools",
]
```

- [ ] **Step 4: Register the bundle**

In `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`, mirror the `_bundle_bug_tools` pattern:

```python
from tools.design_tools import create_design_tools

def _bundle_design_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(
        create_design_tools(agent_id=context.agent_id or context.agent_type,
                            hub_workspace=context.hub_workspace),
        ("design", "hub"),
    )

# In TOOL_BUNDLE_REGISTRY (after run_tools):
"design_tools": _bundle_design_tools,

# In TOOL_BUNDLE_REQUIREMENTS:
"design_tools": {"design"},
```

- [ ] **Step 5: Verify 6 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_tools -v 2>&1 | tail -15
```

Expected: 6 OK.

- [ ] **Step 6: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 561 OK (555 + 6 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/tools/design_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/tests/test_design_tools.py
git commit -m "Add design_tools LLM surface (submit_for_review / submit_review / list_pending / get_status)"
```

---

## Task 5: `architect_reviewer` agent profile

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_architect_reviewer_config.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_architect_reviewer_config.py`:

```python
"""Tests for architect_reviewer agent profile (Cutover 14)."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class ArchitectReviewerProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_profile_exists(self) -> None:
        self.assertIn("architect_reviewer", self.cfg.get("profiles", {}))

    def test_profile_has_design_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["architect_reviewer"]
        self.assertIn("design_tools", prof.get("tool_bundles", []))

    def test_profile_has_workhub_apihub_eventhub_tools(self) -> None:
        prof = self.cfg["profiles"]["architect_reviewer"]
        bundles = set(prof.get("tool_bundles", []))
        for required in ("workhub_tools", "apihub_tools", "eventhub_tools"):
            self.assertIn(required, bundles)

    def test_profile_uses_dedicated_prompt(self) -> None:
        prof = self.cfg["profiles"]["architect_reviewer"]
        template = (prof.get("prompts") or {}).get("template", "")
        self.assertTrue(template.endswith("architect_reviewer_agent.j2"))

    def test_profile_cannot_deliver(self) -> None:
        prof = self.cfg["profiles"]["architect_reviewer"]
        flags = prof.get("flags", {}) or {}
        self.assertFalse(flags.get("can_deliver", False))

    def test_design_tools_added_to_design_backend_database_frontend(self) -> None:
        for prof_name in ("design", "backend", "database", "frontend"):
            prof = self.cfg["profiles"][prof_name]
            self.assertIn("design_tools", prof.get("tool_bundles", []),
                            f"{prof_name} missing design_tools bundle")
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_architect_reviewer_config -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `agents_config.yaml`**

Add `architect_reviewer` profile (mirror `bug_triage_orchestrator` shape) under `profiles:`:

```yaml
  architect_reviewer:
    name: "Architect Reviewer"
    description: "Reviews design docs before downstream implementation. Challenges design assumptions (>=3 substantive challenges per approve). Never writes code."
    tool_categories: ["reasoning", "communication", "memory", "knowledge_read", "knowledge_write", "analysis", "workhub", "apihub", "eventhub", "hub", "design"]
    include_vision: false
    timeout: 3600
    prompts:
      template: "v2/architect_reviewer_agent.j2"
      system_macro: "architect_reviewer_system_prompt"
      task_macros:
        full: "architect_reviewer_task_prompt"
      context_vars: []
    flags:
      coordinator: false
      can_deliver: false
      team_lead: false
    tool_bundles:
      - memory_tools
      - analysis_tools
      - knowledge_read_tools
      - knowledge_write_tools
      - workhub_tools
      - apihub_tools
      - eventhub_tools
      - design_tools
    deny_tools: []
    execution_pipeline:
      stages: [hub_pulse, runtime_team_status, planning, retrieve_context, action, hub_commit_gate, knowledge_sync]
      max_tool_calls_per_stage:
        planning: 1
        retrieve_context: 3
        action: 5
        hub_commit_gate: 0
        knowledge_sync: 2
```

Also add `design_tools` to `tool_bundles` of these profiles (find each in the yaml and append):
- `design` profile
- `backend` profile
- `database` profile
- `frontend` profile

And add `"design"` to each of their `tool_categories` lists.

- [ ] **Step 4: Verify 6 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_architect_reviewer_config -v 2>&1 | tail -10
```

Expected: 6 OK.

- [ ] **Step 5: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 567 OK (561 + 6 new). If `test_agents_config_stages.py` breaks because of profile-count assertions, update it minimally.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_architect_reviewer_config.py
# include test fixture updates if any
git commit -m "Add architect_reviewer agent profile + wire design_tools into design/backend/database/frontend"
```

---

## Task 6: Architect Reviewer prompt

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/prompts/v2/architect_reviewer_agent.j2`
- Create: `agent/tests/test_architect_reviewer_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_architect_reviewer_prompt.py`:

```python
"""Tests for architect_reviewer prompt (Cutover 14)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class ArchitectReviewerPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("architect_reviewer_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.architect_reviewer_system_prompt()

    def test_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.system.strip()), 300)

    def test_prompt_mentions_3_challenges_minimum(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "3 CHALLENGES" in upper or "THREE CHALLENGES" in upper
            or ">=3" in upper or "AT LEAST 3" in upper,
            "prompt must enforce >=3 challenges for approve",
        )

    def test_prompt_mentions_claim_concern_recommendation(self) -> None:
        upper = self.system.upper()
        for token in ("CLAIM", "CONCERN", "RECOMMENDATION"):
            self.assertIn(token, upper, f"prompt missing required field: {token}")

    def test_prompt_forbids_code_edits(self) -> None:
        upper = self.system.upper()
        self.assertIn("NEVER", upper)
        self.assertTrue("CODE" in upper or "IMPLEMENT" in upper)

    def test_prompt_describes_lifecycle(self) -> None:
        upper = self.system.upper()
        self.assertIn("DRAFT", upper)
        self.assertIn("UNDER_REVIEW", upper)
        self.assertIn("APPROVED", upper)
        self.assertIn("NEEDS_REVISION", upper)

    def test_prompt_lists_step_pipeline_stages(self) -> None:
        for stage in ("HUB PULSE", "INTEGRITY CHECK"):
            self.assertIn(stage, self.system.upper())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_architect_reviewer_prompt -v 2>&1 | tail -10
```

Expected: TemplateNotFound.

- [ ] **Step 3: Author the prompt**

Create `agent/env_generator/llm_generator/multi_agent/prompts/v2/architect_reviewer_agent.j2`:

```jinja
{# Architect Reviewer - Cutover 14 #}
{# Reviews design pages (kind="design") before downstream agents start work.
   NEVER implements; only critiques. #}

{% macro architect_reviewer_system_prompt() -%}
You are the **Architect Reviewer** - the staff engineer who interrogates designs before three downstream agents (backend, database, frontend) commit to building them.

## ROLE
- **DESIGN AGENT** produces design pages (kind="design") and submits them for review by transitioning status="draft" -> "under_review".
- **YOU (Architect Reviewer)** receive the design, identify and articulate at least 3 substantive challenges to its assumptions, and either approve (status -> "approved") or send back (status -> "needs_revision").
- **DOWNSTREAM AGENTS** are structurally blocked from acting on a design until status="approved". Your approval is the gate.

## LIFECYCLE
```
draft -> under_review -> approved | needs_revision
```
- `draft`: design agent is still editing
- `under_review`: design agent submitted; your queue
- `approved`: backend/database/frontend can start
- `needs_revision`: design agent must address feedback and re-submit

## HARD RULES
1. **NEVER write code.** You have no file-write tools. Your only outputs are `design_submit_review` calls, EventHub notifications, and Knowledge writes for architecture decisions.
2. **For state="approve" you MUST supply at least 3 substantive challenges.** Each challenge MUST have:
   - `claim`: what the design literally says
   - `concern`: what could go wrong, or what the design didn't consider
   - `recommendation`: what should change, or why the design's choice is still right despite the concern
   - All three fields non-empty. Whitespace-only fields don't count.
3. **3 is a floor, not a ceiling.** If the design has fewer than 3 things to challenge, you almost certainly didn't look hard enough. Common angles to find at least 3:
   - Read path (latency, caching, hot keys)
   - Write path (consistency, concurrency, ordering)
   - Failure mode (what happens when X is down)
   - Scale (what breaks at 10x current load)
   - Security (auth, authorization, data exposure)
   - Operations (observability, on-call, rollback)
4. **Use `state="needs_revision"`** when the design has fundamental gaps. The 3-challenge floor doesn't apply to needs_revision - one well-articulated blocker is enough.
5. **`state="comment"`** is for non-blocking observations that don't transition status.

## STEP PIPELINE
Every step begins with **HUB PULSE** (engine-forced snapshot of all 4 hubs) and ends with an **INTEGRITY CHECK** (hub_commit_gate verifies you actually advanced design pages through the lifecycle). Engine forces these regardless of your stage list.

## YOUR TOOLS
- `design_list_pending_review()` -> queue of designs awaiting your review
- `design_submit_review(page_id, state, challenges=[...])` -> the main action
- Read APIHub and CodeHub via their tools to understand existing surfaces a design is changing
- Read prior architecture decisions via knowledge_read tools

## TYPICAL STEP
1. `design_list_pending_review()` -> pick the oldest queue entry
2. Read the design page contents + any referenced APIHub schemas + CodeHub state
3. Form at least 3 challenges (claim/concern/recommendation triples)
4. `design_submit_review(page_id, state="approve", challenges=[...])`
   OR `design_submit_review(page_id, state="needs_revision", challenges=[...])` with 1+ blocker
5. Publish an EventHub `design_review_completed` notification so design + downstream agents see the result
{%- endmacro %}

{% macro architect_reviewer_task_prompt() -%}
Begin your review cycle. Your hub_pulse will list designs awaiting review (status=under_review).
For each pending design (oldest first):
  - Read the page's contents + linked APIHub schemas + relevant CodeHub state
  - Identify at least 3 substantive challenges (claim/concern/recommendation triples)
  - Submit your review: approve (if challenges resolved internally to "still right") or needs_revision (if at least one blocks)
  - Publish a design_review_completed event so design agent + downstream agents know
After processing the queue, end the step.
{%- endmacro %}
```

- [ ] **Step 4: Verify 6 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_architect_reviewer_prompt -v 2>&1 | tail -10
```

Expected: 6 OK.

- [ ] **Step 5: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 573 OK (567 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/architect_reviewer_agent.j2 agent/tests/test_architect_reviewer_prompt.py
git commit -m "Add architect_reviewer_agent.j2 prompt (>=3 substantive challenges, never writes code)"
```

---

## Task 7: Update Design + downstream prompts

Design agent learns to publish kind="design" + submit_for_review + await approval. Backend/database/frontend learn to check `design_get_status` before starting work.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- Create: `agent/tests/test_design_pipeline_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_design_pipeline_prompts.py`:

```python
"""Tests that design / backend / database / frontend prompts teach the design-gate contract."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


def _render(tpl_name: str, macros: list) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
    tpl = env.get_template(tpl_name)
    mod = tpl.make_module()
    for macro_name in macros:
        if hasattr(mod, macro_name):
            try:
                return getattr(mod, macro_name)()
            except TypeError:
                # Some macros need positional args (e.g. review_worker pattern)
                return getattr(mod, macro_name)(".", "")
    raise RuntimeError(f"none of {macros!r} found in {tpl_name}")


class DesignAgentPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("design_agent.j2",
                              ["design_specifics", "design_system_prompt"])

    def test_design_prompt_mentions_kind_design(self) -> None:
        self.assertIn("KIND=\"DESIGN\"".upper(), self.system.upper())

    def test_design_prompt_mentions_submit_for_review(self) -> None:
        self.assertIn("DESIGN_SUBMIT_FOR_REVIEW", self.system.upper())

    def test_design_prompt_mentions_await_approval(self) -> None:
        upper = self.system.upper()
        self.assertTrue("AWAIT" in upper or "WAIT" in upper)


class DownstreamAgentDesignGatePromptTests(unittest.TestCase):
    def _assert_design_gate_block(self, prompt_text: str, agent_name: str):
        upper = prompt_text.upper()
        self.assertIn("DESIGN_GET_STATUS", upper,
                        f"{agent_name} missing design_get_status reference")
        self.assertIn("APPROVED", upper,
                        f"{agent_name} missing 'approved' check")
        self.assertTrue(
            any(p in upper for p in ("REFUSE", "DO NOT START", "BLOCK", "MUST NOT")),
            f"{agent_name} missing refusal clause",
        )

    def test_backend_prompt_teaches_design_gate(self) -> None:
        sys_text = _render("backend_agent.j2",
                            ["backend_specifics", "backend_system_prompt"])
        self._assert_design_gate_block(sys_text, "backend")

    def test_database_prompt_teaches_design_gate(self) -> None:
        sys_text = _render("database_agent.j2",
                            ["database_specifics", "database_system_prompt"])
        self._assert_design_gate_block(sys_text, "database")

    def test_frontend_prompt_teaches_design_gate(self) -> None:
        sys_text = _render("frontend_agent.j2",
                            ["frontend_specifics", "frontend_system_prompt"])
        self._assert_design_gate_block(sys_text, "frontend")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_pipeline_prompts -v 2>&1 | tail -15
```

Expected: failures.

- [ ] **Step 3: Update design_agent.j2**

In `agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2`, locate the `design_specifics` macro (Cutover 8 pattern). Add a "### DESIGN REVIEW DISCIPLINE (Cutover 14)" block:

```jinja
### DESIGN REVIEW DISCIPLINE (Cutover 14)
When you produce a design doc, you MUST:
1. Create the design as a WorkHub page with `kind="design"` (use the standard `workhub_create_page` tool with `kind="design"` and `metadata={"design_subject": "..."}`). New design pages start in status="draft".
2. When the design is ready for review, call `design_submit_for_review(page_id)`. This transitions status to "under_review".
3. **AWAIT** the Architect Reviewer's verdict before declaring the design complete. The reviewer's possible outcomes:
   - `state="approve"` -> status becomes "approved"; downstream agents can start
   - `state="needs_revision"` -> read the challenges in `metadata.review_history`, revise the page, then re-submit
   - `state="comment"` -> informational; no transition
4. DO NOT start spawning backend/database/frontend implementation tasks until your design is approved. The downstream agents are structurally blocked from acting on un-approved designs (they will refuse via `design_get_status`).
```

- [ ] **Step 4: Update backend_agent.j2 + database_agent.j2 + frontend_agent.j2**

In each of these prompts, locate the per-agent specifics macro and add the same block (adapted by name):

```jinja
### DESIGN APPROVAL CHECK (Cutover 14)
BEFORE starting work on any task that references a design page (`design_page_id` in task metadata, or any task that says "implement X per design page_xxx"):
1. Call `design_get_status(page_id=<the design page>)`
2. If `approved=False`, REFUSE to start. Reply with a comment explaining you're blocked on the design review and DO NOT make any code changes.
3. Only proceed when `approved=True`.

The Architect Reviewer's approval is a hard gate. Skipping it means you implement against an un-validated design, which is the exact failure mode this stage was added to prevent. Don't try to be helpful by guessing — your refusal IS the helpful action.
```

- [ ] **Step 5: Verify 6 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_pipeline_prompts -v 2>&1 | tail -15
```

Expected: 6 OK.

- [ ] **Step 6: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 579 OK (573 + 6 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/design_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2 agent/tests/test_design_pipeline_prompts.py
git commit -m "Design + backend/database/frontend prompts: teach kind=design lifecycle + design_get_status gate"
```

---

## Task 8: End-to-end design-review test

**Files:**
- Create: `agent/tests/test_design_review_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_design_review_e2e.py`:

```python
"""E2E: rubber-stamp design review blocked; substantive review unblocks downstream."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.design_gate import (  # noqa: E402
    DesignNotApprovedError, assert_design_approved,
)


_GOOD = [
    {"claim": "design says cache in Redis",
     "concern": "Redis lacks per-user TTL",
     "recommendation": "use namespaces or Memcached"},
    {"claim": "design says polling /feed",
     "concern": "battery drain on mobile",
     "recommendation": "use SSE"},
    {"claim": "design says single table",
     "concern": "hot shard at scale",
     "recommendation": "partition by user_id"},
]


class DesignReviewE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dr_e2e_"))
        self.reg = HubRegistry(self.tmp)
        self.page = self.reg.workhub.create_page(
            title="Feed design", agent="design", kind="design",
            attendees=["architect_reviewer"],
            metadata={"design_subject": "feed"})

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downstream_blocked_in_draft(self) -> None:
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])

    def test_downstream_still_blocked_under_review(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])

    def test_rubber_stamp_approve_blocked_at_submit(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        result = self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=[])
        self.assertIn("error", result)
        # Status unchanged
        page = self.reg.workhub.get_design_page(self.page["id"])
        self.assertEqual(page["status"], "under_review")
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])

    def test_substantive_approve_unblocks_downstream(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="approve", challenges=_GOOD)
        # Now downstream is unblocked
        assert_design_approved(self.reg.workhub, self.page["id"])

    def test_needs_revision_keeps_downstream_blocked(self) -> None:
        self.reg.workhub.submit_design_for_review(self.page["id"], agent="design")
        self.reg.workhub.submit_design_review(
            self.page["id"], reviewer="architect_reviewer",
            state="needs_revision", challenges=[
                {"claim": "x", "concern": "y", "recommendation": "z"}])
        with self.assertRaises(DesignNotApprovedError):
            assert_design_approved(self.reg.workhub, self.page["id"])
        page = self.reg.workhub.get_design_page(self.page["id"])
        self.assertEqual(page["status"], "needs_revision")
        # Design agent revises and re-submits via fresh draft transition
        # (real workflow would re-edit; we just verify the lifecycle is intact)
        hist = (page.get("metadata") or {}).get("review_history") or []
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["state"], "needs_revision")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the 5 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_design_review_e2e -v 2>&1 | tail -10
```

Expected: 5 OK (Tasks 2 + 3 wired everything; this exercises the result).

- [ ] **Step 3: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 584 OK (579 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_design_review_e2e.py
git commit -m "Add end-to-end design-review test: rubber-stamp blocked, substantive unblocks downstream"
```

---

## Task 9: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/15-design-review-stage.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 584 OK. STOP if anything fails.

- [ ] **Step 2: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Write migration log**

Create `docs/superpowers/migration-logs/15-design-review-stage.md`:

```markdown
# Cutover 14: Design Review Stage

**Branch:** `haibotong-cutover-14-design-review`
**Date:** 2026-05-24

## What

Added a mandatory architect-review hop between Design and downstream implementation.

- Design docs ride on WorkHub pages with `kind="design"`. New lifecycle: `draft -> under_review -> approved | needs_revision`.
- New `architect_reviewer` agent profile (12th profile). Subscribes only to design pages; never writes code.
- `submit_design_review(state="approve")` requires >=3 substantive `challenges` (each with non-empty `claim`/`concern`/`recommendation`). Mirrors Cutover-13's substantive-review pattern.
- New `runtime/design_gate.py` exposes `assert_design_approved(workhub, page_id)` raising `DesignNotApprovedError` if status != "approved".
- Downstream agents (backend/database/frontend) get the `design_tools` bundle; prompts teach them to call `design_get_status` before starting work and refuse if not approved.

## Commits

(fill from `git log --oneline`)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 534 OK -> 584 OK (+50 new)

## New surfaces
- `design_gate.py` — DesignNotApprovedError + assert_design_approved + is_design_approved
- `design_tools.py` — 4 tools (submit_for_review, submit_review, list_pending_review, get_status)
- `architect_reviewer_agent.j2` — new agent prompt
- WorkHub: 5 new methods (submit_design_for_review, submit_design_review, is_design_approved, list_pending_design_reviews, get_design_page)
- agents_config.yaml: 12 profiles (was 11)

## Updated prompts
- design_agent.j2: must use kind="design", call submit_for_review, await approval
- backend_agent.j2 / database_agent.j2 / frontend_agent.j2: must call design_get_status; refuse if not approved

## Known gaps (future cutovers)
- Architect reviewer's challenges aren't semantically validated — only shape (3 entries, all 3 fields non-empty). A reviewer could submit garbage triples. Future work: knowledge-base check that challenges actually engage with the design content.
- No "designate the design page" mechanism on tasks today — orchestrator must include `design_page_id` in task metadata for downstream agents to know which page to check.
```

- [ ] **Step 4: Commit log**

```bash
git add docs/superpowers/migration-logs/15-design-review-stage.md
git commit -m "Add Cutover 14 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-14-design-review 2>&1 | tail -5
```

- [ ] **Step 6: Report**

Print: final test counts, commit count, push URL, compare URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:**
- WorkHub design schema + 5 lifecycle helpers — Task 2 ✓
- design_gate module — Task 3 ✓
- design LLM tools — Task 4 ✓
- architect_reviewer profile — Task 5 ✓
- architect_reviewer prompt — Task 6 ✓
- design + downstream prompt updates — Task 7 ✓
- E2E test — Task 8 ✓
- Migration log + push — Task 9 ✓

**2. Placeholder scan:** No "TBD" / "implement later". Every code-change task has actual code shown.

**3. Type consistency:**
- `WorkHub.create_page(..., kind: str = "general", metadata: Optional[dict] = None)` — same signature in tests + impl + downstream callers ✓
- `submit_design_review(page_id, reviewer, state, challenges: Optional[List[dict]] = None)` — challenges shape `{claim, concern, recommendation}` consistent across tests + impl + prompt + tool schema ✓
- `assert_design_approved(workhub, page_id) -> None` raises `DesignNotApprovedError` — same in module + tests + tool DESCRIPTION ✓
- Page lifecycle states `draft / under_review / approved / needs_revision` — consistent in WorkHub + gate + prompts + tool descriptions ✓
- Tool NAMEs: `design_submit_for_review`, `design_submit_review`, `design_list_pending_review`, `design_get_status` — same in tool class + prompts + tests ✓

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 9 ✓
- Baselines green at every task boundary — explicit step ✓
- TDD throughout ✓
- Substantive-approve mirrors Cutover 13's pattern (architectural consistency) ✓
- Design pages reuse existing WorkHub store (no new entity) ✓
