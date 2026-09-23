r"""#1202rm: every page declaring `apis_used: []` while the backend has a contract.

`apis_used` is read in 103 places across six modules. Several judgements need it non-empty:
#151's decoy-twin check requires `apis` before it inspects what the route renders, the
consumer-wiring audit has nothing to reconcile without it, and a page's defined->implemented
flip stops asking whether its own APIs are referenced.

So a lane that registers every page with an empty list does not FAIL those checks — it switches
them off, silently and all at once. Measured, and worsening: r128 7 of 10 pages empty, r129 8
of 13, r130 14 of 14, r131 13 of 13. r131 is the run where an unprimed agent found nine of
twelve pages rendering a mock module (#1202rl), and nothing in the framework had said a word
about a video app whose every page claims to need no data.

A contradiction, not a threshold: r130 registered 14 pages against 26 business endpoints, r131
13 against 34. An app with no business endpoints is a different thing and is not flagged.

The first draft called `rh.list_endpoints()`. The real method is `get_endpoints`; the
AttributeError landed in the outer except and the gate returned [] on every run — passing r130
and r131, the two runs it was written for. It looked healthy and detected nothing. Validating
on known samples is what caught it.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import deliverability as D  # noqa: E402


class _RH:
    def __init__(self, pages, endpoints):
        self._p, self._e = pages, endpoints

    def list_ui_pages(self):
        return self._p

    def get_endpoints(self):
        return self._e


class _Hubs:
    def __init__(self, rh):
        self.registryhub = rh


def _biz(n):
    return {f"GET /api/r{i}": {"kind": "business"} for i in range(n)}


def test_the_r131_shape_is_caught():
    pages = {f"p{i}": {"apis_used": []} for i in range(13)}
    out = D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, _biz(34))))
    assert out and "13 registered ui_page(s)" in out[0] and "34 business endpoint" in out[0]


def test_one_declaring_page_is_enough_to_pass():
    """This is the all-empty contradiction, not a coverage metric."""
    pages = {f"p{i}": {"apis_used": []} for i in range(12)}
    pages["p12"] = {"apis_used": ["GET /api/videos"]}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, _biz(34)))) == []


def test_an_app_with_no_business_contract_is_not_flagged():
    """A genuinely static site registers no business endpoints; it is a different thing."""
    pages = {f"p{i}": {"apis_used": []} for i in range(5)}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, {}))) == []


def test_infra_and_auth_endpoints_do_not_count_as_a_contract():
    """/health, /auth/login and the tenant control plane exist in every env."""
    eps = {"GET /health": {"kind": "infra"}, "POST /auth/login": {"kind": "auth"},
           "POST /oauth/token": {"kind": "oauth"}}
    pages = {f"p{i}": {"apis_used": []} for i in range(5)}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, eps))) == []


def test_the_fixed_surface_is_recognised_by_PATH_when_kind_is_absent():
    """A registration that omits `kind` leaves an empty string, and the first draft counted
    /health and /auth/register as business -- an existing regression test registering exactly
    those two read as "a contract with 2 business endpoints" and the gate fired on it."""
    eps = {"GET /health": {"path": "/health"},
           "POST /auth/register": {"path": "/auth/register"}}
    pages = {"home": {"apis_used": []}}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, eps))) == []


def test_a_real_business_route_without_kind_still_counts():
    """The path filter must not swallow the signal it exists to read."""
    eps = {f"GET /api/videos/{i}": {"path": f"/api/videos/{i}"} for i in range(4)}
    pages = {"home": {"apis_used": []}}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, eps)))


def test_no_pages_at_all_is_not_this_finding():
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH({}, _biz(9)))) == []


def test_the_meta_key_is_not_counted_as_a_page():
    pages = {"_meta": {"version": 3}, "p1": {"apis_used": ["GET /api/x"]}}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, _biz(9)))) == []


def test_a_registry_without_the_method_is_not_a_verdict():
    class _Bare:
        def list_ui_pages(self):
            return {"p1": {"apis_used": []}}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_Bare())) == []


def test_the_message_says_the_checks_are_switched_off_not_failed():
    """A reader who thinks the other gates ran and passed draws the opposite conclusion."""
    pages = {f"p{i}": {"apis_used": []} for i in range(4)}
    out = D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, _biz(9))))[0]
    assert "turns those checks OFF rather than failing them" in out


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ENVGEN_PAGE_API_DECLARATION_GATE", "0")
    pages = {f"p{i}": {"apis_used": []} for i in range(13)}
    assert D._no_page_declares_an_api_1202rm(_Hubs(_RH(pages, _biz(34)))) == []


def test_the_gate_is_reachable_from_the_blocker_list():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "deliverability.py").read_text(encoding="utf-8")
    assert src.count("blockers.extend(_no_page_declares_an_api_1202rm") == 1
