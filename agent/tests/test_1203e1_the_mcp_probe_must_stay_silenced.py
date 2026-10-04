r"""#1203e1: the MCP probe battery has never run, and that is CORRECT — pinned so nobody "fixes" it.

`RunHub._list_registryhub_mcp_servers` filters `status == "defined"`. That is the same predicate
#1203d6 just corrected in `plan_probe`, and it has the same effect: 152 of the 153
`mcp:server:*` records in the corpus are `implemented`, so the list comes back empty and the
MCP battery never runs. MEASURED: `mcp_probes.total` is 0 in **100% of the 2414 gate records
across 54 runs**, which also makes `deliverability.functionally_validated`'s
`mcp_counts["failed"] == 0` term vacuous.

Every surface feature says "twin of #1203d6, fix it the same way". It is not, and this file
exists so that the next reader finds that out before shipping it:

  * `mcp_server/app/start.sh` line 1 — "Launch the FastMCP server (agentsuite-red pool runs
    this as a subprocess)." The pipeline BUILDS the server (123 runs carry `mcp_server/`) and
    the DOWNSTREAM consumer starts it.
  * 0 of 191 generated `docker-compose.yml` files declare an mcp service, and no MCP container
    has ever existed. That is by design, not an omission.
  * r138 is the natural positive control: its server record was `defined`, so the probe DID run
    — and returned `transport: [Errno 111] Connection refused` on all four attempts.

Widening the filter would therefore add a permanently failing probe to every run
(`fail_count += 1` → run `status: failed` → the "no successful RunHub run" blocker). That is
the shape that cost r151 a launch: #1203d6 removed a different accidental shield and exposed
#1203e0's empty-body failures on framework-owned endpoints, and the run had to be stopped at
$11.70. Three times in one session a filter looked wrong and the question behind it was
unanswerable; this is the third.

The real defect is reported elsewhere (#1202xr: 26% of generated MCP tools cannot pass a query
parameter, which survived 144 runs precisely because nothing ever called them). Fixing it needs
a consumer that starts the server, not a probe pretending one did.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hubs.runhub import service as SV  # noqa: E402


def _fn():
    return inspect.getsource(SV.RunHub._list_registryhub_mcp_servers)


def test_the_filter_is_still_exactly_defined():
    """★ The non-action itself. If this fails, read the docstring above before changing it."""
    assert 's.get("status") == "defined"' in _fn(), (
        "the MCP server filter was widened. The MCP server is not running during a run by "
        "design (mcp_server/app/start.sh line 1), so this adds a permanently failing probe "
        "to every run — see this module's docstring and r138's connection-refused control."
    )


def test_d6s_allow_list_is_not_used_here():
    """The specific wrong fix, named so the mistake is hard to make by accident."""
    assert "_LIVE_STATUSES_1203D6" not in _fn(), _fn()


def test_the_reason_lives_with_the_code():
    """#1202zz: a decision whose reason is not in the code gets re-litigated. The docstring must
    carry the three facts that make the non-action correct, not just assert it."""
    doc = (SV.RunHub._list_registryhub_mcp_servers.__doc__ or "")
    assert "start.sh" in doc, "the downstream-starts-it fact is missing"
    assert "r138" in doc, "the positive control is missing"
    assert "#1203d6" in doc, "the twin it must not be confused with is unnamed"


def test_the_function_still_returns_a_list_on_a_missing_registry():
    """Behaviour unchanged: a docstring-only patch must stay docstring-only."""
    class _S:
        mcp_registry = None
    assert SV.RunHub._list_registryhub_mcp_servers(_S()) == []


def test_an_implemented_server_is_still_excluded():
    """The exact records the corpus holds — 152 of 153."""
    class _Reg:
        @staticmethod
        def get_mcp_servers():
            return {"mcp:server:app": {"name": "app", "transport": "http",
                                       "status": "implemented"},
                    "mcp:server:old": {"name": "old", "transport": "http",
                                       "status": "defined"}}

    class _S:
        mcp_registry = _Reg()
    out = SV.RunHub._list_registryhub_mcp_servers(_S())
    assert [s["name"] for s in out] == ["old"], out


def test_the_docstring_does_not_claim_the_surface_is_healthy():
    """★ Not a whitewash: the non-action is about THIS probe, and the docstring must still name
    the real defect so the decision cannot be quoted as 'MCP is fine'."""
    doc = (SV.RunHub._list_registryhub_mcp_servers.__doc__ or "")
    assert "#1202xr" in doc and "never exercised" in doc, doc[-400:]
