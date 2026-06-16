# Cutover 21: Seed Data Sufficiency Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Block `deliver_project()` if any APIHub-registered table is missing seed data, has too few rows, or contains placeholder-quality data (`user1/user2/test/foo/lorem ipsum`). Database agent must `register_seed_data(table, row_count, sample_excerpt)` after seeding; audit verifies coverage.

**Architecture:** APIHub gains `register_seed_data(table_name, row_count, sample_excerpt, agent)` / `get_seed_data(name)` / `list_seed_registrations()` helpers (mirror provider/consumer pattern). Tables can declare `min_seed_rows` in metadata (default `5`). New `runtime/seed_audit.py` scans every registered table, validates: (a) seed_data entry exists, (b) `row_count ≥ min_seed_rows`, (c) `sample_excerpt` passes placeholder-detection regex (score ≥ threshold = fail). `DeliverProjectTool` refuses if any table fails, unless allowlisted via existing Cutover-19 `mark_intentionally_dead("seed:<table>", reason)`. Force-deliver bypass reuses Cutover 19/20 audited mechanism.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Pure stdlib (`re`, `dataclasses`).

---

## Context for Worker

### Why this cutover exists

The system generates schemas and migrations, but nothing enforces that the seed data is sufficient and realistic. Symptoms today:
- Tables with 1-2 token rows (`user1`, `user2`)
- "Lorem ipsum" content where real-looking text was required
- Boolean columns with all `true` or all `false`
- Empty seed files (schema created, no rows inserted)

Frontend can render UI against empty tables → page shows "No items" forever. RunHub HTTP probe returns empty arrays → "passing" but useless. The user requirement "足够 data" has zero mechanical enforcement.

### Why agent-reported (not file-scan) seeds

A static scan of seed SQL / migration files is brittle: too many formats (raw SQL, ORM bulk_create, JSON fixtures, JS migrations). Cleaner approach: Database agent SELF-REPORTS via `register_seed_data(table, row_count, sample_excerpt)` after seeding. Audit reads the registration; agent has unambiguous ownership of the truth.

This mirrors Cutover 7's APIHub `register_consumer` pattern — and Cutover 19's "every endpoint must have a consumer" reverse check. Here: "every table must have seed data registered".

### Seed registration schema

Stored on a new `_seed_registrations` JsonStore inside APIHub:

```python
{
    "users": {
        "table_name": "users",
        "row_count": 42,
        "sample_excerpt": [
            {"id": 1, "name": "Alex Chen", "email": "alex.chen@example.com", "is_active": True},
            {"id": 2, "name": "Maria Rodriguez", "email": "maria.r@example.com", "is_active": False},
            ...up to 3 rows...
        ],
        "min_rows_required": 5,
        "registered_by": "database",
        "registered_at": <epoch>,
    },
    ...
}
```

### Placeholder detection

`detect_placeholder_score(sample_excerpt: List[dict]) -> float`:
- Returns score in `[0.0, 1.0]`
- 0.0 = no placeholder markers; 1.0 = all rows look fake
- Patterns scored:
  - **Generic placeholder words** (any of `test`, `foo`, `bar`, `baz`, `qux`, `asdf`, `qwerty`, `lorem`, `ipsum`, `placeholder`, `dummy`, `sample`, `example`): each match +0.15
  - **Sequential-name pattern** (e.g., `user1` / `user2` / `User 1` / `User_2` / `name_3`): each match +0.30
  - **Repeated values across rows** (same name in 3+ rows): +0.40
  - **All same boolean** in a column across all sample rows: +0.20
- Capped at 1.0
- Threshold for "placeholder-quality": `score ≥ 0.5` → fail audit

### Audit logic

For each registered table `T` in APIHub:
1. Look up `seed_data[T]`. If missing → flag `T` as `missing_seed`.
2. `row_count < (T.metadata.min_seed_rows or 5)` → flag `low_row_count`.
3. `detect_placeholder_score(sample_excerpt) >= 0.5` → flag `placeholder_content`.

