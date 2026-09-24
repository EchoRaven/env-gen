"""#303 — registryhub_list_endpoints / list_tables return COMPACT rows
(method/path/status/provider), NOT the full schema+metadata. Details via the
existing registryhub_get_endpoint(id). The list is re-fetched dozens of times a
run; the schema/metadata fields are ~85% of each row and rarely needed in a list.
Same 'compact list + get-by-id' pattern as #302's inbox preview.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import RegistryHubListEndpointsTool, RegistryHubGetEndpointTool  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reg():
    tmp = Path(tempfile.mkdtemp(prefix="reg303_"))
    reg = HubRegistry(tmp)
    reg.registryhub.register_endpoint(
        "GET", "/api/videos",
        schema={"request": {"limit": "int", "cursor": "str"},
                "response": {"items": "list", "next": "str"}},
        provider="backend", agent="backend", status="implemented")
    return reg, tmp


def test_list_endpoints_is_compact():
    reg, tmp = _reg()
    try:
        out = _run(RegistryHubListEndpointsTool(agent_id="backend", hub_workspace=reg)._run())
        eps = out.data["endpoints"]
        assert eps, "should list the registered endpoint"
        row = next(iter(eps.values()))
        # compact identifying fields kept
        assert row.get("method") == "GET" and row.get("path") == "/api/videos"
        assert row.get("status") == "implemented" and row.get("provider") == "backend"
        # heavy fields dropped from the LIST
        assert "schema" not in row
        assert "metadata" not in row
        # a pointer to the full-detail tool
        assert "get_endpoint" in str(out.data).lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_get_endpoint_still_has_full_schema():
    # the on-demand detail path is unchanged — full schema recoverable by id
    reg, tmp = _reg()
    try:
        eid = next(iter(reg.registryhub.get_endpoints().keys()))
        out = _run(RegistryHubGetEndpointTool(agent_id="backend", hub_workspace=reg)._run(endpoint_id=eid))
        assert "schema" in str(out.data)          # full detail retained on the get path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
