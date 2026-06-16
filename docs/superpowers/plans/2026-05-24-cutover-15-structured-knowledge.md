# Cutover 15: Structured Knowledge Outputs (ADR / Runbook / Postmortem)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force the Knowledge agent (and others writing to Knowledge) to produce structured engineering documents — Architecture Decision Records (ADR), runbooks, postmortems — instead of dumping free-form notes. Each structured document type has required fields validated at write time.

**Architecture:** Extend the existing `Knowledge` dataclass with 3 new `KnowledgeCategory` values (`ADR`, `RUNBOOK`, `POSTMORTEM`) and per-category structured metadata fields. Add 3 convenience LLM tools (`submit_adr`, `submit_runbook`, `submit_postmortem`) that validate required fields before persistence + 3 listing tools. Knowledge agent prompt teaches when to use each type. Existing `store_knowledge`/`query_knowledge` continue to work for ad-hoc entries; the structured tools are additive.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Existing surfaces: `multi_agent/knowledge/types.py` (Knowledge dataclass + KnowledgeCategory enum), `tools/knowledge_tools.py` (StoreKnowledgeTool / QueryKnowledgeTool), `KnowledgeStore` (sqlite backend).

---

## Context for Worker

### Why this cutover exists

Today the Knowledge agent has rich free-form output but **no enforced structure**. Real engineering orgs produce three categorical document types that the system currently can't:

- **ADR** (Architecture Decision Record): captures *why* an architectural choice was made, what alternatives were considered, and consequences. Without ADRs, the next agent re-litigates settled decisions or breaks invariants nobody documented.
- **Runbook**: step-by-step operational procedure for a known scenario (deploy X, recover from Y, rotate Z). Without runbooks, every incident is debugged from scratch.
- **Postmortem**: structured incident retrospective with timeline, impact, root cause, and action items. Without postmortems, the same class of bug recurs.

This cutover adds these three structured document types with field validation at write time. Free-form `store_knowledge` continues to work — the new tools are additive and ergonomic.

### Schema additions

3 new `KnowledgeCategory` enum values:

```python
class KnowledgeCategory(str, Enum):
    # ...existing values...
    ADR = "adr"
    RUNBOOK = "runbook"
    POSTMORTEM = "postmortem"
```

`Knowledge` dataclass gets a new field `structured_fields: Dict[str, Any]` (default `{}`) holding the per-category structured payload. We do NOT add 10+ new top-level dataclass fields — that bloats the schema and most are mutually exclusive by category.

Per-category required keys in `structured_fields`:

- **ADR**: `decision` (str), `context` (str), `alternatives` (List[str]), `consequences` (str), `status` (one of: proposed | accepted | deprecated | superseded)
- **RUNBOOK**: `trigger` (str), `steps` (List[str], ≥3 entries), `verification` (str), `rollback` (str)
- **POSTMORTEM**: `incident_date` (ISO date string), `impact` (str), `timeline` (List[str], ≥3 entries), `root_cause` (str), `action_items` (List[str], ≥1 entry)

Validation happens in the 3 new submit tools (not in `Knowledge.__post_init__`) so free-form writes via `store_knowledge` aren't affected.

### Tool surface

3 submit tools + 3 list tools:

- `submit_adr(title, decision, context, alternatives, consequences, status="accepted", tags=[])` — validates required fields, sets `category=ADR`, calls existing `KnowledgeStore.store`
- `submit_runbook(title, trigger, steps, verification, rollback, tags=[])` — same pattern
- `submit_postmortem(title, incident_date, impact, timeline, root_cause, action_items, tags=[])` — same pattern
- `list_adrs(status=None, limit=20)` — queries `KnowledgeStore` filtered by `category=ADR`
- `list_runbooks(limit=20)`
- `list_postmortems(limit=20)`

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python`
- No Claude trailer on commits; no emojis
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 7
- Both baselines green at every task: regressions 7 OK; discover 584 OK after Cutover 14
- HubTool framework convention: `NAME`, `DESCRIPTION`, `PARAMETERS`, async `_run`, `_finalize_hub_tools` — BUT the existing knowledge_tools.py uses `BaseTool` (not `HubTool`) and a different bundle pattern. Inspect `tools/knowledge_tools.py` (the existing tools file) before assuming HubTool conventions.

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/tools/structured_knowledge_tools.py` — 6 new tools
- `agent/tests/test_knowledge_categories.py`
- `agent/tests/test_structured_knowledge_tools.py`
- `agent/tests/test_knowledge_agent_structured_prompt.py`
- `agent/tests/test_structured_knowledge_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/knowledge/types.py` — add 3 categories + `structured_fields` to `Knowledge`
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `structured_knowledge_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `structured_knowledge_tools` bundle to `knowledge` profile
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2` — teach when to use each type

