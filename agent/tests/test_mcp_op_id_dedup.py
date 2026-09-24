"""mcp_scaffold: MCP tool names must be COLLISION-FREE across the whole contract.

tool_op_id strips a leading 'api/v1/' OR 'api/' for readability, so two distinct endpoints
can derive the SAME name — e.g. GET /api/tenants and GET /api/v1/tenants both -> get_tenants.
The server then emits two `async def get_tenants` (the second shadows the first) and the
registry records two tools with the same name -> an INCOMPLETE/AMBIGUOUS MCP surface (and the
test-user's mcp-completeness check is fooled). render_mcp_server + mcp_tool_records now apply a
deterministic dedup so every endpoint gets a unique tool name.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.mcp_scaffold import mcp_tool_records, render_mcp_server  # noqa: E402

_COLLIDING = {
    "GET /api/tenants": {"method": "GET", "path": "/api/tenants", "kind": "business", "schema": {}},
    "GET /api/v1/tenants": {"method": "GET", "path": "/api/v1/tenants", "kind": "business", "schema": {}},
}


def test_records_have_unique_names_on_collision():
    names = [r["tool_name"] for r in mcp_tool_records(_COLLIDING)]
    assert len(names) == 2
    assert len(set(names)) == 2, f"duplicate MCP tool names: {names}"


def test_server_defines_two_distinct_tools_on_collision():
    server = render_mcp_server(_COLLIDING)
    tenant_defs = [d for d in re.findall(r"async def (\w+)\(", server) if "tenants" in d]
    assert len(tenant_defs) == 2 and len(set(tenant_defs)) == 2, tenant_defs


def test_non_colliding_contract_keeps_base_names():
    eps = {
        "GET /api/posts": {"method": "GET", "path": "/api/posts", "kind": "business", "schema": {}},
        "POST /api/posts": {"method": "POST", "path": "/api/posts", "kind": "business", "schema": {}},
    }
    names = sorted(r["tool_name"] for r in mcp_tool_records(eps))
    assert names == ["get_posts", "post_posts"]  # unchanged for the common case


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
