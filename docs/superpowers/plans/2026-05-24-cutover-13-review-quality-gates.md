# Cutover 13: Review Quality Hard Gates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop "LGTM theater" reviews. An `approve` state on a PR review must include (a) ≥1 inline comment citing a specific file + line range from the diff, and (b) ≥1 `considered_alternatives` entry explaining an approach the reviewer evaluated and chose not to recommend. CodeHub rejects approve-state reviews that lack either; the merge-time gate rejects PRs whose ALL-approve reviewer set contains any review that doesn't pass these checks.

**Architecture:** Extend `CodeHub.submit_review` with two structural validations gated by `state == "approve"`. Add a new top-level `considered_alternatives: List[str]` field on the stored review. Extend the existing Cutover-7 merge-time approval gate to additionally verify each approving review meets the substantive-review schema. Update reviewer prompts (`review_worker_agent.j2` and orchestrator-as-reviewer rules in `orchestrator_agent.j2`) to teach the new contract.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Existing surfaces: `CodeHub.submit_review` (this file's pre-Cutover-13 implementation), `CodeHub.merge_pull_request` with L2 verifier+task-completion gate (Cutover 7), `CodeHub.force_merge_pull_request` orchestrator-only bypass (Cutover 7), `codehub_tools` LLM bundle.

---

## Context for Worker

### Why this cutover exists

After Cutover 7 we have a hard rule: PRs need ≥2 reviewers including the orchestrator, all must approve. But "approve" means nothing more than `state == "approve"` — a reviewer agent can submit `submit_review(pr_id, reviewer, state="approve", comments=[], inline_comments=[])` and the PR sails through. In practice this turns the 2-reviewer rule into compliance theater: two agents type "LGTM" and the PR merges with no actual scrutiny.

**Real engineering review needs two things to be substantive:**

1. **Specificity** — reviewer references the actual diff, not the high-level abstract. Concrete proof: at least one inline comment with a real file path + line number tied to lines that exist in the PR's diff.
2. **Critical thinking** — reviewer considered alternative approaches and articulated why they're not taking them. Without this, "approve" is "I read it and didn't see a reason to object," which is a much weaker signal than "I considered options A, B, C and X is the right call here."

This cutover bakes both into the contract.

### The new review payload shape

```python
{
    "id": "review_<hex>",
    "pr_id": "pr_<hex>",
    "reviewer": "backend_reviewer",
    "state": "approve",                     # approve | request_changes | comment
    "comments": [...],                       # existing free-form comments
    "inline_comments": [                     # MUST have >= 1 for state == "approve"
        {"file": "backend/routes/feed.py", "line": 42, "body": "..."},
        ...
    ],
    "considered_alternatives": [             # MUST have >= 1 for state == "approve"
        "Considered fetching from cache directly; rejected because cache lacks user-scoped TTL.",
        ...
    ],
    "submitted_at": <epoch>,
    "_updated_by": "backend_reviewer",
    "_updated_at": <epoch>,
}
```

Both new requirements apply ONLY when `state == "approve"`. `state == "request_changes"` and `state == "comment"` continue to work without these fields — you don't need to explain alternatives when you're blocking a PR.

### Validation behavior

`submit_review` returns `{"error": ...}` (matching the existing error-return pattern) when:
- `state == "approve"` AND `inline_comments` is empty
- `state == "approve"` AND `considered_alternatives` is missing/empty
- `considered_alternatives` is provided but any entry is empty/whitespace-only (defends against `["", ""]`)

The PR's stored `reviews` array is NOT mutated on validation failure. No event is published.

### Merge-time gate behavior

The existing `_is_pr_approved` logic in CodeHub already requires `state == "approve"` from ≥2 reviewers including the mandatory orchestrator. Cutover 13 adds a `_is_review_substantive(review)` helper called inside the approval check. A review where `state == "approve"` but missing the substantive fields is silently treated as **not an approval** for merge-gate purposes (the validation in `submit_review` should have caught it earlier; this is defense-in-depth for stored reviews that pre-date Cutover 13 or were written by buggy tools).

`force_merge_pull_request` (orchestrator-only bypass) bypasses this gate just like it bypasses the others. The audit log entry records the substantive-review skip for forensics.

### LLM tool surface

The existing `codehub_submit_review` tool (from the `codehub_tools` bundle) needs a new `considered_alternatives: List[str]` parameter. Existing callers using the tool without that parameter will get a validation error from `submit_review` if their state is `approve` — which is the intended behavior; existing prompts will be updated in Tasks 5/6.

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (`dt` conda env)
- No Claude trailer on commits
- No emojis in code or prompts
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 8
- Both baselines green at every task boundary: `python agent/tests/run_regressions.py` (7 OK) and `python -m unittest discover agent/tests -p 'test_*.py'` (509 OK after Cutover 12)
- Worktree path: `worktrees/<agent_id>`; default git branch: `master`

---

## File Structure

**New files:**
- `agent/tests/test_codehub_substantive_review.py` — validation tests for `submit_review`
- `agent/tests/test_codehub_merge_substantive_gate.py` — merge-gate tests
- `agent/tests/test_review_quality_e2e.py` — end-to-end: 2 LGTM-only reviews can't merge; 2 substantive can
- `agent/tests/test_review_worker_quality_prompt.py` — prompt assertion tests
- `agent/tests/test_orchestrator_reviewer_quality_prompt.py` — prompt assertion tests

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — extend `submit_review` validation + `_is_pr_approved` substantive check
- `agent/env_generator/llm_generator/tools/hub_tools.py` (or wherever `codehub_submit_review` is defined — re-grep) — add `considered_alternatives` parameter
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/review_worker_agent.j2` — add REVIEW QUALITY block
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — add reviewer-quality reminder to the existing review rules

---

## Task 1: Worktree setup + baseline

**Files:**
- Create: `docs/superpowers/cutover-13-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-13-review-quality
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-13-review-quality`, branched from `haibotong-0521-pipeline-web-tools` at post-Cutover-12 SHA. (If missing: `git worktree add -b haibotong-cutover-13-review-quality .worktrees/haibotong-cutover-13-review-quality haibotong-0521-pipeline-web-tools` from repo root.)

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 509 OK.

- [ ] **Step 3: Inventory current submit_review surface**

```bash
grep -nE "def submit_review" agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py
grep -nE "codehub_submit_review|submit_review" agent/env_generator/llm_generator/tools/hub_tools.py | head -5
```

Record the actual line + LLM-tool location for Task 4. The tool may live in a different file — adjust accordingly.

- [ ] **Step 4: Confirm Cutover-7 strict-approval gate location**

```bash
grep -nE "def _is_pr_approved|MANDATORY_REVIEWER|strict_approval" agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py | head -5
```

Record line numbers — Task 3 will modify `_is_pr_approved`.

- [ ] **Step 5: Write baseline note**

Create `docs/superpowers/cutover-13-baseline.md`:

```markdown
# Cutover 13 Baseline (Review Quality Hard Gates)

## Test counts
- regressions: 7 OK
- discover: 509 OK

## Today's gap
`CodeHub.submit_review(state="approve", inline_comments=[], comments=[])` is
currently accepted. Two such "LGTM" reviews satisfy the Cutover-7 2-reviewer
rule and let the PR merge. This is review-as-compliance-theater.

## After Cutover 13
- `submit_review` rejects `state=="approve"` without >=1 inline_comment cited on a real diff line
- `submit_review` rejects `state=="approve"` without >=1 considered_alternatives entry
- merge-gate `_is_pr_approved` defends in depth: silently downgrades substantively-empty approvals
- review_worker prompt + orchestrator prompt teach the new contract
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/cutover-13-baseline.md
git commit -m "Cutover 13: record pre-flight baseline (regressions 7 OK, discover 509 OK)"
```

---

## Task 2: `submit_review` validates substantive approve

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`
- Create: `agent/tests/test_codehub_substantive_review.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_codehub_substantive_review.py`:

```python
"""Tests for substantive-review validation on CodeHub.submit_review (Cutover 13)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _make_pr(reg, branch="agent/backend", agent="backend"):
    pr = reg.codehub.open_pull_request(
        branch=branch, base="master", title="t", body="b",
        author=agent, agent=agent,
    )
    return pr


_INLINE_OK = [{"file": "backend/x.py", "line": 10, "body": "consider extracting"}]
_ALT_OK = ["considered separate validator module; rejected — too small to extract"]


class SubmitReviewSubstantiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="subst_rev_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = _make_pr(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_approve_with_inline_and_alternatives_is_accepted(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=_ALT_OK)
        self.assertNotIn("error", result)
        self.assertEqual(result["state"], "approve")
        self.assertEqual(result["considered_alternatives"], _ALT_OK)

    def test_approve_without_inline_comments_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=[],
            considered_alternatives=_ALT_OK)
        self.assertIn("error", result)
        self.assertIn("inline_comments", result["error"].lower())

    def test_approve_without_considered_alternatives_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=[])
        self.assertIn("error", result)
        self.assertIn("alternative", result["error"].lower())

    def test_approve_with_missing_considered_alternatives_kwarg_is_rejected(self) -> None:
        # Backwards-compat: existing callers that don't pass considered_alternatives at all
        # must also be rejected when state=="approve".
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK)
        self.assertIn("error", result)
        self.assertIn("alternative", result["error"].lower())

    def test_approve_with_whitespace_only_alternative_is_rejected(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=_INLINE_OK,
            considered_alternatives=["", "   "])
        self.assertIn("error", result)

    def test_request_changes_with_no_inline_no_alternatives_is_accepted(self) -> None:
        # Blocking a PR doesn't need substantive structure — that's a separate signal
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="request_changes",
            inline_comments=[],
            considered_alternatives=[])
        self.assertNotIn("error", result)
        self.assertEqual(result["state"], "request_changes")

    def test_comment_state_does_not_require_substantive_fields(self) -> None:
        result = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="comment",
            inline_comments=[],
            considered_alternatives=[])
        self.assertNotIn("error", result)

    def test_failed_validation_does_not_mutate_pr_reviews_array(self) -> None:
        pr_before = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        reviews_before = list(pr_before.get("reviews", []))
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="r1", state="approve",
            inline_comments=[], considered_alternatives=[])
        pr_after = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertEqual(pr_after.get("reviews", []), reviews_before)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_substantive_review -v 2>&1 | tail -15
```

Expected: most tests fail because:
- `submit_review` doesn't yet accept `considered_alternatives` kwarg (TypeError)
- No validation rejects empty approvals

- [ ] **Step 3: Implement validation**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`, modify `submit_review` signature and add validation:

Find the existing signature:
```python
def submit_review(
    self,
    pr_id: str,
    reviewer: str,
    state: str,
    comments: Optional[List[dict]] = None,
    inline_comments: Optional[List[dict]] = None,
) -> dict:
```

Replace with:
```python
def submit_review(
    self,
    pr_id: str,
    reviewer: str,
    state: str,
    comments: Optional[List[dict]] = None,
    inline_comments: Optional[List[dict]] = None,
    considered_alternatives: Optional[List[str]] = None,
) -> dict:
```

Right after the `pr` lookup (just below `if not pr: return {"error": ...}`), BEFORE the `inline_comments` normalization, add the substantive-approve validation:

```python
        # Cutover 13: substantive-approve gate
        if state == "approve":
            if not inline_comments:
                return {"error": "approve requires at least one inline_comment citing a diff line"}
            alts = [a for a in (considered_alternatives or []) if isinstance(a, str) and a.strip()]
            if not alts:
                return {"error": "approve requires at least one non-empty considered_alternatives entry"}
```

Then, in the review dict assembly (where `comments`, `inline_comments`, etc. are stored), add the new field:

```python
        review = {
            "id": review_id,
            "pr_id": pr_id,
            "reviewer": reviewer,
            "state": state,
            "comments": comments or [],
            "inline_comments": normalized_inline,
            "considered_alternatives": [a for a in (considered_alternatives or []) if isinstance(a, str) and a.strip()],
            "submitted_at": now,
            "_updated_by": reviewer,
            "_updated_at": now,
        }
```

- [ ] **Step 4: Verify 8 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_substantive_review -v 2>&1 | tail -15
```

Expected: 8 OK.

- [ ] **Step 5: Run both baselines + watch existing codehub review tests carefully**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 517 OK (509 + 8 new). **HOWEVER** — pre-existing tests that call `submit_review(state="approve", inline_comments=[])` or omit `considered_alternatives` WILL now fail. Common offenders to update:
- `test_codehub_merge.py`
- `test_codehub_premerge_gate.py`
- `test_codehub_strict_approval.py`
- `test_codehub_force_merge.py`

For each pre-existing test that now fails because it submits a non-substantive approve, add `inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}]` and `considered_alternatives=["considered X; not needed here"]` to the call. **Do not weaken or skip the test** — it was passing because the gate didn't exist; with the gate, the test must now create substantive reviews. This is the cost of the new contract.

If `_is_pr_approved` tests fail in unexpected ways (not from the missing kwargs), STOP and re-read — your validation may be over-aggressive.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py agent/tests/test_codehub_substantive_review.py agent/tests/test_codehub_merge.py agent/tests/test_codehub_premerge_gate.py agent/tests/test_codehub_strict_approval.py agent/tests/test_codehub_force_merge.py
# (only stage the test files you actually had to modify)
git commit -m "CodeHub: submit_review rejects approve without inline_comments + considered_alternatives"
```

---

## Task 3: Merge-gate defense in depth

Even if a buggy tool/test bypasses `submit_review`'s validation and writes a non-substantive review directly to the store, the merge gate should not count it as approval.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`
- Create: `agent/tests/test_codehub_merge_substantive_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_codehub_merge_substantive_gate.py`:

```python
"""Merge-gate defense: PR with non-substantive approve must not be merge-ready (Cutover 13)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_INLINE = [{"file": "backend/x.py", "line": 1, "body": "looked at it"}]
_ALT = ["considered an alt; not needed"]


class MergeSubstantiveGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="merge_subst_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend", base="master", title="t", body="b",
            author="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inject_review_raw(self, reviewer, state, inline_comments=None, considered=None) -> str:
        """Bypass submit_review validation to inject a raw review row."""
        import time, uuid
        rid = f"review_{uuid.uuid4().hex[:10]}"
        review = {
            "id": rid, "pr_id": self.pr["id"], "reviewer": reviewer, "state": state,
            "comments": [], "inline_comments": inline_comments or [],
            "considered_alternatives": considered or [],
            "submitted_at": time.time(),
            "_updated_by": reviewer, "_updated_at": time.time(),
        }
        self.reg.codehub.stores.code_reviews.update(
            lambda m: m.set(rid, review, reviewer), change_info={"agent": reviewer})
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        pr.setdefault("reviews", []).append(rid)
        self.reg.codehub.stores.pull_requests.update(
            lambda m: m.set(self.pr["id"], pr, reviewer), change_info={"agent": reviewer})
        return rid

    def test_two_substantive_approvals_yield_pr_approved_true(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertTrue(self.reg.codehub._is_pr_approved(pr))

    def test_substantive_approve_plus_empty_approve_NOT_approved(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=[], considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))

    def test_substantive_approve_plus_inline_only_NOT_approved(self) -> None:
        # Has inline comments but missing considered_alternatives -> not substantive
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=_INLINE, considered=_ALT)
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=_INLINE, considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))

    def test_two_empty_approvals_NOT_approved(self) -> None:
        self._inject_review_raw("orchestrator", "approve",
                                inline_comments=[], considered=[])
        self._inject_review_raw("reviewer2", "approve",
                                inline_comments=[], considered=[])
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_merge_substantive_gate -v 2>&1 | tail -15
```

Expected: tests fail — `_is_pr_approved` doesn't yet filter out empty approvals.

- [ ] **Step 3: Add `_is_review_substantive` helper + gate filter**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`:

Right above `_is_pr_approved`, add:

```python
    @staticmethod
    def _is_review_substantive(review: dict) -> bool:
        """Cutover 13: an approve-state review must have at least one inline comment AND
        at least one non-empty considered_alternatives entry to count as substantive."""
        if (review or {}).get("state") != "approve":
            return True  # only approve reviews need to be substantive
        if not (review.get("inline_comments") or []):
            return False
        alts = [a for a in (review.get("considered_alternatives") or [])
                if isinstance(a, str) and a.strip()]
        return bool(alts)
```

Then in `_is_pr_approved`, change the line that collects approver reviewers to filter through `_is_review_substantive`:

Find the existing pattern (approx):
```python
approved = {r.get("reviewer") for r in reviews if r.get("state") == "approve"}
```

Change to:
```python
approved = {r.get("reviewer") for r in reviews
            if r.get("state") == "approve" and self._is_review_substantive(r)}
```

- [ ] **Step 4: Verify 4 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_merge_substantive_gate -v 2>&1 | tail -10
```

Expected: 4 OK.

- [ ] **Step 5: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 521 OK (517 + 4 new). If existing tests now fail because they used the legacy-shape `submit_review` and now `_is_pr_approved` rejects their reviews, those fixtures need the same treatment as Task 2 Step 5 — update them to include `considered_alternatives` AND `inline_comments`.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py agent/tests/test_codehub_merge_substantive_gate.py
# include any test fixture updates that were strictly required
git commit -m "CodeHub merge gate: _is_pr_approved filters out non-substantive approve reviews"
```

---

## Task 4: Update `codehub_submit_review` LLM tool

Add `considered_alternatives: List[str]` parameter so reviewer agents can supply it.

**Files:**
- Modify: the tool file containing `codehub_submit_review` (locate it; likely `agent/env_generator/llm_generator/tools/hub_tools.py`)
- Create: `agent/tests/test_codehub_submit_review_tool.py`

- [ ] **Step 1: Locate the tool**

```bash
grep -rnE "class .*SubmitReview|NAME = .codehub_submit_review|submit_review" agent/env_generator/llm_generator/tools/ | head -10
```

Record the path + class name.

- [ ] **Step 2: Write failing test**

Create `agent/tests/test_codehub_submit_review_tool.py`:

```python
"""Test that codehub_submit_review tool accepts + forwards considered_alternatives."""

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

# Probe the tool — class name may be CodeHubSubmitReviewTool / SubmitReviewTool / etc.
from tools.hub_tools import (  # noqa: E402
    create_hub_tools as _create_hub_tools,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _find_submit_review_tool(reg):
    for tool in _create_hub_tools(agent_id="reviewer", hub_workspace=reg):
        if getattr(tool, "NAME", "") == "codehub_submit_review":
            return tool
    raise AssertionError("codehub_submit_review tool not found")


class SubmitReviewToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="srt_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend", base="master", title="t", body="b",
            author="backend", agent="backend")
        self.tool = _find_submit_review_tool(self.reg)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tool_accepts_considered_alternatives(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="approve",
            inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}],
            considered_alternatives=["considered alt A; rejected because B"],
        ))
        self.assertTrue(result.success, f"tool failed: {result.error_message}")

    def test_tool_forwards_empty_alternatives_to_failure(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="approve",
            inline_comments=[{"file": "x.py", "line": 1, "body": "ok"}],
            considered_alternatives=[],
        ))
        self.assertFalse(result.success)

    def test_tool_request_changes_does_not_require_alternatives(self) -> None:
        result = _run_async(self.tool._run(
            pr_id=self.pr["id"], state="request_changes",
            inline_comments=[],
            considered_alternatives=[],
        ))
        self.assertTrue(result.success, f"tool failed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_submit_review_tool -v 2>&1 | tail -10
```

Expected: tool likely doesn't accept the new kwarg.

- [ ] **Step 4: Update the tool**

Open the tool file located in Step 1. The tool class will have:
- `PARAMETERS` (JSON schema dict) — add `considered_alternatives` as `{"type": "array", "items": {"type": "string"}, "default": []}`. Mark as required ONLY if the existing pattern treats `inline_comments` as required (mirror that).
- `_run(self, *, pr_id, state, ...)` signature — add `considered_alternatives: list = None` kwarg
- Pass it through to `self._hubs.codehub.submit_review(..., considered_alternatives=considered_alternatives)`

Update the tool's `DESCRIPTION` to mention the new requirement:

```python
DESCRIPTION = ("Submit a PR review. For state='approve', you MUST supply "
                "at least one inline_comment (citing a real diff line) AND "
                "at least one considered_alternatives entry. Empty approve = rejected.")
```

- [ ] **Step 5: Verify 3 tool tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_codehub_submit_review_tool -v 2>&1 | tail -10
```

Expected: 3 OK.

- [ ] **Step 6: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 524 OK (521 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/tools/hub_tools.py agent/tests/test_codehub_submit_review_tool.py
# (use the actual tool file path you located in Step 1)
git commit -m "codehub_submit_review tool: add considered_alternatives parameter + update description"
```

---

## Task 5: Update review_worker prompt

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/review_worker_agent.j2`
- Create: `agent/tests/test_review_worker_quality_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_review_worker_quality_prompt.py`:

```python
"""Tests that review_worker prompt teaches the substantive-review contract."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class ReviewWorkerQualityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("review_worker_agent.j2")
        mod = tpl.make_module()
        # Macro name may vary; try common patterns
        for name in ("review_worker_specifics", "reviewer_specifics",
                      "review_worker_system_prompt"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find review_worker specifics macro")

    def test_prompt_mentions_inline_comments_requirement(self) -> None:
        self.assertIn("INLINE", self.system.upper())

    def test_prompt_mentions_considered_alternatives_requirement(self) -> None:
        self.assertIn("CONSIDERED_ALTERNATIVES", self.system.upper())

    def test_prompt_forbids_lgtm_only_approvals(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "LGTM" in upper or "EMPTY APPROVE" in upper or "RUBBER STAMP" in upper,
            "prompt must explicitly warn against rubber-stamp approvals",
        )

    def test_prompt_specifies_at_least_one(self) -> None:
        # Reinforce the "MUST have >=1" cardinality
        upper = self.system.upper()
        self.assertTrue("AT LEAST ONE" in upper or ">=1" in upper or "AT LEAST 1" in upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_review_worker_quality_prompt -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `review_worker_agent.j2`**

Find the existing `review_worker_specifics` (or analog) macro. Add a "## REVIEW QUALITY CONTRACT" block somewhere visible (e.g., near the existing review instructions):

```jinja
## REVIEW QUALITY CONTRACT (Cutover 13)
"LGTM" is NOT a review. CodeHub will reject `state="approve"` if you don't supply BOTH:
1. **At least one inline_comment** with a real file path + line number from the diff:
   `inline_comments=[{"file": "backend/routes/feed.py", "line": 42, "body": "..."}]`
2. **At least one considered_alternatives entry** explaining an approach you evaluated and chose not to recommend:
   `considered_alternatives=["Considered batching reads via Redis pipeline; rejected because endpoint p99 already meets SLA."]`

If the change is genuinely trivial (typo, formatting), still cite at least one line + one alternative ("considered leaving the typo; rejected because docs are public-facing"). You can ALWAYS find one alternative — your job as reviewer is to be the second mind on the change, not the rubber stamp.

For `state="request_changes"` and `state="comment"`, these fields are not required. They're required only for `state="approve"` because that's the signal that lets the PR merge.

Rubber-stamp approvals waste the entire 2-reviewer system. Don't ship them.
```

- [ ] **Step 4: Verify 4 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_review_worker_quality_prompt -v 2>&1 | tail -10
```

Expected: 4 OK.

- [ ] **Step 5: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 528 OK (524 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/review_worker_agent.j2 agent/tests/test_review_worker_quality_prompt.py
git commit -m "review_worker prompt: REVIEW QUALITY CONTRACT — inline_comments + considered_alternatives required"
```

---

## Task 6: Update orchestrator prompt (orchestrator IS the mandatory reviewer)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_reviewer_quality_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_reviewer_quality_prompt.py`:

```python
"""Tests that orchestrator prompt teaches the substantive-review contract when reviewing."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorReviewerQualityPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_mentions_inline_comments_when_reviewing(self) -> None:
        self.assertIn("INLINE", self.system.upper())

    def test_prompt_mentions_considered_alternatives_when_reviewing(self) -> None:
        self.assertIn("CONSIDERED_ALTERNATIVES", self.system.upper())

    def test_prompt_says_orchestrator_is_mandatory_reviewer(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "MANDATORY REVIEWER" in upper or "MANDATORY" in upper,
            "prompt should remind orchestrator it is the mandatory reviewer",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_reviewer_quality_prompt -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `orchestrator_agent.j2`**

In `lead_specifics()`, find the existing reviewer-related rules (likely near the Cutover-7 mandatory-reviewer language or Cutover-11 RUN VERIFICATION block). Add (or extend) a "### REVIEW QUALITY (Cutover 13)" block:

```jinja
### REVIEW QUALITY (Cutover 13)
You are the **mandatory reviewer** on every PR (Cutover 7). When you `codehub_submit_review(state="approve", ...)`, you MUST supply:

1. `inline_comments=[{"file": "...", "line": <int>, "body": "..."}]` — at least one comment cited on a real diff line. You looked at the diff; prove it by referencing a specific line.

2. `considered_alternatives=["I considered X; rejected because Y", ...]` — at least one alternative approach you evaluated. Reviewers exist to be a second mind on the change. "I have nothing to add" is not a review — find one alternative the author didn't take, and say why their choice is right (or wrong).

If you call `codehub_submit_review(state="approve")` without these, CodeHub returns an error and the PR stays blocked. The same rule applies to every other reviewer agent — when you suggest reviewers, expect substantive reviews back; reject rubber-stamp approvals via comment or request_changes if you see one slip through.

`state="request_changes"` and `state="comment"` do NOT require these fields.
```

- [ ] **Step 4: Verify 3 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_reviewer_quality_prompt -v 2>&1 | tail -10
```

Expected: 3 OK.

- [ ] **Step 5: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 531 OK (528 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_orchestrator_reviewer_quality_prompt.py
git commit -m "Orchestrator prompt: REVIEW QUALITY — mandatory reviewer must submit substantive approve"
```

---

## Task 7: End-to-end test: rubber-stamp PR can't merge; substantive PR can

**Files:**
- Create: `agent/tests/test_review_quality_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_review_quality_e2e.py`:

```python
"""End-to-end test: enforces the Cutover-13 review-quality gate at the merge surface.

Proves:
- Two rubber-stamp approves cannot pass `_is_pr_approved` (and merge is blocked)
- Two substantive approves CAN pass, and merge succeeds.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_INLINE = [{"file": "backend/x.py", "line": 1, "body": "looked at it"}]
_ALT = ["considered alt approach; rejected because A"]


class ReviewQualityE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rq_e2e_"))
        self.reg = HubRegistry(self.tmp)
        self.pr = self.reg.codehub.open_pull_request(
            branch="agent/backend", base="master", title="t", body="b",
            author="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_rubber_stamp_approves_are_rejected_at_submit(self) -> None:
        r1 = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=[], considered_alternatives=[])
        r2 = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="reviewer2", state="approve",
            inline_comments=[], considered_alternatives=[])
        self.assertIn("error", r1)
        self.assertIn("error", r2)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertEqual(pr.get("reviews", []), [],
                         "rejected submissions must not be stored on the PR")

    def test_two_substantive_approves_allow_merge_ready(self) -> None:
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="reviewer2", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        self.assertTrue(self.reg.codehub._is_pr_approved(pr))
        self.assertEqual(pr.get("merge_state"), "ready")

    def test_substantive_plus_rubber_stamp_NOT_approved(self) -> None:
        self.reg.codehub.submit_review(
            self.pr["id"], reviewer="orchestrator", state="approve",
            inline_comments=_INLINE, considered_alternatives=_ALT)
        # second reviewer tries to rubber-stamp via the tool -> rejected at submit
        bad = self.reg.codehub.submit_review(
            self.pr["id"], reviewer="reviewer2", state="approve",
            inline_comments=[], considered_alternatives=[])
        self.assertIn("error", bad)
        pr = self.reg.codehub.stores.pull_requests.get(self.pr["id"])
        # Only one approve stored; 2-reviewer rule still requires both, so not approved
        self.assertFalse(self.reg.codehub._is_pr_approved(pr))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_review_quality_e2e -v 2>&1 | tail -10
```

Expected: 3 OK on first run (Tasks 2 + 3 already wired the validation; this test exercises the result).

If a test fails:
- `test_two_rubber_stamp_approves_are_rejected_at_submit` failing → Task 2 validation isn't returning an error (re-check `submit_review` validation order)
- `test_two_substantive_approves_allow_merge_ready` failing → check that the PR's `merge_state` field is being set to `"ready"` by `submit_review` after both substantive approves land. If `merge_state` isn't reachable that way (the existing code sets it conditionally), the test should assert `_is_pr_approved(pr)` is True and skip the merge_state check — adjust accordingly without weakening the substantive-approve assertion.
- `test_substantive_plus_rubber_stamp_NOT_approved` failing → re-check Task 3's `_is_review_substantive` filter on `_is_pr_approved`.

- [ ] **Step 3: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 534 OK (531 + 3 new).

- [ ] **Step 4: Commit**

```bash
git add agent/tests/test_review_quality_e2e.py
git commit -m "Add end-to-end test: rubber-stamp approves blocked; substantive approves merge-ready"
```

---

## Task 8: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/14-review-quality-gates.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 534 OK. STOP if anything fails.

- [ ] **Step 2: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Migration log**

Create `docs/superpowers/migration-logs/14-review-quality-gates.md`:

```markdown
# Cutover 13: Review Quality Hard Gates

**Branch:** `haibotong-cutover-13-review-quality`
**Date:** 2026-05-24

## What

Stopped "LGTM theater" reviews. `CodeHub.submit_review(state="approve", ...)`
now requires at least one inline_comment (cited on a real diff line) AND at
least one non-empty `considered_alternatives` entry. The merge-time gate
(`_is_pr_approved`) defends in depth: even if a review row is written to the
store bypassing `submit_review` validation, it doesn't count toward approval
unless substantive. Updated `codehub_submit_review` tool, `review_worker`
prompt, and orchestrator prompt to teach the new contract.

## Commits

(fill from `git log --oneline haibotong-0521-pipeline-web-tools..HEAD`)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 509 OK -> 534 OK (+25 new tests)

## New surfaces
- `CodeHub.submit_review(considered_alternatives=...)` — new kwarg, validated when `state=="approve"`
- `CodeHub._is_review_substantive(review)` — staticmethod helper
- `codehub_submit_review` LLM tool — new `considered_alternatives` parameter + updated description

## Prompts
- `review_worker_agent.j2`: REVIEW QUALITY CONTRACT block (no LGTM, cite a line, list an alternative)
- `orchestrator_agent.j2`: REVIEW QUALITY block (orchestrator is mandatory reviewer; same rule applies)

## Known gaps (future cutovers)
- Inline_comment line numbers aren't verified against actual diff lines (no diff parsing yet); a malicious reviewer could cite a fake line. Diff-line verification is a larger sub-project.
- No "did the reviewer actually read the diff" semantic check; we can only verify shape.
```

- [ ] **Step 4: Commit log**

```bash
git add docs/superpowers/migration-logs/14-review-quality-gates.md
git commit -m "Add Cutover 13 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-13-review-quality 2>&1 | tail -5
```

- [ ] **Step 6: Report**

Print: final test counts, commit count, push URL, compare URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:**
- submit_review validates approve → Task 2 ✓
- Merge-gate filters non-substantive approve → Task 3 ✓
- LLM tool exposes considered_alternatives → Task 4 ✓
- Reviewer prompt teaches the contract → Task 5 ✓
- Orchestrator-as-reviewer reminded → Task 6 ✓
- E2E test → Task 7 ✓
- Migration log + push → Task 8 ✓

**2. Placeholder scan:** No "TBD" / "implement later". Every code-change task shows the actual code.

**3. Type consistency:**
- `submit_review(..., considered_alternatives: Optional[List[str]] = None)` — same in service + tool + tests + prompts ✓
- `review["considered_alternatives"]: List[str]` stored on the review row ✓
- `_is_review_substantive(review) -> bool` — same name + behavior in service + tests ✓
- Error keywords in returns: `"inline_comments"` and `"alternative"` — tests assert lowercase substring matches; impl uses lowercase ✓
- `state ∈ {"approve", "request_changes", "comment"}` — same set across tests and prompts ✓

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 8 ✓
- Baselines green at every task boundary — explicit step in each task ✓
- TDD — every code-change task starts with failing tests ✓
- Pre-existing tests need fixture updates (Task 2 Step 5) — explicitly called out ✓
- Defense in depth: validation at submit + filter at merge gate ✓