Tables can opt out by:
- Setting `metadata.min_seed_rows = 0` (e.g., for empty/lookup tables that genuinely shouldn't have seeds at design time)
- Orchestrator allowlisting via `mark_intentionally_dead("seed:<table>", reason)`

### Deliver gate

`DeliverProjectTool.execute` (after Cutover 20 visual gate):
1. Build seed_dead = `audit_seed_data(hub_registry).flagged_tables` (each entry: `{table, reason, detail}`)
2. Subtract `mark_intentionally_dead` allowlist entries with `seed:<table>` prefix
3. Refuse if any remaining; suggest `register_seed_data(...)` or allowlist
4. `force_deliver=True` orchestrator-only bypass → publish `seed_audit_bypass` EventHub event

### Out of scope (deferred)

- **Dynamic seed verification against running DB**: future cutover ties to RunHub
- **Referential integrity / FK coverage**: future cutover
- **Time-series spread for date columns**: future
- **Schema-aware diversity** (e.g., enum value coverage): future — current placeholder detection is content-quality only

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (dt conda env)
- No Claude trailer; no emojis
- TDD throughout
- Bite-sized commits; no push until Task 8
- Both baselines green at every task: regressions 7 OK; discover 788 OK after Cutover 20

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/seed_audit.py` — placeholder detection + `audit_seed_data`
- `agent/env_generator/llm_generator/tools/seed_tools.py` — 3 LLM tools
- `agent/tests/test_apihub_seed_registration.py`
- `agent/tests/test_seed_audit.py`
- `agent/tests/test_seed_tools.py`
- `agent/tests/test_deliver_seed_gate.py`
- `agent/tests/test_seed_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — add `register_seed_data`, `get_seed_data`, `list_seed_registrations` + `_seed_registrations` JsonStore
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` — `DeliverProjectTool` adds seed gate
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `seed_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `seed_tools` to database + orchestrator + verifier
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2` — SEED DATA DISCIPLINE block
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — SEED SUFFICIENCY DISCIPLINE block

---

## Task 1: Worktree + baseline + APIHub recon

**Files:**
- Create: `docs/superpowers/cutover-21-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-21-seed-data
git status
git log --oneline -3
```

If missing: `git worktree add -b haibotong-cutover-21-seed-data .worktrees/haibotong-cutover-21-seed-data haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 788 OK.

- [ ] **Step 3: Inventory APIHub store init pattern**

```bash
grep -nE "self\._tables |self\._consumers |self\._table_consumers " agent/env_generator/llm_generator/multi_agent/runtime/apihub.py | head -5
```

Confirm: stores are `JsonStore(self.hub_dir / "apihub_<name>.json")`. Task 2 mirrors for `_seed_registrations`.

- [ ] **Step 4: Inventory existing deliver gates anchor**

```bash
grep -nE "visual_review_bypass|coverage gate|Cutover 19|Cutover 20" agent/env_generator/llm_generator/tools/agent_interaction_tools.py | head -10
```

Note Cutover-20 visual gate end-line. Task 6 inserts seed gate immediately after.

- [ ] **Step 5: Baseline note + commit**

Create `docs/superpowers/cutover-21-baseline.md`:

```markdown
# Cutover 21 Baseline (Seed Data Sufficiency)

## Test counts
- regressions: 7 OK
- discover: 788 OK

## Gap this cutover closes
Generated apps ship with placeholder seeds (user1/user2/lorem ipsum) or empty
tables. Frontend renders "No items" / "Loading..." against empty DB; RunHub
probes pass but the user sees nothing. No mechanical enforcement of "足够 data".

## Approach
- Database agent self-reports via register_seed_data(table, row_count, sample_excerpt)
- runtime/seed_audit.py validates: registered, row_count >= min_rows, placeholder_score < 0.5
- DeliverProjectTool refuses if any table fails, unless mark_intentionally_dead allowlisted
- force_deliver orchestrator-only bypass (Cutover 19/20 pattern; new event type seed_audit_bypass)

## Threshold defaults
- min_seed_rows: 5 (per table; override via metadata.min_seed_rows or 0 to opt out)
- placeholder_score floor: 0.5 (multiple placeholder markers required to fail)
```

```bash
git add docs/superpowers/cutover-21-baseline.md
git commit -m "Cutover 21: record pre-flight baseline (regressions 7 OK, discover 788 OK)"
```

---

## Task 2: APIHub seed_data registration

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`
- Create: `agent/tests/test_apihub_seed_registration.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_apihub_seed_registration.py`:

```python
"""Tests for APIHub seed registration helpers (Cutover 21)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_SAMPLE_USERS = [
    {"id": 1, "name": "Alex Chen", "email": "alex.chen@example.com", "is_active": True},
    {"id": 2, "name": "Maria Rodriguez", "email": "maria.r@example.com", "is_active": False},
    {"id": 3, "name": "Yuki Tanaka", "email": "yuki@example.com", "is_active": True},
]


class APIHubSeedRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_seed_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_seed_data_stores_record(self) -> None:
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database")
        record = self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_SAMPLE_USERS,
            agent="database")
        self.assertEqual(record["table_name"], "users")
        self.assertEqual(record["row_count"], 42)
        self.assertEqual(len(record["sample_excerpt"]), 3)
        self.assertEqual(record["registered_by"], "database")

    def test_register_unregistered_table_fails(self) -> None:
        result = self.reg.apihub.register_seed_data(
            "missing_table", row_count=10, sample_excerpt=[],
            agent="database")
        self.assertIn("error", result)
        self.assertIn("not registered", result["error"].lower())

    def test_negative_row_count_rejected(self) -> None:
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database")
        result = self.reg.apihub.register_seed_data(
            "users", row_count=-1, sample_excerpt=_SAMPLE_USERS,
            agent="database")
        self.assertIn("error", result)

    def test_get_seed_data_returns_record(self) -> None:
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_SAMPLE_USERS,
            agent="database")
        got = self.reg.apihub.get_seed_data("users")
        self.assertIsNotNone(got)
        self.assertEqual(got["row_count"], 42)

    def test_get_seed_data_returns_none_for_unregistered(self) -> None:
        self.assertIsNone(self.reg.apihub.get_seed_data("nonexistent"))

    def test_list_seed_registrations_returns_all(self) -> None:
        for name in ("users", "posts", "comments"):
            self.reg.apihub.register_table(name, schema={"columns": []},
                                            provider="database", agent="database")
            self.reg.apihub.register_seed_data(
                name, row_count=10, sample_excerpt=[{"id": 1}],
                agent="database")
        regs = self.reg.apihub.list_seed_registrations()
        self.assertEqual(set(regs.keys()), {"users", "posts", "comments"})

    def test_register_updates_existing(self) -> None:
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=5, sample_excerpt=[{"id": 1}], agent="database")
        # Re-register with higher count
        self.reg.apihub.register_seed_data(
            "users", row_count=50, sample_excerpt=_SAMPLE_USERS, agent="database")
        got = self.reg.apihub.get_seed_data("users")
        self.assertEqual(got["row_count"], 50)
        self.assertEqual(len(got["sample_excerpt"]), 3)

    def test_min_seed_rows_metadata_round_trips(self) -> None:
        # Database agent can declare a table needs more than the default 5 rows
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database",
                                        min_seed_rows=20)
        table = self.reg.apihub.get_table("users")
        self.assertEqual((table.get("metadata") or {}).get("min_seed_rows"), 20)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_seed_registration -v 2>&1 | tail -15
```

Expected: AttributeError on `register_seed_data` / `get_seed_data` / `list_seed_registrations`.

- [ ] **Step 3: Extend APIHub**

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`:

**(a)** Add `_seed_registrations` JsonStore to `__init__`. Find where `_table_consumers` is initialized and add right after:

```python
        self._seed_registrations = JsonStore(self.hub_dir / "apihub_seed_registrations.json")
```

**(b)** Add the 3 new helper methods near `register_table_consumer`:

```python
    def register_seed_data(self, table_name: str, row_count: int,
                            sample_excerpt: Optional[List[dict]] = None,
                            agent: str = "") -> dict:
        """Record that a table has been seeded.

        Database agent calls this after running seed scripts. Audit reads
        these registrations to verify every table has sufficient data."""
        # Validate
        if not isinstance(row_count, int) or row_count < 0:
            return {"error": "row_count must be a non-negative integer"}
        existing_table = self._tables.value().get(table_name)
        if existing_table is None:
            return {"error": f"table not registered: {table_name!r} "
                              f"(call register_table first)"}
        sample = list(sample_excerpt or [])[:3]  # cap at 3 sample rows
        now = time.time()
        record = {
            "table_name": table_name,
            "row_count": row_count,
            "sample_excerpt": sample,
            "registered_by": agent or "database",
            "registered_at": now,
        }
        self._seed_registrations.update(
            lambda m: m.set(table_name, record, agent or "database"),
            change_info={"agent": agent or "database"},
        )
        self._emit("seed_registered", record, recipients=[])
        return record

    def get_seed_data(self, table_name: str) -> Optional[dict]:
        return self._seed_registrations.value().get(table_name)

    def list_seed_registrations(self) -> Dict[str, dict]:
        return dict(self._seed_registrations.value() or {})
```

If `Optional` / `List` / `Dict` imports are missing at the top of the file, add them (they should already be present from prior cutovers — verify with `head -15` of the file).

- [ ] **Step 4: Verify 8 tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_seed_registration -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 8 OK; 7 OK / 796 OK (788 + 8 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/apihub.py agent/tests/test_apihub_seed_registration.py
git commit -m "APIHub: add register_seed_data + get_seed_data + list_seed_registrations"
```

---

## Task 3: seed_audit module (placeholder detection + audit)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/seed_audit.py`
- Create: `agent/tests/test_seed_audit.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_seed_audit.py`:

```python
"""Tests for runtime/seed_audit.py (Cutover 21)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.seed_audit import (  # noqa: E402
    SeedReport, audit_seed_data, detect_placeholder_score,
)


_GOOD_USERS = [
    {"id": 1, "name": "Alex Chen", "email": "alex.chen@gmail.com", "is_active": True},
    {"id": 2, "name": "Maria Rodriguez", "email": "maria.r@gmail.com", "is_active": False},
    {"id": 3, "name": "Yuki Tanaka", "email": "yuki@gmail.com", "is_active": True},
]

_PLACEHOLDER_USERS = [
    {"id": 1, "name": "user1", "email": "test@example.com", "is_active": True},
    {"id": 2, "name": "user2", "email": "foo@example.com", "is_active": True},
    {"id": 3, "name": "user3", "email": "bar@example.com", "is_active": True},
]


class DetectPlaceholderScoreTests(unittest.TestCase):
    def test_empty_excerpt_returns_zero(self) -> None:
        self.assertEqual(detect_placeholder_score([]), 0.0)

    def test_realistic_data_returns_low_score(self) -> None:
        score = detect_placeholder_score(_GOOD_USERS)
        self.assertLess(score, 0.5,
                          f"good data scored too high: {score}")

    def test_placeholder_data_returns_high_score(self) -> None:
        score = detect_placeholder_score(_PLACEHOLDER_USERS)
        self.assertGreaterEqual(score, 0.5,
                                  f"placeholder data scored too low: {score}")

    def test_sequential_names_flagged(self) -> None:
        rows = [{"name": f"item{i}"} for i in range(3)]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.5)

    def test_lorem_ipsum_flagged(self) -> None:
        rows = [{"body": "Lorem ipsum dolor sit amet, consectetur adipiscing"}]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.3)

    def test_all_same_bool_flagged(self) -> None:
        rows = [{"name": "A", "active": True},
                {"name": "B", "active": True},
                {"name": "C", "active": True}]
        self.assertGreaterEqual(detect_placeholder_score(rows), 0.2)

    def test_score_capped_at_1(self) -> None:
        rows = [{"name": f"user{i}", "title": f"item{i}",
                 "body": f"lorem ipsum {i}"} for i in range(5)]
        self.assertLessEqual(detect_placeholder_score(rows), 1.0)


class AuditSeedDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seed_aud_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tables_returns_clean(self) -> None:
        report = audit_seed_data(self.reg)
        self.assertIsInstance(report, SeedReport)
        self.assertEqual(report.flagged_tables, [])
        self.assertTrue(report.is_clean)

    def test_unregistered_table_flagged_missing_seed(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["table"], "users")
        self.assertEqual(report.flagged_tables[0]["reason"], "missing_seed")

    def test_low_row_count_flagged(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=3, sample_excerpt=_GOOD_USERS, agent="database")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "low_row_count")

    def test_high_row_count_passes(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_GOOD_USERS, agent="database")
        report = audit_seed_data(self.reg)
        self.assertEqual(report.flagged_tables, [])

    def test_placeholder_content_flagged(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=20, sample_excerpt=_PLACEHOLDER_USERS, agent="database")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "placeholder_content")

    def test_custom_min_seed_rows_respected(self) -> None:
        # Table declares it needs at least 20 rows
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database",
            min_seed_rows=20)
        self.reg.apihub.register_seed_data(
            "users", row_count=10, sample_excerpt=_GOOD_USERS, agent="database")
        report = audit_seed_data(self.reg)
        self.assertEqual(len(report.flagged_tables), 1)
        self.assertEqual(report.flagged_tables[0]["reason"], "low_row_count")
        self.assertEqual(report.flagged_tables[0]["detail"]["min_seed_rows"], 20)

    def test_min_seed_rows_zero_skips_table(self) -> None:
        # Table opts out via min_seed_rows=0 (e.g., empty lookup table)
        self.reg.apihub.register_table(
            "config", schema={"columns": []}, provider="database", agent="database",
            min_seed_rows=0)
        report = audit_seed_data(self.reg)
        self.assertEqual(report.flagged_tables, [])

    def test_all_dead_paths_property(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.apihub.register_table(
            "posts", schema={"columns": []}, provider="database", agent="database")
        report = audit_seed_data(self.reg)
        paths = report.all_flagged_paths
        self.assertIn("seed:users", paths)
        self.assertIn("seed:posts", paths)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_seed_audit -v 2>&1 | tail -10
```

- [ ] **Step 3: Implement seed_audit**

Create `agent/env_generator/llm_generator/multi_agent/runtime/seed_audit.py`:

```python
"""Seed data audit (Cutover 21)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


# Placeholder marker words (case-insensitive)
_PLACEHOLDER_WORDS = {
    "test", "foo", "bar", "baz", "qux", "asdf", "qwerty",
    "lorem", "ipsum", "placeholder", "dummy", "sample", "example_user",
    "todo", "tbd", "xxxx",
}

# Sequential name pattern: word followed by 1+ digits (e.g., user1, item_2, name3)
_SEQUENTIAL_RE = re.compile(r"^[a-zA-Z_]+[\s_-]?\d+$")


def detect_placeholder_score(rows: List[dict]) -> float:
    if not rows:
        return 0.0
    score = 0.0

    # 1. Generic placeholder words in any string value
    placeholder_hit_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            lowered = v.lower()
            for word in _PLACEHOLDER_WORDS:
                if word in lowered:
                    placeholder_hit_count += 1
                    break  # only count once per value
    score += min(placeholder_hit_count, 5) * 0.15

    # 2. Sequential-name pattern
    sequential_hits = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            if _SEQUENTIAL_RE.match(v.strip()):
                sequential_hits += 1
                break
    score += min(sequential_hits, 3) * 0.30

    # 3. All-same-boolean across rows (only if >=3 rows)
    if len(rows) >= 3:
        bool_columns: Dict[str, Set[bool]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                if isinstance(v, bool):
                    bool_columns.setdefault(k, set()).add(v)
        for vals in bool_columns.values():
            if len(vals) == 1:
                score += 0.20
                break  # only count once

    return min(score, 1.0)


@dataclass
class SeedReport:
    flagged_tables: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.flagged_tables

    @property
    def all_flagged_paths(self) -> Set[str]:
        return {f"seed:{f['table']}" for f in self.flagged_tables}

    def to_dict(self) -> dict:
        return {
            "flagged_tables": list(self.flagged_tables),
            "is_clean": self.is_clean,
        }


_DEFAULT_MIN_ROWS = 5
_PLACEHOLDER_THRESHOLD = 0.5


def audit_seed_data(hub_registry) -> SeedReport:
    apihub = getattr(hub_registry, "apihub", None)
    if apihub is None or not hasattr(apihub, "list_tables"):
        return SeedReport()
    tables = apihub.list_tables() or {}
    seed_regs = (apihub.list_seed_registrations() if hasattr(apihub, "list_seed_registrations") else {}) or {}

    flagged: List[dict] = []
    for name, table in tables.items():
        if (table.get("status") or "defined") != "defined":
            continue
        meta = table.get("metadata") or {}
        min_rows = meta.get("min_seed_rows", _DEFAULT_MIN_ROWS)
        if min_rows == 0:
            continue  # explicit opt-out

        reg = seed_regs.get(name)
        if reg is None:
            flagged.append({
                "table": name,
                "reason": "missing_seed",
                "detail": {"min_seed_rows": min_rows,
                           "hint": "call register_seed_data after seeding"},
            })
            continue

        row_count = reg.get("row_count", 0)
        if row_count < min_rows:
            flagged.append({
                "table": name,
                "reason": "low_row_count",
                "detail": {"row_count": row_count,
                           "min_seed_rows": min_rows},
            })
            continue

        score = detect_placeholder_score(reg.get("sample_excerpt") or [])
        if score >= _PLACEHOLDER_THRESHOLD:
            flagged.append({
                "table": name,
                "reason": "placeholder_content",
                "detail": {"placeholder_score": round(score, 2),
                           "threshold": _PLACEHOLDER_THRESHOLD,
                           "sample_size": len(reg.get("sample_excerpt") or [])},
            })

    return SeedReport(flagged_tables=flagged)


__all__ = ["SeedReport", "audit_seed_data", "detect_placeholder_score"]
```

- [ ] **Step 4: Verify ~15 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_seed_audit -v 2>&1 | tail -20
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 15 OK; 7 OK / 811 OK (796 + 15 new).

If the placeholder-detection regex flags "good" data (e.g., name fields containing "Sample" string), tune the threshold OR adjust the placeholder word list. Don't weaken tests to mask real bugs — adjust the score weights or pattern list.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/seed_audit.py agent/tests/test_seed_audit.py
git commit -m "Add seed_audit: detect placeholder content + audit row counts per table"
```

---

## Task 4: Seed LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/seed_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_seed_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_seed_tools.py`:

```python
"""Tests for seed LLM tools (Cutover 21)."""

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


_GOOD = [{"id": 1, "name": "Alex", "email": "alex@gmail.com", "is_active": True}]


class SeedToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seed_tools_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.apihub.register_table("users", schema={"columns": []},
                                        provider="database", agent="database")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_seed_data_tool(self) -> None:
        from tools.seed_tools import RegisterSeedDataTool
        tool = RegisterSeedDataTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            table_name="users", row_count=42,
            sample_excerpt=[{"id": 1, "name": "Alex"}]))
        self.assertTrue(result.success)
        self.assertEqual(result.data["record"]["row_count"], 42)

    def test_register_seed_data_unknown_table_fails(self) -> None:
        from tools.seed_tools import RegisterSeedDataTool
        tool = RegisterSeedDataTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            table_name="missing", row_count=10,
            sample_excerpt=[]))
        self.assertFalse(result.success)

    def test_seed_audit_check_clean(self) -> None:
        from tools.seed_tools import (
            RegisterSeedDataTool, SeedAuditCheckTool,
        )
        _run_async(RegisterSeedDataTool(hub_registry=self.reg).execute(
            table_name="users", row_count=42, sample_excerpt=_GOOD))
        result = _run_async(SeedAuditCheckTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertTrue(result.data["is_clean"])
        self.assertEqual(result.data["flagged_tables"], [])

    def test_seed_audit_check_flags_missing(self) -> None:
        from tools.seed_tools import SeedAuditCheckTool
        result = _run_async(SeedAuditCheckTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertFalse(result.data["is_clean"])
        self.assertEqual(result.data["flagged_tables"][0]["reason"], "missing_seed")

    def test_list_seed_issues_summary(self) -> None:
        from tools.seed_tools import ListSeedIssuesTool
        result = _run_async(ListSeedIssuesTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        # missing seed → flagged
        self.assertEqual(len(result.data["issues"]), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement tools**

Create `agent/env_generator/llm_generator/tools/seed_tools.py`:

```python
"""Seed data LLM tools (Cutover 21)."""

from __future__ import annotations

from typing import Any, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.seed_audit import audit_seed_data


class _SeedToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterSeedDataTool(_SeedToolBase):
    NAME = "register_seed_data"
    DESCRIPTION = ("Database agent records that a table has been seeded. "
                    "row_count must be the actual row count after seeding. "
                    "sample_excerpt provides 1-3 representative rows for "
                    "placeholder-quality detection.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "row_count": {"type": "integer", "minimum": 0},
                    "sample_excerpt": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "1-3 representative seeded rows",
                    },
                },
                "required": ["table_name", "row_count", "sample_excerpt"],
            }, required=["table_name", "row_count", "sample_excerpt"])

    async def execute(self, *, table_name: str, row_count: int,
                       sample_excerpt: list, **_kw) -> ToolResult:
        record = self.hub_registry.apihub.register_seed_data(
            table_name=table_name, row_count=row_count,
            sample_excerpt=sample_excerpt,
            agent=getattr(self, "_agent_id", None) or "database")
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"record": record})


class SeedAuditCheckTool(_SeedToolBase):
    NAME = "seed_audit_check"
    DESCRIPTION = ("Audit seed data coverage across all registered tables. "
                    "Returns flagged tables with reasons (missing_seed | "
                    "low_row_count | placeholder_content) and details.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry)
        return ToolResult.ok(data=report.to_dict())


class ListSeedIssuesTool(_SeedToolBase):
    NAME = "list_seed_issues"
    DESCRIPTION = ("List current seed issues with table+reason pairs. "
                    "Convenience over seed_audit_check for the orchestrator's "
                    "deliver-readiness checklist.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry)
        issues = [
            {"table": f["table"], "reason": f["reason"], "detail": f["detail"]}
            for f in report.flagged_tables
        ]
        return ToolResult.ok(data={"issues": issues, "count": len(issues)})


_SEED_TOOLS = [RegisterSeedDataTool, SeedAuditCheckTool, ListSeedIssuesTool]


def create_seed_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _SEED_TOOLS]


__all__ = ["RegisterSeedDataTool", "SeedAuditCheckTool", "ListSeedIssuesTool",
            "create_seed_tools"]
```

- [ ] **Step 3: Register bundle + wire to database/orchestrator/verifier**

In `tool_bundles.py`:

```python
from tools.seed_tools import create_seed_tools

def _bundle_seed_tools(builder, context) -> None:
    builder.add(create_seed_tools(hub_registry=context.hub_workspace),
                "knowledge")

# TOOL_BUNDLE_REGISTRY:
"seed_tools": _bundle_seed_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"seed_tools": {"knowledge"},
```

In `agents_config.yaml`, add `seed_tools` to **database**, **orchestrator**, and **verifier** profile `tool_bundles` lists.

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_seed_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 816 OK (811 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/seed_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_seed_tools.py
git commit -m "Add seed_tools: register_seed_data / seed_audit_check / list_seed_issues + database/orch/verifier wiring"
```

---

## Task 5: DeliverProjectTool seed gate

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`
- Create: `agent/tests/test_deliver_seed_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliver_seed_gate.py`:

```python
"""DeliverProjectTool seed gate tests (Cutover 21)."""

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


_GOOD = [{"id": 1, "name": "Alex Chen", "email": "alex@gmail.com"}]


def _agent(reg, gen_id=5000.0, agent_type="orchestrator"):
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


class DeliverSeedGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="del_seed_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 5000.0)

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

    def test_deliver_succeeds_with_no_tables(self) -> None:
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_refuses_when_table_missing_seed(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        result = self._deliver()
        self.assertFalse(result.success)
        self.assertIn("users", result.error_message)
        self.assertIn("seed", result.error_message.lower())

    def test_deliver_succeeds_when_seed_registered(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_GOOD, agent="database")
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_succeeds_when_table_allowlisted(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        self.reg.workhub.mark_path_intentionally_dead(
            "seed:users", reason="empty by design (lookup table)",
            agent="orchestrator")
        result = self._deliver()
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_force_deliver_bypasses_seed_gate(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        result = self._deliver(force_deliver=True)
        self.assertTrue(result.success, f"failed: {result.error_message}")
        events = list(self.reg.eventhub.list_events_by_type("seed_audit_bypass"))
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Add seed gate**

In `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`, in `DeliverProjectTool.execute`, immediately AFTER the Cutover 20 visual gate, add:

```python
        # Cutover 21: seed audit gate
        try:
            registry = getattr(self.agent, "hub_registry", None)
            agent_type = getattr(self.agent, "agent_type", "")
            force = kwargs.get("force_deliver") or False

            if registry is not None and hasattr(registry, "apihub"):
                from multi_agent.runtime.seed_audit import audit_seed_data
                report = audit_seed_data(registry)
                allowlist_paths = {
                    e.get("path") for e in
                    (registry.workhub.list_coverage_allowlist() or [])
                    if e.get("path")
                }
                # Filter out allowlisted entries
                flagged = [
                    f for f in report.flagged_tables
                    if f"seed:{f['table']}" not in allowlist_paths
                ]
                if flagged:
                    if force:
                        if agent_type != "orchestrator":
                            return ToolResult.fail(error_message=(
                                "force_deliver is orchestrator-only; "
                                f"caller agent_type={agent_type!r}"))
                        try:
                            registry.eventhub.publish_event(
                                source_hub="deliver",
                                event_type="seed_audit_bypass",
                                payload={"flagged_tables": flagged,
                                          "by": agent_type},
                                priority="high")
                        except Exception:
                            pass
                    else:
                        sample = [(f["table"], f["reason"]) for f in flagged[:5]]
                        return ToolResult.fail(error_message=(
                            f"refused: {len(flagged)} table(s) failed seed audit: "
                            f"{sample}. Database agent must register_seed_data "
                            f"with sufficient rows + realistic content. "
                            f"Or mark_intentionally_dead('seed:<table>', reason)."))
        except Exception:
            pass  # defense in depth
```

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_seed_gate -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 821 OK (816 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/agent_interaction_tools.py agent/tests/test_deliver_seed_gate.py
git commit -m "DeliverProjectTool: seed audit gate (refuse if any table missing seed / low rows / placeholder content)"
```

---

## Task 6: Database + Orchestrator prompts

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_seed_prompts.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_seed_prompts.py`:

```python
"""Tests that database + orchestrator prompts teach seed sufficiency discipline."""

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


class DatabaseSeedPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("database_agent.j2",
                              ["database_specifics", "database_system_prompt"])

    def test_mentions_register_seed_data(self) -> None:
        self.assertIn("REGISTER_SEED_DATA", self.system.upper())

    def test_warns_against_placeholder_content(self) -> None:
        upper = self.system.upper()
        self.assertTrue(any(p in upper for p in
                              ("PLACEHOLDER", "USER1", "LOREM", "REALISTIC")))

    def test_mentions_min_seed_rows(self) -> None:
        self.assertIn("MIN_SEED_ROWS", self.system.upper())


class OrchestratorSeedPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("orchestrator_agent.j2", ["lead_specifics"])

    def test_mentions_seed_audit(self) -> None:
        upper = self.system.upper()
        self.assertTrue("SEED_AUDIT_CHECK" in upper or "SEED AUDIT" in upper)

    def test_mentions_seed_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("SEED", upper)
        self.assertIn("DELIVER", upper)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Update prompts**

In `database_agent.j2`, locate `database_specifics` macro and append:

```jinja
### SEED DATA DISCIPLINE (Cutover 21)
After running seed scripts/migrations, you MUST call `register_seed_data(table_name, row_count, sample_excerpt)` for EVERY APIHub-registered table.

- `row_count` = actual count after seeding (from your INSERT result, not estimate)
- `sample_excerpt` = 1-3 representative rows (as dicts) — used to detect placeholder content

**Hard rules**:
1. NO placeholder content. Bad: `user1`, `user2`, `foo`, `lorem ipsum`, `test_user_3`, `Item 1`/`Item 2`/`Item 3`. Good: realistic names, varied emails, real-looking content.
2. Boolean columns must have BOTH true AND false present in sample (audit flags if all rows have the same boolean value).
3. Default minimum: 5 rows per table. Override via `register_table(..., min_seed_rows=N)`. Use `min_seed_rows=0` ONLY for empty-by-design lookup tables (e.g., a `feature_flags` table you populate at runtime).

Audit failure modes (each refuses `deliver_project()`):
- `missing_seed`: table registered but `register_seed_data` never called → call it
- `low_row_count`: `row_count < min_seed_rows` → add more seed rows
- `placeholder_content`: `sample_excerpt` triggers placeholder detector (score ≥ 0.5) → rewrite seeds with realistic data

Run `seed_audit_check()` to verify your state. Run `list_seed_issues()` for a summary.
```

In `orchestrator_agent.j2`, locate `lead_specifics` and append (after Cutover 20 VISUAL FIDELITY block):

```jinja
### SEED SUFFICIENCY DISCIPLINE (Cutover 21)
Before `deliver_project()`, you MUST verify every registered table has sufficient + realistic seed data. The DeliverProjectTool runs `seed_audit_check` as a pre-flight gate; refused if any table is `missing_seed`, `low_row_count`, or `placeholder_content`.

Workflow:
1. Run `seed_audit_check()` -> see flagged tables
2. For each flagged table:
   - `missing_seed` -> assign database agent to register_seed_data
   - `low_row_count` -> assign database agent to extend seeds
   - `placeholder_content` -> assign database agent to rewrite with realistic content
   - OR if seeds are intentionally empty (lookup table, runtime-populated): `mark_intentionally_dead('seed:<table>', reason)` to allowlist
3. Re-run `seed_audit_check()` -> should be clean
4. Continue to retro + deliver

If forced to ship over a seed-audit failure, `deliver_project(force_deliver=True)` bypasses (orchestrator-only; publishes `seed_audit_bypass` EventHub event).
```

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_seed_prompts -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 826 OK (821 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/database_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_seed_prompts.py
git commit -m "Database + orchestrator prompts: SEED DATA DISCIPLINE + SEED SUFFICIENCY workflow"
```

---

## Task 7: E2E + migration log + push

**Files:**
- Create: `agent/tests/test_seed_e2e.py`
- Create: `docs/superpowers/migration-logs/22-seed-data-sufficiency.md`

- [ ] **Step 1: Write E2E test**

Create `agent/tests/test_seed_e2e.py`:

```python
"""E2E: seed audit blocks deliver; register_seed_data unblocks; force_deliver audits."""

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


_GOOD = [
    {"id": 1, "name": "Alex Chen", "email": "alex@gmail.com", "is_active": True},
    {"id": 2, "name": "Maria Rodriguez", "email": "maria@gmail.com", "is_active": False},
    {"id": 3, "name": "Yuki Tanaka", "email": "yuki@gmail.com", "is_active": True},
]
_PLACEHOLDER = [
    {"id": 1, "name": "user1", "email": "test@test.com"},
    {"id": 2, "name": "user2", "email": "foo@test.com"},
    {"id": 3, "name": "user3", "email": "bar@test.com"},
]


def _agent(reg, gen_id=6000.0, agent_type="orchestrator"):
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


class SeedE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seed_e2e_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 6000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg))
        return tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_missing_seed_blocks_then_register_unblocks(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        # No seed registered yet -> refused
        r1 = self._deliver()
        self.assertFalse(r1.success)
        # Database agent registers good seed -> unblocked
        self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_GOOD, agent="database")
        r2 = self._deliver()
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_placeholder_seed_blocks_then_real_seed_unblocks(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        # Register with placeholder content -> blocked
        self.reg.apihub.register_seed_data(
            "users", row_count=20, sample_excerpt=_PLACEHOLDER, agent="database")
        r1 = self._deliver()
        self.assertFalse(r1.success)
        self.assertIn("placeholder", r1.error_message.lower())
        # Re-register with realistic data
        self.reg.apihub.register_seed_data(
            "users", row_count=42, sample_excerpt=_GOOD, agent="database")
        r2 = self._deliver()
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_force_deliver_publishes_audit_event(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []}, provider="database", agent="database")
        result = self._deliver(force_deliver=True)
        self.assertTrue(result.success)
        events = list(self.reg.eventhub.list_events_by_type("seed_audit_bypass"))
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify 3 tests + final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_seed_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 829 OK (826 + 3 new).

- [ ] **Step 3: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 4: Write migration log**

Create `docs/superpowers/migration-logs/22-seed-data-sufficiency.md`:

```markdown
# Cutover 21: Seed Data Sufficiency Gate

**Branch:** `haibotong-cutover-21-seed-data`
**Date:** 2026-05-25

## What

Block `deliver_project()` if any APIHub-registered table:
- Has no `register_seed_data` entry (`missing_seed`)
- Has fewer rows than required (`low_row_count`, default 5)
- Contains placeholder content (`user1`/`lorem ipsum`/etc., score >= 0.5)

Database agent self-reports via `register_seed_data(table, row_count, sample_excerpt)`. Audit reads registrations; no file scanning needed.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 788 OK -> 829 OK (+41 new)

## New surfaces
- APIHub: register_seed_data / get_seed_data / list_seed_registrations + _seed_registrations JsonStore
- runtime/seed_audit.py: detect_placeholder_score + audit_seed_data
- tools/seed_tools.py: 3 LLM tools
- DeliverProjectTool seed gate
- Database + orchestrator prompts: SEED DATA DISCIPLINE + SEED SUFFICIENCY workflow

## Placeholder detection rubric
- Generic words (test/foo/bar/lorem/etc.): each match +0.15 (capped at 5)
- Sequential names (user1, item_2): each match +0.30 (capped at 3)
- All-same-boolean column (3+ rows): +0.20
- Threshold for fail: score >= 0.5

## Bypass mechanisms (Cutover 19/20 patterns reused)
- `min_seed_rows=0` in table metadata -> opt out per-table at design time
- `mark_intentionally_dead('seed:<table>', reason)` -> orchestrator allowlist
- `deliver_project(force_deliver=True)` -> orchestrator-only audited bypass (publishes `seed_audit_bypass` EventHub event)

## Known limits (future cutovers)
- Audit reads agent-reported registrations, not real DB state. If database agent
  reports false row_count, audit can't catch it. Future cutover: tie to RunHub
  DB query that verifies actual COUNT(*).
- Placeholder detection is heuristic (regex + word list). False positives
  possible (e.g., real customer named "Test" who exists). Override via
  mark_intentionally_dead allowlist.
- No referential integrity / FK coverage / time-series diversity yet.
```

- [ ] **Step 5: Commit + push**

```bash
git add agent/tests/test_seed_e2e.py docs/superpowers/migration-logs/22-seed-data-sufficiency.md
git commit -m "Add Cutover 21 e2e + migration log"
git push red-env-gen haibotong-cutover-21-seed-data 2>&1 | tail -5
```

- [ ] **Step 6: Report** — final test counts, push URL, deferred items.

---

## Self-Review

**1. Spec coverage:** APIHub seed surface (T2) ✓; seed_audit module (T3) ✓; LLM tools (T4) ✓; DeliverProjectTool gate (T5) ✓; database + orchestrator prompts (T6) ✓; E2E + log + push (T7) ✓.

**2. Placeholder scan:** No TBD / "implement later". All code shown.

**3. Type consistency:**
- `register_seed_data(table_name, row_count, sample_excerpt, agent)` — same signature in APIHub + tool + tests + prompt
- `SeedReport(flagged_tables) + is_clean + all_flagged_paths + to_dict()` — consistent
- Flagged-table shape `{table, reason, detail}` with reasons in `{"missing_seed", "low_row_count", "placeholder_content"}` — consistent
- `min_seed_rows` metadata default 5; `min_seed_rows=0` opt-out — consistent
- Placeholder threshold 0.5 — consistent

**4. Cross-cutting:**
- No Claude trailer (Tasks 1 + 7) ✓
- Baselines green per task ✓
- TDD throughout ✓
- Allowlist reuses Cutover 19 `mark_path_intentionally_dead` with `seed:<table>` prefix — no new allowlist surface ✓
- force_deliver bypass reuses Cutover 19/20 pattern with new event type `seed_audit_bypass` ✓
