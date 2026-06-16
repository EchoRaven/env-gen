# Cutover 26: Per-Project Hub Records (Resume + Backup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each `<workspace>` is treated as a first-class **project record** that survives orchestrator exit/crash and supports resume + backup. Add `project.json` metadata at the workspace root, a `ProjectIndex` that lists/queries projects across a workspaces-root, and wire orchestrator to maintain `last_active_at` / `status` over its lifetime. All five hubs (Code/API/Work/Event/Run) are already JsonStore-backed and per-workspace isolated — no per-hub re-namespacing needed.

**Architecture:** A new `runtime/project.py` module owns `ProjectMetadata` (dataclass + load/save) and `ProjectIndex` (scans a parent dir, lists/filters/sorts projects). `HubRegistry.__init__` writes/refreshes `project.json` on every construction and exposes `set_project_status()` / `touch()` helpers. `Orchestrator` calls `hubs.touch()` after each major phase and `hubs.set_project_status("completed")` on successful delivery. `EnvGenerator`-equivalent callers get a top-level `list_projects(workspaces_root)` and `resume_project(workspaces_root, project_id)` API.

**Tech Stack:** Python 3, JsonStore (existing), dataclasses, pathlib. No new external deps.

---

## Test infrastructure conventions (repo-specific — REQUIRED)

This repo's tests live in `agent/tests/` (single directory, ~920 files). The test runner is **pytest** (in the `dt` conda env, already installed). Regressions are an **explicit unittest suite** loaded by `agent/tests/run_regressions.py` (NOT auto-discovered as pytest tests).

**Every new test file MUST start with this exact boilerplate** so that `from multi_agent.runtime.X import Y` imports resolve. Copy verbatim into each new test:

```python
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
```

Then your imports use the short form:
```python
from multi_agent.runtime.project import ProjectMetadata          # YES
from multi_agent.runtime.hub_registry import HubRegistry         # YES
# from agent.env_generator.llm_generator.multi_agent... import ... # NO
```

Pytest invocation (NOT `python -m pytest agent/env_generator/...`):
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q
```

Regressions invocation (NOT pytest — calls `unittest.TextTestRunner`):
```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

---

## File Structure

**Files to create:**
- `agent/env_generator/llm_generator/multi_agent/runtime/project.py` — `ProjectMetadata` dataclass + `ProjectIndex` (read/write `project.json`, scan workspaces_root, filter by status, sort by last_active)
- `agent/tests/test_project_metadata.py` — unit tests for ProjectMetadata save/load/migrate
- `agent/tests/test_project_index.py` — unit tests for ProjectIndex.list/get/filter
- `agent/tests/test_hub_registry_project.py` — integration tests for HubRegistry persistence + touch + set_status
- `agent/tests/test_project_resume_e2e.py` — e2e: create → exit → reload → resume; create → backup tarball
- `docs/superpowers/migration-logs/26-per-project-hubs.md` — post-merge log

**Files to modify:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — load/refresh `project.json` on init; add `touch()`, `set_project_status(status)`, `project_metadata` property
- `agent/env_generator/llm_generator/multi_agent/orchestrator.py` — pass `project_name`/`description` to HubRegistry; call `hubs.touch()` after phase transitions; call `set_project_status("completed")` on successful delivery and `("failed")` on terminal failure
- `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` — export `ProjectMetadata`, `ProjectIndex`, `list_projects`, `resume_project`

---

## Task 1: Pre-flight baseline

**Files:**
- None (record baseline only)

- [ ] **Step 1: Run the existing test suites and record OK counts**

Run these two commands and record the OK counts:

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-26-per-project-hubs
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
```

Expected: `Ran 7 tests` + `OK`.

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -5
```

Expected: 920 passed.

- [ ] **Step 2: Commit baseline record**

Create the migration log file with the baseline numbers and commit:

```bash
mkdir -p docs/superpowers/migration-logs
cat > docs/superpowers/migration-logs/26-per-project-hubs.md <<'EOF'
# Cutover 26: Per-Project Hub Records (Resume + Backup)

**Branch:** `haibotong-cutover-26-per-project-hubs`
**Date:** 2026-05-26
**Status:** in-progress

## Pre-flight baseline
- Regressions: 7 OK
- Discover: 920 OK
EOF
git add docs/superpowers/migration-logs/26-per-project-hubs.md
git commit -m "Cutover 26: record pre-flight baseline (regressions 7 OK, discover 920 OK)"
```