---

## Task 1: Worktree setup + baseline

**Files:**
- Create: `docs/superpowers/cutover-15-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-15-structured-knowledge
git status
git log --oneline -3
```

Expected: clean, on `haibotong-cutover-15-structured-knowledge`. If missing: `git worktree add -b haibotong-cutover-15-structured-knowledge .worktrees/haibotong-cutover-15-structured-knowledge haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 584 OK.

- [ ] **Step 3: Inventory existing knowledge tools convention**

```bash
grep -nE "class .*Tool\(|NAME = |super\(\)\.__init__" agent/env_generator/llm_generator/tools/knowledge_tools.py | head -15
```

Record: tool base class (`BaseTool`? `HubTool`?), how tools access KnowledgeStore, async vs sync, ToolResult shape.

- [ ] **Step 4: Inventory knowledge bundle registration**

```bash
grep -nE "knowledge_tools|knowledge_write_tools|knowledge_read_tools" agent/env_generator/llm_generator/multi_agent/tool_bundles.py | head -10
```

Record the existing bundle name(s) and the registration pattern.

- [ ] **Step 5: Write baseline note**

Create `docs/superpowers/cutover-15-baseline.md`:

```markdown
# Cutover 15 Baseline (Structured Knowledge Outputs)

## Test counts
- regressions: 7 OK
- discover: 584 OK

## Gap this cutover closes
Knowledge agent produces free-form notes; no structured ADR / runbook /
postmortem categories. Settled architecture decisions, operational procedures,
and incident retrospectives get lost in unstructured dumps.

## Existing surfaces we extend
- `KnowledgeCategory` enum in `multi_agent/knowledge/types.py` — has 30+
  free-form categories; adding 3 structured ones (ADR/RUNBOOK/POSTMORTEM)
- `Knowledge` dataclass — adding `structured_fields: Dict[str, Any]`
- `tools/knowledge_tools.py` — uses BaseTool (not HubTool); adding sibling
  `structured_knowledge_tools.py` with same convention

## Tool surface added (6 tools)
- submit_adr / submit_runbook / submit_postmortem (validated writes)
- list_adrs / list_runbooks / list_postmortems (filtered queries)
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/cutover-15-baseline.md
git commit -m "Cutover 15: record pre-flight baseline (regressions 7 OK, discover 584 OK)"
```

---

## Task 2: Add 3 new categories + `structured_fields` to `Knowledge`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/knowledge/types.py`
- Create: `agent/tests/test_knowledge_categories.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_knowledge_categories.py`:

```python
"""Tests for new structured Knowledge categories (Cutover 15)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.knowledge.types import Knowledge, KnowledgeCategory  # noqa: E402


class KnowledgeCategoriesTests(unittest.TestCase):
    def test_adr_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.ADR.value, "adr")

    def test_runbook_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.RUNBOOK.value, "runbook")

    def test_postmortem_category_exists(self) -> None:
        self.assertEqual(KnowledgeCategory.POSTMORTEM.value, "postmortem")


class KnowledgeStructuredFieldsTests(unittest.TestCase):
    def test_default_structured_fields_is_empty_dict(self) -> None:
        k = Knowledge(title="x")
        self.assertEqual(k.structured_fields, {})

    def test_can_construct_with_structured_fields(self) -> None:
        k = Knowledge(title="adr-001", category=KnowledgeCategory.ADR,
                      structured_fields={"decision": "use postgres",
                                          "context": "needed ACID",
                                          "alternatives": ["mysql", "sqlite"],
                                          "consequences": "ops overhead",
                                          "status": "accepted"})
        self.assertEqual(k.structured_fields["decision"], "use postgres")
        self.assertEqual(k.structured_fields["status"], "accepted")

    def test_to_dict_includes_structured_fields(self) -> None:
        k = Knowledge(title="r1", category=KnowledgeCategory.RUNBOOK,
                      structured_fields={"trigger": "deploy", "steps": ["a", "b", "c"],
                                          "verification": "v", "rollback": "r"})
        d = k.to_dict()
        self.assertIn("structured_fields", d)
        self.assertEqual(d["structured_fields"]["trigger"], "deploy")
        self.assertEqual(d["category"], "runbook")

    def test_from_dict_roundtrips_structured_fields(self) -> None:
        if not hasattr(Knowledge, "from_dict"):
            self.skipTest("Knowledge.from_dict not present in this version")
        payload = {
            "title": "pm1", "category": "postmortem",
            "structured_fields": {
                "incident_date": "2026-05-23", "impact": "p99 +400ms",
                "timeline": ["t1", "t2", "t3"], "root_cause": "cache miss",
                "action_items": ["a1"],
            },
        }
        k = Knowledge.from_dict(payload)
        self.assertEqual(k.category, KnowledgeCategory.POSTMORTEM)
        self.assertEqual(k.structured_fields["impact"], "p99 +400ms")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_knowledge_categories -v 2>&1 | tail -10
```

