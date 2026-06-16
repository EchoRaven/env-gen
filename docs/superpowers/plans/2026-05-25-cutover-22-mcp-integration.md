# Cutover 22: MCP Integration (APIHub Registration + RunHub Probe)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Treat MCP servers/tools as first-class registered resources on APIHub (mirroring `register_endpoint` / `register_table`). RunHub probes declared MCP servers (stdio liveness or HTTP reach) during runs and publishes `runhub/run_failed` events for failed probes — the existing BugTriageOrchestrator chain (Cutover 10-12) auto-routes them to the owning agent (backend). Dead MCP tools (registered, no consumer) are caught by the existing coverage gate (Cutover 19).

**Architecture:** Backend agent owns MCP — both server implementation and registration. APIHub gains `register_mcp_server(name, transport, endpoint, provider, agent)` + `register_mcp_tool(server_name, tool_name, schema, provider, agent)` + `register_mcp_consumer(server_name, tool_name, file_path, agent)`. Stored on a single new `_mcp_registry` JsonStore. RunHub's `start_run` extended with `_probe_mcp_servers` step (after the existing HTTP probe loop, before `down()`). Failed probes emit `run_failed` events with `affected_mcp_server` / `affected_mcp_tool` in `bug_artifacts` — BugTriageOrch resolver picks them up via `owner_hint` field. Coverage audit (Cutover 19) extended to flag MCP tools with no registered consumer.

**Tech Stack:** Python 3.11 (`/home/haibotong/miniconda3/envs/dt/bin/python`), unittest. Pure stdlib (`subprocess`, `socket`, existing `httpx`/urllib via Cutover 11 helpers).

---

## Context for Worker

### Why this cutover exists

The user requirement "具有 MCP" had zero mechanical enforcement. Today:
- Backend can implement an MCP server that nobody invokes — coverage gate doesn't catch it (Cutover 19 only scans HTTP endpoints / DB tables)
- RunHub HTTP probe (Cutover 11) doesn't speak MCP; a broken MCP server passes the deliver gate
- Frontend can `call_mcp_tool('filesystem.read')` against an undeclared MCP server with no schema verification

After this cutover:
- Backend MUST `register_mcp_server` + `register_mcp_tool` for each MCP capability shipped
- Frontend (or any consumer) MUST `register_mcp_consumer(server_name, tool_name, file_path)` per usage
- RunHub probes every registered MCP server; failures route to BugTriageOrch automatically
- Coverage gate refuses deliver if any MCP tool has zero consumers (mirrors Cutover 19 endpoint check)

### Resource model

Single `_mcp_registry` JsonStore. Keys are `mcp:<scope>:<name>` so we can co-locate servers + tools + consumers cleanly:

```python
{
    # Server registration
    "mcp:server:filesystem": {
        "kind": "server",
        "name": "filesystem",
        "transport": "stdio",            # stdio | http | sse | websocket
        "endpoint": "./bin/mcp-fs",      # binary path for stdio; URL for http
        "provider": "backend",
        "status": "defined",
        "registered_at": <epoch>,
    },
    # Tool registration (associated with a server)
    "mcp:tool:filesystem:read_file": {
        "kind": "tool",
        "server_name": "filesystem",
        "tool_name": "read_file",
        "schema": {"input": {...}, "output": {...}},
        "provider": "backend",
        "status": "defined",
    },
    # Consumer registration
    "mcp:consumer:filesystem:read_file:frontend/src/api/fs.ts": {
        "kind": "consumer",
        "server_name": "filesystem",
        "tool_name": "read_file",
        "file_path": "frontend/src/api/fs.ts",
        "agent": "frontend",
    },
}
```

### RunHub MCP probe semantics (MVP — keep simple)

For each registered MCP server with `status == "defined"`:

- **stdio transport**: spawn `endpoint` as subprocess with stdin/stdout. Wait 2 seconds (configurable). If process exits with non-zero in that window → fail (server crashed on startup). If still running after 2s → pass (basic liveness only — full handshake is a future enhancement).
- **http / sse transport**: HEAD/GET request to `endpoint`. 2xx/3xx → pass. 4xx/5xx/timeout/refused → fail (reusing Cutover 11 `_ssrf_check` + httpx).
- **websocket**: SKIP for MVP (return `skipped: websocket_not_supported`).

Each failed probe publishes `runhub/run_failed` event with:
```python
{
    "source": "runhub",
    "severity": "P1",
    "title": f"MCP server '{name}' failed {transport} liveness probe",
    "bug_artifacts": {
        "affected_mcp_server": name,
        "transport": transport,
        "expected": "reachable",
        "actual": <failure detail>,
        "run_id": run_id,
        "branch": branch,
        "owner_hint": provider,   # routes to backend via BugTriageOrch
    },
}
```

### Coverage gate extension

`runtime/coverage_audit.py` gains `scan_dead_mcp_tools(hub_registry)`:
- For each registered tool with `status == "defined"`, check if any `consumer` entry exists for that `(server_name, tool_name)`
- If none → flag as `dead_mcp_tool`

Added to `CoverageReport.dead_mcp_tools` field. Existing deliver gate (Cutover 19) naturally includes it via `all_dead_paths`.

### Out of scope (deferred)

- **Full MCP protocol handshake**: parse JSON-RPC `initialize`/`tools/list` responses. MVP just does liveness/reachability.
- **WebSocket transport probing**: skipped with `skipped: websocket_not_supported`
- **MCP resource probing**: only tools today, not `resources`/`prompts` capabilities
- **Schema validation against actual tool responses**: registered schema is informational only

### Conventions (inherited)