---

## Task 2: ProjectMetadata dataclass (TDD)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/project.py`
- Create: `agent/tests/test_project_metadata.py`

- [ ] **Step 1: Write the failing test for ProjectMetadata save/load roundtrip**

```python
# agent/tests/test_project_metadata.py
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.project import (
    ProjectMetadata,
    load_project_metadata,
    save_project_metadata,
)


def test_project_metadata_save_load_roundtrip(tmp_path: Path):
    md = ProjectMetadata(
        id="proj_abc",
        name="Demo App",
        description="todo app for testing",
        created_at=1000.0,
        last_active_at=1500.0,
        status="active",
        agents_used=["orchestrator", "frontend"],
    )
    save_project_metadata(tmp_path, md)
    loaded = load_project_metadata(tmp_path)
    assert loaded == md


def test_load_project_metadata_returns_none_when_missing(tmp_path: Path):
    assert load_project_metadata(tmp_path) is None


def test_save_creates_project_json_file(tmp_path: Path):
    md = ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0)
    save_project_metadata(tmp_path, md)
    p = tmp_path / "project.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["id"] == "x"


def test_status_must_be_known_value():
    with pytest.raises(ValueError):
        ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0, status="bogus")


def test_default_status_is_active():
    md = ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0)
    assert md.status == "active"


def test_legacy_workspace_without_project_json_treated_as_unregistered(tmp_path: Path):
    # Simulate pre-cutover workspace: shared/hubs/ exists but no project.json
    (tmp_path / "shared" / "hubs").mkdir(parents=True)
    assert load_project_metadata(tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-26-per-project-hubs && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_metadata.py -v`

Expected: All FAIL with `ImportError: cannot import name 'ProjectMetadata' from ...project` (module does not exist yet).

- [ ] **Step 3: Implement ProjectMetadata + save/load**

```python
# agent/env_generator/llm_generator/multi_agent/runtime/project.py
"""
Project-level metadata persistence.

A "project" == a single env-generator workspace (output_dir). One project per
workspace. Metadata lives at `<workspace>/project.json` and survives crashes,
exits, and orchestrator re-starts. The 5 hubs (Code/API/Work/Event/Run) are
already isolated per workspace via `<workspace>/shared/hubs/`, so no
per-hub project-id namespacing is needed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

VALID_STATUSES = {"active", "paused", "completed", "failed", "archived"}
PROJECT_JSON = "project.json"


@dataclass
class ProjectMetadata:
    id: str
    name: str
    created_at: float
    last_active_at: float
    description: str = ""
    status: str = "active"
    agents_used: List[str] = field(default_factory=list)
    schema_version: int = 1

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {self.status!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMetadata":
        # Only pass known fields — tolerate forward-compat extras.
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def save_project_metadata(workspace_dir: Path, md: ProjectMetadata) -> Path:
    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / PROJECT_JSON
    path.write_text(json.dumps(md.to_dict(), indent=2, sort_keys=True))
    return path


def load_project_metadata(workspace_dir: Path) -> Optional[ProjectMetadata]:
    path = Path(workspace_dir) / PROJECT_JSON
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return ProjectMetadata.from_dict(data)


def now_ts() -> float:
    return time.time()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_metadata.py -v`

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/project.py \
        agent/tests/test_project_metadata.py
git commit -m "Cutover 26: add ProjectMetadata dataclass + JSON persistence"
```

---

## Task 3: ProjectIndex (list + filter + resume lookup)

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/project.py` (add `ProjectIndex` class + top-level helpers)
- Create: `agent/tests/test_project_index.py`

- [ ] **Step 1: Write failing tests for ProjectIndex**