Expected: AttributeError on `KnowledgeCategory.ADR` etc.

- [ ] **Step 3: Add 3 enum values**

In `agent/env_generator/llm_generator/multi_agent/knowledge/types.py`, in the `KnowledgeCategory` enum (find by `class KnowledgeCategory`), add at the end (after `ANTI_PATTERN`):

```python
    # Structured engineering documents (Cutover 15)
    ADR = "adr"                             # Architecture Decision Record
    RUNBOOK = "runbook"                     # Operational procedure
    POSTMORTEM = "postmortem"               # Incident retrospective
```

- [ ] **Step 4: Add `structured_fields` to `Knowledge` dataclass**

In the `Knowledge` dataclass (find by `class Knowledge:`), add as a new field (after `related_ids` or another safe location):

```python
    # Structured payload for ADR/RUNBOOK/POSTMORTEM categories (Cutover 15).
    # Free-form for other categories.
    structured_fields: Dict[str, Any] = field(default_factory=dict)
```

In `to_dict`, add `"structured_fields": self.structured_fields` to the returned dict.

In `from_dict` (if present), parse `structured_fields` defaulting to `{}`:
```python
structured_fields=d.get("structured_fields", {}) or {},
```

If `from_dict` doesn't exist, that's fine — the 4th test will skip.

- [ ] **Step 5: Verify 7 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_knowledge_categories -v 2>&1 | tail -15
```

Expected: 7 OK (or 6 OK + 1 skip if `from_dict` doesn't exist).

- [ ] **Step 6: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 591 OK (584 + 7 new). If any existing knowledge test breaks because `Knowledge` now has an extra field, that's surprising — the new field defaults to `{}` so equality checks should still pass. If a test does deep equality on `to_dict()` output expecting an exact key set, update it minimally.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/knowledge/types.py agent/tests/test_knowledge_categories.py
git commit -m "Knowledge: add ADR/RUNBOOK/POSTMORTEM categories + structured_fields dict"
```

---

## Task 3: Structured submit + list LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/structured_knowledge_tools.py`
- Create: `agent/tests/test_structured_knowledge_tools.py`

- [ ] **Step 1: Inspect knowledge_tools.py convention**

```bash
sed -n '130,200p' agent/env_generator/llm_generator/tools/knowledge_tools.py
```

Note: how `StoreKnowledgeTool` accesses `KnowledgeStore` (likely via `_get_store()` module-level helper), the `BaseTool` base, the `_run`/`execute` method signature, the `ToolResult` shape. **Use the same convention** — don't introduce `HubTool` patterns here.

- [ ] **Step 2: Write failing tests**

Create `agent/tests/test_structured_knowledge_tools.py`:

```python
"""Tests for structured knowledge LLM tools (Cutover 15)."""

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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh_store(tmp):
    """Build an isolated KnowledgeStore over a temp sqlite file."""
    from multi_agent.knowledge.store import KnowledgeStore
    db_path = Path(tmp) / "k.db"
    return KnowledgeStore(db_url=f"sqlite:///{db_path}")


class StructuredKnowledgeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="struct_k_"))
        self.store = _fresh_store(self.tmp)
        # Reset the module-level singleton to use our isolated store
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = self.store

    def tearDown(self) -> None:
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- submit_adr ----

    def test_submit_adr_with_all_required_fields_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="ADR-001: use postgres",
            decision="use postgres",
            context="need ACID for financial data",
            alternatives=["mysql", "sqlite"],
            consequences="ops overhead is acceptable",
            status="accepted"))
        self.assertTrue(result.success, f"failed: {result.error_message}")
        self.assertIn("id", result.data)

    def test_submit_adr_rejects_missing_alternatives(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=[], consequences="x", status="accepted"))
        self.assertFalse(result.success)

    def test_submit_adr_rejects_invalid_status(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=["a"], consequences="x", status="bogus"))
        self.assertFalse(result.success)

    # ---- submit_runbook ----

    def test_submit_runbook_with_all_required_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitRunbookTool
        result = _run_async(SubmitRunbookTool().execute(
            title="deploy frontend",
            trigger="ready to ship feature/x",
            steps=["pull main", "yarn build", "yarn deploy"],
            verification="curl /health returns 200",
            rollback="yarn deploy --rollback"))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_runbook_rejects_fewer_than_3_steps(self) -> None:
        from tools.structured_knowledge_tools import SubmitRunbookTool
        result = _run_async(SubmitRunbookTool().execute(
            title="x", trigger="t",
            steps=["one", "two"],
            verification="v", rollback="r"))
        self.assertFalse(result.success)

    # ---- submit_postmortem ----

    def test_submit_postmortem_with_all_required_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="P-001: feed 500s",
            incident_date="2026-05-23",
            impact="p99 +400ms for 30min",
            timeline=["12:00 alert fired", "12:05 oncall paged",
                       "12:30 rolled back"],
            root_cause="cache miss storm after deploy",
            action_items=["add cache warming step to runbook"]))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_postmortem_rejects_empty_action_items(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=[]))
        self.assertFalse(result.success)

    def test_submit_postmortem_rejects_fewer_than_3_timeline_entries(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="2026-05-23", impact="i",
            timeline=["a", "b"], root_cause="r", action_items=["x"]))
        self.assertFalse(result.success)

    # ---- list tools ----

    def test_list_adrs_returns_submitted_adrs(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
        )
        _run_async(SubmitADRTool().execute(
            title="ADR-001", decision="d", context="c",
            alternatives=["a"], consequences="x", status="accepted"))
        _run_async(SubmitADRTool().execute(
            title="ADR-002", decision="d2", context="c2",
            alternatives=["b"], consequences="y", status="proposed"))
        result = _run_async(ListADRsTool().execute())
        self.assertTrue(result.success)
        adrs = result.data["adrs"]
        self.assertEqual(len(adrs), 2)
        titles = {a["title"] for a in adrs}
        self.assertEqual(titles, {"ADR-001", "ADR-002"})

    def test_list_adrs_filters_by_status(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
        )
        _run_async(SubmitADRTool().execute(
            title="A1", decision="d", context="c",
            alternatives=["a"], consequences="x", status="accepted"))
        _run_async(SubmitADRTool().execute(
            title="A2", decision="d", context="c",
            alternatives=["a"], consequences="x", status="proposed"))
        result = _run_async(ListADRsTool().execute(status="accepted"))
        adrs = result.data["adrs"]
        self.assertEqual(len(adrs), 1)
        self.assertEqual(adrs[0]["title"], "A1")

    def test_list_runbooks_returns_submitted_runbooks(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitRunbookTool, ListRunbooksTool,
        )
        _run_async(SubmitRunbookTool().execute(
            title="R1", trigger="t", steps=["a", "b", "c"],
            verification="v", rollback="r"))
        result = _run_async(ListRunbooksTool().execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["runbooks"]), 1)

    def test_list_postmortems_returns_submitted(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitPostmortemTool, ListPostmortemsTool,
        )
        _run_async(SubmitPostmortemTool().execute(
            title="P1", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))
        result = _run_async(ListPostmortemsTool().execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["postmortems"]), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_structured_knowledge_tools -v 2>&1 | tail -15
```

Expected: ImportError on `structured_knowledge_tools`.

- [ ] **Step 4: Implement the 6 tools**

Create `agent/env_generator/llm_generator/tools/structured_knowledge_tools.py`. Match the existing knowledge_tools.py convention (likely `BaseTool` base, not `HubTool`):

