"""mcp_scaffold: MCP tool names must be COLLISION-FREE across the whole contract.

tool_op_id strips a leading 'api/v1/' OR 'api/' for readability, so two distinct endpoints
can derive the SAME name — e.g. GET /api/videos and GET /api/v1/videos both -> get_videos.
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

# #1203a3: this fixture used /api/tenants and /api/v1/tenants. `mcp_scaffold` now classifies
# with `lifecycle.is_business`, the same predicate every other check uses, and /api/v1/tenants is
# the literal control-surface example in that function's docstring — so one of the two was
# filtered and the collision could no longer occur. The `kind: "business"` tag did not save it,
# which is the whole point of the path net ("the kind tag alone is not enough").
# The property under test is unchanged: `tool_op_id` strips a leading `api/v1/` OR `api/`, so any
# two endpoints differing only by that prefix collide. Two BUSINESS paths show it just as well.
_COLLIDING = {
    "GET /api/videos": {"method": "GET", "path": "/api/videos", "kind": "business", "schema": {}},
    "GET /api/v1/videos": {"method": "GET", "path": "/api/v1/videos", "kind": "business",
                           "schema": {}},
}


def test_records_have_unique_names_on_collision():
    names = [r["tool_name"] for r in mcp_tool_records(_COLLIDING)]
    assert len(names) == 2
    assert len(set(names)) == 2, f"duplicate MCP tool names: {names}"


def test_server_defines_two_distinct_tools_on_collision():
    server = render_mcp_server(_COLLIDING)
    defs = [d for d in re.findall(r"async def (\w+)\(", server) if "videos" in d]
    assert len(defs) == 2 and len(set(defs)) == 2, defs


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