```python
# agent/tests/test_project_index.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.project import (
    ProjectIndex,
    ProjectMetadata,
    save_project_metadata,
)


def _seed(root: Path, pid: str, name: str, status: str, last_active: float):
    ws = root / pid
    ws.mkdir(parents=True, exist_ok=True)
    save_project_metadata(
        ws,
        ProjectMetadata(id=pid, name=name, created_at=last_active, last_active_at=last_active, status=status),
    )


def test_list_empty_workspaces_root(tmp_path):
    idx = ProjectIndex(tmp_path)
    assert idx.list() == []


def test_list_returns_all_projects(tmp_path):
    _seed(tmp_path, "proj_a", "App A", "active", 100.0)
    _seed(tmp_path, "proj_b", "App B", "completed", 200.0)
    idx = ProjectIndex(tmp_path)
    ids = sorted(p.id for p in idx.list())
    assert ids == ["proj_a", "proj_b"]


def test_list_skips_directories_without_project_json(tmp_path):
    (tmp_path / "not_a_project").mkdir()
    _seed(tmp_path, "proj_a", "App A", "active", 100.0)
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_a"]


def test_list_filters_by_status(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    _seed(tmp_path, "proj_b", "B", "completed", 2.0)
    _seed(tmp_path, "proj_c", "C", "completed", 3.0)
    idx = ProjectIndex(tmp_path)
    completed_ids = sorted(p.id for p in idx.list(status="completed"))
    assert completed_ids == ["proj_b", "proj_c"]


def test_list_sorted_by_last_active_desc(tmp_path):
    _seed(tmp_path, "proj_old", "old", "active", 100.0)
    _seed(tmp_path, "proj_new", "new", "active", 999.0)
    _seed(tmp_path, "proj_mid", "mid", "active", 500.0)
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_new", "proj_mid", "proj_old"]


def test_get_returns_workspace_path_for_known_project(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    idx = ProjectIndex(tmp_path)
    md, workspace = idx.get("proj_a")
    assert md.id == "proj_a"
    assert workspace == tmp_path / "proj_a"


def test_get_unknown_project_returns_none(tmp_path):
    idx = ProjectIndex(tmp_path)
    assert idx.get("nope") == (None, None)


def test_list_skips_corrupted_project_json(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "project.json").write_text("{not valid json")
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_a"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_index.py -v`

Expected: All FAIL with `ImportError: cannot import name 'ProjectIndex' ...`.

- [ ] **Step 3: Implement ProjectIndex (append to project.py)**

Append to `agent/env_generator/llm_generator/multi_agent/runtime/project.py`:

```python
from typing import Iterable, Tuple


class ProjectIndex:
    """
    Scans a workspaces-root directory for child workspaces containing
    `project.json` files. Provides list/filter/get APIs for project pickers
    (UI homepage, CLI `resume`).

    Layout assumption:
        <workspaces_root>/
            <project_id_1>/   # workspace == project
                project.json
                shared/hubs/...
            <project_id_2>/
                project.json
                shared/hubs/...
            not_a_project/    # ignored (no project.json)
    """

    def __init__(self, workspaces_root: Path):
        self.root = Path(workspaces_root)

    def _iter_metadata(self) -> Iterable[Tuple[ProjectMetadata, Path]]:
        if not self.root.exists():
            return
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            md = load_project_metadata(child)
            if md is None:
                continue
            yield md, child

    def list(self, status: Optional[str] = None) -> List[ProjectMetadata]:
        results = []
        for md, _ in self._iter_metadata():
            if status is not None and md.status != status:
                continue
            results.append(md)
        results.sort(key=lambda m: m.last_active_at, reverse=True)
        return results

    def get(self, project_id: str) -> Tuple[Optional[ProjectMetadata], Optional[Path]]:
        for md, workspace in self._iter_metadata():
            if md.id == project_id:
                return md, workspace
        return None, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_index.py -v`

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/project.py \
        agent/tests/test_project_index.py
git commit -m "Cutover 26: add ProjectIndex for cross-workspace project enumeration"
```

---

## Task 4: HubRegistry persists + maintains project.json

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`
- Create: `agent/tests/test_hub_registry_project.py`

- [ ] **Step 1: Write the failing test for HubRegistry persistence integration**

