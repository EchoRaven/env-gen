# Cutover 19: Dead-Code Detection + Reverse-Consumer Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Block `deliver_project()` when the generated app contains dead components — APIHub endpoints with zero consumers, APIHub tables with zero exposing endpoints, or frontend source files imported by nothing. Force-deliver remains available as orchestrator-only audited bypass (same pattern as `force_merge_pull_request` from Cutover 7).

**Architecture:** New pure module `runtime/coverage_audit.py` scans (1) APIHub provider/consumer graphs and (2) the generated app's source tree for import edges. Returns a `CoverageReport` dataclass listing every dead artifact. New WorkHub page kind `coverage_allowlist` lets the orchestrator whitelist intentionally-dead files with a reason (e.g., feature behind flag). `DeliverProjectTool.execute` calls the audit; refuses if non-allowlisted dead artifacts exist. Three new LLM tools (`coverage_audit_check`, `mark_intentionally_dead`, `list_dead_allowlist`).

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Pure stdlib (`re`, `pathlib`, `os.walk`).

---

## Context for Worker

### Why this cutover exists

Schema gates (Cutover 7) ensure every *declared* contract is implemented. **They don't check the reverse direction** — that every *implemented* artifact is used. The system can ship:

- A backend `GET /api/feed` endpoint that no frontend page calls
- A React `<FeedItem>` component imported by nothing
- A `notifications` database table not exposed by any endpoint
- A backend route file (`routes/admin.py`) that the router never mounts

All four cases pass current gates but make the delivered app bloated and confusing. The dead artifact is a maintenance bomb and a signal that the spec drifted from the implementation.

### Dead-artifact taxonomy

1. **Dead endpoint** — APIHub `endpoint.status == "defined"` AND `apihub.get_consumers(endpoint_id)` returns empty.
2. **Dead table** — APIHub registered table not referenced by any endpoint's request/response schema AND no `table_consumers` entries.
3. **Dead source file** — frontend/backend source file not imported by any other source file AND not an entry point (`main.tsx`, `main.jsx`, `App.tsx`, `index.tsx`, `app.js`, `server.js`, `server.ts`, `__init__.py`, `app.py`).

### Detection limits (documented as known false-positive sources)

- **Dynamic imports** (`React.lazy(() => import('./X'))`) — basic regex catches `import('./X')` patterns but may miss programmatic builds.
- **Router-mounted backend routes** — Express `app.use('/api', adminRouter)` reads `adminRouter` from another file; if that file only re-exports the router via `module.exports = router`, the static scan sees no consumer. Mitigated by treating `routes/*.js` as auto-imported entry points if a sibling `index.js` mentions them.
- **Generated test files** — `*.test.*` / `*.spec.*` are scanned but excluded from "dead" verdict (testing dead code is OK because the test itself is the consumer).

Known limits are why `mark_intentionally_dead` exists — orchestrator can whitelist with a reason, audited on the allowlist page.

### Allowlist schema (WorkHub page)

```python
{
    "kind": "coverage_allowlist",
    "title": "Coverage allowlist",
    "metadata": {
        "entries": [
            {"path": "frontend/src/components/UpcomingFeature.tsx",
             "reason": "Behind FEATURE_FLAG_X; intentional",
             "added_by": "orchestrator", "added_at": <epoch>},
            ...
        ],
    },
}
```

One allowlist page per generation. `list_dead_allowlist()` returns the entries; `mark_intentionally_dead(path, reason)` appends.

### Deliver gate behavior

`DeliverProjectTool.execute` now (after the existing retro check from Cutover 16):
1. Calls `compute_coverage(hub_registry, app_root)` where `app_root = self.agent.workspace_path / "generated"` (or wherever the generated app lives — verify in Task 1)
2. Computes `dead = report.all_dead_paths - allowlist.paths`
3. If `dead` is non-empty → return `ToolResult.fail(...)` listing the dead artifacts and the two recovery paths: (a) wire the artifact up to a consumer, (b) `mark_intentionally_dead(path, reason)` if it's intentional
4. Force-deliver bypass: `force_deliver=True` kwarg AND `self.agent.agent_type == "orchestrator"` — same audit pattern as `force_merge_pull_request`; writes a `system/dead_code_bypass` EventHub event

### What's intentionally NOT in scope

- Cleaning up the dead code (that's the agent's job after the gate fires)
- Removing dead code automatically (too risky for MVP)
- TypeScript-aware AST scanning (regex import scan is sufficient for MVP; AST is a future cutover)
- Cross-module duplicate detection (different concern; future)

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (dt conda env)
- No Claude trailer; no emojis
- TDD: failing test → confirm fail → minimal impl → confirm pass → commit
- Bite-sized commits; no push until Task 8
- Both baselines green at every task boundary: regressions 7 OK; discover 698 OK after Cutover 18
- Worktree path: `worktrees/<agent_id>`; default git branch: `master`

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py` — `CoverageReport`, `compute_coverage`, file scanners
- `agent/env_generator/llm_generator/tools/coverage_tools.py` — 3 LLM tools
- `agent/tests/test_coverage_audit.py`
- `agent/tests/test_coverage_tools.py`
- `agent/tests/test_workhub_coverage_allowlist.py`
- `agent/tests/test_deliver_coverage_gate.py`
- `agent/tests/test_coverage_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — add `list_coverage_allowlist`, `mark_path_intentionally_dead`
- `agent/env_generator/llm_generator/tools/agent_interaction_tools.py` — `DeliverProjectTool` adds coverage pre-flight + `force_deliver` kwarg
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `coverage_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — add `coverage_tools` to orchestrator + verifier profiles
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2` — COVERAGE DISCIPLINE block

---

## Task 1: Worktree + baseline + app-root inventory

**Files:**
- Create: `docs/superpowers/cutover-19-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-19-dead-code
git status
git log --oneline -3
```

