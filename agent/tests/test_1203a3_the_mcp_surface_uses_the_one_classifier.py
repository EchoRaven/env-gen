r"""#1203a3: the MCP surface classified BUSINESS by the kind tag alone, and shipped auth tools.

`backend_audit` states the project's rule outright: endpoints that "sit on /auth/*, which
`lifecycle.is_business` removes from every other check". `mcp_scaffold.business_endpoints` was
the one exception — it tested `_endpoint_kind(ep) in FIXED_ENDPOINT_KINDS`, the kind TAG only —
while its own docstring promised "the fixed auth/oauth/infra/spine surface are excluded".

#853 SAW THIS COMING and closed the other half. It unified the kinds CONSTANT across six
modules and wrote: *"mcp_scaffold's consequence is the most concrete: a `control` endpoint would
be projected as an MCP tool, handing an agent `reset` or `init-tenant`."* That fixes records that
CARRY a kind. It could not fix the case `lifecycle.is_business` exists for — quoting its own
docstring, "a lane routinely DECLARES a control-surface endpoint ... with NO kind, so it
mis-classifies as business".

MEASURED over 180 corpus runs, before: the two `business_endpoints` disagreed on 49 runs, 138
endpoints, ALL ONE-DIRECTIONAL — mcp said business, lifecycle did not, never the reverse. Every
sample was auth: /auth/signup, /auth/logout, /auth/login, /auth/me. r140's delivered MCP tool
list carried `post_auth_signup` and `post_auth_logout`. After: 0 runs disagree and 0 endpoints
were lost, which the one-directionality predicted — lifecycle's verdict was a strict subset.

★ THE TEST THAT MATTERS IS "THERE IS NO SECOND CLASSIFIER", #853's own lesson: agreement can be
restored by hand and diverge again, which is what six modules did with the constant.

★ The MCP surface has never been exercised (2379 tools marked `implemented`, 0 calls across the
runs carrying tool counts), so the measured harm is zero calls — the same honest limit as
#1203a0. What it buys is that the agent-facing deliverable stops advertising the auth surface as
business, and that the docstring's promise becomes true.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import mcp_scaffold as MS  # noqa: E402
from multi_agent.runtime import lifecycle as LC  # noqa: E402


def _eps(*recs):
    return {"e%d" % i: r for i, r in enumerate(recs)}


_BIZ = {"method": "GET", "path": "/api/videos"}


def test_a_business_endpoint_is_still_returned():
    """Non-vacuity first: a classifier that excluded everything would pass every test below."""
    out = MS.business_endpoints(_eps(_BIZ))
    assert [e["path"] for e in out] == ["/api/videos"], out


def test_an_auth_path_with_no_kind_is_excluded():
    """★ The defect. No `kind` at all, so a kind-only test saw a business endpoint."""
    out = MS.business_endpoints(_eps(_BIZ, {"method": "POST", "path": "/api/auth/signup"}))
    assert [e["path"] for e in out] == ["/api/videos"], out


def test_the_unprefixed_auth_path_is_excluded_too():
    """The corpus carries both spellings; r76 had /auth/signup AND /api/auth/signup."""
    out = MS.business_endpoints(_eps({"method": "POST", "path": "/auth/logout"}))
    assert out == [], out


def test_a_control_plane_path_with_no_kind_is_excluded():
    """#853 named `reset` and `init-tenant` as what this would hand an agent."""
    for path in ("/api/v1/reset", "/api/v1/admin/init-tenant", "/api/v1/tenants"):
        assert MS.business_endpoints(_eps({"method": "POST", "path": path})) == [], path


def test_a_tagged_fixed_endpoint_is_still_excluded():
    """#853's half must keep working — this is a regression guard on the kind path, which the
    new classifier also covers."""
    out = MS.business_endpoints(_eps({"method": "POST", "path": "/api/thing", "kind": "control"}))
    assert out == [], out


def test_a_deprecated_status_is_excluded_case_insensitively():
    """`lifecycle._status` lowercases and this did not, so a record stored as "Deprecated" was
    excluded there and kept here — the same fact, two spellings of the same check."""
    for spelling in ("deprecated", "Deprecated", "DEPRECATED", " deprecated "):
        out = MS.business_endpoints(_eps(dict(_BIZ, status=spelling)))
        assert out == [], spelling


def test_a_record_without_a_method_is_still_skipped():
    """This function's own requirement, not lifecycle's — pinned so the shared classifier does
    not quietly widen what gets a tool."""
    assert MS.business_endpoints(_eps({"path": "/api/videos"})) == []


def test_the_sort_is_still_deterministic():
    out = MS.business_endpoints(_eps(
        {"method": "POST", "path": "/api/z"}, {"method": "GET", "path": "/api/a"},
        {"method": "DELETE", "path": "/api/a"}))
    assert [(e["path"], e["method"]) for e in out] == [
        ("/api/a", "DELETE"), ("/api/a", "GET"), ("/api/z", "POST")]


def test_the_two_functions_now_agree():
    """Behavioural equivalence on the shape that used to split them."""
    eps = _eps(_BIZ, {"method": "POST", "path": "/api/auth/signup"},
               {"method": "GET", "path": "/auth/me"},
               {"method": "POST", "path": "/api/v1/reset"})
    a = {(str(e.get("method", "")).upper(), e["path"]) for e in MS.business_endpoints(eps)}
    b = {(str(e.get("method", "")).upper(), e["path"]) for e in LC.business_endpoints(eps)}
    assert a == b, "mcp=%r lifecycle=%r" % (sorted(a), sorted(b))


def test_there_is_no_second_classifier():
    """★ #853's lesson, applied one level up from the constant it unified: the test that holds is
    not "the copies agree" but "there is no second copy". `business_endpoints` must DELEGATE —
    no local kind-membership test, and the delegation must actually gate the append."""
    src = inspect.getsource(MS.business_endpoints)
    tree = ast.parse(src.lstrip())

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and (getattr(n.func, "id", "") or getattr(n.func, "attr", "")) == "_is_business_1203a3"]
    assert len(calls) == 1, "called %d times" % len(calls)

    # it must sit in an `if` that continues — not be computed and discarded
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node.test)):
            guarded = any(isinstance(x, ast.Continue) for x in ast.walk(node))
    assert guarded, "the verdict is computed but does not gate the append"

    assert "_endpoint_kind" not in src, "the kind-only classifier came back"
    assert "FIXED_ENDPOINT_KINDS" not in src and "_NON_BUSINESS_KINDS" not in src, (
        "a second kind-membership test reappeared in this function")


def test_the_module_no_longer_carries_its_own_kind_reader():
    """The helper is gone, not just unused — an unused copy is the next person's shortcut."""
    assert not hasattr(MS, "_endpoint_kind"), "_endpoint_kind is back at module level"
    assert not hasattr(MS, "_NON_BUSINESS_KINDS"), "the kinds alias is back"


def test_the_shared_classifier_is_the_one_every_other_check_uses():
    """Pinned by identity, so aliasing a local copy under the same name fails."""
    assert MS._is_business_1203a3 is LC.is_business