```python
"""Structured knowledge tools — ADR / Runbook / Postmortem (Cutover 15).

Wraps the existing KnowledgeStore with shape-validated submit + list helpers
for engineering documents. Free-form `store_knowledge` continues to work
for ad-hoc notes; these tools enforce structure for the 3 document types.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

from ._base import BaseTool, ToolCategory, ToolResult
from .knowledge_tools import _get_store


_ADR_STATUS = ("proposed", "accepted", "deprecated", "superseded")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _import_types():
    from multi_agent.knowledge.types import Knowledge, KnowledgeCategory
    return Knowledge, KnowledgeCategory


def _validate_nonempty_str(value: Any, name: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return f"{name} must be a non-empty string"
    return None


def _validate_list_min(value: Any, name: str, min_len: int) -> Optional[str]:
    if not isinstance(value, list) or len(value) < min_len:
        return f"{name} must be a list of length >= {min_len}"
    bad = [i for i, v in enumerate(value) if not isinstance(v, str) or not v.strip()]
    if bad:
        return f"{name} entries at index {bad} are empty or non-string"
    return None


class SubmitADRTool(BaseTool):
    NAME = "submit_adr"
    DESCRIPTION = ("Submit an Architecture Decision Record. Required: title, "
                    "decision, context, alternatives (list), consequences, "
                    "status (proposed | accepted | deprecated | superseded).")

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "decision": {"type": "string"},
                "context": {"type": "string"},
                "alternatives": {"type": "array", "items": {"type": "string"}},
                "consequences": {"type": "string"},
                "status": {"type": "string", "enum": list(_ADR_STATUS),
                            "default": "accepted"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title", "decision", "context", "alternatives",
                          "consequences"],
        }

    async def execute(self, *, title: str, decision: str, context: str,
                       alternatives: list, consequences: str,
                       status: str = "accepted",
                       tags: list = None) -> ToolResult:
        for field, name in [(title, "title"), (decision, "decision"),
                             (context, "context"), (consequences, "consequences")]:
            err = _validate_nonempty_str(field, name)
            if err:
                return ToolResult(success=False, error_message=err)
        err = _validate_list_min(alternatives, "alternatives", 1)
        if err:
            return ToolResult(success=False, error_message=err)
        if status not in _ADR_STATUS:
            return ToolResult(success=False,
                              error_message=f"status must be one of {_ADR_STATUS}")
        Knowledge, KnowledgeCategory = _import_types()
        k = Knowledge(title=title, category=KnowledgeCategory.ADR,
                      summary=decision, tags=tags or [],
                      structured_fields={
                          "decision": decision, "context": context,
                          "alternatives": alternatives,
                          "consequences": consequences, "status": status,
                      })
        _get_store().store(k)
        return ToolResult(success=True, data={"id": k.id, "title": k.title})


class SubmitRunbookTool(BaseTool):
    NAME = "submit_runbook"
    DESCRIPTION = ("Submit a Runbook. Required: title, trigger, steps (>=3), "
                    "verification, rollback.")

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "trigger": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "string"},
                "rollback": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title", "trigger", "steps", "verification", "rollback"],
        }

    async def execute(self, *, title: str, trigger: str, steps: list,
                       verification: str, rollback: str,
                       tags: list = None) -> ToolResult:
        for field, name in [(title, "title"), (trigger, "trigger"),
                             (verification, "verification"), (rollback, "rollback")]:
            err = _validate_nonempty_str(field, name)
            if err:
                return ToolResult(success=False, error_message=err)
        err = _validate_list_min(steps, "steps", 3)
        if err:
            return ToolResult(success=False, error_message=err)
        Knowledge, KnowledgeCategory = _import_types()
        k = Knowledge(title=title, category=KnowledgeCategory.RUNBOOK,
                      summary=trigger, tags=tags or [],
                      structured_fields={
                          "trigger": trigger, "steps": steps,
                          "verification": verification, "rollback": rollback,
                      })
        _get_store().store(k)
        return ToolResult(success=True, data={"id": k.id, "title": k.title})


class SubmitPostmortemTool(BaseTool):
    NAME = "submit_postmortem"
    DESCRIPTION = ("Submit a Postmortem. Required: title, incident_date "
                    "(YYYY-MM-DD), impact, timeline (>=3 entries), root_cause, "
                    "action_items (>=1).")

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "incident_date": {"type": "string"},
                "impact": {"type": "string"},
                "timeline": {"type": "array", "items": {"type": "string"}},
                "root_cause": {"type": "string"},
                "action_items": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title", "incident_date", "impact", "timeline",
                          "root_cause", "action_items"],
        }

    async def execute(self, *, title: str, incident_date: str, impact: str,
                       timeline: list, root_cause: str, action_items: list,
                       tags: list = None) -> ToolResult:
        for field, name in [(title, "title"), (impact, "impact"),
                             (root_cause, "root_cause")]:
            err = _validate_nonempty_str(field, name)
            if err:
                return ToolResult(success=False, error_message=err)
        if not _DATE_RE.match(incident_date or ""):
            return ToolResult(success=False,
                              error_message="incident_date must be YYYY-MM-DD")
        err = _validate_list_min(timeline, "timeline", 3)
        if err:
            return ToolResult(success=False, error_message=err)
        err = _validate_list_min(action_items, "action_items", 1)
        if err:
            return ToolResult(success=False, error_message=err)
        Knowledge, KnowledgeCategory = _import_types()
        k = Knowledge(title=title, category=KnowledgeCategory.POSTMORTEM,
                      summary=impact, tags=tags or [],
                      structured_fields={
                          "incident_date": incident_date, "impact": impact,
                          "timeline": timeline, "root_cause": root_cause,
                          "action_items": action_items,
                      })
        _get_store().store(k)
        return ToolResult(success=True, data={"id": k.id, "title": k.title})


def _list_by_category(category, status_filter: Optional[str] = None,
                       limit: int = 20) -> list:
    """Helper: query KnowledgeStore for entries of a given category."""
    Knowledge, KnowledgeCategory = _import_types()
    store = _get_store()
    # Use the broad list/query API — falls back to filtering Python-side
    # to keep impl portable across store backends.
    all_entries = []
    if hasattr(store, "list_all"):
        all_entries = list(store.list_all())
    elif hasattr(store, "query"):
        # KnowledgeQuery surfaces vary; fall back to iter
        from multi_agent.knowledge.types import KnowledgeQuery
        results = store.query(KnowledgeQuery(category=category, limit=limit * 4))
        all_entries = [r.knowledge if hasattr(r, "knowledge") else r for r in results]
    else:
        return []
    out = []
    for k in all_entries:
        if getattr(k, "category", None) != category:
            continue
        if status_filter and (k.structured_fields or {}).get("status") != status_filter:
            continue
        out.append({"id": k.id, "title": k.title,
                     "structured_fields": k.structured_fields,
                     "tags": k.tags,
                     "created_at": k.created_at.isoformat() if hasattr(k.created_at, "isoformat") else str(k.created_at)})
        if len(out) >= limit:
            break
    return out


class ListADRsTool(BaseTool):
    NAME = "list_adrs"
    DESCRIPTION = "List Architecture Decision Records, optionally filtered by status."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(_ADR_STATUS)},
                "limit": {"type": "integer", "default": 20},
            },
        }

    async def execute(self, *, status: str = None, limit: int = 20) -> ToolResult:
        Knowledge, KnowledgeCategory = _import_types()
        adrs = _list_by_category(KnowledgeCategory.ADR, status, limit)
        return ToolResult(success=True, data={"adrs": adrs})


class ListRunbooksTool(BaseTool):
    NAME = "list_runbooks"
    DESCRIPTION = "List Runbooks."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        }

    async def execute(self, *, limit: int = 20) -> ToolResult:
        Knowledge, KnowledgeCategory = _import_types()
        return ToolResult(success=True, data={
            "runbooks": _list_by_category(KnowledgeCategory.RUNBOOK, None, limit)})


class ListPostmortemsTool(BaseTool):
    NAME = "list_postmortems"
    DESCRIPTION = "List Postmortems."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.parameters = {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        }

    async def execute(self, *, limit: int = 20) -> ToolResult:
        Knowledge, KnowledgeCategory = _import_types()
        return ToolResult(success=True, data={
            "postmortems": _list_by_category(KnowledgeCategory.POSTMORTEM, None, limit)})


_STRUCTURED_KNOWLEDGE_TOOLS = [
    SubmitADRTool, SubmitRunbookTool, SubmitPostmortemTool,
    ListADRsTool, ListRunbooksTool, ListPostmortemsTool,
]


def create_structured_knowledge_tools() -> list:
    return [cls() for cls in _STRUCTURED_KNOWLEDGE_TOOLS]


__all__ = [
    "SubmitADRTool", "SubmitRunbookTool", "SubmitPostmortemTool",
    "ListADRsTool", "ListRunbooksTool", "ListPostmortemsTool",
    "create_structured_knowledge_tools",
]
```