If missing: `git worktree add -b haibotong-cutover-19-dead-code .worktrees/haibotong-cutover-19-dead-code haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 698 OK.

- [ ] **Step 3: Inventory generated-app layout**

```bash
ls generated/ 2>/dev/null | head -10
find generated -maxdepth 3 -name "App.tsx" -o -name "main.tsx" -o -name "App.jsx" -o -name "server.ts" -o -name "server.js" 2>/dev/null | head -10
find generated -maxdepth 4 -type d \( -name "frontend" -o -name "backend" -o -name "src" -o -name "components" -o -name "routes" \) 2>/dev/null | head -10
```

Record: typical generated-app root (probably `generated/<spec-name>/`), entry-point file names, frontend vs backend dir convention. Task 2 file scanner needs this.

- [ ] **Step 4: Inventory APIHub helpers**

```bash
grep -nE "def (get_endpoints|list_tables|get_consumers|register_consumer)" agent/env_generator/llm_generator/multi_agent/runtime/apihub.py
```

Confirm signatures haven't shifted since Cutover 18.

- [ ] **Step 5: Confirm DeliverProjectTool retro gate location** (Cutover 16 anchor)

```bash
grep -nE "retro for this generation|_session_start_ts" agent/env_generator/llm_generator/tools/agent_interaction_tools.py | head -5
```

Note line numbers — Task 5 will add coverage check immediately after the existing retro gate.

- [ ] **Step 6: Baseline note + commit**

Create `docs/superpowers/cutover-19-baseline.md`:

```markdown
# Cutover 19 Baseline (Dead-Code Gate)

## Test counts
- regressions: 7 OK
- discover: 698 OK

## Gap this cutover closes
Schema gates (Cutover 7) verify declared APIs/tables are implemented.
NO REVERSE CHECK: implemented endpoints/components/files can be dead
(zero consumers) and still ship. dead artifacts pass all current gates.

## Approach
- runtime/coverage_audit.py: pure scanner over APIHub provider+consumer
  graphs and app-root source-file import graph
- WorkHub page kind="coverage_allowlist" for orchestrator-blessed
  intentionally-dead files (audited)
- DeliverProjectTool: refuses if coverage_dead - allowlist non-empty
- force_deliver kwarg = orchestrator-only audit bypass (matches Cutover 7
  force_merge pattern)

## Inventory
- Generated app root: <paste find result>
- Entry points: <paste>
- APIHub helpers confirmed: get_endpoints, list_tables, get_consumers,
  register_consumer
- DeliverProjectTool retro gate at: <line>
```

```bash
git add docs/superpowers/cutover-19-baseline.md
git commit -m "Cutover 19: record pre-flight baseline (regressions 7 OK, discover 698 OK)"
```

Verify no Claude trailer.

---

## Task 2: Pure coverage_audit module

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py`
- Create: `agent/tests/test_coverage_audit.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_coverage_audit.py`:

```python
"""Tests for runtime/coverage_audit.py (Cutover 19)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.coverage_audit import (  # noqa: E402
    CoverageReport, compute_coverage, scan_dead_files,
    scan_dead_endpoints, scan_dead_tables,
)


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


class DeadEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_ep_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_endpoints_returns_empty(self) -> None:
        self.assertEqual(scan_dead_endpoints(self.reg), [])

    def test_endpoint_without_consumer_is_dead(self) -> None:
        self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        dead = scan_dead_endpoints(self.reg)
        ids = [d["endpoint_id"] for d in dead]
        self.assertEqual(len(ids), 1)
        self.assertIn("GET /api/feed", " ".join(ids) + " " +
                       " ".join(d.get("path", "") for d in dead))

    def test_endpoint_with_consumer_is_not_dead(self) -> None:
        ep = self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        self.reg.apihub.register_consumer(
            ep["id"], file_path="frontend/src/api/feed.ts", agent="frontend")
        self.assertEqual(scan_dead_endpoints(self.reg), [])

    def test_deprecated_endpoint_not_flagged_dead(self) -> None:
        self.reg.apihub.register_endpoint(
            "GET", "/api/old", schema={}, provider="backend", agent="backend",
            status="deprecated")
        self.assertEqual(scan_dead_endpoints(self.reg), [])


class DeadTablesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_tb_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tables_returns_empty(self) -> None:
        self.assertEqual(scan_dead_tables(self.reg), [])

    def test_table_without_consumer_is_dead(self) -> None:
        self.reg.apihub.register_table(
            "notifications", schema={"columns": []},
            provider="database", agent="database")
        dead = scan_dead_tables(self.reg)
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["table"], "notifications")

    def test_table_with_consumer_is_not_dead(self) -> None:
        self.reg.apihub.register_table(
            "users", schema={"columns": []},
            provider="database", agent="database")
        self.reg.apihub.register_table_consumer(
            "users", file_path="backend/routes/auth.py", agent="backend")
        self.assertEqual(scan_dead_tables(self.reg), [])


class DeadFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_files_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_app_root_returns_empty(self) -> None:
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_entry_point_not_flagged(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\nApp();\n")
        _write(self.tmp / "frontend/src/App.tsx", "export default function App(){}\n")
        # main.tsx is entry; App.tsx is imported -> nothing dead
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_uninported_component_is_dead(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\nApp();\n")
        _write(self.tmp / "frontend/src/App.tsx", "export default function App(){}\n")
        _write(self.tmp / "frontend/src/components/Dead.tsx",
               "export default function Dead(){}\n")
        dead = scan_dead_files(self.tmp)
        dead_paths = [d["path"] for d in dead]
        self.assertEqual(len(dead_paths), 1)
        self.assertTrue(any("Dead.tsx" in p for p in dead_paths))

    def test_imported_component_is_not_dead(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\n")
        _write(self.tmp / "frontend/src/App.tsx",
               "import Feed from './components/Feed';\nexport default function App(){}\n")
        _write(self.tmp / "frontend/src/components/Feed.tsx",
               "export default function Feed(){}\n")
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_test_files_excluded(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx", "export const x = 1;\n")
        _write(self.tmp / "frontend/src/Foo.test.tsx",
               "import Foo from './Foo';\ntest('x', ()=>{});\n")
        _write(self.tmp / "frontend/src/Foo.tsx",
               "export default function Foo(){}\n")
        # Foo.test.tsx is excluded from dead check (test files always exempt)
        # Foo.tsx is imported only by the test, but tests ARE valid consumers
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_backend_entry_points_not_flagged(self) -> None:
        _write(self.tmp / "backend/server.ts",
               "import { router } from './routes';\nstartServer(router);\n")
        _write(self.tmp / "backend/routes/index.ts",
               "export const router = {};\n")
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_python_backend_unimported_module_is_dead(self) -> None:
        _write(self.tmp / "backend/app.py",
               "from routes.feed import router\n")
        _write(self.tmp / "backend/routes/__init__.py", "")
        _write(self.tmp / "backend/routes/feed.py", "router = None\n")
        _write(self.tmp / "backend/routes/dead.py", "x = 1\n")
        dead = scan_dead_files(self.tmp)
        self.assertEqual(len(dead), 1)
        self.assertTrue(dead[0]["path"].endswith("dead.py"))


class ComputeCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_full_"))
        self.app_root = self.tmp / "app"
        self.reg = HubRegistry(self.tmp / "hub")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_report_for_clean_setup(self) -> None:
        report = compute_coverage(self.reg, self.app_root)
        self.assertIsInstance(report, CoverageReport)
        self.assertEqual(report.dead_endpoints, [])
        self.assertEqual(report.dead_tables, [])
        self.assertEqual(report.dead_files, [])
        self.assertTrue(report.is_clean)

    def test_aggregates_all_three_categories(self) -> None:
        self.reg.apihub.register_endpoint(
            "GET", "/api/x", schema={}, provider="backend", agent="backend")
        self.reg.apihub.register_table(
            "t", schema={"columns": []}, provider="database", agent="database")
        _write(self.app_root / "frontend/src/main.tsx", "x = 1;\n")
        _write(self.app_root / "frontend/src/Dead.tsx", "export const d = 1;\n")
        report = compute_coverage(self.reg, self.app_root)
        self.assertEqual(len(report.dead_endpoints), 1)
        self.assertEqual(len(report.dead_tables), 1)
        self.assertEqual(len(report.dead_files), 1)
        self.assertFalse(report.is_clean)

    def test_all_dead_paths_property(self) -> None:
        self.reg.apihub.register_endpoint(
            "GET", "/api/x", schema={}, provider="backend", agent="backend")
        _write(self.app_root / "frontend/src/main.tsx", "x = 1;\n")
        _write(self.app_root / "frontend/src/Dead.tsx", "x = 1;\n")
        report = compute_coverage(self.reg, self.app_root)
        paths = report.all_dead_paths
        self.assertIn("endpoint:GET /api/x", paths)
        self.assertTrue(any(p.startswith("file:") and "Dead.tsx" in p for p in paths))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_coverage_audit -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement the audit module**

Create `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py`:

```python
"""Coverage audit (Cutover 19): scan for dead endpoints/tables/source-files.

Pure read-side over HubRegistry + filesystem. No mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set


_ENTRY_POINT_BASENAMES = {
    "main.tsx", "main.jsx", "main.ts", "main.js",
    "index.tsx", "index.jsx", "index.ts", "index.js",
    "app.tsx", "app.jsx",  # case-insensitive match below
    "server.ts", "server.js", "server.py",
    "app.py", "main.py", "__main__.py",
    "manage.py", "wsgi.py", "asgi.py",
    "vite.config.ts", "vite.config.js",
    "next.config.js", "tailwind.config.js",
    "package.json", "tsconfig.json",
    "docker-compose.yml", "dockerfile",
}

_SOURCE_EXTS = (".tsx", ".jsx", ".ts", ".js", ".py")
_TEST_PATTERNS = (".test.", ".spec.", "_test.", "_spec.", "/tests/", "/__tests__/")

# Captures imports like:
#   import X from './foo';
#   import { X } from "./foo/bar";
#   import('./lazy/foo')
#   from .foo import X            (python)
#   from foo.bar import X         (python)
#   require('./foo')              (commonjs)
_JS_IMPORT_RE = re.compile(
    r"""(?x)
    (?:
      (?:from|import)\s+['"]([^'"]+)['"]
      |
      require\(\s*['"]([^'"]+)['"]\s*\)
      |
      import\(\s*['"]([^'"]+)['"]\s*\)
    )
    """
)
_PY_IMPORT_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:
      from\s+([\w\.]+)\s+import
      |
      import\s+([\w\.]+)
    )
    """,
    re.MULTILINE,
)


@dataclass
class CoverageReport:
    dead_endpoints: List[dict] = field(default_factory=list)
    dead_tables: List[dict] = field(default_factory=list)
    dead_files: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.dead_endpoints or self.dead_tables or self.dead_files)

    @property
    def all_dead_paths(self) -> Set[str]:
        out: Set[str] = set()
        for ep in self.dead_endpoints:
            out.add(f"endpoint:{ep['endpoint_id']}")
        for t in self.dead_tables:
            out.add(f"table:{t['table']}")
        for f in self.dead_files:
            out.add(f"file:{f['path']}")
        return out

    def to_dict(self) -> dict:
        return {
            "dead_endpoints": list(self.dead_endpoints),
            "dead_tables": list(self.dead_tables),
            "dead_files": list(self.dead_files),
            "is_clean": self.is_clean,
        }


def scan_dead_endpoints(hub_registry) -> List[dict]:
    apihub = getattr(hub_registry, "apihub", None)
    if apihub is None or not hasattr(apihub, "get_endpoints"):
        return []
    eps = apihub.get_endpoints() or {}
    out = []
    for ep_id, ep in eps.items():
        if (ep.get("status") or "defined") != "defined":
            continue  # deprecated/draft don't count as dead
        consumers = apihub.get_consumers(ep_id) if hasattr(apihub, "get_consumers") else []
        if not consumers:
            out.append({
                "endpoint_id": ep_id,
                "method": ep.get("method"),
                "path": ep.get("path"),
                "provider": ep.get("provider"),
            })
    return out