- Python: `/home/haibotong/miniconda3/envs/dt/bin/python` (dt env)
- No Claude trailer; no emojis
- TDD throughout; bite-sized commits; no push until Task 8
- Both baselines green at every task boundary: regressions 7 OK; discover 829 OK after Cutover 21

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/tools/mcp_registry_tools.py` — 5 LLM tools
- `agent/tests/test_apihub_mcp_registry.py`
- `agent/tests/test_runhub_mcp_probe.py`
- `agent/tests/test_mcp_registry_tools.py`
- `agent/tests/test_coverage_audit_mcp.py`
- `agent/tests/test_mcp_e2e.py`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — add `_mcp_registry` JsonStore + 6 helpers (register_mcp_server / register_mcp_tool / register_mcp_consumer / get_mcp_servers / get_mcp_tools / get_mcp_consumers)
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py` — add `_probe_mcp_servers` step in `start_run`; default probe runner for MCP transports
- `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py` — add `scan_dead_mcp_tools` + extend `CoverageReport.dead_mcp_tools`
- `agent/env_generator/llm_generator/multi_agent/tool_bundles.py` — register `mcp_registry_tools` bundle
- `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml` — wire `mcp_registry_tools` to backend + frontend + orchestrator
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2` — MCP REGISTRATION DISCIPLINE block
- `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2` — MCP CONSUMER REGISTRATION block

---

## Task 1: Worktree + baseline + recon

**Files:**
- Create: `docs/superpowers/cutover-22-baseline.md`

- [ ] **Step 1: Verify worktree**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-22-mcp
git status
git log --oneline -3
```

If missing: `git worktree add -b haibotong-cutover-22-mcp .worktrees/haibotong-cutover-22-mcp haibotong-0521-pipeline-web-tools` from repo root.

- [ ] **Step 2: Baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 829 OK.

- [ ] **Step 3: Confirm RunHub probe anchor**

```bash
grep -nE "_publish_run_failed|_list_apihub_endpoints|def start_run" agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py | head -5
```

Note: line where the HTTP probe loop ends. Task 3 inserts MCP probe step immediately after.

- [ ] **Step 4: Confirm CoverageReport anchor**

```bash
grep -nE "class CoverageReport|dead_endpoints|dead_tables|all_dead_paths" agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py | head -10
```

Task 5 extends `CoverageReport` with `dead_mcp_tools` field and `all_dead_paths` to include `mcp_tool:<server>:<tool>`.

- [ ] **Step 5: Baseline note + commit**

Create `docs/superpowers/cutover-22-baseline.md`:

```markdown
# Cutover 22 Baseline (MCP Integration)

## Test counts
- regressions: 7 OK
- discover: 829 OK

## Gap this cutover closes
No mechanical enforcement of "具有 MCP". Backend can ship a broken MCP
server; RunHub HTTP probe doesn't speak MCP; coverage gate doesn't catch
unused MCP tools.

## Approach
- Backend owns MCP. APIHub registers MCP server/tool/consumer (mirror endpoint).
- RunHub probes each declared MCP server (stdio liveness or HTTP reach) post-run.
- Failed probe -> runhub/run_failed -> BugTriageOrch -> backend (existing chain).
- Coverage gate (Cutover 19) extended: registered MCP tool without consumer = dead.
- Force-deliver bypass reuses Cutover 19/20/21 pattern (mcp_audit_bypass event).

## Out of scope
- Full MCP protocol handshake (just liveness)
- WebSocket transport probe (skipped)
- Schema validation against tool responses
```

```bash
git add docs/superpowers/cutover-22-baseline.md
git commit -m "Cutover 22: record pre-flight baseline (regressions 7 OK, discover 829 OK)"
```

---