**Adapt the imports** (`from ._base import BaseTool, ToolCategory, ToolResult` and `from .knowledge_tools import _get_store`) if the real conventions differ. Check `knowledge_tools.py` for the exact import shape.

- [ ] **Step 5: Verify 13 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_structured_knowledge_tools -v 2>&1 | tail -25
```

Expected: 13 OK. If `_list_by_category` returns empty because of store query API differences, adjust the helper to match `KnowledgeStore`'s actual query surface (the test setup already sets `_kt._knowledge_store` to a fresh store, so storage + retrieval should round-trip).

- [ ] **Step 6: Both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 604 OK (591 + 13 new).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/tools/structured_knowledge_tools.py agent/tests/test_structured_knowledge_tools.py
git commit -m "Add structured_knowledge_tools: submit_adr/runbook/postmortem + list_adrs/runbooks/postmortems"
```

---

## Task 4: Register bundle + wire to knowledge profile

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_structured_knowledge_bundle.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_structured_knowledge_bundle.py`:

```python
"""Tests for structured_knowledge_tools bundle registration."""

import unittest
from pathlib import Path

import yaml

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

CONFIG = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents" / "agents_config.yaml"


class StructuredKnowledgeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG) as f:
            cls.cfg = yaml.safe_load(f)

    def test_knowledge_profile_has_structured_knowledge_tools_bundle(self) -> None:
        prof = self.cfg["profiles"]["knowledge"]
        self.assertIn("structured_knowledge_tools", prof.get("tool_bundles", []))

    def test_bundle_registry_has_entry(self) -> None:
        import importlib
        mod = importlib.import_module(
            "multi_agent.tool_bundles")
        self.assertIn("structured_knowledge_tools", mod.TOOL_BUNDLE_REGISTRY)
```

- [ ] **Step 2: Register the bundle**

In `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`, add (mirror an existing knowledge-bundle pattern):

```python
from tools.structured_knowledge_tools import create_structured_knowledge_tools

def _bundle_structured_knowledge_tools(builder, context) -> None:
    builder.add(create_structured_knowledge_tools(), ("knowledge",))

