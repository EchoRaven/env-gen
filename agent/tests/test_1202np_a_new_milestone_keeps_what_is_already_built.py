"""#1202np: a later milestone's finalize keeps an endpoint IMPLEMENTED when its schema is unchanged.

#1202mw kept statuses on a resume of the SAME milestone; a NEW milestone's finalize still wrote
`status="defined"` over every endpoint its contract re-declared. tiktok-r125 M4 was stall-finalized
from the registry (#1202kp), so its contract was the registry itself: all 44 endpoints went
implemented -> defined at 11:11:42-11:12:11, the delivery gate reported `no_implemented_endpoints`
and 14 "endpoint not implemented in registry", and backend was re-woken to redo serving endpoints.
The same `no_implemented_endpoints` appears in r120, r121, r122 and r124.

A schema that changed still returns to `defined` (test_1202mv covers that case).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402
from test_1202mv_a_resume_does_not_re_hold_a_settled_kickoff import (  # noqa: E402
    _finalize, _kickoff, _mark_built)


def _hubs(tmp):
    (Path(tmp) / "shared").mkdir()
    return HubRegistry(Path(tmp))


def test_r125_m4_an_unchanged_endpoint_stays_implemented():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs, ms=1))
        _mark_built(hubs)
        _finalize(hubs, _kickoff(hubs, ms=4))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "implemented"


def test_a_first_milestone_still_registers_defined():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs, ms=1))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "defined"


def test_a_deprecated_endpoint_is_not_kept_deprecated_by_a_contract_that_names_it():
    """Only `implemented` is kept: a contract re-declaring a deprecated endpoint revives it."""
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _finalize(hubs, _kickoff(hubs, ms=1))
        ep = hubs.registryhub.get_endpoints()["GET /api/posts"]
        hubs.registryhub.register_endpoint(method="GET", path="/api/posts",
                                           schema=ep.get("schema"), provider="backend",
                                           agent="backend", status="deprecated")
        _finalize(hubs, _kickoff(hubs, ms=2))
        assert hubs.registryhub.get_endpoints()["GET /api/posts"]["status"] == "defined"


def test_the_helper_reads_the_registry_it_is_given():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        assert RK._kept_status_1202np(hubs, {"method": "GET", "path": "/api/nope"}) == "defined"
        assert RK._kept_status_1202np(object(), {"method": "GET", "path": "/x"}) == "defined"