## Task 2: APIHub MCP registration

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`
- Create: `agent/tests/test_apihub_mcp_registry.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_apihub_mcp_registry.py`:

```python
"""Tests for APIHub MCP registry helpers (Cutover 22)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class APIHubMCPServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_server_stores_record(self) -> None:
        record = self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend", agent="backend")
        self.assertEqual(record["name"], "filesystem")
        self.assertEqual(record["transport"], "stdio")
        self.assertEqual(record["provider"], "backend")

    def test_register_mcp_server_rejects_unknown_transport(self) -> None:
        result = self.reg.apihub.register_mcp_server(
            name="x", transport="carrier_pigeon",
            endpoint="x", provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_register_mcp_server_rejects_empty_name(self) -> None:
        result = self.reg.apihub.register_mcp_server(
            name="", transport="stdio",
            endpoint="x", provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_get_mcp_servers_returns_all(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="fs", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.apihub.register_mcp_server(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend", agent="backend")
        servers = self.reg.apihub.get_mcp_servers()
        self.assertEqual(set(servers.keys()), {"fs", "git"})


class APIHubMCPToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_tool_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_tool_stores_record(self) -> None:
        record = self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={"input": {"path": "string"}, "output": {"content": "string"}},
            provider="backend", agent="backend")
        self.assertEqual(record["server_name"], "filesystem")
        self.assertEqual(record["tool_name"], "read_file")

    def test_register_mcp_tool_requires_server_to_exist(self) -> None:
        result = self.reg.apihub.register_mcp_tool(
            server_name="nonexistent", tool_name="x",
            schema={}, provider="backend", agent="backend")
        self.assertIn("error", result)

    def test_get_mcp_tools_filters_by_server(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="git", transport="stdio", endpoint="./git",
            provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="git", tool_name="status",
            schema={}, provider="backend", agent="backend")
        fs_tools = self.reg.apihub.get_mcp_tools(server_name="filesystem")
        self.assertEqual(len(fs_tools), 1)
        self.assertEqual(list(fs_tools.values())[0]["tool_name"], "read_file")

    def test_get_mcp_tools_no_filter_returns_all(self) -> None:
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="write_file",
            schema={}, provider="backend", agent="backend")
        all_tools = self.reg.apihub.get_mcp_tools()
        self.assertEqual(len(all_tools), 2)


class APIHubMCPConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="api_mcp_cons_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_mcp_consumer_stores_record(self) -> None:
        record = self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts", agent="frontend")
        self.assertEqual(record["server_name"], "filesystem")
        self.assertEqual(record["tool_name"], "read_file")
        self.assertEqual(record["file_path"], "frontend/src/api/fs.ts")

    def test_register_consumer_requires_tool_to_exist(self) -> None:
        result = self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="nonexistent",
            file_path="x.ts", agent="frontend")
        self.assertIn("error", result)

    def test_get_mcp_consumers_filters_by_server_and_tool(self) -> None:
        self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="a.ts", agent="frontend")
        self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="b.ts", agent="frontend")
        consumers = self.reg.apihub.get_mcp_consumers(
            server_name="filesystem", tool_name="read_file")
        self.assertEqual(len(consumers), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_mcp_registry -v 2>&1 | tail -15
```

Expected: AttributeError on `register_mcp_server` etc.

- [ ] **Step 3: Add MCP registry to APIHub**

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`:

**(a)** Add JsonStore in `__init__`, after `_seed_registrations`:

```python
        self._mcp_registry = JsonStore(self.hub_dir / "apihub_mcp_registry.json")
```

**(b)** Add `_mcp_registry` to `ensure_documents()` list (find the existing list and append).

**(c)** Add the 6 new helpers (place after `list_seed_registrations` from Cutover 21):

```python
    _VALID_MCP_TRANSPORTS = {"stdio", "http", "sse", "websocket"}

    def register_mcp_server(self, name: str, transport: str, endpoint: str,
                              provider: str = "", agent: str = "",
                              status: str = "defined") -> dict:
        if not isinstance(name, str) or not name.strip():
            return {"error": "server name must be non-empty"}
        if transport not in self._VALID_MCP_TRANSPORTS:
            return {"error": f"transport must be one of {sorted(self._VALID_MCP_TRANSPORTS)}"}
        key = f"mcp:server:{name}"
        now = time.time()
        record = {
            "kind": "server",
            "name": name, "transport": transport, "endpoint": endpoint,
            "provider": provider, "status": status,
            "_updated_by": agent, "_updated_at": now,
        }
        self._mcp_registry.update(lambda m: m.set(key, record, agent),
                                    change_info={"agent": agent})
        self._emit("mcp_server_registered", record, recipients=[])
        return record

    def get_mcp_servers(self) -> Dict[str, dict]:
        return {
            v["name"]: v
            for v in (self._mcp_registry.value() or {}).values()
            if v.get("kind") == "server"
        }

    def register_mcp_tool(self, server_name: str, tool_name: str,
                            schema: dict = None, provider: str = "",
                            agent: str = "", status: str = "defined") -> dict:
        if server_name not in self.get_mcp_servers():
            return {"error": f"mcp server not registered: {server_name!r} "
                              f"(call register_mcp_server first)"}
        if not isinstance(tool_name, str) or not tool_name.strip():
            return {"error": "tool_name must be non-empty"}
        key = f"mcp:tool:{server_name}:{tool_name}"
        now = time.time()
        record = {
            "kind": "tool",
            "server_name": server_name, "tool_name": tool_name,
            "schema": schema or {}, "provider": provider, "status": status,
            "_updated_by": agent, "_updated_at": now,
        }
        self._mcp_registry.update(lambda m: m.set(key, record, agent),
                                    change_info={"agent": agent})
        self._emit("mcp_tool_registered", record, recipients=[])
        return record

    def get_mcp_tools(self, server_name: str = None) -> Dict[str, dict]:
        out = {}
        for k, v in (self._mcp_registry.value() or {}).items():
            if v.get("kind") != "tool":
                continue
            if server_name is not None and v.get("server_name") != server_name:
                continue
            out[k] = v
        return out

    def register_mcp_consumer(self, server_name: str, tool_name: str,
                                file_path: str, agent: str = "") -> dict:
        tool_key = f"mcp:tool:{server_name}:{tool_name}"
        if tool_key not in (self._mcp_registry.value() or {}):
            return {"error": f"mcp tool not registered: {server_name}/{tool_name}"}
        key = f"mcp:consumer:{server_name}:{tool_name}:{file_path}:{agent}"
        now = time.time()
        record = {
            "kind": "consumer",
            "server_name": server_name, "tool_name": tool_name,
            "file_path": file_path, "agent": agent,
            "_updated_by": agent, "_updated_at": now,
        }
        self._mcp_registry.update(lambda m: m.set(key, record, agent),
                                    change_info={"agent": agent})
        return record

    def get_mcp_consumers(self, server_name: str = None,
                            tool_name: str = None) -> List[dict]:
        out = []
        for v in (self._mcp_registry.value() or {}).values():
            if v.get("kind") != "consumer":
                continue
            if server_name is not None and v.get("server_name") != server_name:
                continue
            if tool_name is not None and v.get("tool_name") != tool_name:
                continue
            out.append(v)
        return out
```

- [ ] **Step 4: Verify 11 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_apihub_mcp_registry -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 11 OK; 7 OK / 840 OK (829 + 11 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/apihub.py agent/tests/test_apihub_mcp_registry.py
git commit -m "APIHub: add register_mcp_server / register_mcp_tool / register_mcp_consumer + 3 getters"
```

---

## Task 3: RunHub MCP probe

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`
- Create: `agent/tests/test_runhub_mcp_probe.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_runhub_mcp_probe.py`:

```python
"""Tests for RunHub MCP probe step (Cutover 22)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402


class _FakeCompose:
    def __init__(self):
        self.up_called = False
        self.down_called = False
    def up(self, timeout=180.0):
        self.up_called = True
        return ComposeResult(returncode=0, stdout="up ok")
    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _FakeHealthyHC:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.05)


def _stdio_probe_factory(crash_servers=None):
    """Returns a fake stdio probe that crashes for any name in crash_servers."""
    crash_servers = crash_servers or set()
    def _probe(server):
        if server["name"] in crash_servers:
            return {"healthy": False, "detail": "process exited rc=1"}
        return {"healthy": True, "detail": "alive after 2s"}
    return _probe


def _http_probe_factory(unhealthy_servers=None):
    unhealthy_servers = unhealthy_servers or set()
    def _probe(server):
        if server["name"] in unhealthy_servers:
            return {"healthy": False, "detail": "connection refused"}
        return {"healthy": True, "detail": "HTTP 200"}
    return _probe


def _passing_http_probe(plan):
    return {"status_code": 200, "body_excerpt": "ok",
            "transport_error": None, "latency_ms": 5.0}


class RunHubMCPProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="runhub_mcp_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_mcp_servers_no_probes(self) -> None:
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe)
        # No MCP probes section in run record
        self.assertEqual(run.get("mcp_probes", []), [])

    def test_registered_stdio_server_probed_healthy(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["server"], "filesystem")
        self.assertEqual(mcp_probes[0]["verdict"], "pass")

    def test_crashed_stdio_server_publishes_run_failed(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(crash_servers={"filesystem"}),
            mcp_http_probe=_http_probe_factory())
        events = list(self.reg.eventhub.list_events_by_type("run_failed"))
        mcp_failures = [
            e for e in events
            if (e.get("payload") or {}).get("bug_artifacts", {}).get("affected_mcp_server")
        ]
        self.assertEqual(len(mcp_failures), 1)
        artifacts = mcp_failures[0]["payload"]["bug_artifacts"]
        self.assertEqual(artifacts["affected_mcp_server"], "filesystem")
        self.assertEqual(artifacts["transport"], "stdio")
        self.assertEqual(artifacts["owner_hint"], "backend")

    def test_http_transport_uses_http_probe(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["transport"], "http")
        self.assertEqual(mcp_probes[0]["verdict"], "pass")

    def test_websocket_transport_skipped(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="ws_server", transport="websocket", endpoint="ws://localhost:9001",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(),
            mcp_http_probe=_http_probe_factory())
        mcp_probes = run.get("mcp_probes", [])
        self.assertEqual(len(mcp_probes), 1)
        self.assertEqual(mcp_probes[0]["verdict"], "skipped")

    def test_run_status_failed_when_mcp_fails(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        run = self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=_stdio_probe_factory(crash_servers={"filesystem"}),
            mcp_http_probe=_http_probe_factory())
        self.assertEqual(run["status"], "failed")
        self.assertGreaterEqual(run["fail_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_mcp_probe -v 2>&1 | tail -15
```

Expected: AttributeError or TypeError on the missing `mcp_*_probe` kwargs.

- [ ] **Step 3: Extend `RunHub.start_run` with MCP probe step**

In `agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py`:

**(a)** Extend `start_run` signature to accept `mcp_stdio_probe=None, mcp_http_probe=None`:

```python
    def start_run(self, *,
                   branch: str,
                   generated_dir: str,
                   base_url: str,
                   agent: str = "",
                   compose: Any = None,
                   healthcheck: Any = None,
                   probe_runner: Any = None,
                   mcp_stdio_probe: Any = None,
                   mcp_http_probe: Any = None,
                   timeout_s: int = 300) -> dict:
```

**(b)** After the existing HTTP probe loop (find the `for ep in endpoints:` loop in `start_run`), and BEFORE the final status-update + `down()` block, insert the MCP probe step:

```python
            # Cutover 22: MCP server probes
            mcp_probes: list = []
            mcp_stdio = mcp_stdio_probe or self._default_mcp_stdio_probe()
            mcp_http = mcp_http_probe or self._default_mcp_http_probe()
            mcp_servers = self._list_apihub_mcp_servers()
            for server in mcp_servers:
                transport = server.get("transport") or "stdio"
                verdict_record = {
                    "server": server["name"],
                    "transport": transport,
                    "endpoint": server.get("endpoint"),
                    "provider": server.get("provider"),
                }
                if transport == "websocket":
                    verdict_record["verdict"] = "skipped"
                    verdict_record["reason"] = "websocket_not_supported"
                    mcp_probes.append(verdict_record)
                    continue
                if transport == "stdio":
                    raw = mcp_stdio(server)
                elif transport in ("http", "sse"):
                    raw = mcp_http(server)
                else:
                    verdict_record["verdict"] = "skipped"
                    verdict_record["reason"] = f"unknown_transport:{transport}"
                    mcp_probes.append(verdict_record)
                    continue
                healthy = bool(raw.get("healthy"))
                verdict_record["verdict"] = "pass" if healthy else "fail"
                verdict_record["detail"] = raw.get("detail")
                mcp_probes.append(verdict_record)
                if not healthy:
                    fail_count += 1
                    self._publish_mcp_failure(run_id, branch, server, raw)
```

Update the final status / persist block to include `mcp_probes`:

```python
            final_status = "failed" if fail_count > 0 else "completed"
            self.update_run_status(run_id, final_status, agent="runhub",
                                    probes=probes, fail_count=fail_count,
                                    mcp_probes=mcp_probes)
```

**(c)** Add helper methods on `RunHub`:

```python
    def _list_apihub_mcp_servers(self) -> list:
        if self.apihub is None or not hasattr(self.apihub, "get_mcp_servers"):
            return []
        return [s for s in (self.apihub.get_mcp_servers() or {}).values()
                if s.get("status") == "defined"]

    def _publish_mcp_failure(self, run_id: str, branch: str,
                                server: dict, raw: dict) -> None:
        if self.eventhub is None:
            return
        payload = {
            "source": "runhub",
            "severity": "P1",
            "title": (f"MCP server {server['name']!r} failed "
                       f"{server.get('transport')} liveness probe"),
            "bug_artifacts": {
                "affected_mcp_server": server["name"],
                "transport": server.get("transport"),
                "endpoint": server.get("endpoint"),
                "expected": "reachable",
                "actual": raw.get("detail"),
                "run_id": run_id,
                "branch": branch,
                "owner_hint": server.get("provider"),
            },
        }
        self.eventhub.publish_event(
            source_hub="runhub", event_type="run_failed",
            payload=payload, priority="high")

    def _default_mcp_stdio_probe(self):
        import subprocess
        import time as _time
        def _probe(server):
            cmd = server.get("endpoint")
            if not cmd:
                return {"healthy": False, "detail": "no endpoint configured"}
            try:
                proc = subprocess.Popen(
                    cmd if isinstance(cmd, list) else cmd.split(),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                _time.sleep(2.0)  # liveness window
                if proc.poll() is not None:
                    return {"healthy": False,
                            "detail": f"process exited rc={proc.returncode}"}
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return {"healthy": True, "detail": "alive after 2s"}
            except FileNotFoundError:
                return {"healthy": False, "detail": f"binary not found: {cmd}"}
            except Exception as e:
                return {"healthy": False, "detail": f"spawn failed: {e}"}
        return _probe

    def _default_mcp_http_probe(self):
        def _probe(server):
            endpoint = server.get("endpoint")
            if not endpoint:
                return {"healthy": False, "detail": "no endpoint configured"}
            try:
                import httpx
                resp = httpx.get(endpoint, timeout=5.0)
                if 200 <= resp.status_code < 400:
                    return {"healthy": True, "detail": f"HTTP {resp.status_code}"}
                return {"healthy": False,
                        "detail": f"HTTP {resp.status_code}"}
            except Exception as e:
                return {"healthy": False, "detail": f"transport: {e}"}
        return _probe
```

- [ ] **Step 4: Verify 6 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_runhub_mcp_probe -v 2>&1 | tail -15
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 6 OK; 7 OK / 846 OK (840 + 6 new).

If existing RunHub tests break because `start_run` now requires `mcp_*_probe` kwargs to be optional and the tests pass extra args, that's the expected design — they should NOT have to pass MCP probes; defaults should kick in only when MCP servers exist (and existing tests have no MCP servers, so probes skip).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/runhub/service.py agent/tests/test_runhub_mcp_probe.py
git commit -m "RunHub: MCP probe step (stdio liveness + HTTP reach) -> run_failed events on failure"
```

---

## Task 4: MCP LLM tools

**Files:**
- Create: `agent/env_generator/llm_generator/tools/mcp_registry_tools.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/tool_bundles.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml`
- Create: `agent/tests/test_mcp_registry_tools.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_mcp_registry_tools.py`:

```python
"""Tests for MCP registry LLM tools (Cutover 22)."""

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


class MCPRegistryToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp_tools_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_server_tool(self) -> None:
        from tools.mcp_registry_tools import RegisterMCPServerTool
        tool = RegisterMCPServerTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            name="filesystem", transport="stdio",
            endpoint="./bin/mcp-fs", provider="backend"))
        self.assertTrue(result.success)
        self.assertEqual(result.data["server"]["name"], "filesystem")

    def test_register_tool_requires_server(self) -> None:
        from tools.mcp_registry_tools import RegisterMCPToolTool
        tool = RegisterMCPToolTool(hub_registry=self.reg)
        result = _run_async(tool.execute(
            server_name="missing", tool_name="x",
            schema={}, provider="backend"))
        self.assertFalse(result.success)

    def test_register_consumer_full_flow(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, RegisterMCPToolTool, RegisterMCPConsumerTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend"))
        result = _run_async(RegisterMCPConsumerTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts"))
        self.assertTrue(result.success)

    def test_list_servers_tool(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, ListMCPServersTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="fs", transport="stdio", endpoint="./fs", provider="backend"))
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="git", transport="http", endpoint="http://localhost:9000",
            provider="backend"))
        result = _run_async(ListMCPServersTool(hub_registry=self.reg).execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["servers"]), 2)

    def test_list_tools_tool(self) -> None:
        from tools.mcp_registry_tools import (
            RegisterMCPServerTool, RegisterMCPToolTool, ListMCPToolsTool,
        )
        _run_async(RegisterMCPServerTool(hub_registry=self.reg).execute(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend"))
        _run_async(RegisterMCPToolTool(hub_registry=self.reg).execute(
            server_name="filesystem", tool_name="write_file",
            schema={}, provider="backend"))
        result = _run_async(ListMCPToolsTool(hub_registry=self.reg).execute(
            server_name="filesystem"))
        self.assertEqual(len(result.data["tools"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement tools**

Create `agent/env_generator/llm_generator/tools/mcp_registry_tools.py`. Match `BaseTool` convention (same as seed_tools / coverage_tools):

```python
"""MCP registry LLM tools (Cutover 22)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param


class _MCPToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterMCPServerTool(_MCPToolBase):
    NAME = "mcp_register_server"
    DESCRIPTION = ("Register an MCP server (backend agent uses this). "
                    "transport: stdio | http | sse | websocket. "
                    "endpoint: binary path for stdio, URL for http/sse.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "transport": {"type": "string",
                                    "enum": ["stdio", "http", "sse", "websocket"]},
                    "endpoint": {"type": "string"},
                    "provider": {"type": "string", "default": "backend"},
                },
                "required": ["name", "transport", "endpoint"],
            }, required=["name", "transport", "endpoint"])

    async def execute(self, *, name: str, transport: str, endpoint: str,
                       provider: str = "backend", **_kw) -> ToolResult:
        record = self.hub_registry.apihub.register_mcp_server(
            name=name, transport=transport, endpoint=endpoint,
            provider=provider,
            agent=getattr(self, "_agent_id", None) or provider)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"server": record})


class RegisterMCPToolTool(_MCPToolBase):
    NAME = "mcp_register_tool"
    DESCRIPTION = ("Register an MCP tool exposed by a server. Backend agent "
                    "calls this for each tool the MCP server provides.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "schema": {"type": "object",
                                "description": "input/output schema"},
                    "provider": {"type": "string", "default": "backend"},
                },
                "required": ["server_name", "tool_name", "schema"],
            }, required=["server_name", "tool_name", "schema"])

    async def execute(self, *, server_name: str, tool_name: str,
                       schema: dict, provider: str = "backend", **_kw) -> ToolResult:
        record = self.hub_registry.apihub.register_mcp_tool(
            server_name=server_name, tool_name=tool_name,
            schema=schema, provider=provider,
            agent=getattr(self, "_agent_id", None) or provider)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"tool": record})


class RegisterMCPConsumerTool(_MCPToolBase):
    NAME = "mcp_register_consumer"
    DESCRIPTION = ("Register that a file consumes an MCP tool. Consumer agents "
                    "(typically frontend) call this per-usage.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "file_path": {"type": "string"},
                },
                "required": ["server_name", "tool_name", "file_path"],
            }, required=["server_name", "tool_name", "file_path"])

    async def execute(self, *, server_name: str, tool_name: str,
                       file_path: str, **_kw) -> ToolResult:
        agent = getattr(self, "_agent_id", None) or "frontend"
        record = self.hub_registry.apihub.register_mcp_consumer(
            server_name=server_name, tool_name=tool_name,
            file_path=file_path, agent=agent)
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"consumer": record})


class ListMCPServersTool(_MCPToolBase):
    NAME = "mcp_list_servers"
    DESCRIPTION = "List all registered MCP servers."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        servers = list((self.hub_registry.apihub.get_mcp_servers() or {}).values())
        return ToolResult.ok(data={"servers": servers})


class ListMCPToolsTool(_MCPToolBase):
    NAME = "mcp_list_tools"
    DESCRIPTION = "List MCP tools, optionally filtered by server name."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {"server_name": {"type": "string"}},
            }, required=[])

    async def execute(self, *, server_name: str = None, **_kw) -> ToolResult:
        tools = list(
            (self.hub_registry.apihub.get_mcp_tools(server_name=server_name) or {}).values()
        )
        return ToolResult.ok(data={"tools": tools})


_MCP_TOOLS = [RegisterMCPServerTool, RegisterMCPToolTool, RegisterMCPConsumerTool,
               ListMCPServersTool, ListMCPToolsTool]


def create_mcp_registry_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _MCP_TOOLS]


__all__ = [
    "RegisterMCPServerTool", "RegisterMCPToolTool", "RegisterMCPConsumerTool",
    "ListMCPServersTool", "ListMCPToolsTool",
    "create_mcp_registry_tools",
]
```

- [ ] **Step 3: Register bundle + wire to backend / frontend / orchestrator**

In `tool_bundles.py`:

```python
from tools.mcp_registry_tools import create_mcp_registry_tools

def _bundle_mcp_registry_tools(builder, context) -> None:
    builder.add(create_mcp_registry_tools(hub_registry=context.hub_workspace),
                "knowledge")

# TOOL_BUNDLE_REGISTRY:
"mcp_registry_tools": _bundle_mcp_registry_tools,

# TOOL_BUNDLE_REQUIREMENTS:
"mcp_registry_tools": {"knowledge"},
```

In `agents_config.yaml`, add `mcp_registry_tools` to `backend`, `frontend`, and `orchestrator` profile `tool_bundles` lists.

- [ ] **Step 4: Verify 5 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_mcp_registry_tools -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 5 OK; 7 OK / 851 OK (846 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/tools/mcp_registry_tools.py agent/env_generator/llm_generator/multi_agent/tool_bundles.py agent/env_generator/llm_generator/multi_agent/agents/agents_config.yaml agent/tests/test_mcp_registry_tools.py
git commit -m "Add mcp_registry_tools: 5 LLM tools + wire to backend/frontend/orchestrator"
```

---

## Task 5: Coverage gate extension for dead MCP tools

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py`
- Create: `agent/tests/test_coverage_audit_mcp.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_coverage_audit_mcp.py`:

```python
"""Tests for coverage_audit MCP extension (Cutover 22)."""

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
    compute_coverage, scan_dead_mcp_tools,
)


class DeadMCPToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_mcp_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tools_returns_empty(self) -> None:
        self.assertEqual(scan_dead_mcp_tools(self.reg), [])

    def test_tool_with_no_consumer_is_dead(self) -> None:
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        dead = scan_dead_mcp_tools(self.reg)
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["server"], "filesystem")
        self.assertEqual(dead[0]["tool"], "read_file")

    def test_tool_with_consumer_not_dead(self) -> None:
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts", agent="frontend")
        self.assertEqual(scan_dead_mcp_tools(self.reg), [])

    def test_compute_coverage_includes_dead_mcp_tools(self) -> None:
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        tmp_app = Path(self.tmp) / "app"
        tmp_app.mkdir()
        (tmp_app / "main.tsx").write_text("x = 1;\n")
        report = compute_coverage(self.reg, tmp_app)
        self.assertEqual(len(report.dead_mcp_tools), 1)
        self.assertFalse(report.is_clean)
        paths = report.all_dead_paths
        self.assertIn("mcp_tool:filesystem:read_file", paths)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure + Step 3: Extend coverage_audit**

In `agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py`:

**(a)** Add `dead_mcp_tools` field to `CoverageReport`:

```python
@dataclass
class CoverageReport:
    dead_endpoints: List[dict] = field(default_factory=list)
    dead_tables: List[dict] = field(default_factory=list)
    dead_files: List[dict] = field(default_factory=list)
    dead_mcp_tools: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.dead_endpoints or self.dead_tables
                     or self.dead_files or self.dead_mcp_tools)

    @property
    def all_dead_paths(self) -> Set[str]:
        out: Set[str] = set()
        for ep in self.dead_endpoints:
            out.add(f"endpoint:{ep['endpoint_id']}")
        for t in self.dead_tables:
            out.add(f"table:{t['table']}")
        for f in self.dead_files:
            out.add(f"file:{f['path']}")
        for mt in self.dead_mcp_tools:
            out.add(f"mcp_tool:{mt['server']}:{mt['tool']}")
        return out

    def to_dict(self) -> dict:
        return {
            "dead_endpoints": list(self.dead_endpoints),
            "dead_tables": list(self.dead_tables),
            "dead_files": list(self.dead_files),
            "dead_mcp_tools": list(self.dead_mcp_tools),
            "is_clean": self.is_clean,
        }
```

**(b)** Add `scan_dead_mcp_tools`:

```python
def scan_dead_mcp_tools(hub_registry) -> List[dict]:
    apihub = getattr(hub_registry, "apihub", None)
    if apihub is None or not hasattr(apihub, "get_mcp_tools"):
        return []
    tools = apihub.get_mcp_tools() or {}
    out = []
    for key, tool in tools.items():
        if (tool.get("status") or "defined") != "defined":
            continue
        server = tool.get("server_name")
        tool_name = tool.get("tool_name")
        consumers = apihub.get_mcp_consumers(server_name=server, tool_name=tool_name)
        if not consumers:
            out.append({
                "server": server,
                "tool": tool_name,
                "provider": tool.get("provider"),
            })
    return out
```

**(c)** Update `compute_coverage` to call the new scanner:

```python
def compute_coverage(hub_registry, app_root) -> CoverageReport:
    app_root = Path(app_root)
    return CoverageReport(
        dead_endpoints=scan_dead_endpoints(hub_registry),
        dead_tables=scan_dead_tables(hub_registry),
        dead_files=scan_dead_files(app_root),
        dead_mcp_tools=scan_dead_mcp_tools(hub_registry),
    )
```

**(d)** Update `__all__` to include `scan_dead_mcp_tools`.

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_coverage_audit_mcp -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 855 OK (851 + 4 new). The existing Cutover 19 coverage tests should remain green (CoverageReport default for `dead_mcp_tools` is empty list — no regression in `is_clean` / `all_dead_paths` for tests that don't use MCP).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/coverage_audit.py agent/tests/test_coverage_audit_mcp.py
git commit -m "coverage_audit: extend to flag dead MCP tools (registered tool with zero consumers)"
```

---

## Task 6: Backend + Frontend prompts

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2`
- Modify: `agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2`
- Create: `agent/tests/test_mcp_prompts.py`

- [ ] **Step 1: Write failing test**

Create `agent/tests/test_mcp_prompts.py`:

```python
"""Tests that backend + frontend prompts teach MCP registration discipline."""

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


class BackendMCPPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("backend_agent.j2",
                              ["backend_specifics", "backend_system_prompt"])

    def test_mentions_mcp_register_server(self) -> None:
        self.assertIn("MCP_REGISTER_SERVER", self.system.upper())

    def test_mentions_mcp_register_tool(self) -> None:
        self.assertIn("MCP_REGISTER_TOOL", self.system.upper())

    def test_mentions_transport_options(self) -> None:
        upper = self.system.upper()
        self.assertIn("STDIO", upper)
        self.assertIn("HTTP", upper)


class FrontendMCPPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("frontend_agent.j2",
                              ["frontend_specifics", "frontend_system_prompt"])

    def test_mentions_mcp_register_consumer(self) -> None:
        self.assertIn("MCP_REGISTER_CONSUMER", self.system.upper())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Update backend prompt**

In `backend_agent.j2` → `backend_specifics`, append:

```jinja
### MCP REGISTRATION DISCIPLINE (Cutover 22)
When you implement an MCP server in this project, you MUST register it via APIHub for it to be probed at run time + caught by the dead-code gate.

Workflow:
1. Implement the MCP server (stdio binary OR HTTP/SSE endpoint).
2. Call `mcp_register_server(name=<short_name>, transport="stdio"|"http"|"sse"|"websocket", endpoint=<path or URL>, provider="backend")`.
3. For EACH tool the server exposes: `mcp_register_tool(server_name=<name>, tool_name=<tool>, schema={input: {...}, output: {...}}, provider="backend")`.
4. RunHub will probe the server (stdio: spawn + 2s liveness; http/sse: GET reachability). Failed probes route to BugTriageOrch.
5. Frontend will `mcp_register_consumer(server_name, tool_name, file_path)` for each usage — coverage gate refuses deliver if any of your registered tools has zero consumers.

Notes:
- `transport="websocket"` is registered but skipped at probe time (MVP limitation; flagged in run report).
- For stdio servers, `endpoint` is the executable path (relative to workspace or absolute). Ensure it's built + executable before RunHub runs.
- For http/sse, `endpoint` is the URL where the MCP transport is served.
```

- [ ] **Step 3: Update frontend prompt**

In `frontend_agent.j2` → `frontend_specifics`, append:

```jinja
### MCP CONSUMER REGISTRATION (Cutover 22)
When you write code that calls an MCP tool, you MUST register the usage:

```
mcp_register_consumer(server_name=<server>, tool_name=<tool>, file_path=<your file>)
```

This enables the coverage gate to verify every MCP tool the backend ships has at least one consumer. Without this registration, `deliver_project()` will refuse with "dead mcp tool" errors.

Use `mcp_list_servers()` + `mcp_list_tools(server_name=...)` to discover what's available.
```

- [ ] **Step 4: Verify 4 tests + baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_mcp_prompts -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 4 OK; 7 OK / 859 OK (855 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/prompts/v2/backend_agent.j2 agent/env_generator/llm_generator/multi_agent/prompts/v2/frontend_agent.j2 agent/tests/test_mcp_prompts.py
git commit -m "Backend + frontend prompts: MCP REGISTRATION + CONSUMER discipline"
```

---

## Task 7: E2E + migration log + push

**Files:**
- Create: `agent/tests/test_mcp_e2e.py`
- Create: `docs/superpowers/migration-logs/23-mcp-integration.md`

- [ ] **Step 1: Write E2E test**

Create `agent/tests/test_mcp_e2e.py`:

```python
"""E2E: register MCP -> probe failure routes to bug -> dead tool blocks deliver."""

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
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402


class _FakeCompose:
    def __init__(self):
        self.up_called = False
        self.down_called = False
    def up(self, timeout=180.0):
        self.up_called = True
        return ComposeResult(returncode=0, stdout="up ok")
    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _FakeHealthyHC:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.05)


def _passing_http_probe(plan):
    return {"status_code": 200, "body_excerpt": "ok",
            "transport_error": None, "latency_ms": 5.0}


def _agent(reg, gen_id=7000.0, agent_type="orchestrator", app_root=None):
    a = MagicMock()
    a.hub_registry = reg
    a._session_start_ts = gen_id
    a.app_root = str(app_root) if app_root else None
    a.workspace_path = None
    a.agent_type = agent_type
    return a


def _add_retro(reg, gen_id):
    reg.workhub.create_page(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


class MCPE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcp_e2e_"))
        self.reg = HubRegistry(self.tmp / "hub")
        _add_retro(self.reg, 7000.0)
        # Subscriptions
        collect_hub_pulse(self.reg, "bug_triage_orchestrator")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_mcp_probe_lands_in_bug_orch_inbox(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        crashing_probe = lambda s: {"healthy": False, "detail": "exited rc=1"}
        self.reg.runhub.start_run(
            branch="x", generated_dir="/tmp/g",
            base_url="http://localhost:8000", agent="orch",
            compose=_FakeCompose(),
            healthcheck=_FakeHealthyHC(),
            probe_runner=_passing_http_probe,
            mcp_stdio_probe=crashing_probe)
        # run_failed event should reach BugTriageOrch via subscription
        inbox = self.reg.eventhub.get_inbox("bug_triage_orchestrator") or {"items": {}}
        items = inbox.get("items") or {}
        mcp_failures = []
        for event_id in items.keys():
            ev = self.reg.eventhub.get_event(event_id)
            if ev and ev.get("event_type") == "run_failed":
                payload = ev.get("payload") or {}
                if (payload.get("bug_artifacts") or {}).get("affected_mcp_server"):
                    mcp_failures.append(ev)
        self.assertGreaterEqual(len(mcp_failures), 1)

    def test_dead_mcp_tool_blocks_deliver(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        from tools.agent_interaction_tools import DeliverProjectTool
        tool = DeliverProjectTool(agent=_agent(self.reg, app_root=self.tmp / "empty"))
        # Create empty app root so file scan doesn't false-fire
        (self.tmp / "empty").mkdir()
        (self.tmp / "empty" / "main.tsx").write_text("x = 1;\n")
        result = tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                               checklist={"no_bugs": True, "requirements_met": True,
                                            "fully_functional": True, "docker_ok": True})
        self.assertFalse(result.success)
        self.assertIn("mcp", result.error_message.lower())

    def test_dead_mcp_tool_unblocked_after_consumer_registered(self) -> None:
        self.reg.apihub.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")
        self.reg.apihub.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        from tools.agent_interaction_tools import DeliverProjectTool
        (self.tmp / "empty").mkdir()
        (self.tmp / "empty" / "main.tsx").write_text("x = 1;\n")

        # Register consumer
        self.reg.apihub.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts", agent="frontend")

        tool = DeliverProjectTool(agent=_agent(self.reg, app_root=self.tmp / "empty"))
        result = tool.execute(confirmation="CONFIRMED", delivery_summary="d",
                               checklist={"no_bugs": True, "requirements_met": True,
                                            "fully_functional": True, "docker_ok": True})
        self.assertTrue(result.success, f"deliver failed: {result.error_message}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify 3 tests + final baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_mcp_e2e -v 2>&1 | tail -10
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 3 OK; 7 OK / 862 OK (859 + 3 new).

- [ ] **Step 3: Zero Claude trailers**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`.

- [ ] **Step 4: Write migration log**

Create `docs/superpowers/migration-logs/23-mcp-integration.md`:

```markdown
# Cutover 22: MCP Integration (APIHub Registration + RunHub Probe)

**Branch:** `haibotong-cutover-22-mcp`
**Date:** 2026-05-25

## What

Treats MCP servers/tools as first-class APIHub resources (mirror endpoint/table
pattern). RunHub probes them post-run (stdio liveness or HTTP reach). Failed
probes route to BugTriageOrchestrator via existing chain. Coverage gate
refuses deliver if any registered MCP tool has zero consumers.

## Why

The "具有 MCP" requirement had zero enforcement. Backend could ship broken
MCP servers; coverage gate only scanned HTTP endpoints + DB tables; RunHub
HTTP probe didn't speak MCP.

## Commits

(fill from git log)

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 829 OK -> 862 OK (+33 new)

## New surfaces
- APIHub: register_mcp_server / register_mcp_tool / register_mcp_consumer + 3 getters + _mcp_registry JsonStore
- RunHub.start_run: optional mcp_stdio_probe / mcp_http_probe kwargs; _probe_mcp_servers step; _publish_mcp_failure helper
- runtime/coverage_audit.py: scan_dead_mcp_tools + CoverageReport.dead_mcp_tools field
- tools/mcp_registry_tools.py: 5 LLM tools

## Wiring
- mcp_registry_tools bundle -> backend + frontend + orchestrator profiles
- Backend prompt: MCP REGISTRATION DISCIPLINE
- Frontend prompt: MCP CONSUMER REGISTRATION

## Bypass mechanisms (consistent with Cutovers 19-21)
- mark_intentionally_dead("mcp_tool:<server>:<tool>", reason) -> orchestrator allowlist (covered by existing dead-code gate logic)
- force_deliver=True orchestrator-only bypass (existing audit chain)

## Known limits (future cutovers)
- Probe is liveness-only (stdio: 2s; http: HEAD reach). Full JSON-RPC handshake + tools/list verification is a follow-up cutover.
- Websocket transport skipped at probe time (registered, not validated).
- No automatic schema validation against tool responses.
- Backend agent must manually wire the MCP server into the docker compose stack for probe to find it.
```

- [ ] **Step 5: Commit + push**

```bash
git add agent/tests/test_mcp_e2e.py docs/superpowers/migration-logs/23-mcp-integration.md
git commit -m "Add Cutover 22 e2e + migration log"
git push red-env-gen haibotong-cutover-22-mcp 2>&1 | tail -5
```

- [ ] **Step 6: Report** — final test counts, push URL, deferred items.

---

## Self-Review

**1. Spec coverage:** APIHub MCP registration (T2) ✓; RunHub MCP probe (T3) ✓; LLM tools (T4) ✓; coverage_audit extension (T5) ✓; backend + frontend prompts (T6) ✓; E2E + log + push (T7) ✓.

**2. Placeholder scan:** No TBD / "implement later". All code shown.

**3. Type consistency:**
- `register_mcp_server(name, transport, endpoint, provider, agent, status)` — consistent across APIHub + tool + tests + prompt
- `register_mcp_tool(server_name, tool_name, schema, provider, agent, status)` — consistent
- `register_mcp_consumer(server_name, tool_name, file_path, agent)` — consistent
- Transport enum `{stdio, http, sse, websocket}` — consistent in APIHub + tool schema + RunHub
- `bug_artifacts.affected_mcp_server` field — same in publish + test assertions
- `CoverageReport.dead_mcp_tools` + `all_dead_paths` with `mcp_tool:<server>:<tool>` prefix — consistent
- Tool NAMEs: `mcp_register_server` / `mcp_register_tool` / `mcp_register_consumer` / `mcp_list_servers` / `mcp_list_tools` — same in tool + prompt + tests

**4. Cross-cutting:**
- No Claude trailer (T1 + T7) ✓
- Baselines green per task ✓
- TDD throughout ✓
- RunHub probe is injectable (`mcp_stdio_probe` / `mcp_http_probe` kwargs) — tests don't need real subprocess/httpx ✓
- Coverage extension reuses CoverageReport.all_dead_paths — existing Cutover 19 deliver gate works unchanged ✓
- Failed probe uses existing run_failed event type — Cutover 12 subscription chain delivers to BugTriageOrch unmodified ✓