# In TOOL_BUNDLE_REGISTRY:
"structured_knowledge_tools": _bundle_structured_knowledge_tools,

# In TOOL_BUNDLE_REQUIREMENTS:
"structured_knowledge_tools": {"knowledge"},
```

If `builder.add(tools, category)` expects a different signature (e.g., string vs tuple), match the existing knowledge bundle pattern.

- [ ] **Step 3: Wire to knowledge profile**

In `agents_config.yaml`, find `knowledge:` profile, add `structured_knowledge_tools` to its `tool_bundles` list (after the existing knowledge-related bundles).

- [ ] **Step 4: Verify 2 tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_structured_knowledge_bundle -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 2 new OK; 7 OK / 606 OK (604 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_structured_knowledge_bundle.py
git commit -m "Register structured_knowledge_tools bundle + wire to knowledge profile"
```

---

## Task 5: Update Knowledge agent prompt

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2`
- Create: `agent/tests/test_knowledge_agent_structured_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_knowledge_agent_structured_prompt.py`:

```python
"""Tests that knowledge_agent prompt teaches structured outputs."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class KnowledgeAgentStructuredPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("knowledge_agent.j2")
        mod = tpl.make_module()
        for name in ("knowledge_specifics", "knowledge_system_prompt"):
            if hasattr(mod, name):
                try:
                    cls.system = getattr(mod, name)()
                except TypeError:
                    cls.system = getattr(mod, name)(".", "")
                break
        else:
            raise RuntimeError("no knowledge specifics/system macro")

    def test_prompt_mentions_submit_adr(self) -> None:
        self.assertIn("SUBMIT_ADR", self.system.upper())

    def test_prompt_mentions_submit_runbook(self) -> None:
        self.assertIn("SUBMIT_RUNBOOK", self.system.upper())

    def test_prompt_mentions_submit_postmortem(self) -> None:
        self.assertIn("SUBMIT_POSTMORTEM", self.system.upper())

    def test_prompt_explains_when_to_use_each_type(self) -> None:
        upper = self.system.upper()
        # Heuristic: prompt should describe the trigger condition for each type
        self.assertIn("DECISION", upper)
        self.assertIn("INCIDENT", upper)
        self.assertTrue("OPERATIONAL" in upper or "PROCEDURE" in upper or "DEPLOY" in upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_knowledge_agent_structured_prompt -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `knowledge_agent.j2`**

Find the macro (likely `knowledge_specifics` or `knowledge_system_prompt`) and add a block:

```jinja
## STRUCTURED ENGINEERING DOCUMENTS (Cutover 15)
For the three categorical document types below, use the dedicated submit tools instead of free-form `store_knowledge`. They validate required fields and produce queryable, structured records.

- `submit_adr(title, decision, context, alternatives, consequences, status)` - Architecture **DECISION** Record. Use when an architectural choice was made (database engine, framework, protocol). Captures WHY, alternatives considered, and consequences. Status: proposed | accepted | deprecated | superseded.

- `submit_runbook(title, trigger, steps, verification, rollback)` - Operational **PROCEDURE**. Use when shipping new operational behavior (deploy steps, recovery from a known scenario, rotation procedure). Requires at least 3 steps + verification step + rollback.

- `submit_postmortem(title, incident_date, impact, timeline, root_cause, action_items)` - **INCIDENT** retrospective. Use after a runtime failure (RunHub `run_failed`, on-call page). Timeline >=3 entries; at least 1 action item required.

Use `list_adrs(status=)`, `list_runbooks()`, `list_postmortems()` to retrieve.

Free-form `store_knowledge` continues to work for ad-hoc notes that don't fit these three shapes.
```

- [ ] **Step 4: Verify 4 tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_knowledge_agent_structured_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 610 OK (606 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/knowledge_agent.j2 agent/tests/test_knowledge_agent_structured_prompt.py
git commit -m "Knowledge agent prompt: teach submit_adr / submit_runbook / submit_postmortem"
```

---

## Task 6: End-to-end test

**Files:**
- Create: `agent/tests/test_structured_knowledge_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_structured_knowledge_e2e.py`:

```python
"""End-to-end: structured submit + list workflow with isolated KnowledgeStore."""

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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class StructuredKnowledgeE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sk_e2e_"))
        from multi_agent.knowledge.store import KnowledgeStore
        self.store = KnowledgeStore(db_url=f"sqlite:///{self.tmp}/k.db")
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = self.store

    def tearDown(self) -> None:
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_doc_lifecycle(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, SubmitRunbookTool, SubmitPostmortemTool,
            ListADRsTool, ListRunbooksTool, ListPostmortemsTool,
        )
        # Submit one of each
        _run_async(SubmitADRTool().execute(
            title="ADR-001", decision="d", context="c",
            alternatives=["a", "b"], consequences="x", status="accepted"))
        _run_async(SubmitRunbookTool().execute(
            title="R-001", trigger="t",
            steps=["s1", "s2", "s3"], verification="v", rollback="r"))
        _run_async(SubmitPostmortemTool().execute(
            title="P-001", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))

        # List each
        adrs = _run_async(ListADRsTool().execute()).data["adrs"]
        runbooks = _run_async(ListRunbooksTool().execute()).data["runbooks"]
        postmortems = _run_async(ListPostmortemsTool().execute()).data["postmortems"]

        self.assertEqual(len(adrs), 1)
        self.assertEqual(len(runbooks), 1)
        self.assertEqual(len(postmortems), 1)
        self.assertEqual(adrs[0]["structured_fields"]["status"], "accepted")
        self.assertEqual(runbooks[0]["structured_fields"]["steps"],
                          ["s1", "s2", "s3"])
        self.assertEqual(postmortems[0]["structured_fields"]["action_items"],
                          ["x"])

    def test_bad_submissions_reject_and_do_not_persist(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
            SubmitRunbookTool, SubmitPostmortemTool,
        )
        # ADR with empty alternatives
        r1 = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=[], consequences="x", status="accepted"))
        self.assertFalse(r1.success)
        # Runbook with 2 steps
        r2 = _run_async(SubmitRunbookTool().execute(
            title="x", trigger="t", steps=["a", "b"],
            verification="v", rollback="r"))
        self.assertFalse(r2.success)
        # Postmortem with bad date
        r3 = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="yesterday", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))
        self.assertFalse(r3.success)

        adrs = _run_async(ListADRsTool().execute()).data["adrs"]
        self.assertEqual(adrs, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_structured_knowledge_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 2 OK; 7 OK / 612 OK (610 + 2 new).

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_structured_knowledge_e2e.py
git commit -m "Add end-to-end test: structured doc submit -> list lifecycle (validation + persistence)"
```

---

## Task 7: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/16-structured-knowledge.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 612 OK. STOP if anything fails.

- [ ] **Step 2: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Write migration log**

Create `docs/superpowers/migration-logs/16-structured-knowledge.md` summarizing:
- Why: Knowledge agent had no structured engineering doc types
- 3 new categories (ADR, RUNBOOK, POSTMORTEM) + structured_fields dict on Knowledge
- 6 new tools (3 submit + 3 list) with field validation
- agents_config.yaml: knowledge profile gets structured_knowledge_tools bundle
- Knowledge agent prompt teaches when to use each type
- Commits (fill from git log)
- Test deltas: 584 → 612 (+28)
- Known gap: postmortem `action_items` aren't linked to WorkHub tasks today; future work could auto-create tasks

- [ ] **Step 4: Commit log**

```bash
git add docs/superpowers/migration-logs/16-structured-knowledge.md
git commit -m "Add Cutover 15 migration log"
```

- [ ] **Step 5: Push**

```bash
git push red-env-gen haibotong-cutover-15-structured-knowledge 2>&1 | tail -5
```

- [ ] **Step 6: Report**

Print: final test counts, commit count, push URL, compare URL, anything to flag for merge.

---

## Self-Review

**1. Spec coverage:**
- 3 new categories + structured_fields — Task 2 ✓
- 6 LLM tools — Task 3 ✓
- Bundle + profile wiring — Task 4 ✓
- Knowledge agent prompt — Task 5 ✓
- E2E test — Task 6 ✓
- Migration log + push — Task 7 ✓

**2. Placeholder scan:** No "TBD" / "implement later". Every code-change task has actual code.

**3. Type consistency:**
- `KnowledgeCategory.{ADR, RUNBOOK, POSTMORTEM}` — values `"adr"`, `"runbook"`, `"postmortem"` ✓
- `Knowledge.structured_fields: Dict[str, Any]` — same shape in dataclass + to_dict + from_dict + tools ✓
- Tool NAMEs match across tool + prompt + tests: `submit_adr`, `submit_runbook`, `submit_postmortem`, `list_adrs`, `list_runbooks`, `list_postmortems` ✓
- ADR status values: `proposed | accepted | deprecated | superseded` — consistent ✓
- Field minimums: ADR alternatives ≥1; runbook steps ≥3; postmortem timeline ≥3 + action_items ≥1 — consistent ✓
- ISO date regex `^\d{4}-\d{2}-\d{2}$` for postmortem incident_date ✓

**4. Cross-cutting:**
- No Claude trailer — Tasks 1 + 7 ✓
- Baselines green at every task boundary ✓
- TDD throughout ✓
- Reuses existing KnowledgeStore (no new persistence layer) ✓
- Free-form `store_knowledge` still works (additive surface) ✓