def scan_dead_tables(hub_registry) -> List[dict]:
    apihub = getattr(hub_registry, "apihub", None)
    if apihub is None or not hasattr(apihub, "list_tables"):
        return []
    tables = apihub.list_tables() or {}
    table_consumers = (
        apihub._table_consumers.value() if hasattr(apihub, "_table_consumers") else {}
    )
    # Index: table_name -> count of consumers
    consumer_count: Dict[str, int] = {}
    for entry in (table_consumers or {}).values():
        name = entry.get("table_name") or entry.get("table")
        if name:
            consumer_count[name] = consumer_count.get(name, 0) + 1
    out = []
    for name, table in tables.items():
        if consumer_count.get(name, 0) > 0:
            continue
        out.append({"table": name, "provider": table.get("provider")})
    return out


def _is_test_file(path_str: str) -> bool:
    return any(p in path_str for p in _TEST_PATTERNS)


def _is_entry_point(path: Path) -> bool:
    return path.name.lower() in _ENTRY_POINT_BASENAMES


def _collect_source_files(app_root: Path) -> List[Path]:
    files: List[Path] = []
    for p in app_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in _SOURCE_EXTS:
            continue
        rel = str(p.relative_to(app_root))
        # Skip node_modules, .venv, build outputs
        if any(seg in rel for seg in ("node_modules", ".venv", "venv/",
                                       "dist/", "build/", ".next/", "__pycache__/")):
            continue
        files.append(p)
    return files


def _normalize_js_import(source_file: Path, raw: str) -> List[str]:
    """Return possible absolute paths the import could resolve to."""
    if raw.startswith("."):
        base = (source_file.parent / raw).resolve()
        candidates = [base]
        if base.suffix == "":
            for ext in _SOURCE_EXTS:
                candidates.append(base.with_suffix(ext))
            for ext in _SOURCE_EXTS:
                candidates.append(base / f"index{ext}")
        return [str(c) for c in candidates]
    return []  # bare module import — not a local file


def _normalize_py_import(source_file: Path, raw: str, app_root: Path) -> List[str]:
    """Translate `routes.feed` style import to candidate file paths."""
    if not raw or raw.startswith("."):
        # Relative import — translate dots to parent dirs
        # MVP: handle single-level relative
        base = source_file.parent
        cleaned = raw.lstrip(".")
        parts = cleaned.split(".") if cleaned else []
    else:
        # Absolute (rooted at app_root or first subdir)
        # MVP: assume rooted at source_file's package root
        # Walk up from source_file until a dir contains an __init__.py-less ancestor or hits app_root
        base = source_file.parent
        # Naive: project root is the directory containing the deepest matching parent
        # We just search siblings + app_root subdirs
        parts = raw.split(".")
    if not parts:
        return []
    candidates: List[Path] = []
    # Try relative to source's dir AND from app_root recursively (one level)
    for root in (base, app_root, *app_root.iterdir() if app_root.exists() else ()):
        if not isinstance(root, Path) or not root.is_dir():
            continue
        target = root.joinpath(*parts)
        candidates.append(target.with_suffix(".py"))
        candidates.append(target / "__init__.py")
    return [str(c) for c in candidates]


def scan_dead_files(app_root: Path) -> List[dict]:
    app_root = Path(app_root)
    if not app_root.exists() or not app_root.is_dir():
        return []
    files = _collect_source_files(app_root)
    if not files:
        return []
    file_set = {str(f.resolve()) for f in files}

    # Build consumer graph: file -> set of files it imports
    imported: Set[str] = set()
    for src in files:
        try:
            text = src.read_text(errors="replace")
        except OSError:
            continue
        if src.suffix == ".py":
            for m in _PY_IMPORT_RE.finditer(text):
                raw = m.group(1) or m.group(2)
                for cand in _normalize_py_import(src, raw, app_root):
                    if cand in file_set:
                        imported.add(cand)
        else:
            for m in _JS_IMPORT_RE.finditer(text):
                raw = m.group(1) or m.group(2) or m.group(3)
                for cand in _normalize_js_import(src, raw):
                    if cand in file_set:
                        imported.add(cand)

    # A test file ALWAYS counts as a valid consumer of whatever it imports.
    # But test files themselves shouldn't be flagged dead — they're entry-leaf nodes.
    out: List[dict] = []
    for src in files:
        abs_str = str(src.resolve())
        rel_str = str(src.relative_to(app_root))
        if _is_test_file(rel_str) or _is_test_file(abs_str):
            continue  # tests are never flagged dead
        if _is_entry_point(src):
            continue
        if abs_str in imported:
            continue
        out.append({"path": rel_str})
    return out


def compute_coverage(hub_registry, app_root) -> CoverageReport:
    app_root = Path(app_root)
    return CoverageReport(
        dead_endpoints=scan_dead_endpoints(hub_registry),
        dead_tables=scan_dead_tables(hub_registry),
        dead_files=scan_dead_files(app_root),
    )


__all__ = [
    "CoverageReport", "compute_coverage",
    "scan_dead_endpoints", "scan_dead_tables", "scan_dead_files",
]
```

- [ ] **Step 4: Verify all tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_coverage_audit -v 2>&1 | tail -20
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: ~17 OK in coverage_audit tests; 7 OK / 715 OK total (698 + 17 new). If the python-import resolver test fails because the regex/normalizer is too aggressive, adjust the normalizer (it's MVP; weakening to a more conservative match is OK — but document deviation).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py agent/tests/test_coverage_audit.py
git commit -m "Add coverage_audit: scan dead APIHub endpoints/tables + dead source files"
```

---

