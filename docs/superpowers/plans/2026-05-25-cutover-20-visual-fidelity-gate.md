# Cutover 20: UI Visual Fidelity Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Block `deliver_project()` if any UI route marked `critical=true` lacks an approved Visual Review. A new **Visual Reviewer** agent compares the route's screenshot against the reference image (via existing `CompareWithScreenshotTool`), produces a structured `VisualReviewReport` with similarity_score + ≥3 deviations, and either approves (similarity ≥ 0.75 + substantive deviations) or sends back. Mirrors Cutover 14's Architect Review pattern but for visual instead of structural fidelity.

**Architecture:** Visual reviews ride on WorkHub pages with `kind="visual_review"` (parallel to Cutover 14's `kind="design"`). Lifecycle `pending → reviewing → approved | needs_revision`. New `visual_reviewer` agent profile (13th). Frontend/orchestrator registers a review task via `register_visual_review_task(route, screenshot_path, reference_path, critical=True)`. Reviewer iterates pending tasks, calls existing `CompareWithScreenshotTool`, submits structured report. DeliverProjectTool gate refuses if any `critical=true` task isn't approved — uses Cutover 19's `mark_intentionally_dead` allowlist for "no reference image available" / "intentionally divergent" cases.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Reuses existing surfaces: WorkHub pages (Cutover 14), `CompareWithScreenshotTool` (vision_tools.py), `CaptureWebpageTool` (image_search_tools.py — Playwright already wired).

---

## Context for Worker

### Why this cutover exists

The system can ship a UI that compiles, type-checks, and has no dead components — but looks nothing like the reference design the spec required. Cutover 14's Architect Reviewer catches design *assumptions*, not visual *fidelity*. Without this cutover, the user requirement "设计美观，符合提供的reference材料要求" has zero mechanical enforcement.

### Out of scope (deferred)

- **Automated screenshot capture inside the gate**: Playwright is in the toolbox via `CaptureWebpageTool` but wiring it into `RunHub.start_run` as an automatic post-run step is its own cutover. MVP: frontend/orchestrator captures + uploads screenshot via `record_route_screenshot(...)` tool; gate just enforces the review.
- **Component-level visual fidelity**: only full-route comparison. Per-component diff is a follow-up.
- **A/B comparison across runs**: only screenshot-vs-reference, not screenshot-vs-prior-screenshot.

### Visual review schema (WorkHub page)

```python
{
    "kind": "visual_review",
    "status": "pending",   # pending | reviewing | approved | needs_revision
    "title": "Feed page visual review",
    "metadata": {
        "route": "/feed",
        "screenshot_path": "/abs/path/to/screenshots/feed.png",
        "reference_path": "/abs/path/to/references/feed.png",
        "critical": True,
        "registered_by": "frontend",
        "review_history": [
            {
                "review_id": "vrev_<hex>",
                "at": <epoch>,
                "by": "visual_reviewer",
                "state": "approve",   # approve | needs_revision | comment
                "similarity_score": 0.82,
                "deviations": [
                    {"aspect": "primary button color",
                     "expected": "#1d4ed8 (indigo-700)",
                     "actual": "#2563eb (blue-600)",
                     "severity": "low"},
                    ...
                ],
                "summary": "Layout matches; minor color drift on accents",
            },
            ...
        ],
    },
}
```

### Substantive-review requirements (mirror Cutover 13/14)

For `state="approve"`:
- `similarity_score` must be in `[0.0, 1.0]`
- For `critical=true` tasks: `similarity_score >= 0.75`
- `deviations` must contain ≥3 substantive entries (each with non-empty `aspect`/`expected`/`actual`/`severity`)
- `summary` must be ≥20 chars (no `"LGTM"`/`"looks good"` rubber-stamps)

For `state="needs_revision"`: at least 1 substantive deviation required; no similarity floor.

For `state="comment"`: no transition, no minimums.

### Deliver gate

`DeliverProjectTool.execute` adds (after Cutover 19 coverage gate):
1. List all `kind="visual_review"` pages where `metadata.critical == True`
2. Any not-approved → list them; refuse deliver (suggest `mark_intentionally_dead("visual:<route>", reason)` allowlist override)
3. `force_deliver=True` still bypasses (existing Cutover 19 mechanism); publishes `visual_review_bypass` EventHub audit event

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (dt conda env)
- No Claude trailer; no emojis
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 9
- Both baselines green at every task boundary: regressions 7 OK; discover 737 OK after Cutover 19
- Worktree path: `worktrees/<agent_id>`

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/visual_review_gate.py` — `assert_critical_visuals_approved`, `VisualReviewNotApprovedError`
- `agent/env_generator/llm_generator/tools/visual_review_tools.py` — 4 tools
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/visual_reviewer_agent.j2`
- `agent/tests/test_workhub_visual_review.py`
- `agent/tests/test_visual_review_gate.py`
- `agent/tests/test_visual_review_tools.py`
- `agent/tests/test_visual_reviewer_config.py`
- `agent/tests/test_visual_reviewer_prompt.py`
- `agent/tests/test_visual_review_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — add `register_visual_review_task`, `submit_visual_review`, `is_visual_approved`, `list_pending_visual_reviews`, `list_critical_visual_reviews`, `get_visual_review`
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` — `DeliverProjectTool` adds visual pre-flight check
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `visual_review_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `visual_reviewer` profile (13th); add `visual_review_tools` to frontend + orchestrator + visual_reviewer
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — VISUAL FIDELITY DISCIPLINE block
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2` — must `register_visual_review_task` per critical route

---

## Task 1: Worktree + baseline + recon

**Files:**
- Create: `docs/superpowers/cutover-20-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-20-visual-fidelity
git status
git log --oneline -3
```

If missing: `git worktree add -b haibotong-cutover-20-visual-fidelity .worktrees/haibotong-cutover-20-visual-fidelity haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 737 OK.

- [ ] **Step 3: Inventory existing vision/capture tool surface**

```bash
grep -nE "class (CompareWithScreenshotTool|CaptureWebpageTool|AnalyzeImageTool)" agent/env_generator/llm_generator/tools/*.py
grep -nE "def execute" agent/env_generator/llm_generator/tools/vision_tools.py | head -5
```

Confirm `CompareWithScreenshotTool.execute(reference_image, generated_image)` exists — visual_reviewer prompt will call this.

- [ ] **Step 4: Inventory profile count + design_review anchor**

```bash
grep -nE "^  [a-z_]+:$" agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml | head -20
grep -nE "list_pending_design_reviews|submit_design_review" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py | head -3
```

Record: 12 profiles today (Cutover 14 added `architect_reviewer` as 12th). The 13th `visual_reviewer` is added in Task 5. Note the `submit_design_review` line — it's the Cutover-14 anchor for placing new visual-review helpers nearby.

- [ ] **Step 5: Baseline note + commit**

Create `docs/superpowers/cutover-20-baseline.md`:

```markdown
# Cutover 20 Baseline (UI Visual Fidelity Gate)

## Test counts
- regressions: 7 OK
- discover: 737 OK

## Gap this cutover closes
Cutover 14 (Architect Reviewer) catches design *assumptions*, not visual
*fidelity*. A generated UI that compiles + has no dead components can still
look nothing like the reference. No mechanical enforcement of "符合 reference
材料" today.

## Approach
- WorkHub kind="visual_review" pages (mirror Cutover 14 design_review)
- New visual_reviewer agent (13th profile) - never writes code
- submit_visual_review requires similarity_score in [0,1] + >=3 deviations + summary
- DeliverProjectTool refuses if any critical visual_review not approved
- force_deliver bypass (Cutover 19 pattern) for legitimate divergence

## Existing surfaces reused
- WorkHub pages with kind+status+metadata (Cutover 14)
- CompareWithScreenshotTool / AnalyzeImageTool (vision_tools.py)
- CaptureWebpageTool / Playwright (image_search_tools.py - for future
  auto-screenshot wiring, NOT this cutover)
- mark_intentionally_dead allowlist (Cutover 19)
```

```bash
git add docs/superpowers/cutover-20-baseline.md
git commit -m "Cutover 20: record pre-flight baseline (regressions 7 OK, discover 737 OK)"
```

---

## Task 2: WorkHub visual_review helpers

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_visual_review.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_workhub_visual_review.py`:

```python
"""Tests for WorkHub visual_review helpers (Cutover 20)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEVIATIONS = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8 (indigo-700)",
     "actual": "#2563eb (blue-600)", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px gap between logo and nav",
     "actual": "8px gap", "severity": "medium"},
    {"aspect": "feed card border radius",
     "expected": "12px rounded corners",
     "actual": "4px rounded corners", "severity": "low"},
]


class WorkHubVisualReviewLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_vis_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_creates_pending_task(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed",
            screenshot_path="/tmp/feed.png",
            reference_path="/tmp/ref-feed.png",
            critical=True, agent="frontend")
        self.assertEqual(page["kind"], "visual_review")
        self.assertEqual(page["status"], "pending")
        self.assertEqual(page["metadata"]["route"], "/feed")
        self.assertTrue(page["metadata"]["critical"])

    def test_list_pending_returns_only_pending(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.register_visual_review_task(
            route="/about", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        pending = self.reg.workhub.list_pending_visual_reviews()
        self.assertEqual(len(pending), 2)

    def test_list_critical_returns_only_critical(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.register_visual_review_task(
            route="/about", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        critical = self.reg.workhub.list_critical_visual_reviews()
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0]["metadata"]["route"], "/feed")

    def test_get_visual_review_returns_match(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        got = self.reg.workhub.get_visual_review(page["id"])
        self.assertEqual(got["id"], page["id"])

    def test_get_visual_review_returns_none_for_non_visual_kind(self) -> None:
        other = self.reg.workhub.create_page(title="x", agent="o", kind="design")
        self.assertIsNone(self.reg.workhub.get_visual_review(other["id"]))


class WorkHubVisualReviewSubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_vis_submit_"))
        self.reg = HubRegistry(self.tmp)
        self.page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_approve_with_3_deviations_and_high_similarity_succeeds(self) -> None:
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS,
            summary="Layout matches; minor color drift on accents")
        self.assertEqual(result["status"], "approved")
        self.assertTrue(self.reg.workhub.is_visual_approved(self.page["id"]))

    def test_approve_with_2_deviations_rejected(self) -> None:
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS[:2],
            summary="...........................")
        self.assertIn("error", result)
        self.assertIn("deviations", result["error"].lower())

    def test_approve_with_low_similarity_on_critical_rejected(self) -> None:
        # Critical task with similarity 0.5 -> rejected
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.50,
            deviations=_GOOD_DEVIATIONS,
            summary="Many large deviations; should not approve")
        self.assertIn("error", result)
        self.assertIn("similarity", result["error"].lower())

    def test_approve_short_summary_rejected(self) -> None:
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.80,
            deviations=_GOOD_DEVIATIONS, summary="LGTM")
        self.assertIn("error", result)
        self.assertIn("summary", result["error"].lower())

    def test_approve_similarity_out_of_range_rejected(self) -> None:
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=1.5,
            deviations=_GOOD_DEVIATIONS, summary="................")
        self.assertIn("error", result)

    def test_needs_revision_with_1_deviation_accepted(self) -> None:
        result = self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="needs_revision", similarity_score=0.30,
            deviations=[_GOOD_DEVIATIONS[0]],
            summary="Layout completely off")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "needs_revision")

    def test_non_critical_low_similarity_approve_allowed(self) -> None:
        # Non-critical task with similarity 0.4 -> allowed (no critical floor)
        non_critical = self.reg.workhub.register_visual_review_task(
            route="/admin", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        result = self.reg.workhub.submit_visual_review(
            non_critical["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.40,
            deviations=_GOOD_DEVIATIONS,
            summary="Admin page is internal; not held to brand standards")
        self.assertNotIn("error", result)

    def test_review_history_appended(self) -> None:
        self.reg.workhub.submit_visual_review(
            self.page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.82,
            deviations=_GOOD_DEVIATIONS,
            summary="Layout matches; minor drift on accents")
        page = self.reg.workhub.get_visual_review(self.page["id"])
        hist = (page.get("metadata") or {}).get("review_history") or []
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["state"], "approve")
        self.assertEqual(hist[0]["similarity_score"], 0.82)
        self.assertEqual(len(hist[0]["deviations"]), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_visual_review -v 2>&1 | tail -15
```

Expected: AttributeError on `register_visual_review_task` etc.

- [ ] **Step 3: Implement the 6 helpers**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, add (near `submit_design_review` from Cutover 14):

```python
    _VALID_VISUAL_REVIEW_STATES = {"approve", "needs_revision", "comment"}
    _CRITICAL_SIMILARITY_FLOOR = 0.75
    _MIN_DEVIATIONS_FOR_APPROVE = 3
    _MIN_SUMMARY_LEN_FOR_APPROVE = 20

    def register_visual_review_task(self, route: str, screenshot_path: str,
                                      reference_path: str, critical: bool = False,
                                      agent: str = "") -> dict:
        return self.create_page(
            title=f"Visual review: {route}",
            agent=agent or "frontend",
            kind="visual_review",
            attendees=["visual_reviewer"],
            metadata={
                "route": route,
                "screenshot_path": screenshot_path,
                "reference_path": reference_path,
                "critical": bool(critical),
                "review_history": [],
            },
        )

    def get_visual_review(self, page_id: str) -> Optional[dict]:
        page = self.stores.pages.get(page_id)
        if not page or page.get("kind") != "visual_review":
            return None
        return page

    def list_pending_visual_reviews(self) -> list:
        return [p for p in (self.stores.pages.value() or {}).values()
                if p.get("kind") == "visual_review"
                and p.get("status") in ("pending", "reviewing")]

    def list_critical_visual_reviews(self) -> list:
        return [p for p in (self.stores.pages.value() or {}).values()
                if p.get("kind") == "visual_review"
                and (p.get("metadata") or {}).get("critical") is True]

    def is_visual_approved(self, page_id: str) -> bool:
        page = self.get_visual_review(page_id)
        return bool(page and page.get("status") == "approved")

    def submit_visual_review(self, page_id: str, reviewer: str, state: str,
                               similarity_score: float = None,
                               deviations: Optional[List[dict]] = None,
                               summary: str = "") -> dict:
        page = self.get_visual_review(page_id)
        if not page:
            return {"error": f"visual_review page not found: {page_id}"}
        if state not in self._VALID_VISUAL_REVIEW_STATES:
            return {"error": f"invalid state: {state!r}"}

        if state == "approve":
            if not isinstance(similarity_score, (int, float)):
                return {"error": "similarity_score required (number in [0,1])"}
            if similarity_score < 0.0 or similarity_score > 1.0:
                return {"error": f"similarity_score must be in [0,1], got {similarity_score}"}
            substantive = []
            for d in (deviations or []):
                if not isinstance(d, dict):
                    continue
                aspect = (d.get("aspect") or "").strip()
                expected = (d.get("expected") or "").strip()
                actual = (d.get("actual") or "").strip()
                severity = (d.get("severity") or "").strip()
                if aspect and expected and actual and severity:
                    substantive.append({"aspect": aspect, "expected": expected,
                                         "actual": actual, "severity": severity})
            if len(substantive) < self._MIN_DEVIATIONS_FOR_APPROVE:
                return {"error": f"approve requires at least "
                                  f"{self._MIN_DEVIATIONS_FOR_APPROVE} substantive deviations "
                                  f"each with non-empty aspect/expected/actual/severity"}
            if not isinstance(summary, str) or len(summary.strip()) < self._MIN_SUMMARY_LEN_FOR_APPROVE:
                return {"error": f"summary must be >= {self._MIN_SUMMARY_LEN_FOR_APPROVE} chars "
                                  f"(no rubber-stamp approvals)"}
            critical = (page.get("metadata") or {}).get("critical") is True
            if critical and similarity_score < self._CRITICAL_SIMILARITY_FLOOR:
                return {"error": f"critical route requires similarity_score >= "
                                  f"{self._CRITICAL_SIMILARITY_FLOOR} for approve "
                                  f"(got {similarity_score})"}
            deviations = substantive
        elif state == "needs_revision":
            if not (deviations or []):
                return {"error": "needs_revision requires at least 1 deviation"}

        import uuid
        review_id = f"vrev_{uuid.uuid4().hex[:10]}"
        now = time.time()
        review = {
            "review_id": review_id, "at": now, "by": reviewer,
            "state": state,
            "similarity_score": float(similarity_score) if isinstance(similarity_score, (int, float)) else None,
            "deviations": deviations or [],
            "summary": summary,
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

        updated["_updated_by"] = reviewer
        updated["_updated_at"] = now
        self.stores.pages.update(lambda m: m.set(page_id, updated, reviewer),
                                  change_info={"agent": reviewer})
        self._emit(f"visual_review_{state}", updated,
                    recipients=updated.get("attendees", []) or [],
                    priority="high")
        return updated
```

- [ ] **Step 4: Verify all tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_visual_review -v 2>&1 | tail -20
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 13 OK; 7 OK / 750 OK (737 + 13 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_visual_review.py
git commit -m "WorkHub: add visual_review lifecycle (>=3 deviations + similarity_score for approve)"
```

---

## Task 3: `visual_review_gate` module

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/visual_review_gate.py`
- Create: `agent/tests/test_visual_review_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_visual_review_gate.py`:

```python
"""Tests for visual_review_gate (Cutover 20)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.visual_review_gate import (  # noqa: E402
    VisualReviewNotApprovedError, assert_critical_visuals_approved,
    list_unapproved_critical,
)


_GOOD_DEV = [
    {"aspect": "a", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "b", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "c", "expected": "e", "actual": "a2", "severity": "low"},
]


class VisualReviewGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_gate_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_passes_when_no_visual_reviews(self) -> None:
        assert_critical_visuals_approved(self.reg.workhub)

    def test_passes_when_only_non_critical_unapproved(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/admin", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        assert_critical_visuals_approved(self.reg.workhub)

    def test_raises_when_critical_pending(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        with self.assertRaises(VisualReviewNotApprovedError):
            assert_critical_visuals_approved(self.reg.workhub)

    def test_passes_when_critical_approved(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches; minor color drift on accents")
        assert_critical_visuals_approved(self.reg.workhub)

    def test_raises_when_critical_needs_revision(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="needs_revision", similarity_score=0.30,
            deviations=[_GOOD_DEV[0]], summary="Layout off")
        with self.assertRaises(VisualReviewNotApprovedError):
            assert_critical_visuals_approved(self.reg.workhub)

    def test_list_unapproved_critical_returns_them(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        unapproved = list_unapproved_critical(self.reg.workhub)
        self.assertEqual(len(unapproved), 1)
        self.assertEqual(unapproved[0]["metadata"]["route"], "/feed")

    def test_error_message_lists_routes(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.register_visual_review_task(
            route="/profile", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        try:
            assert_critical_visuals_approved(self.reg.workhub)
            self.fail("expected raise")
        except VisualReviewNotApprovedError as e:
            msg = str(e)
            self.assertIn("/feed", msg)
            self.assertIn("/profile", msg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Implement gate**

Create `agent/env_generator/llm_generator/multi_agent/runtime/visual_review_gate.py`:

```python
"""Visual review gate (Cutover 20). Pure read-side over WorkHub."""

from __future__ import annotations


class VisualReviewNotApprovedError(RuntimeError):
    pass


def list_unapproved_critical(workhub) -> list:
    """Return all visual_review pages with critical=True and status != 'approved'."""
    if workhub is None or not hasattr(workhub, "list_critical_visual_reviews"):
        return []
    out = []
    for page in workhub.list_critical_visual_reviews():
        if page.get("status") != "approved":
            out.append(page)
    return out


def assert_critical_visuals_approved(workhub) -> None:
    unapproved = list_unapproved_critical(workhub)
    if not unapproved:
        return
    routes = [(p.get("metadata") or {}).get("route", "?") for p in unapproved]
    raise VisualReviewNotApprovedError(
        f"{len(unapproved)} critical route(s) lack approved visual review: "
        f"{', '.join(routes)}. Review each via the visual_reviewer agent, "
        f"or mark_intentionally_dead('visual:<route>', reason) to override.")


__all__ = ["VisualReviewNotApprovedError",
            "assert_critical_visuals_approved", "list_unapproved_critical"]
```

- [ ] **Step 4: Verify 7 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_review_gate -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK; 7 OK / 757 OK (750 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/visual_review_gate.py agent/tests/test_visual_review_gate.py
git commit -m "Add visual_review_gate: assert_critical_visuals_approved raises if any critical route not approved"
```

---

## Task 4: Visual review LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/visual_review_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Create: `agent/tests/test_visual_review_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_visual_review_tools.py`:

```python
"""Tests for visual review LLM tools (Cutover 20)."""

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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_GOOD_DEV = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8", "actual": "#2563eb", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px gap", "actual": "8px gap", "severity": "medium"},
    {"aspect": "card border radius",
     "expected": "12px", "actual": "4px", "severity": "low"},
]


class VisualReviewToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_creates_visual_review_task(self) -> None:
        from tools.visual_review_tools import RegisterVisualReviewTaskTool
        tool = RegisterVisualReviewTaskTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            route="/feed", screenshot_path="/tmp/feed.png",
            reference_path="/tmp/ref-feed.png", critical=True))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["metadata"]["route"], "/feed")

    def test_list_pending_returns_pending_pages(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, ListPendingVisualReviewsTool,
        )
        _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        result = _run_async(ListPendingVisualReviewsTool(
            hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["pending"]), 1)

    def test_submit_approve_with_3_deviations(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(SubmitVisualReviewTool(
            hub_registry=self.reg).execute(
            page_id=page_id, state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches reference closely; minor color drift"))
        self.assertTrue(result.success)
        self.assertEqual(result.data["page"]["status"], "approved")

    def test_submit_approve_with_2_deviations_fails(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(SubmitVisualReviewTool(
            hub_registry=self.reg).execute(
            page_id=page_id, state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV[:2],
            summary="..............................."))
        self.assertFalse(result.success)

    def test_get_status_returns_current(self) -> None:
        from tools.visual_review_tools import (
            RegisterVisualReviewTaskTool, GetVisualReviewStatusTool,
        )
        page_result = _run_async(RegisterVisualReviewTaskTool(
            hub_registry=self.reg).execute(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True))
        page_id = page_result.data["page"]["id"]
        result = _run_async(GetVisualReviewStatusTool(
            hub_registry=self.reg).execute(page_id=page_id))
        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "pending")
        self.assertEqual(result.data["critical"], True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Implement tools**

Create `agent/env_generator/llm_generator/tools/visual_review_tools.py`. Match the `BaseTool` + `tool_definition` property convention (same as retro_tools / design_tools / coverage_tools):

```python
"""Visual review LLM tools (Cutover 20)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param


class _VisualReviewToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterVisualReviewTaskTool(_VisualReviewToolBase):
    NAME = "register_visual_review_task"
    DESCRIPTION = ("Register a UI route for visual review. Frontend agent calls this "
                    "for each route that has a reference image. critical=True for "
                    "routes that must pass visual review before deliver_project().")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "route": {"type": "string"},
                    "screenshot_path": {"type": "string"},
                    "reference_path": {"type": "string"},
                    "critical": {"type": "boolean", "default": True},
                },
                "required": ["route", "screenshot_path", "reference_path"],
            }, required=["route", "screenshot_path", "reference_path"])

    async def execute(self, *, route: str, screenshot_path: str,
                       reference_path: str, critical: bool = True,
                       **_kw) -> ToolResult:
        page = self.hub_registry.workhub.register_visual_review_task(
            route=route, screenshot_path=screenshot_path,
            reference_path=reference_path, critical=critical,
            agent=self._agent_id or "frontend")
        return ToolResult.ok(data={"page": page})


class SubmitVisualReviewTool(_VisualReviewToolBase):
    NAME = "submit_visual_review"
    DESCRIPTION = ("Visual reviewer submits a structured review. For state='approve', "
                    "you MUST supply similarity_score in [0,1] (>=0.75 for critical "
                    "routes), at least 3 substantive deviations (each with "
                    "aspect/expected/actual/severity), and a >=20-char summary.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "state": {"type": "string",
                               "enum": ["approve", "needs_revision", "comment"]},
                    "similarity_score": {"type": "number"},
                    "deviations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "aspect": {"type": "string"},
                                "expected": {"type": "string"},
                                "actual": {"type": "string"},
                                "severity": {"type": "string"},
                            },
                            "required": ["aspect", "expected", "actual", "severity"],
                        },
                    },
                    "summary": {"type": "string"},
                },
                "required": ["page_id", "state"],
            }, required=["page_id", "state"])

    async def execute(self, *, page_id: str, state: str,
                       similarity_score: float = None,
                       deviations: list = None, summary: str = "",
                       **_kw) -> ToolResult:
        result = self.hub_registry.workhub.submit_visual_review(
            page_id=page_id, reviewer=self._agent_id or "visual_reviewer",
            state=state, similarity_score=similarity_score,
            deviations=deviations or [], summary=summary)
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(error_message=result["error"])
        return ToolResult.ok(data={"page": result})


class ListPendingVisualReviewsTool(_VisualReviewToolBase):
    NAME = "list_pending_visual_reviews"
    DESCRIPTION = "List visual review tasks awaiting reviewer attention."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        pending = self.hub_registry.workhub.list_pending_visual_reviews()
        out = [{"id": p["id"],
                "route": (p.get("metadata") or {}).get("route"),
                "critical": (p.get("metadata") or {}).get("critical"),
                "screenshot_path": (p.get("metadata") or {}).get("screenshot_path"),
                "reference_path": (p.get("metadata") or {}).get("reference_path")}
               for p in pending]
        return ToolResult.ok(data={"pending": out})


class GetVisualReviewStatusTool(_VisualReviewToolBase):
    NAME = "get_visual_review_status"
    DESCRIPTION = "Get current status of a visual review task by page_id."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {"page_id": {"type": "string"}},
                "required": ["page_id"],
            }, required=["page_id"])

    async def execute(self, *, page_id: str, **_kw) -> ToolResult:
        page = self.hub_registry.workhub.get_visual_review(page_id)
        if page is None:
            return ToolResult.fail(
                error_message=f"visual_review page not found: {page_id}")
        meta = page.get("metadata") or {}
        return ToolResult.ok(data={
            "page_id": page_id, "status": page.get("status"),
            "route": meta.get("route"),
            "critical": bool(meta.get("critical")),
            "review_count": len(meta.get("review_history") or []),
            "approved": page.get("status") == "approved",
        })


_VISUAL_TOOLS = [RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
                  ListPendingVisualReviewsTool, GetVisualReviewStatusTool]


def create_visual_review_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _VISUAL_TOOLS]


__all__ = [
    "RegisterVisualReviewTaskTool", "SubmitVisualReviewTool",
    "ListPendingVisualReviewsTool", "GetVisualReviewStatusTool",
    "create_visual_review_tools",
]
```

- [ ] **Step 4: Register bundle**

In `tool_bundles.py`, mirror `_bundle_coverage_tools` from Cutover 19:

```python
from tools.visual_review_tools import create_visual_review_tools

def _bundle_visual_review_tools(builder, context) -> None:
    builder.add(create_visual_review_tools(hub_registry=context.hub_workspace),
                "knowledge")

# TOOL_BUNDLE_REGISTRY:
"visual_review_tools": _bundle_visual_review_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"visual_review_tools": {"knowledge"},
```

(Wiring to specific agent profiles happens in Task 5.)

- [ ] **Step 5: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_review_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 762 OK (757 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/tools/visual_review_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/tests/test_visual_review_tools.py
git commit -m "Add visual_review_tools: register/submit/list_pending/get_status + bundle wiring"
```

---

## Task 5: `visual_reviewer` agent profile

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_visual_reviewer_config.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_visual_reviewer_config.py`:

```python
"""Tests for visual_reviewer agent profile (Cutover 20)."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class VisualReviewerProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_profile_exists(self) -> None:
        self.assertIn("visual_reviewer", self.cfg.get("profiles", {}))

    def test_profile_has_visual_review_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["visual_reviewer"]
        self.assertIn("visual_review_tools", prof.get("tool_bundles", []))

    def test_profile_has_vision_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["visual_reviewer"]
        self.assertIn("vision_tools", prof.get("tool_bundles", []))

    def test_profile_uses_dedicated_prompt(self) -> None:
        prof = self.cfg["profiles"]["visual_reviewer"]
        template = (prof.get("prompts") or {}).get("template", "")
        self.assertTrue(template.endswith("visual_reviewer_agent.j2"))

    def test_profile_cannot_deliver(self) -> None:
        prof = self.cfg["profiles"]["visual_reviewer"]
        flags = prof.get("flags", {}) or {}
        self.assertFalse(flags.get("can_deliver", False))

    def test_visual_review_tools_added_to_frontend_and_orchestrator(self) -> None:
        for name in ("frontend", "orchestrator"):
            prof = self.cfg["profiles"][name]
            self.assertIn("visual_review_tools", prof.get("tool_bundles", []),
                            f"{name} missing visual_review_tools bundle")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Add profile + wire bundles**

In `agents_config.yaml`, add (mirror `architect_reviewer` shape):

```yaml
  visual_reviewer:
    name: "Visual Reviewer"
    description: "Compares generated UI screenshots against reference images. Submits structured visual fidelity reports with similarity scores + deviations. Never writes code."
    tool_categories: ["reasoning", "communication", "memory", "knowledge_read", "knowledge_write", "analysis", "workhub", "apihub", "eventhub", "hub", "knowledge", "vision"]
    include_vision: true
    timeout: 3600
    prompts:
      template: "v2/visual_reviewer_agent.j2"
      system_macro: "visual_reviewer_system_prompt"
      task_macros:
        full: "visual_reviewer_task_prompt"
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
      - vision_tools
      - reference_images
      - visual_review_tools
    deny_tools: []
    execution_pipeline:
      stages: [hub_pulse, runtime_team_status, planning, retrieve_context, action, hub_commit_gate, knowledge_sync]
      max_tool_calls_per_stage:
        planning: 1
        retrieve_context: 3
        action: 6
        hub_commit_gate: 0
        knowledge_sync: 2
```

Also add `visual_review_tools` to the **frontend** and **orchestrator** profile `tool_bundles` lists.

⚠️ **Note**: Cutover 18 dropped `memory_tools` bundle. If line look-up shows `memory_tools` is in `architect_reviewer` profile, that's residue — but don't touch it unless tests demand. For our NEW profile, omit `memory_tools` (matches post-Cutover-18 state).

If `test_agents_config_stages.py` breaks on profile count, update minimally.

- [ ] **Step 4: Verify 6 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_reviewer_config -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 6 OK; 7 OK / 768 OK (762 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_visual_reviewer_config.py
git commit -m "Add visual_reviewer agent profile (13th) + wire visual_review_tools to frontend/orchestrator"
```

---

## Task 6: visual_reviewer prompt

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/prompts/v2/visual_reviewer_agent.j2`
- Create: `agent/tests/test_visual_reviewer_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_visual_reviewer_prompt.py`:

```python
"""Tests for visual_reviewer prompt (Cutover 20)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class VisualReviewerPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("visual_reviewer_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.visual_reviewer_system_prompt()

    def test_prompt_renders_nonempty(self) -> None:
        self.assertGreater(len(self.system.strip()), 300)

    def test_prompt_mentions_similarity_score_floor(self) -> None:
        upper = self.system.upper()
        self.assertIn("0.75", upper)
        self.assertIn("SIMILARITY", upper)

    def test_prompt_mentions_3_deviations_minimum(self) -> None:
        upper = self.system.upper()
        self.assertTrue(any(s in upper for s in ("3 DEVIATIONS", "THREE DEVIATIONS",
                                                    ">=3", "AT LEAST 3")))

    def test_prompt_mentions_aspect_expected_actual(self) -> None:
        upper = self.system.upper()
        for token in ("ASPECT", "EXPECTED", "ACTUAL", "SEVERITY"):
            self.assertIn(token, upper)

    def test_prompt_forbids_code_edits(self) -> None:
        upper = self.system.upper()
        self.assertIn("NEVER", upper)
        self.assertTrue("CODE" in upper or "IMPLEMENT" in upper)

    def test_prompt_mentions_compare_with_screenshot_tool(self) -> None:
        upper = self.system.upper()
        self.assertIn("COMPARE_WITH_SCREENSHOT", upper)

    def test_prompt_describes_lifecycle(self) -> None:
        upper = self.system.upper()
        for state in ("PENDING", "APPROVED", "NEEDS_REVISION"):
            self.assertIn(state, upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Author the prompt**

Create `agent/env_generator/llm_generator/multi_agent/prompts/v2/visual_reviewer_agent.j2`:

```jinja
{# Visual Reviewer - Cutover 20 #}
{# Compares generated UI screenshots against reference images. NEVER writes code. #}

{% macro visual_reviewer_system_prompt() -%}
You are the **Visual Reviewer** - the design QA reviewer who verifies generated UI matches the reference design.

## ROLE
- **FRONTEND AGENT** generates UI code + captures screenshots and registers a visual review task via `register_visual_review_task(route, screenshot_path, reference_path, critical=True/False)`.
- **YOU (Visual Reviewer)** receive the task, compare the screenshot to the reference using `compare_with_screenshot(reference_image=<path>, generated_image=<path>)`, and submit a structured `submit_visual_review` call with similarity_score + deviations + summary.
- **DOWNSTREAM**: `deliver_project()` refuses if any `critical=True` route lacks an approved visual review. Your approval is the gate.

## LIFECYCLE
```
pending -> reviewing -> approved | needs_revision
```
- `pending`: frontend registered the task; awaiting you
- `reviewing`: you are inspecting (informal; not a required transition)
- `approved`: visuals match reference closely enough
- `needs_revision`: significant deviations; frontend must fix and re-submit

## HARD RULES (for state="approve")
1. **NEVER write code or edit files.** You have no file-write tools. Your only outputs are `submit_visual_review` calls, EventHub notifications, and knowledge writes.
2. **`similarity_score`** MUST be a number in [0.0, 1.0] reflecting overall visual fidelity. Use 0.0 for "nothing in common", 0.5 for "same layout but wrong colors/spacing", 0.85 for "looks correct with minor cosmetic drift", 1.0 for "indistinguishable from reference". Be honest.
3. **`similarity_score >= 0.75`** is required for `critical=True` routes. If the score is below 0.75 on a critical route, you MUST use `state="needs_revision"`.
4. **At least 3 substantive deviations** required (`deviations=[{aspect, expected, actual, severity}, ...]`). Each MUST have all four fields non-empty. Examples of good aspects:
   - Color: primary button color, link color, background tint
   - Spacing: gap between elements, padding inside cards, line-height
   - Typography: font family, weight, size hierarchy
   - Layout: column count, alignment, sticky headers, sidebar position
   - Imagery: aspect ratio, border radius, drop-shadow
   - Component density: feed card count per viewport, navigation item count
5. **`summary`** MUST be >=20 chars. No "LGTM" / "looks good" rubber stamps. State concisely what's right and what's drifted.

## STEP PIPELINE
Every step begins with **HUB PULSE** (engine-forced snapshot of all 4 hubs) and ends with an **INTEGRITY CHECK** (hub_commit_gate). Engine forces these regardless of stage list.

## YOUR TOOLS
- `list_pending_visual_reviews()` -> the queue
- `compare_with_screenshot(reference_image, generated_image)` -> vision LLM produces a structured comparison (you use this as input to your deviation list; the LLM call gives you the raw diff, but YOU decide what counts as approve-worthy)
- `analyze_image(image_path, focus_area="layout"/"colors"/"typography")` -> deeper single-image inspection if needed
- `submit_visual_review(page_id, state, similarity_score, deviations, summary)` -> the main action
- Read APIHub / WorkHub for context on what the page is supposed to do

## TYPICAL STEP
1. `list_pending_visual_reviews()` -> pick the oldest entry (or highest-critical)
2. Call `compare_with_screenshot(reference_image=<reference_path>, generated_image=<screenshot_path>)`
3. From the comparison output + your own inspection, identify at least 3 substantive deviations
4. Assess overall similarity (0.0 - 1.0); be strict — 0.75 is a quality floor, not an average
5. `submit_visual_review(page_id, state="approve" if matches_well else "needs_revision", similarity_score=..., deviations=[...], summary="...")`
6. EventHub auto-publishes a `visual_review_{state}` event; frontend agent picks it up
{%- endmacro %}

{% macro visual_reviewer_task_prompt() -%}
Begin your review cycle. Your hub_pulse will list visual reviews awaiting your attention.
For each pending review (critical routes first):
  - Read the page's metadata (route, screenshot_path, reference_path, critical)
  - Call `compare_with_screenshot(reference_image=<ref>, generated_image=<screenshot>)`
  - Identify at least 3 substantive deviations (aspect/expected/actual/severity)
  - Assess similarity (0.0-1.0)
  - Submit your review: approve (if similarity >= 0.75 on critical) OR needs_revision
After processing the queue, end the step.
{%- endmacro %}
```

- [ ] **Step 4: Verify 7 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_reviewer_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK; 7 OK / 775 OK (768 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/visual_reviewer_agent.j2 agent/tests/test_visual_reviewer_prompt.py
git commit -m "Add visual_reviewer_agent.j2 prompt (>=3 deviations + 0.75 critical floor + compare_with_screenshot)"
```

---

## Task 7: DeliverProjectTool visual gate

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`
- Create: `agent/tests/test_deliver_visual_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliver_visual_gate.py`:

```python
"""DeliverProjectTool visual gate tests (Cutover 20)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEV = [
    {"aspect": "a", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "b", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "c", "expected": "e", "actual": "a2", "severity": "low"},
]


def _agent(reg, gen_id=3000.0, agent_type="orchestrator"):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


class DeliverVisualGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliver_vis_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 3000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED",
                             delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_deliver_succeeds_with_no_visual_reviews(self) -> None:
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_succeeds_with_only_noncritical_unapproved(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/admin", screenshot_path="s", reference_path="r",
            critical=False, agent="frontend")
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_refuses_when_critical_pending(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        result = self._deliver()
        self.assertFalse(result.success)
        self.assertIn("/feed", result.error_message)
        self.assertIn("visual", result.error_message.lower())

    def test_deliver_succeeds_when_critical_approved(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches; minor color drift on accents")
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_force_deliver_bypasses_visual_gate_with_audit(self) -> None:
        self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        result = self._deliver(force_deliver=True)
        self.assertTrue(result.success, f"failed: {result.error_message}")
        events = list(self.reg.eventhub.list_events_by_type("visual_review_bypass"))
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_visual_gate -v 2>&1 | tail -10
```

Expected: failures — visual gate not wired yet.

- [ ] **Step 3: Add visual gate to `DeliverProjectTool.execute`**

In `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`, find the existing **Cutover 19 coverage gate** (added just after the Cutover 16 retro gate). Insert the visual gate **immediately after** the coverage gate (so order is: retro → coverage → visual):

```python
        # Cutover 20: visual review gate
        try:
            registry = getattr(self.agent, "hub_registry", None)
            agent_type = getattr(self.agent, "agent_type", "")
            force = kwargs.get("force_deliver") or False

            if registry is not None and hasattr(registry, "workhub"):
                from multi_agent.runtime.visual_review_gate import (
                    list_unapproved_critical,
                )
                unapproved = list_unapproved_critical(registry.workhub)
                if unapproved:
                    if force:
                        if agent_type != "orchestrator":
                            return ToolResult.fail(error_message=(
                                "force_deliver is orchestrator-only; "
                                f"caller agent_type={agent_type!r}"))
                        try:
                            routes = [(p.get("metadata") or {}).get("route")
                                       for p in unapproved]
                            registry.eventhub.publish_event(
                                source_hub="deliver",
                                event_type="visual_review_bypass",
                                payload={"unapproved_routes": routes,
                                          "by": agent_type},
                                priority="high")
                        except Exception:
                            pass
                    else:
                        routes = [(p.get("metadata") or {}).get("route", "?")
                                   for p in unapproved]
                        return ToolResult.fail(error_message=(
                            f"refused: {len(unapproved)} critical route(s) lack "
                            f"approved visual review: {', '.join(routes)}. "
                            f"Have visual_reviewer agent submit_visual_review "
                            f"for each, or force_deliver=True (orchestrator-only)."))
        except Exception:
            pass  # defense in depth
```

(Adapt `kwargs` access to match existing signature pattern. If the existing `execute` already destructures `force_deliver`, reuse the variable.)

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_visual_gate -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 780 OK (775 + 5 new). The Cutover 19 coverage + Cutover 16 retro tests should remain green.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/agent_interaction_tools.py agent/tests/test_deliver_visual_gate.py
git commit -m "DeliverProjectTool: visual review gate (block if any critical route not approved)"
```

---

## Task 8: Orchestrator + frontend prompts

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- Create: `agent/tests/test_visual_pipeline_prompts.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_visual_pipeline_prompts.py`:

```python
"""Tests that orchestrator + frontend prompts teach visual fidelity discipline."""

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
    for name in macros:
        if hasattr(mod, name):
            try:
                return getattr(mod, name)()
            except TypeError:
                return getattr(mod, name)(".", "")
    raise RuntimeError(f"no macro found in {tpl_name}")


class OrchestratorVisualPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("orchestrator_agent.j2", ["lead_specifics"])

    def test_mentions_visual_reviewer_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("VISUAL", upper)
        self.assertIn("DELIVER", upper)

    def test_mentions_critical_routes(self) -> None:
        self.assertIn("CRITICAL", self.system.upper())


class FrontendVisualPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("frontend_agent.j2",
                              ["frontend_specifics", "frontend_system_prompt"])

    def test_mentions_register_visual_review_task(self) -> None:
        self.assertIn("REGISTER_VISUAL_REVIEW_TASK", self.system.upper())

    def test_mentions_reference_image(self) -> None:
        upper = self.system.upper()
        self.assertIn("REFERENCE", upper)

    def test_mentions_capture_screenshot(self) -> None:
        upper = self.system.upper()
        self.assertTrue(any(s in upper for s in ("SCREENSHOT", "CAPTURE", "CAPTUREWEBPAGE")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_pipeline_prompts -v 2>&1 | tail -10
```

- [ ] **Step 3: Update orchestrator prompt**

In `lead_specifics()` of `orchestrator_agent.j2`, append (after Cutover 19 COVERAGE DISCIPLINE block):

```jinja
### VISUAL FIDELITY DISCIPLINE (Cutover 20)
For every critical UI route (marked `critical=true` in design page), the **Visual Reviewer** must approve a comparison between the generated screenshot and the reference image before `deliver_project()` succeeds.

Workflow:
1. After backend + frontend implementation complete, ensure each critical route has:
   - a captured screenshot at a known path (frontend agent captures via `capture_webpage` or upload from test runs)
   - a reference image (from the reference_images bundle declared at design time)
   - a registered task: `register_visual_review_task(route, screenshot_path, reference_path, critical=True)`
2. Wait for Visual Reviewer to process the queue. It will produce `submit_visual_review(state="approve" | "needs_revision", similarity_score, deviations, summary)`.
3. If any critical route is `needs_revision`, assign a fix task to the frontend agent; loop.
4. When all critical visual reviews are approved -> proceed to retro -> deliver.

If a route is intentionally allowed to diverge from reference (e.g., admin tooling not in the design system), use `mark_intentionally_dead("visual:<route>", reason)` to allowlist it. The deliver gate respects this allowlist.

`force_deliver=True` bypasses the visual gate as well (orchestrator-only, audited via `visual_review_bypass` EventHub event).
```

- [ ] **Step 4: Update frontend prompt**

In `frontend_specifics` (or analog) of `frontend_agent.j2`, append:

```jinja
### VISUAL REVIEW REGISTRATION (Cutover 20)
For every critical route you build, you MUST register a visual review task:
1. After implementing the route, capture a screenshot (e.g., via `capture_webpage(url=http://localhost:3000<route>, output_filename=...)`)
2. Identify the corresponding reference image (from the project's reference_images bundle — the design page metadata should reference it)
3. Call `register_visual_review_task(route=<route>, screenshot_path=<absolute>, reference_path=<absolute>, critical=True)`

For non-critical routes (admin tools, debug views, secondary flows), set `critical=False` — the gate won't enforce approval but the task still gets reviewed for the record.

DO NOT skip this step. `deliver_project()` will refuse if any critical route lacks an approved review. Skipping creates work for the orchestrator + visual_reviewer at the end of the run instead of distributing it.
```

- [ ] **Step 5: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_pipeline_prompts -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 785 OK (780 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2 agent/tests/test_visual_pipeline_prompts.py
git commit -m "Orchestrator + frontend prompts: VISUAL FIDELITY DISCIPLINE + register_visual_review_task workflow"
```

---

## Task 9: E2E + migration log + push

**Files:**
- Create: `agent/tests/test_visual_review_e2e.py`
- Create: `docs/superpowers/migration-logs/21-visual-fidelity-gate.md`

- [ ] **Step 1: Write the E2E test**

Create `agent/tests/test_visual_review_e2e.py`:

```python
"""E2E: critical route blocks deliver; substantive review unblocks; force-deliver audits."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEV = [
    {"aspect": "primary button color",
     "expected": "#1d4ed8", "actual": "#2563eb", "severity": "low"},
    {"aspect": "header spacing",
     "expected": "16px", "actual": "8px", "severity": "medium"},
    {"aspect": "card border radius",
     "expected": "12px", "actual": "4px", "severity": "low"},
]


def _agent(reg, gen_id=4000.0, agent_type="orchestrator"):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


class VisualReviewE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vis_e2e_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 4000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_full_flow_register_review_approve_deliver(self) -> None:
        # Frontend registers task
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        # Deliver refused
        r1 = self._deliver()
        self.assertFalse(r1.success)
        # Visual reviewer approves
        self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV,
            summary="Layout matches reference; minor color drift on accents")
        # Deliver succeeds
        r2 = self._deliver()
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_rubber_stamp_approve_blocked_at_submit(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        result = self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.85,
            deviations=_GOOD_DEV[:2],  # only 2 deviations
            summary="..............................")
        self.assertIn("error", result)
        # Status stays pending
        latest = self.reg.workhub.get_visual_review(page["id"])
        self.assertEqual(latest["status"], "pending")

    def test_low_similarity_on_critical_forces_needs_revision(self) -> None:
        page = self.reg.workhub.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        # Try to approve with similarity=0.5
        r = self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="approve", similarity_score=0.50,
            deviations=_GOOD_DEV,
            summary="Layout off; should not approve")
        self.assertIn("error", r)
        # needs_revision with same low score is accepted
        r2 = self.reg.workhub.submit_visual_review(
            page["id"], reviewer="visual_reviewer",
            state="needs_revision", similarity_score=0.50,
            deviations=[_GOOD_DEV[0]],
            summary="Layout off")
        self.assertNotIn("error", r2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify 3 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_visual_review_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 788 OK (785 + 3 new).

- [ ] **Step 3: Final baselines + zero Claude trailer check**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 4: Write migration log**

Create `docs/superpowers/migration-logs/21-visual-fidelity-gate.md`:

```markdown
# Cutover 20: UI Visual Fidelity Gate

**Branch:** `haibotong-cutover-20-visual-fidelity`
**Date:** 2026-05-25

## What

Visual reviewer agent (13th profile) + structural gate that blocks
`deliver_project()` if any UI route marked `critical=true` lacks an approved
Visual Review. Approve requires similarity_score >= 0.75 (critical routes),
>=3 substantive deviations (aspect/expected/actual/severity), and >=20-char summary.

Same pattern as Cutover 14 architect-review (>=3 challenges) but for visual
instead of structural design.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 737 OK -> 788 OK (+51 new)

## New surfaces
- runtime/visual_review_gate.py — assert_critical_visuals_approved + list_unapproved_critical
- tools/visual_review_tools.py — 4 tools (register/submit/list/get_status)
- prompts/v2/visual_reviewer_agent.j2 — new agent prompt
- WorkHub: register_visual_review_task / submit_visual_review / list_pending_visual_reviews / list_critical_visual_reviews / is_visual_approved / get_visual_review
- 13th agent profile: visual_reviewer

## Reused surfaces
- WorkHub pages with kind="visual_review" (Cutover 14 pattern)
- CompareWithScreenshotTool from vision_tools.py (Cutover 18 inventory)
- mark_intentionally_dead allowlist (Cutover 19 escape hatch)
- force_deliver orchestrator-only audit bypass (Cutover 19 pattern)

## Known limits (future cutovers)
- Frontend / orchestrator must manually capture screenshots + register tasks
  (RunHub does not yet auto-screenshot post-run; future cutover)
- Vision comparison uses CompareWithScreenshotTool which is itself LLM-based;
  the similarity_score is what the visual_reviewer judges, not an automated metric
- No per-component diff yet — only full-route comparison
```

- [ ] **Step 5: Commit log + push**

```bash
git add agent/tests/test_visual_review_e2e.py docs/superpowers/migration-logs/21-visual-fidelity-gate.md
git commit -m "Add Cutover 20 e2e + migration log"
git push red-env-gen haibotong-cutover-20-visual-fidelity 2>&1 | tail -5
```

- [ ] **Step 6: Report** — final test counts, push URL, deferred items.

---

## Self-Review

**1. Spec coverage:**
- WorkHub visual_review schema + 6 helpers — Task 2 ✓
- visual_review_gate module — Task 3 ✓
- 4 LLM tools — Task 4 ✓
- visual_reviewer profile (13th) — Task 5 ✓
- visual_reviewer prompt — Task 6 ✓
- DeliverProjectTool visual gate + force bypass — Task 7 ✓
- Orchestrator + frontend prompts — Task 8 ✓
- E2E + log + push — Task 9 ✓

**2. Placeholder scan:** No "TBD" / "implement later".

**3. Type consistency:**
- `register_visual_review_task(route, screenshot_path, reference_path, critical=False, agent="")` — same signature in WorkHub + tool + tests + prompt
- `submit_visual_review(page_id, reviewer, state, similarity_score, deviations, summary)` — consistent across module/tool/tests
- Deviation shape `{aspect, expected, actual, severity}` — same in WorkHub validation + tool schema + prompt
- Lifecycle states `pending / reviewing / approved / needs_revision` — consistent
- Tool NAMEs: `register_visual_review_task`, `submit_visual_review`, `list_pending_visual_reviews`, `get_visual_review_status` — same in tool class + prompt + tests
- Similarity floor 0.75 — consistent across WorkHub validation + prompt + gate

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 9 ✓
- Baselines green at every task boundary ✓
- TDD throughout ✓
- Substantive-review pattern mirrors Cutover 13/14 (architectural consistency) ✓
- Force-deliver bypass mirrors Cutover 19 (audited via EventHub) ✓
- Visual reviews reuse existing WorkHub store (no new entity) ✓