```python
# agent/tests/test_hub_registry_project.py
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.project import (
    load_project_metadata,
    ProjectMetadata,
)


def test_hub_registry_creates_project_json_on_first_init(tmp_path):
    reg = HubRegistry(tmp_path, project_name="My App", project_description="todo demo")
    md = load_project_metadata(tmp_path)
    assert md is not None
    assert md.name == "My App"
    assert md.description == "todo demo"
    assert md.status == "active"
    assert md.id  # auto-generated
    assert md.created_at > 0
    assert md.last_active_at >= md.created_at


def test_hub_registry_uses_explicit_project_id_when_provided(tmp_path):
    reg = HubRegistry(tmp_path, project_id="proj_custom_123", project_name="X")
    md = load_project_metadata(tmp_path)
    assert md.id == "proj_custom_123"


def test_hub_registry_reuses_existing_project_metadata_on_reload(tmp_path):
    reg1 = HubRegistry(tmp_path, project_name="First", project_description="d1")
    md1 = load_project_metadata(tmp_path)

    # Simulate restart: new HubRegistry pointed at same workspace, no name passed
    reg2 = HubRegistry(tmp_path)
    md2 = load_project_metadata(tmp_path)
    assert md2.id == md1.id
    assert md2.name == "First"          # preserved
    assert md2.description == "d1"      # preserved
    assert md2.created_at == md1.created_at


def test_hub_registry_passing_name_to_existing_project_does_not_clobber(tmp_path):
    HubRegistry(tmp_path, project_name="Original")
    HubRegistry(tmp_path, project_name="DIFFERENT NAME")
    md = load_project_metadata(tmp_path)
    assert md.name == "Original"


def test_touch_updates_last_active_at(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    md_before = load_project_metadata(tmp_path)
    time.sleep(0.01)
    reg.touch()
    md_after = load_project_metadata(tmp_path)
    assert md_after.last_active_at > md_before.last_active_at


def test_set_project_status_persists(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    reg.set_project_status("completed")
    md = load_project_metadata(tmp_path)
    assert md.status == "completed"


def test_set_project_status_rejects_invalid(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    with pytest.raises(ValueError):
        reg.set_project_status("totally_bogus")


def test_project_metadata_property_returns_current(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    assert reg.project_metadata.status == "active"
    reg.set_project_status("paused")
    assert reg.project_metadata.status == "paused"


def test_hub_registry_init_does_not_break_existing_hubs(tmp_path):
    # Sanity: post-Cutover 26 init must still leave hubs functional.
    reg = HubRegistry(tmp_path, project_name="X")
    assert reg.apihub is not None
    assert reg.codehub is not None
    assert reg.workhub is not None
    assert reg.eventhub is not None
    assert reg.runhub is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_registry_project.py -v`

