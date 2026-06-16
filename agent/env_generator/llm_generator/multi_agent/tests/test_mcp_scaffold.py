"""Unit tests for the deterministic MCP server projection (Phase 3c).

The MCP tool surface is a 1:1 projection of the registered BUSINESS endpoints —
consistency-by-construction, never LLM-authored. Guards: deterministic tool
naming, business-only selection (auth/oauth/infra/spine excluded), faithful
per-endpoint tool bodies, and a REAL runtime check that imports a generated
server (fastmcp is installed) and asserts the projected tools register on the
FastMCP app.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.mcp_scaffold import (  # noqa: E402
    business_endpoints,
    tool_op_id,
    render_tool,
    render_mcp_server,
    mcp_tool_records,
    write_mcp_server,
)


def _ep(method, path, kind=None, **md):
    rec = {"method": method, "path": path, "status": "implemented",
           "schema": {"request": {}, "response": {}}}
    if kind:
        rec["kind"] = kind
    rec.update(md)
    return rec


def _contract():
    # a mixed contract: business endpoints + the fixed surface (kind-tagged).
    return {
        "GET /api/posts": _ep("GET", "/api/posts"),
        "POST /api/posts": _ep("POST", "/api/posts"),
        "GET /api/posts/{id}": _ep("GET", "/api/posts/{id}"),
        "DELETE /api/posts/{id}": _ep("DELETE", "/api/posts/{id}"),
        "POST /auth/login": _ep("POST", "/auth/login", kind="auth"),
        "GET /.well-known/jwks.json": _ep("GET", "/.well-known/jwks.json", kind="oauth"),
        "GET /health": _ep("GET", "/health", kind="infra"),
    }


class ToolOpIdTests(unittest.TestCase):
    def test_naming_is_deterministic_and_collision_free(self):
        self.assertEqual(tool_op_id("GET", "/api/posts"), "get_posts")
        self.assertEqual(tool_op_id("POST", "/api/posts"), "post_posts")
        self.assertEqual(tool_op_id("GET", "/api/posts/{id}"), "get_posts_by_id")
        self.assertEqual(tool_op_id("GET", "/api/v1/teams/{tid}/members"), "get_teams_by_tid_members")
        self.assertEqual(tool_op_id("GET", "/"), "get_root")
        # verb prefix disambiguates same-path methods
        self.assertNotEqual(tool_op_id("GET", "/api/posts"), tool_op_id("POST", "/api/posts"))

    def test_op_ids_are_valid_python_identifiers(self):
        for m, p in [("GET", "/api/posts"), ("GET", "/api/posts/{id}"),
                     ("POST", "/api/v1/a-b/c.d")]:
            self.assertTrue(tool_op_id(m, p).isidentifier())


class BusinessSelectionTests(unittest.TestCase):
    def test_excludes_auth_oauth_infra_spine_and_deprecated(self):
        eps = _contract()
        eps["GET /api/old"] = _ep("GET", "/api/old"); eps["GET /api/old"]["status"] = "deprecated"
        biz = business_endpoints(eps)
        paths = {e["path"] for e in biz}
        self.assertEqual(paths, {"/api/posts", "/api/posts/{id}"})  # business only
        self.assertNotIn("/auth/login", paths)
        self.assertNotIn("/health", paths)
        self.assertNotIn("/api/old", paths)

    def test_kind_under_metadata_is_honored(self):
        # RegistryHub stores **metadata into a metadata dict — kind may live there.
        eps = {"POST /auth/login": _ep("POST", "/auth/login")}
        eps["POST /auth/login"].pop("kind", None)
        eps["POST /auth/login"]["metadata"] = {"kind": "auth"}
        self.assertEqual(business_endpoints(eps), [])


class RenderToolTests(unittest.TestCase):
    def test_get_with_path_param_becomes_typed_arg(self):
        src = render_tool(_ep("GET", "/api/posts/{id}"))
        self.assertIn("async def get_posts_by_id(id: str) -> str:", src)
        self.assertIn('await _request("GET", f"{API_BASE_URL}/api/posts/{id}")', src)
        self.assertNotIn("json=", src)  # GET has no body

    def test_write_method_takes_body(self):
        src = render_tool(_ep("POST", "/api/posts"))
        self.assertIn("async def post_posts(body: dict | None = None) -> str:", src)
        self.assertIn('await _request("POST", f"{API_BASE_URL}/api/posts", json=(body or {}))', src)

    def test_colon_style_param_normalized_to_fstring(self):
        src = render_tool(_ep("GET", "/api/posts/:id"))
        self.assertIn('f"{API_BASE_URL}/api/posts/{id}"', src)


class RenderServerTests(unittest.TestCase):
    def test_full_server_has_skeleton_and_one_tool_per_business_endpoint(self):
        src = render_mcp_server(_contract(), env_name="app")
        self.assertIn("from fastmcp import FastMCP", src)
        self.assertIn('mcp = FastMCP("App MCP"', src)
        self.assertIn('mcp.run(transport="http"', src)
        self.assertIn("jwks.json", src)  # verifies against backend JWKS
        # one tool per business endpoint; none for the fixed surface
        self.assertEqual(src.count("@mcp.tool()"), 4)
        self.assertIn("async def get_posts(", src)
        self.assertIn("async def post_posts(", src)
        self.assertIn("async def get_posts_by_id(", src)
        self.assertIn("async def delete_posts_by_id(", src)
        self.assertNotIn("auth_login", src)
        self.assertNotIn("def get_health", src)

    def test_generated_main_is_valid_python(self):
        src = render_mcp_server(_contract(), env_name="app")
        compile(src, "main.py", "exec")  # raises SyntaxError on a bad emit

    def test_empty_business_contract_still_valid_skeleton(self):
        src = render_mcp_server({"POST /auth/login": _ep("POST", "/auth/login", kind="auth")}, "app")
        compile(src, "main.py", "exec")
        self.assertEqual(src.count("@mcp.tool()"), 0)


class WriteServerTests(unittest.TestCase):
    def test_writes_mcp_server_tree(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            res = write_mcp_server(out, _contract(), env_name="app")
            sd = out / "mcp_server" / "app"
            self.assertTrue((sd / "main.py").is_file())
            self.assertTrue((sd / "pyproject.toml").is_file())
            self.assertTrue((sd / "start.sh").is_file())
            self.assertEqual(res["tool_count"], 4)
            names = {t["tool_name"] for t in res["tools"]}
            self.assertEqual(names, {"get_posts", "post_posts", "get_posts_by_id", "delete_posts_by_id"})


class ToolRecordTests(unittest.TestCase):
    def test_records_carry_method_path_schema(self):
        recs = mcp_tool_records(_contract())
        by_name = {r["tool_name"]: r for r in recs}
        self.assertEqual(by_name["get_posts_by_id"]["method"], "GET")
        self.assertEqual(by_name["get_posts_by_id"]["path"], "/api/posts/{id}")
        self.assertEqual(by_name["get_posts_by_id"]["schema"]["input"]["path_params"], ["id"])


def _import_generated(main_py: Path):
    """Import a generated main.py as an isolated module (DISABLE_OAUTH dev)."""
    sd = main_py.parent
    sys.path.insert(0, str(sd))
    os.environ["DISABLE_OAUTH"] = "1"
    os.environ["API_BASE_URL"] = "http://localhost:1"
    try:
        spec = importlib.util.spec_from_file_location("generated_mcp_main", main_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(sd))


@unittest.skipUnless(
    importlib.util.find_spec("fastmcp") is not None, "fastmcp not installed")
class RuntimeImportTests(unittest.TestCase):
    """Decisive runtime check: a generated server imports and its projected
    tools actually register on the FastMCP app."""

    def test_generated_server_imports_and_registers_tools(self):
        with tempfile.TemporaryDirectory() as td:
            res = write_mcp_server(Path(td), _contract(), env_name="app")
            mod = _import_generated(res["main_py"])
            self.assertTrue(hasattr(mod, "mcp"))

            m = mod.mcp
            tools = m.get_tools()
            if asyncio.iscoroutine(tools):
                tools = asyncio.run(tools)
            names = set(tools.keys()) if isinstance(tools, dict) else {
                getattr(t, "name", None) or getattr(t, "key", None) for t in tools}
            for expected in ("get_posts", "post_posts", "get_posts_by_id", "delete_posts_by_id"):
                self.assertIn(expected, names)
            # the fixed surface is NOT a tool
            self.assertNotIn("post_auth_login", names)
            sys.modules.pop("generated_mcp_main", None)


class _FakeMapView:
    def __init__(self, d): self._d = d
    def set(self, k, v, agent=None): self._d[k] = v; return v


class _FakeStore:
    def __init__(self): self._d = {}
    def value(self): return dict(self._d)
    def update(self, fn, change_info=None): fn(_FakeMapView(self._d))


class MCPRegistryRoleGateTests(unittest.TestCase):
    """Phase 3c added 'orchestrator' to the register_mcp_server/tool allowed set
    (mirrors registryhub) so the deterministic projection can publish the contract."""

    def _registry(self):
        from multi_agent.runtime.mcp_registry import MCPRegistry
        return MCPRegistry(registry_store=_FakeStore(), eventhub=None)

    def test_orchestrator_may_register_server_and_tool(self):
        reg = self._registry()
        srv = reg.register_mcp_server(name="app", transport="http",
                                      endpoint="mcp_server/app/main.py",
                                      agent="orchestrator", status="implemented")
        self.assertEqual(srv.get("name"), "app")
        tool = reg.register_mcp_tool(server_name="app", tool_name="get_posts",
                                     schema={}, agent="orchestrator", status="implemented")
        self.assertEqual(tool.get("tool_name"), "get_posts")

    def test_backend_still_allowed_and_other_actor_rejected(self):
        reg = self._registry()
        reg.register_mcp_server(name="app", transport="http", endpoint="x", agent="backend")
        with self.assertRaises(PermissionError):
            reg.register_mcp_server(name="bad", transport="http", endpoint="x", agent="frontend")


class _CaptureMCP:
    def __init__(self):
        self.servers = []
        self.tools = []

    def register_mcp_server(self, **kw):
        self.servers.append(kw); return kw

    def register_mcp_tool(self, **kw):
        self.tools.append(kw); return kw


class _GenMcpStub:
    def __init__(self, output_dir, endpoints):
        import logging

        class _Apihub:
            def __init__(self, eps): self._eps = eps
            def get_endpoints(self): return self._eps

        class _Hubs:
            pass
        self.output_dir = Path(output_dir)
        self._logger = logging.getLogger("stub_gen_mcp")
        self.hubs = _Hubs()
        self.hubs.registryhub = _Apihub(endpoints)
        self.hubs.mcp_registry = _CaptureMCP()


class GenerateMcpWiringTests(unittest.TestCase):
    def test_emits_server_and_registers_business_tools_implemented(self):
        from multi_agent.orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as td:
            stub = _GenMcpStub(td, _contract())
            asyncio.new_event_loop().run_until_complete(Orchestrator._generate_mcp(stub))
            # emitted the server tree
            self.assertTrue((Path(td) / "mcp_server" / "app" / "main.py").is_file())
            # registered the server + exactly the 4 business tools, all implemented
            self.assertEqual(len(stub.hubs.mcp_registry.servers), 1)
            self.assertEqual(stub.hubs.mcp_registry.servers[0]["status"], "implemented")
            self.assertEqual(stub.hubs.mcp_registry.servers[0]["agent"], "orchestrator")
            tool_names = {t["tool_name"] for t in stub.hubs.mcp_registry.tools}
            self.assertEqual(tool_names, {"get_posts", "post_posts", "get_posts_by_id", "delete_posts_by_id"})
            for t in stub.hubs.mcp_registry.tools:
                self.assertEqual(t["status"], "implemented")
                self.assertEqual(t["agent"], "orchestrator")

    def test_no_business_endpoints_skips_projection(self):
        from multi_agent.orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as td:
            only_fixed = {"POST /auth/login": _ep("POST", "/auth/login", kind="auth")}
            stub = _GenMcpStub(td, only_fixed)
            asyncio.new_event_loop().run_until_complete(Orchestrator._generate_mcp(stub))
            self.assertFalse((Path(td) / "mcp_server").exists())
            self.assertEqual(stub.hubs.mcp_registry.servers, [])


if __name__ == "__main__":
    unittest.main()