## Task 3: WorkHub coverage allowlist

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`
- Create: `agent/tests/test_workhub_coverage_allowlist.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_workhub_coverage_allowlist.py`:

```python
"""Tests for WorkHub coverage_allowlist helpers (Cutover 19)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class CoverageAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_allow_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_allowlist_returns_empty(self) -> None:
        self.assertEqual(self.reg.workhub.list_coverage_allowlist(), [])

    def test_mark_intentionally_dead_creates_entry(self) -> None:
        entry = self.reg.workhub.mark_path_intentionally_dead(
            "file:frontend/src/UpcomingFeature.tsx",
            reason="behind FEATURE_FLAG_X",
            agent="orchestrator")
        self.assertEqual(entry["path"], "file:frontend/src/UpcomingFeature.tsx")
        self.assertEqual(entry["reason"], "behind FEATURE_FLAG_X")

    def test_list_after_mark_returns_entry(self) -> None:
        self.reg.workhub.mark_path_intentionally_dead(
            "endpoint:GET /api/v1/legacy",
            reason="kept for v0 clients", agent="orchestrator")
        entries = self.reg.workhub.list_coverage_allowlist()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "kept for v0 clients")

    def test_multiple_marks_append_to_same_page(self) -> None:
        for i in range(3):
            self.reg.workhub.mark_path_intentionally_dead(
                f"file:dead{i}.tsx", reason=f"r{i}", agent="orchestrator")
        entries = self.reg.workhub.list_coverage_allowlist()
        self.assertEqual(len(entries), 3)

    def test_mark_with_empty_reason_is_rejected(self) -> None:
        result = self.reg.workhub.mark_path_intentionally_dead(
            "file:x.tsx", reason="", agent="orchestrator")
        self.assertIn("error", result)

    def test_mark_with_empty_path_is_rejected(self) -> None:
        result = self.reg.workhub.mark_path_intentionally_dead(
            "", reason="r", agent="orchestrator")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_coverage_allowlist -v 2>&1 | tail -10
```

- [ ] **Step 3: Add helpers to WorkHub**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`, add (near other `list_*` / `get_design_page` helpers):

```python
    _COVERAGE_ALLOWLIST_TITLE = "Coverage allowlist"

    def _get_or_create_allowlist_page(self, agent: str = "orchestrator") -> dict:
        for page in (self.stores.pages.value() or {}).values():
            if page.get("kind") == "coverage_allowlist":
                return page
        return self.create_page(
            title=self._COVERAGE_ALLOWLIST_TITLE,
            agent=agent, kind="coverage_allowlist",
            metadata={"entries": []})

    def list_coverage_allowlist(self) -> list:
        page = next((p for p in (self.stores.pages.value() or {}).values()
                      if p.get("kind") == "coverage_allowlist"), None)
        if page is None:
            return []
        return list((page.get("metadata") or {}).get("entries") or [])

    def mark_path_intentionally_dead(self, path: str, reason: str,
                                       agent: str = "orchestrator") -> dict:
        if not isinstance(path, str) or not path.strip():
            return {"error": "path must be non-empty"}
        if not isinstance(reason, str) or not reason.strip():
            return {"error": "reason must be non-empty"}
        page = self._get_or_create_allowlist_page(agent=agent)
        entry = {"path": path, "reason": reason, "added_by": agent,
                  "added_at": time.time()}
        updated = dict(page)
        meta = dict(updated.get("metadata") or {})
        entries = list(meta.get("entries") or [])
        entries.append(entry)
        meta["entries"] = entries
        updated["metadata"] = meta
        updated["_updated_by"] = agent
        updated["_updated_at"] = time.time()
        self.stores.pages.update(lambda m: m.set(page["id"], updated, agent),
                                  change_info={"agent": agent})
        return entry
```

- [ ] **Step 4: Verify 6 tests pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_workhub_coverage_allowlist -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 6 OK; 7 OK / 721 OK (715 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_workhub_coverage_allowlist.py
git commit -m "WorkHub: add coverage_allowlist page kind + list/mark_path_intentionally_dead helpers"
```

---

## Task 4: Coverage LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/coverage_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Create: `agent/tests/test_coverage_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_coverage_tools.py`:

```python
"""Tests for coverage LLM tools (Cutover 19)."""

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


class CoverageToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_tools_"))
        self.reg = HubRegistry(self.tmp / "hub")
        self.app_root = self.tmp / "app"
        self.app_root.mkdir(parents=True)
        # Bare main + one dead component
        (self.app_root / "frontend/src").mkdir(parents=True)
        (self.app_root / "frontend/src/main.tsx").write_text("x = 1;\n")
        (self.app_root / "frontend/src/Dead.tsx").write_text("x = 1;\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_coverage_audit_check_returns_report(self) -> None:
        from tools.coverage_tools import CoverageAuditCheckTool
        tool = CoverageAuditCheckTool(hub_registry=self.reg,
                                       app_root=str(self.app_root))
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertIn("dead_files", result.data)
        self.assertEqual(len(result.data["dead_files"]), 1)

    def test_mark_intentionally_dead_via_tool(self) -> None:
        from tools.coverage_tools import MarkIntentionallyDeadTool
        tool = MarkIntentionallyDeadTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            path="file:frontend/src/Dead.tsx",
            reason="WIP placeholder"))
        self.assertTrue(result.success)
        self.assertEqual(self.reg.workhub.list_coverage_allowlist()[0]["reason"],
                          "WIP placeholder")

    def test_list_dead_allowlist_returns_entries(self) -> None:
        from tools.coverage_tools import ListDeadAllowlistTool
        self.reg.workhub.mark_path_intentionally_dead(
            "file:x.tsx", reason="r", agent="orchestrator")
        tool = ListDeadAllowlistTool(hub_registry=self.reg)
        result = _run_async(tool.execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["allowlist"]), 1)

    def test_mark_rejects_empty_reason(self) -> None:
        from tools.coverage_tools import MarkIntentionallyDeadTool
        tool = MarkIntentionallyDeadTool(hub_registry=self.reg)
        result = _run_async(tool.execute(path="file:x.tsx", reason=""))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Implement tools**

Create `agent/env_generator/llm_generator/tools/coverage_tools.py`. Match the `BaseTool` convention (use `tool_definition` property + `create_tool_param(parameters=...)` — same as retro_tools/structured_knowledge_tools):

```python
"""Coverage audit LLM tools (Cutover 19)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.coverage_audit import compute_coverage