Expected: 7 FAIL (HubRegistry doesn't accept project_name kwarg yet), 1 PASS (the sanity test).

- [ ] **Step 3: Wire HubRegistry to project.py**

Modify `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`. Add imports at the top with the existing imports:

```python
import uuid
```

And import the project helpers (place near top, after `from pathlib import Path`):

```python
from .project import (
    ProjectMetadata,
    load_project_metadata,
    save_project_metadata,
    now_ts,
)
```

Then replace the existing `__init__` signature and the body up to the `if message_bus is not None:` block with:

```python
    def __init__(
        self,
        base_dir: Path,
        message_bus: Any = None,
        *,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        project_description: Optional[str] = None,
    ):
        from .apihub import APIHub
        from .codehub import CodeHub
        from .eventhub import EventHub
        from .hubs.runhub import RunHub
        from .workhub import WorkHub

        self.base_dir = Path(base_dir)
        self._store_dir = self._resolve_hub_dir(self.base_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        # ---- Project metadata (Cutover 26) ----
        # Existing workspace: reuse metadata as-is (kwargs do NOT clobber).
        # New workspace: create metadata from kwargs (or defaults).
        existing = load_project_metadata(self.base_dir)
        if existing is None:
            now = now_ts()
            self._project = ProjectMetadata(
                id=project_id or f"proj_{uuid.uuid4().hex[:12]}",
                name=project_name or self.base_dir.name or "Unnamed Project",
                description=project_description or "",
                created_at=now,
                last_active_at=now,
                status="active",
            )
            save_project_metadata(self.base_dir, self._project)
        else:
            self._project = existing
            # Always bump last_active_at on construction so resume is observable.
            self._project.last_active_at = now_ts()
            save_project_metadata(self.base_dir, self._project)

        self.eventhub = EventHub(self._store_dir)
        self.codehub = CodeHub(self.base_dir, self._store_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self._store_dir, eventhub=self.eventhub)
        self.apihub = APIHub(self._store_dir, eventhub=self.eventhub)
        self.apihub.attach_workhub(self.workhub)
        self.codehub.attach_workhub(self.workhub)
        self.codehub.attach_apihub(self.apihub)
        self.runhub = RunHub(self._store_dir, eventhub=self.eventhub)
        self.runhub.attach_apihub(self.apihub)

        self.bridge: Optional[Any] = None
        if message_bus is not None:
            from .hubs.eventhub.bridge import MessageBusBridge
            self.bridge = MessageBusBridge(message_bus, self.eventhub)
            self.eventhub.attach_bridge(self.bridge)
```

Then add three new methods near the bottom of the class (just before `# Convenience delegation methods` comment block):

```python
    # ------------------------------------------------------------------
    # Project metadata (Cutover 26)
    # ------------------------------------------------------------------

    @property
    def project_metadata(self) -> ProjectMetadata:
        return self._project

    def touch(self) -> None:
        """Bump last_active_at. Call after major phase transitions."""
        self._project.last_active_at = now_ts()
        save_project_metadata(self.base_dir, self._project)

    def set_project_status(self, status: str) -> None:
        """Update project status. Raises ValueError if status is unknown."""
        if status not in {"active", "paused", "completed", "failed", "archived"}:
            raise ValueError(f"unknown project status: {status!r}")
        self._project.status = status
        self._project.last_active_at = now_ts()
        save_project_metadata(self.base_dir, self._project)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_hub_registry_project.py -v`

Expected: 9 PASS.

- [ ] **Step 5: Run regressions to confirm no break**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py`

Expected: `Ran 7 tests` + `OK`.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py \
        agent/tests/test_hub_registry_project.py
git commit -m "Cutover 26: HubRegistry persists project metadata + touch/set_status helpers"
```

---

## Task 5: Top-level resume_project + list_projects helpers

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/project.py` (add `list_projects` + `resume_project` helpers)
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` (export public surface)
- Create: `agent/tests/test_project_resume_e2e.py`

- [ ] **Step 1: Write the failing e2e test for create→exit→resume + tar backup**

```python
# agent/tests/test_project_resume_e2e.py
import shutil
import sys
import tarfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.project import (
    list_projects,
    resume_project,
    load_project_metadata,
)


def test_e2e_create_two_workspaces_then_list_them(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()

    reg_a = HubRegistry(root / "proj_a_ws", project_id="proj_a", project_name="App A")
    reg_b = HubRegistry(root / "proj_b_ws", project_id="proj_b", project_name="App B")

    listed = list_projects(root)
    ids = sorted(p.id for p in listed)
    assert ids == ["proj_a", "proj_b"]


def test_e2e_resume_returns_workspace_path_and_reusable_registry(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()
    reg1 = HubRegistry(root / "proj_a_ws", project_id="proj_a", project_name="App A")

    # Create some state on hub A
    reg1.workhub.create_task(
        task_id="t1", title="initial task", description="", agent="orchestrator",
        domain="any", priority="P1",
    )

    # "Exit": drop the registry handle
    del reg1

    # Resume from project_id alone (UI/CLI scenario)
    workspace = resume_project(root, "proj_a")
    assert workspace == root / "proj_a_ws"

    reg2 = HubRegistry(workspace)
    task = reg2.workhub.get_task("t1")
    assert task is not None
    assert task["title"] == "initial task"


def test_e2e_resume_unknown_project_returns_none(tmp_path):
    assert resume_project(tmp_path, "nope") is None


def test_e2e_completed_project_still_listed(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()
    reg = HubRegistry(root / "proj_done_ws", project_id="proj_done", project_name="done app")
    reg.set_project_status("completed")
    del reg

    listed = list_projects(root)
    assert any(p.id == "proj_done" and p.status == "completed" for p in listed)


def test_e2e_workspace_is_self_contained_tarball_backup_restores(tmp_path):
    """A workspace dir + project.json is enough to back up and restore."""
    root = tmp_path / "workspaces"
    root.mkdir()
    reg = HubRegistry(root / "orig_ws", project_id="proj_backup", project_name="backup demo")
    reg.workhub.create_task(
        task_id="t_backup", title="will be backed up", description="", agent="orchestrator",
        domain="any", priority="P2",
    )
    del reg

    # Tarball the workspace
    backup = tmp_path / "backup.tar"
    with tarfile.open(backup, "w") as tar:
        tar.add(root / "orig_ws", arcname="restored_ws")

    # Wipe original
    shutil.rmtree(root / "orig_ws")
    assert load_project_metadata(root / "orig_ws") is None  # confirm gone

    # Restore elsewhere
    restore_root = tmp_path / "restored"
    restore_root.mkdir()
    with tarfile.open(backup) as tar:
        tar.extractall(restore_root)

    # Open as a fresh HubRegistry and prove state survived
    reg2 = HubRegistry(restore_root / "restored_ws")
    assert reg2.project_metadata.id == "proj_backup"
    assert reg2.workhub.get_task("t_backup")["title"] == "will be backed up"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_resume_e2e.py -v`

Expected: All FAIL with `ImportError: cannot import name 'list_projects' / 'resume_project'`.

- [ ] **Step 3: Add list_projects + resume_project to project.py**

Append to `agent/env_generator/llm_generator/multi_agent/runtime/project.py`:

```python
def list_projects(workspaces_root: Path, status: Optional[str] = None) -> List[ProjectMetadata]:
    """List projects under a workspaces-root, optionally filtered by status."""
    return ProjectIndex(workspaces_root).list(status=status)


def resume_project(workspaces_root: Path, project_id: str) -> Optional[Path]:
    """Return the workspace path for a project_id, or None if not found.

    The caller passes this path to HubRegistry(...) to resume.
    """
    _, workspace = ProjectIndex(workspaces_root).get(project_id)
    return workspace
```

- [ ] **Step 4: Update runtime/__init__.py exports**

First read it:

```bash
cat agent/env_generator/llm_generator/multi_agent/runtime/__init__.py
```

Then add (or merge into existing exports):

```python
from .project import (
    ProjectMetadata,
    ProjectIndex,
    list_projects,
    resume_project,
    load_project_metadata,
    save_project_metadata,
)
```

If `__all__` exists, add the names; if not, leave imports to drive `from runtime import X`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_project_resume_e2e.py -v`

Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/project.py \
        agent/env_generator/llm_generator/multi_agent/runtime/__init__.py \
        agent/tests/test_project_resume_e2e.py
git commit -m "Cutover 26: list_projects + resume_project public surface + e2e backup/resume"
```

---

## Task 6: Orchestrator wires project_name + touch + completed-status

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/orchestrator.py`

- [ ] **Step 1: Locate the deliver-success path in orchestrator.py**

Run: `grep -n "set_project_status\|def deliver\|deliver_project\|finalize\|complete" agent/env_generator/llm_generator/multi_agent/orchestrator.py | head -20`

Identify the method (or methods) that mark the end of a successful generation run. Likely candidates: a `run()` returning `GenerationResult`, a `deliver()` callback, or a finalize block.

- [ ] **Step 2: Update HubRegistry construction to pass project metadata**

Replace the existing line at `agent/env_generator/llm_generator/multi_agent/orchestrator.py:157`:

```python
        self.hubs = HubRegistry(self.output_dir, message_bus=self.message_bus)
```

with:

```python
        self.hubs = HubRegistry(
            self.output_dir,
            message_bus=self.message_bus,
            project_name=name,
            project_description=getattr(self, "_description", "") or "",
        )
```

(`name` is the `Orchestrator.__init__` parameter at line 109; `_description` is not set today — `getattr` defaults to "".)

- [ ] **Step 3: Add hubs.touch() at the start of run() and hubs.set_project_status() on success/failure**

Find the `run()` method (or top-level execution entry) on `Orchestrator`. At the top of `run()`, before any phase begins, add:

```python
        self.hubs.touch()
```

At the point where a successful `GenerationResult` is constructed (or just before `return result`), add:

```python
        try:
            self.hubs.set_project_status("completed")
        except Exception as e:
            self._logger.warning(f"Failed to mark project completed: {e}")
```

At the equivalent failure-exit point (raised exception or returned `success=False`):

```python
        try:
            self.hubs.set_project_status("failed")
        except Exception as e:
            self._logger.warning(f"Failed to mark project failed: {e}")
```

If `run()` doesn't have clear success/failure branches yet, wrap the existing main body in a `try / except / finally`:

```python
        try:
            result = await self._run_inner()        # whatever the existing body is
            try:
                self.hubs.set_project_status("completed" if result and getattr(result, "success", True) else "failed")
            except Exception as e:
                self._logger.warning(f"Failed to set project status: {e}")
            return result
        except Exception:
            try:
                self.hubs.set_project_status("failed")
            except Exception as e:
                self._logger.warning(f"Failed to set project status: {e}")
            raise
```

(Choose the lighter-touch version if existing branches are obvious — don't restructure unrelated code.)

- [ ] **Step 4: Write a quick smoke test that confirms orchestrator wiring**

Create `agent/env_generator/llm_generator/multi_agent/tests/test_orchestrator_project_status.py`:

```python
"""Cutover 26: orchestrator marks project_metadata.status during a run."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry


def test_hub_registry_constructed_with_name_persists_name(tmp_path):
    # Mirrors the orchestrator's construction call.
    reg = HubRegistry(tmp_path, project_name="my_app")
    assert reg.project_metadata.name == "my_app"


def test_set_status_completed_persists_across_reload(tmp_path):
    reg = HubRegistry(tmp_path, project_name="my_app")
    reg.set_project_status("completed")
    del reg
    reg2 = HubRegistry(tmp_path)
    assert reg2.project_metadata.status == "completed"


def test_resume_after_failed_status(tmp_path):
    reg = HubRegistry(tmp_path, project_name="my_app")
    reg.set_project_status("failed")
    del reg
    # Resuming a failed project is allowed — orchestrator can re-run it
    reg2 = HubRegistry(tmp_path)
    assert reg2.project_metadata.status == "failed"
    reg2.set_project_status("active")  # resume bumps back to active
    assert reg2.project_metadata.status == "active"
```

- [ ] **Step 5: Run the smoke test + regressions**

Run:
```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/test_orchestrator_project_status.py -v
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

Expected: 3 new PASS; `Ran 7 tests` + `OK`.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/orchestrator.py \
        agent/env_generator/llm_generator/multi_agent/tests/test_orchestrator_project_status.py
git commit -m "Cutover 26: orchestrator passes project_name + sets status completed/failed"
```

---

## Task 7: Discover-wide regression sweep + migration log + push

**Files:**
- Modify: `docs/superpowers/migration-logs/26-per-project-hubs.md`

- [ ] **Step 1: Full test sweep**

Run:

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py 2>&1 | tail -5
/home/haibotong/miniconda3/envs/dt/bin/python -m pytest agent/tests/ -q 2>&1 | tail -10
```

Expected:
- Regressions: `Ran 7 tests` + `OK`
- Discover: 920 → ~951 OK (920 prior + 6 metadata + 8 index + 9 hub_registry_project + 5 resume_e2e + 3 orchestrator_status = 31 new)

If anything fails: do NOT bypass. Investigate, fix the root cause, re-run.

- [ ] **Step 2: Update migration log with final test deltas**

Replace the `Status: in-progress` line and append sections so the file looks like:

```markdown
# Cutover 26: Per-Project Hub Records (Resume + Backup)

**Branch:** `haibotong-cutover-26-per-project-hubs`
**Date:** 2026-05-26

## What

Each workspace is now a first-class **project record** that survives
orchestrator exit/crash. `project.json` at workspace root carries
`{id, name, description, created_at, last_active_at, status, agents_used}`.
HubRegistry creates/refreshes it on init; orchestrator marks
`status="completed"` on successful delivery and `"failed"` on terminal
failure. `ProjectIndex` + `list_projects()` + `resume_project()` give the
new UI (Cutover 28) and CLIs a stable enumeration/resume API.

## Why

Pre-Cutover 26, a workspace was an anonymous directory: no name, no
status, no listing. Once the orchestrator exited, nothing distinguished
a half-finished generation from a completed one or from leftover junk.
The user asked for "GitHub-like project records" — persistent, resumable,
backup-friendly. This is the foundation for the new product UI's
homepage/project-picker (Cutover 28) and for the human-agent chat
persistence (Cutover 27).

## Commits

- Cutover 26: record pre-flight baseline (regressions 7 OK, discover 920 OK)
- Cutover 26: add ProjectMetadata dataclass + JSON persistence
- Cutover 26: add ProjectIndex for cross-workspace project enumeration
- Cutover 26: HubRegistry persists project metadata + touch/set_status helpers
- Cutover 26: list_projects + resume_project public surface + e2e backup/resume
- Cutover 26: orchestrator passes project_name + sets status completed/failed
- (this commit) Cutover 26: migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Discover: 920 OK → <FINAL_COUNT> OK (+<DELTA> new)

## New surfaces

- `runtime/project.py` — `ProjectMetadata` dataclass, `ProjectIndex`,
  `list_projects(root)`, `resume_project(root, id)`, `load/save_project_metadata`
- `HubRegistry(base_dir, *, project_id?, project_name?, project_description?)`
  — new kwargs; existing positional callers unaffected
- `HubRegistry.project_metadata` — read-only view of persisted record
- `HubRegistry.touch()` — bump last_active_at
- `HubRegistry.set_project_status(status)` — `active|paused|completed|failed|archived`

## Backup model

A workspace dir is fully self-contained (`project.json` + `shared/hubs/`
JsonStore files). `tar -cf backup.tar <workspace>/` is a complete
backup; extracting elsewhere and constructing `HubRegistry(new_path)`
restores all state. Verified by `test_e2e_workspace_is_self_contained_tarball_backup_restores`.

## Resume model

`resume_project(workspaces_root, project_id)` returns the workspace
Path; pass it to `HubRegistry(path)` (or `Orchestrator(output_dir=path)`).
Existing `project.json` is preserved; passing `project_name` to a
HubRegistry pointed at an existing workspace does NOT clobber the
stored name.

## Schema-version policy

`project.json` carries `schema_version: 1`. Future migrations bump and
ship a converter in `ProjectMetadata.from_dict`. Unknown fields are
tolerated (forward-compat).

## Known limits (future cutovers)

- Project IDs are auto-generated (`proj_<12-hex>`) when not specified.
  No global ID collision check across multiple workspaces-roots.
- `agents_used` is not auto-populated yet — Cutover 27 will populate
  it as agents post messages.
- No archive/cleanup CLI — `status=archived` is persisted but no tool
  yet uses it.
- Backup is `tar -cf` manual; no scheduled snapshot or remote sync.
```

(Fill in `<FINAL_COUNT>` and `<DELTA>` from Step 1's output.)

- [ ] **Step 3: Commit migration log**

```bash
git add docs/superpowers/migration-logs/26-per-project-hubs.md
git commit -m "Cutover 26: migration log"
```

- [ ] **Step 4: Push the branch to Virtue-AI**

```bash
git push -u red-env-gen haibotong-cutover-26-per-project-hubs 2>&1 | tail -5
```

Expected: `Branch 'haibotong-cutover-26-per-project-hubs' set up to track remote ...`.

- [ ] **Step 5: Fast-forward merge into parent + push parent**

```bash
cd /data/common/haibotong/env-gen
git fetch . haibotong-cutover-26-per-project-hubs
git merge --ff-only haibotong-cutover-26-per-project-hubs
git push red-env-gen haibotong-0521-pipeline-web-tools 2>&1 | tail -5
```

Expected: clean ff-merge + clean push.

---

## Self-Review Notes

**Spec coverage:**
- "每个hub都要有对应项目的记录" → Task 2-4 (project.json at workspace root; HubRegistry persists/refreshes)
- "就喝github一样，不是项目完成就消失了" → Task 4 (set_project_status preserves the record); Task 5 (resume_project lookup)
- "这样能resume也能备份" → Task 5 (resume_project) + Task 5 step 1 (backup/restore e2e test)

**Out of scope (deferred):**
- Per-project namespacing *inside* hub stores — not needed; workspace is already the isolation boundary
- Multi-project workspaces — explicitly rejected by user ("workspace = 1 project")
- Archive/cleanup CLI — listed in Known Limits
- UI changes — Cutover 28
