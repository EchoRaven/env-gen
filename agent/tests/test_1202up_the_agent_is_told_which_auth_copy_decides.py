r"""#1202up: the framework resolved `auth_required`; the AGENT was the one reader never told.

One endpoint record can state `auth_required` in three places -- the top level, `schema`, and
the `metadata` mirror -- and they disagree. MEASURED over 155 run directories:

    4852 endpoints
    2257 carry two copies,  400 of those CONTRADICT each other
     388 more state it only in `schema`

and r135 was carrying 3 contradictions out of the 4 endpoints that had both, live, while this
was written.

The framework already settles it. `route_projector.resolve_endpoint_auth` is the single
canonical decision -- top level, then `schema` (what the LANE writes, made to win by #1202ga),
then the mirror, then r58's shape default for an endpoint that states nothing -- with #906's
measurement behind it, and `registryhub._endpoint_requires_auth` and
`remediation_dispatcher` both delegate to it rather than re-deciding.

THE TOOLS DID NOT. `registryhub_get_endpoint` returned the raw record -- 19,970 calls across
the corpus -- so a lane saw two contradictory booleans and no way to know which one the app
will behave by. `registryhub_list_endpoints` (20,481 calls) left auth out of its compact row
entirely, so the only way to ask was one `get_endpoint` per endpoint, which then answered
ambiguously.

WHY THE DIRECTION MATTERS: #906 measured the disagreement as predominantly
`schema=False, metadata=True` -- the lane declared a public read and the mirror still says
private. An agent trusting the mirror puts a login wall in front of an endpoint the framework
serves to anonymous callers, which is the logged-out-landing-page failure #1202kg/#1202kh
exist to prevent.

IT REPORTS, IT DOES NOT REWRITE: the raw record is returned unchanged beside the resolved
value, so a lane that needs to see the copies disagree still can.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.hub_tools import _effective_auth_1202up  # noqa: E402

CONTRADICTS = {"id": "GET /api/videos", "method": "GET", "path": "/api/videos",
               "schema": {"auth_required": False},
               "metadata": {"auth_required": True}}


def test_a_contradicting_record_resolves_the_way_the_framework_will_behave():
    """★ The defect: the agent saw False and True and had to guess."""
    assert _effective_auth_1202up(CONTRADICTS) is False


def test_it_agrees_with_the_framework_resolver_exactly():
    """★ The property that matters more than any single case: this must never become a SECOND
    opinion. #1032 in this codebase is a duplicated normaliser that drifted on one key."""
    from multi_agent.runtime.route_projector import resolve_endpoint_auth

    cases = [
        CONTRADICTS,
        {"method": "GET", "path": "/x", "metadata": {"auth_required": True}},
        {"method": "GET", "path": "/x", "schema": {"auth_required": True}},
        {"method": "GET", "path": "/api/videos"},
        {"method": "POST", "path": "/api/videos"},
        {"method": "DELETE", "path": "/api/videos/{id}"},
        {"method": "GET", "path": "/api/me"},
        {"method": "GET", "path": "/x", "auth_required": True,
         "schema": {"auth_required": False}, "metadata": {"auth_required": False}},
    ]
    for ep in cases:
        assert _effective_auth_1202up(ep) == resolve_endpoint_auth(
            ep.get("method"), ep.get("path"), ep, ep.get("metadata")), ep


def test_the_lane_written_copy_wins():
    """#1202ga made `schema` -- what the LANE writes -- beat the mirror. The tool must report
    that, or it teaches the opposite of what the app does."""
    assert _effective_auth_1202up(CONTRADICTS) is False
    flipped = dict(CONTRADICTS, schema={"auth_required": True},
                   metadata={"auth_required": False})
    assert _effective_auth_1202up(flipped) is True


def test_get_endpoint_reports_beside_the_record_not_instead_of_it():
    """★ A lane that needs to see the two copies disagree still must be able to."""
    import inspect

    from tools.hub_tools import RegistryHubGetEndpointTool

    src = inspect.getsource(RegistryHubGetEndpointTool)
    assert "_out = dict(endpoint)" in src, src[-500:]
    assert '_out["auth_required_effective"]' in src, src[-500:]
    assert "return ToolResult(data=_out)" in src, src[-500:]


def test_the_compact_list_carries_it_too():
    """20,481 list calls could not tell public from private at all; the answer cost one
    `get_endpoint` per endpoint."""
    import inspect

    from tools.hub_tools import RegistryHubListEndpointsTool

    src = inspect.getsource(RegistryHubListEndpointsTool)
    assert '"auth_required_effective": _effective_auth_1202up(v)' in src, src[-600:]


def test_it_never_raises_on_a_malformed_record():
    """It runs inside a tool response: a bad record must cost the annotation, not the call."""
    for bad in ({}, {"method": None, "path": None}, {"metadata": "not-a-dict"},
                {"schema": 5, "metadata": None}):
        _effective_auth_1202up(bad)


def test_it_is_domain_agnostic():
    """★ The user's iron rule: the resolution reads the record's own fields, never what the
    endpoint MEANS. Opaque paths must resolve by shape exactly as named ones do."""
    from multi_agent.runtime.route_projector import resolve_endpoint_auth

    for method in ("GET", "POST", "DELETE"):
        ep = {"method": method, "path": "/api/tok1/tok2"}
        assert _effective_auth_1202up(ep) == resolve_endpoint_auth(
            method, ep["path"], ep, None)