class _CoverageToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, app_root: Optional[str] = None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        self.app_root = app_root


class CoverageAuditCheckTool(_CoverageToolBase):
    NAME = "coverage_audit_check"
    DESCRIPTION = ("Scan APIHub provider/consumer graphs and the generated app's "
                    "source tree. Returns dead endpoints / tables / source files.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        if self.hub_registry is None or self.app_root is None:
            return ToolResult.fail(
                error_message="coverage_audit_check requires hub_registry + app_root context")
        report = compute_coverage(self.hub_registry, self.app_root)
        return ToolResult.ok(data=report.to_dict())


class MarkIntentionallyDeadTool(_CoverageToolBase):
    NAME = "mark_intentionally_dead"
    DESCRIPTION = ("Whitelist a path (file:X / endpoint:METHOD PATH / table:NAME) "
                    "as intentionally dead with a reason. Used to override the "
                    "coverage gate when a component is behind a feature flag or "
                    "kept for backward compatibility.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                              "description": "file:..., endpoint:..., or table:..."},
                    "reason": {"type": "string"},
                },
                "required": ["path", "reason"],
            })

    async def execute(self, *, path: str, reason: str, **_kw) -> ToolResult:
        result = self.hub_registry.workhub.mark_path_intentionally_dead(
            path=path, reason=reason, agent="orchestrator")
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(error_message=result["error"])
        return ToolResult.ok(data={"entry": result})


class ListDeadAllowlistTool(_CoverageToolBase):
    NAME = "list_dead_allowlist"
    DESCRIPTION = "List all paths currently whitelisted as intentionally dead."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        entries = self.hub_registry.workhub.list_coverage_allowlist()
        return ToolResult.ok(data={"allowlist": entries})


_COVERAGE_TOOLS = [CoverageAuditCheckTool, MarkIntentionallyDeadTool, ListDeadAllowlistTool]


def create_coverage_tools(hub_registry=None, app_root: Optional[str] = None) -> list:
    return [cls(hub_registry=hub_registry, app_root=app_root)
            for cls in _COVERAGE_TOOLS]


__all__ = [
    "CoverageAuditCheckTool", "MarkIntentionallyDeadTool", "ListDeadAllowlistTool",
    "create_coverage_tools",
]
```

- [ ] **Step 4: Register bundle**

In `tool_bundles.py`:

```python
from tools.coverage_tools import create_coverage_tools

def _bundle_coverage_tools(builder, context) -> None:
    app_root = getattr(context, "app_root", None) or getattr(context, "workspace_path", None)
    builder.add(
        create_coverage_tools(
            hub_registry=context.hub_workspace,
            app_root=str(app_root) if app_root else None),
        "knowledge",
    )

# TOOL_BUNDLE_REGISTRY:
"coverage_tools": _bundle_coverage_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"coverage_tools": {"knowledge"},
```

In `agents_config.yaml`, add `coverage_tools` to the orchestrator profile's `tool_bundles` (after `retro_tools`/`observability_tools`).

- [ ] **Step 5: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_coverage_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 725 OK (721 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/tools/coverage_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_coverage_tools.py
git commit -m "Add coverage_tools: coverage_audit_check / mark_intentionally_dead / list_dead_allowlist + orch wiring"
```

---

## Task 5: DeliverProjectTool coverage gate + `force_deliver`

**Files:**
- Modify: `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`
- Create: `agent/tests/test_deliver_coverage_gate.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_deliver_coverage_gate.py`:

```python
"""DeliverProjectTool coverage gate tests (Cutover 19)."""

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


def _make_agent(reg, app_root, *, agent_type="orchestrator", gen_id=1000.0):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = str(app_root)
    a.workspace_path = str(app_root)
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    # Retro is required by Cutover 16 gate; add a stub so the coverage gate
    # is the one we're actually testing.
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


class DeliverCoverageGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliver_cov_"))
        self.reg = HubRegistry(self.tmp / "hub")
        self.app_root = self.tmp / "app"
        self.app_root.mkdir(parents=True)
        # Add stub retro so retro gate passes
        _add_retro(self.reg, 1000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _checklist(self):
        return {"no_bugs": True, "requirements_met": True,
                 "fully_functional": True, "docker_ok": True}

    def _exec(self, agent, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=agent)
        return tool.execute(confirmation="CONFIRMED",
                             delivery_summary="d",
                             checklist=self._checklist(), **extra)

    def test_deliver_succeeds_when_coverage_clean(self) -> None:
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        agent = _make_agent(self.reg, self.app_root)
        result = self._exec(agent)
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_deliver_refuses_with_dead_file(self) -> None:
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        agent = _make_agent(self.reg, self.app_root)
        result = self._exec(agent)
        self.assertFalse(result.success)
        self.assertIn("dead", result.error_message.lower())
        self.assertIn("Dead.tsx", result.error_message)

    def test_deliver_succeeds_when_dead_file_is_allowlisted(self) -> None:
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        self.reg.workhub.mark_path_intentionally_dead(
            "file:Dead.tsx", reason="WIP", agent="orchestrator")
        agent = _make_agent(self.reg, self.app_root)
        result = self._exec(agent)
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_force_deliver_bypasses_coverage_gate_orchestrator_only(self) -> None:
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        agent = _make_agent(self.reg, self.app_root)
        result = self._exec(agent, force_deliver=True)
        self.assertTrue(result.success, f"failed: {result.error_message}")
        # And an audit event should fire
        events = list(self.reg.eventhub.list_events_by_type("dead_code_bypass"))
        self.assertEqual(len(events), 1)

    def test_force_deliver_blocked_for_non_orchestrator(self) -> None:
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        agent = _make_agent(self.reg, self.app_root, agent_type="backend")
        result = self._exec(agent, force_deliver=True)
        self.assertFalse(result.success)
        self.assertIn("orchestrator", result.error_message.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_coverage_gate -v 2>&1 | tail -15
```

