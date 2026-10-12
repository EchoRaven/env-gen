"""#1203i7: the endpoint count mixed the lane's work with the framework's own surface.

`hub counts: endpoints=N (implemented=M)` counts every registered endpoint, including the
framework's fixed contract surface -- auth, oauth, the `/.well-known/` discovery documents
and the tenant control surface. `registryhub` registers those as `defined`, and
`defined -> implemented` is not even a legal endpoint transition (`ENDPOINT_STATES` goes
`defined -> implementing -> implemented`), so a large part of that surface stays `defined`
for the life of the run BY DESIGN.

No gate is misled: `all_business_endpoints_implemented` goes through `business_endpoints()`,
which already excludes that surface. The reader who IS misled is whoever reads the printed
count -- and this report is handed to lanes as remediation context, which is the cost
#1202by's comment names three screens up in the same function: "a contradiction that burns
lane attention on a discrepancy that does not exist".

Measured over the last 14 runs, mixed total against business-only:

    r173   44 (27 implemented)  ->  business 24/24 = 100%   mixed understates by 17
    r174   22 ( 0 implemented)  ->  business  5/0           by 17
    r182   40 (27 implemented)  ->  business 21/21 = 100%   by 13
    the other 11 runs                                       by 0-4

★ It cost a real conclusion. Reading r182's line I reported "68% of endpoints implemented,
against r177's 98%" as a difference between the runs. Both are **100%** on the half that is
the lane's work (21/21 and 27/27), and r173 -- which I used as the favourable comparison --
has a LARGER mixed gap than r182. The number invited exactly the wrong comparison.

★★ The first draft of the copy said the rest "stays `defined` by design", and the A/B over
real registries falsified it: of r182's 19 non-business endpoints, 13 are `defined` and SIX
are `implemented` (`/health` plus five auth paths a lane really did implement, which
#1202vl's path-based auth net excludes from BUSINESS). The line now reports the number that
actually reads as missing work, and claims nothing about the rest.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import delivery_gate as _dg  # noqa: E402
from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _business_endpoint_counts_1203i7,
    _business_half_1203i7,
    format_delivery_gate_report,
)


def _ep(method, path, status, kind=None):
    rec = {"id": "%s %s" % (method, path), "method": method, "path": path, "status": status}
    if kind:
        rec["metadata"] = {"kind": kind}
    return rec


#: r182's shape in miniature: business endpoints all implemented, framework surface mixed
R182 = {
    "GET /api/videos": _ep("GET", "/api/videos", "implemented"),
    "POST /api/comments": _ep("POST", "/api/comments", "implemented"),
    "POST /auth/register": _ep("POST", "/auth/register", "defined"),
    "POST /oauth/token": _ep("POST", "/oauth/token", "defined", kind="oauth"),
    "GET /.well-known/jwks.json": _ep("GET", "/.well-known/jwks.json", "defined"),
    "GET /api/v1/tenants": _ep("GET", "/api/v1/tenants", "defined"),
    "GET /health": _ep("GET", "/health", "implemented", kind="control"),
}


def _counts(eps):
    impl = len([v for v in eps.values() if str(v.get("status")) == "implemented"])
    return dict({"endpoints": len(eps), "implemented_endpoints": impl,
                 "tables": 3, "implemented_tables": 3, "pages": 4},
                **_business_endpoint_counts_1203i7(eps))


# ------------------------------------------------------------------ the business half


def test_the_business_half_is_counted_separately():
    c = _counts(R182)
    assert c["business_endpoints"] == 2, c
    assert c["implemented_business_endpoints"] == 2, c


def test_the_line_says_the_business_half_is_complete():
    out = _business_half_1203i7(_counts(R182))
    assert "2/2 BUSINESS endpoints implemented" in out, out


def test_an_unimplemented_business_endpoint_is_not_counted_as_done():
    """★ Every business endpoint in the r182 fixture IS implemented, so "count the
    implemented ones" and "count them all" give the same answer and a mutation swapping them
    survived a round. This fixture makes the two differ."""
    eps = dict(R182)
    eps["POST /api/comments"] = dict(eps["POST /api/comments"], status="implementing")
    c = _counts(eps)
    assert c["business_endpoints"] == 2, c
    assert c["implemented_business_endpoints"] == 1, c
    assert "1/2 BUSINESS endpoints implemented" in _business_half_1203i7(c)


def test_the_line_names_the_number_that_reads_as_missing():
    """★ Not "the rest stays defined" -- that was false for 6 of r182's 19. The useful
    number is: non-business AND not implemented."""
    c = _counts(R182)
    assert c["unimplemented_framework_endpoints"] == 4, c      # register/token/jwks/tenants
    out = _business_half_1203i7(c)
    assert "4 of them are not `implemented`" in out, out
    assert "NOT lane work" in out, out


def test_an_all_implemented_framework_surface_adds_no_tail():
    eps = dict(R182)
    for k in ("POST /auth/register", "POST /oauth/token",
              "GET /.well-known/jwks.json", "GET /api/v1/tenants"):
        eps[k] = dict(eps[k], status="implemented")
    out = _business_half_1203i7(_counts(eps))
    assert "BUSINESS endpoints implemented" in out, out
    assert "not `implemented`" not in out, out


def test_one_unimplemented_reads_as_singular():
    c = dict(_counts(R182), unimplemented_framework_endpoints=1)
    out = _business_half_1203i7(c)
    assert "1 of them is not `implemented` and is NOT lane work" in out, out


def test_a_registry_with_no_framework_surface_is_unchanged():
    """Silent when there is nothing to explain, so the line is byte-identical for the runs
    whose mixed total was already honest."""
    eps = {k: v for k, v in R182.items() if k.startswith(("GET /api/videos", "POST /api/comments"))}
    assert _business_half_1203i7(_counts(eps)) == "", _counts(eps)


# ------------------------------------------------------- absence is not zero


def test_unmeasured_counts_print_nothing():
    """#1202by's rule in this very function: a count that could not be measured must not be
    printed as zero."""
    for c in ({}, None, 7, {"endpoints": 40, "implemented_endpoints": 27},
              {"endpoints": 40, "business_endpoints": 21}):
        assert _business_half_1203i7(c) == "", c


class _BoomRegistry(dict):
    """★ Must be NON-EMPTY to bite: the producer does `(endpoints or {}).values()`, so an
    EMPTY hostile dict is replaced by a plain `{}` and never raises. The first version of
    this test used an empty one and asserted the wrong thing -- that the dict comes back
    with no keys -- when an empty registry legitimately yields zeros and the RENDERER is
    what keeps them off the page."""

    def __init__(self):
        super().__init__({"GET /api/x": {"path": "/api/x", "status": "implemented"}})

    def values(self):
        raise RuntimeError("registry unreadable")


def test_an_unreadable_registry_prints_nothing_rather_than_zeros():
    got = _business_endpoint_counts_1203i7(_BoomRegistry())
    assert got == {}, got
    # and the observable property, which is what #1202by's rule is actually about
    assert _business_half_1203i7(dict({"endpoints": 7, "implemented_endpoints": 3}, **got)) == ""


def test_an_empty_registry_prints_nothing_too():
    """Zeros are fine INSIDE the dict as long as nothing is printed from them."""
    got = _business_endpoint_counts_1203i7({})
    assert _business_half_1203i7(dict({"endpoints": 0, "implemented_endpoints": 0}, **got)) == ""


def test_junk_cannot_raise():
    for eps in (None, [], "", 7, {"a": 1}, {"a": None}):
        assert isinstance(_business_endpoint_counts_1203i7(eps), dict), eps


# ---------------------------------------------------- it reaches both report paths


def test_both_report_paths_carry_it():
    """The failing report is handed to lanes; the passing one is the run's summary. A reader
    of either must not have to subtract the framework surface in their head."""
    src = inspect.getsource(_dg.format_delivery_gate_report)
    assert src.count("_business_half_1203i7") == 2, src.count("_business_half_1203i7")


def test_the_failing_report_renders_it():
    gate = {"ok": False, "state": "failed", "failed_checks": ["business_chain_failing"],
            "hub_counts": _counts(R182)}
    out = format_delivery_gate_report(gate)
    assert "hub counts: endpoints=7" in out, out
    assert "2/2 BUSINESS endpoints implemented" in out, out


def test_the_passing_report_renders_it():
    gate = {"ok": True, "state": "ok", "failed_checks": [], "hub_counts": _counts(R182)}
    out = format_delivery_gate_report(gate)
    assert "2/2 BUSINESS endpoints implemented" in out, out


def test_the_existing_keys_are_untouched():
    """Additive: every other reader of hub_counts must see exactly what it saw before."""
    c = _counts(R182)
    for k in ("endpoints", "implemented_endpoints", "tables", "implemented_tables", "pages"):
        assert k in c, k
    assert c["endpoints"] == 7 and c["implemented_endpoints"] == 3, c
