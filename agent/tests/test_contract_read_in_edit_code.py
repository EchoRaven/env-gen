"""FIX #21 — registryhub contract READ tools must reach the edit_code surface.

The backend/frontend lanes are instructed to consult the RegistryHub contract
(registered at finalize_kickoff) before implementing an endpoint/table. But the
``edit_code`` action stage's category hints don't include registryhub, and
``_HUB_REGISTRATION`` carries only the registryhub *register* (write) tools — so the
registryhub READ tools (``registryhub_get_endpoint`` / ``registryhub_get_table`` / the list
variants) never reached the per-step LLM surface during code writing.

Instagram run #4 (2026-06-06): the backend wrote the framework auth scaffold then
produced ZERO business endpoints across the whole implementation phase — it
claimed each endpoint task then FAILED it with "required source-of-truth RegistryHub
table read was not executed in this step; no deliverable completed", because it
literally could not call registryhub_get_table/get_endpoint while in edit_code (40
fail_task calls, 0 code writes). Notes (5 endpoints) slid by; Instagram (30)
deadlocked. These pin the read tools into edit_code + run_checks closed-by-
construction so the ranker (truncates to ~10) can't drop them.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.base import EnvGenAgent  # noqa: E402

_CONTRACT_READ_TOOLS = (
    "registryhub_get_endpoint",
    "registryhub_list_endpoints",
    "registryhub_get_table",
    "registryhub_list_tables",
)


def test_contract_read_set_defined():
    cr = EnvGenAgent._CONTRACT_READ
    for t in _CONTRACT_READ_TOOLS:
        assert t in cr, f"{t} missing from _CONTRACT_READ"


@pytest.mark.parametrize("tool", _CONTRACT_READ_TOOLS)
def test_edit_code_offers_contract_read(tool):
    """edit_code is where business code is written; the lane MUST be able to
    read the contract source-of-truth in the SAME step (read-then-write)."""
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["edit_code"]
    assert tool in always, (
        f"FIX #21: {tool} must be force-offered in edit_code so the backend can "
        f"read the RegistryHub contract before writing an endpoint, instead of "
        f"failing the task with 'RegistryHub table read was not executed in this step'."
    )


@pytest.mark.parametrize("tool", _CONTRACT_READ_TOOLS)
def test_run_checks_offers_contract_read(tool):
    """run_checks (validation/test authoring) also benefits from reading the
    contract; pinned for the same crowd-out reason."""
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["run_checks"]
    assert tool in always


def test_write_tools_still_present_in_edit_code():
    # regression guard: the read additions must not displace the write tools.
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["edit_code"]
    for t in ("read", "write", "edit", "apply_patch"):
        assert t in always


if __name__ == "__main__":
    import pytest as _p
    raise SystemExit(_p.main([__file__, "-q"]))