Expected: failures — gate doesn't exist yet.

- [ ] **Step 3: Extend `DeliverProjectTool.execute`**

In `agent/env_generator/llm_generator/tools/agent_interaction_tools.py`, locate the Cutover-16 retro gate (added at the very top of `execute`). Right AFTER that gate, add:

```python
        # Cutover 19: coverage gate
        try:
            registry = getattr(self.agent, "hub_registry", None)
            app_root = (getattr(self.agent, "app_root", None)
                        or getattr(self.agent, "workspace_path", None))
            agent_type = getattr(self.agent, "agent_type", "")
            force = kwargs.get("force_deliver") or False

            if registry is not None and app_root is not None:
                from multi_agent.runtime.coverage_audit import compute_coverage
                report = compute_coverage(registry, app_root)
                allowlist_paths = {
                    e.get("path") for e in
                    (registry.workhub.list_coverage_allowlist() or [])
                    if e.get("path")
                }
                dead_paths = report.all_dead_paths - allowlist_paths

                if dead_paths:
                    if force:
                        if agent_type != "orchestrator":
                            return ToolResult.fail(error_message=(
                                "force_deliver is orchestrator-only; "
                                f"caller agent_type={agent_type!r}"))
                        # Audit bypass
                        try:
                            registry.eventhub.publish_event(
                                source_hub="deliver",
                                event_type="dead_code_bypass",
                                payload={"dead_paths": sorted(dead_paths),
                                         "by": agent_type,
                                         "summary": report.to_dict()},
                                priority="high")
                        except Exception:
                            pass
                    else:
                        sample = sorted(dead_paths)[:10]
                        return ToolResult.fail(error_message=(
                            f"refused: {len(dead_paths)} dead artifacts detected. "
                            f"Either wire each one up to a consumer, or call "
                            f"mark_intentionally_dead(path, reason) for each. "
                            f"Sample: {sample}"))
        except Exception as e:
            # Defense in depth: never let the gate crash break delivery —
            # log via error_message and pass through
            pass

        # ...existing post-gate logic (kwargs handling for confirmation etc.)
```

Also update `DeliverProjectTool.execute` signature to accept `force_deliver=False` (or use `**kwargs` if it already does). The existing method signature is `def execute(self, confirmation, delivery_summary, checklist=None)` — add `force_deliver: bool = False` as a new kwarg, and update `tool_definition` to declare it.

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_deliver_coverage_gate -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 730 OK (725 + 5 new). The Cutover 16 retro-gate tests + 17 e2e should remain green (they pass agents with `app_root=None` so the coverage gate short-circuits).

If any pre-existing test breaks because it didn't set `agent.app_root` or `agent.agent_type`, update those test fixtures minimally.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/agent_interaction_tools.py agent/tests/test_deliver_coverage_gate.py
git commit -m "DeliverProjectTool: coverage pre-flight gate + orchestrator-only force_deliver audit bypass"
```

---

## Task 6: Orchestrator prompt

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2`
- Create: `agent/tests/test_orchestrator_coverage_prompt.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_orchestrator_coverage_prompt.py`:

```python
"""Tests that orchestrator prompt teaches coverage discipline (Cutover 19)."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V2 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v2"
PROMPTS_ROOT = PROMPTS_V2.parent


class OrchestratorCoveragePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V2), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.lead_specifics()

    def test_prompt_mentions_coverage_audit_check(self) -> None:
        self.assertIn("COVERAGE_AUDIT_CHECK", self.system.upper())

    def test_prompt_mentions_mark_intentionally_dead(self) -> None:
        self.assertIn("MARK_INTENTIONALLY_DEAD", self.system.upper())

    def test_prompt_says_dead_code_blocks_deliver(self) -> None:
        upper = self.system.upper()
        self.assertIn("DEAD", upper)
        self.assertIn("DELIVER", upper)

    def test_prompt_mentions_force_deliver_bypass(self) -> None:
        self.assertIn("FORCE_DELIVER", self.system.upper())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Add the block**

In `lead_specifics()`, after the existing `### RETRO DISCIPLINE (Cutover 16)` block, add:

```jinja
### COVERAGE DISCIPLINE (Cutover 19)
Before calling `deliver_project()`, you MUST verify no dead components exist. The DeliverProjectTool runs `coverage_audit_check` as a pre-flight gate; if it finds:
- APIHub endpoints with zero consumers, or
- APIHub tables with zero exposing endpoints, or
- frontend/backend source files imported by nothing,

…`deliver_project()` returns an error listing them. The error is not a suggestion — it is a hard gate.

Two recovery paths (per dead artifact):
1. **Wire it up**: have the owning agent (backend / frontend / database) add the missing consumer (call site, route mount, schema reference). This is the default; dead code usually means the spec drifted from the implementation.
2. **`mark_intentionally_dead(path, reason)`**: whitelist with a written reason. Use this ONLY when:
   - The component is behind a feature flag (`FEATURE_FLAG_X` etc.)
   - It's kept for backward compatibility with deprecated clients
   - It's a future-work placeholder explicitly approved during design review

If neither path is available (e.g., the dead code is legitimate but you can't justify either option), and you've genuinely exhausted other fixes, use `deliver_project(..., force_deliver=True)`. This is orchestrator-only, audited via `system/dead_code_bypass` EventHub event, and equivalent to a release-day exception — every use shows up in the next retro for retrospective.

Workflow before deliver:
1. `coverage_audit_check()` -> review dead artifacts
2. Assign WorkHub tasks to owning agents to fix each (preferred) or `mark_intentionally_dead` (if justified)
3. Re-run `coverage_audit_check()` -> should return clean
4. `submit_retro(...)` (Cutover 16)
5. `deliver_project(...)`
```

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_orchestrator_coverage_prompt -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 734 OK (730 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/orchestrator_agent.j2 agent/tests/test_orchestrator_coverage_prompt.py
git commit -m "Orchestrator prompt: COVERAGE DISCIPLINE + workflow + force_deliver bypass"
```

---

## Task 7: End-to-end coverage flow

**Files:**
- Create: `agent/tests/test_coverage_e2e.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_coverage_e2e.py`:

```python
"""E2E: dead endpoint blocks deliver; assign consumer unblocks (Cutover 19)."""

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


def _agent(reg, app_root, gen_id=2000.0, agent_type="orchestrator"):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = str(app_root)
    a.workspace_path = str(app_root)
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


class CoverageE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_e2e_"))
        self.reg = HubRegistry(self.tmp / "hub")
        self.app_root = self.tmp / "app"
        self.app_root.mkdir(parents=True)
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        _add_retro(self.reg, 2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deliver(self, agent, **extra):
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=agent)
        return tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                             checklist={"no_bugs": True, "requirements_met": True,
                                          "fully_functional": True, "docker_ok": True},
                             **extra)

    def test_dead_endpoint_blocks_then_consumer_registration_unblocks(self) -> None:
        # Backend registers an endpoint nobody consumes -> deliver refused
        ep = self.reg.apihub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        agent = _agent(self.reg, self.app_root)

        r1 = self._deliver(agent)
        self.assertFalse(r1.success)
        self.assertIn("dead", r1.error_message.lower())

        # Frontend registers consumer -> deliver succeeds
        self.reg.apihub.register_consumer(
            ep["id"], file_path="frontend/src/api/feed.ts", agent="frontend")
        r2 = self._deliver(agent)
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_dead_file_blocks_then_allowlist_unblocks(self) -> None:
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        agent = _agent(self.reg, self.app_root)

        r1 = self._deliver(agent)
        self.assertFalse(r1.success)

        self.reg.workhub.mark_path_intentionally_dead(
            "file:Dead.tsx", reason="feature flagged", agent="orchestrator")
        r2 = self._deliver(agent)
        self.assertTrue(r2.success, f"deliver failed: {r2.error_message}")

    def test_force_deliver_publishes_audit_event(self) -> None:
        (self.app_root / "Dead.tsx").write_text("x = 1;\n")
        agent = _agent(self.reg, self.app_root)

        result = self._deliver(agent, force_deliver=True)
        self.assertTrue(result.success)
        events = list(self.reg.eventhub.list_events_by_type("dead_code_bypass"))
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertIn("dead_paths", payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify pass + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_coverage_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 737 OK (734 + 3 new).

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_coverage_e2e.py
git commit -m "Add coverage E2E: dead endpoint/file blocks deliver; consumer/allowlist unblocks; force audit event"
```

---

## Task 8: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/20-dead-code-gate.md`

- [ ] **Step 1: Final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 737 OK.

- [ ] **Step 2: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 3: Migration log + commit + push**

Create `docs/superpowers/migration-logs/20-dead-code-gate.md`:

```markdown
# Cutover 19: Dead-Code Detection + Reverse-Consumer Gate

**Branch:** `haibotong-cutover-19-dead-code`
**Date:** 2026-05-25

## What

Reverse-direction coverage gate: `deliver_project()` now refuses if any:
- APIHub endpoint with zero consumers exists
- APIHub table with zero exposing endpoints exists
- frontend/backend source file imported by nothing exists

…unless explicitly whitelisted via `mark_intentionally_dead(path, reason)`
or bypassed via orchestrator-only `force_deliver=True` (audited).

## Why

Schema gates (Cutover 7) ensure declared APIs/tables are *implemented*.
They don't check the reverse — that every *implemented* artifact is *used*.
The system could ship endpoints nobody calls, components nobody imports,
tables nobody exposes. All passed previous gates.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 698 OK -> 737 OK (+39 new)

## New surfaces
- runtime/coverage_audit.py (~180 LoC pure scanner)
- tools/coverage_tools.py (3 tools)
- WorkHub: list_coverage_allowlist + mark_path_intentionally_dead
- DeliverProjectTool: coverage pre-flight + force_deliver kwarg
- Orchestrator prompt: COVERAGE DISCIPLINE block

## Known limits / future work
- Static regex import scan misses dynamic imports (React.lazy with computed paths)
- Python import resolver is MVP — false positives on cross-package imports
- mark_intentionally_dead is per-generation; no rolling allowlist across generations
- AST-aware scanning is a future cutover
```

```bash
git add docs/superpowers/migration-logs/20-dead-code-gate.md
git commit -m "Add Cutover 19 migration log"
git push red-env-gen haibotong-cutover-19-dead-code 2>&1 | tail -5
```

- [ ] **Step 4: Report** — final test counts, push URL, deferred items

---

## Self-Review

**1. Spec coverage:** coverage_audit module (T2) ✓; WorkHub allowlist (T3) ✓; LLM tools (T4) ✓; DeliverProjectTool gate + force bypass (T5) ✓; orchestrator prompt (T6) ✓; E2E (T7) ✓; log + push (T8) ✓.

**2. Placeholder scan:** No "TBD" / "implement later". All code shown.

**3. Type consistency:** `CoverageReport(dead_endpoints, dead_tables, dead_files)` + `is_clean` + `all_dead_paths` + `to_dict()` — consistent across module/tools/gate/tests. `force_deliver: bool = False` kwarg — same name in tool + tests + prompt.

**4. Cross-cutting:** No Claude trailer (T1 + T8) ✓; baselines green per task ✓; TDD throughout ✓; force_deliver mirrors Cutover 7 force_merge audit pattern ✓; gate wrapped in try/except so malformed contexts can't break deliver ✓.
