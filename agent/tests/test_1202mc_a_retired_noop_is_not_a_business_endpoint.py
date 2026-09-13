"""#1202mc — `NOOP /noop`, deprecated, blocked a milestone no lane could unblock.

GROUND TRUTH (tiktok-web-r121 resume #3). M3 ended:

    16:28:13  STUCK — generation aborted without delivery after 21 coordination ticks:
              delivery never SUCCEEDED in 76min of lane time ...
              (now failing ['business_response_key_noncanonical', 'validation_ui_evidence_failed'])

`business_response_key_noncanonical` held exactly one instance, flat across the last twelve
gate evaluations (16:14:45 → 16:26:28), and it was:

    {"endpoint": "NOOP /noop", "response_key": "noop",
     "reason": "projected business endpoint declares non-canonical response_key='noop' —
                the projector emits {items/item} ... Use 'items' or 'item'."}

whose registry record reads

    {"id": "NOOP /noop", "method": "NOOP", "path": "/noop", "status": "deprecated",
     "metadata": {"response_key": "noop", "auth_required": true}}

`NOOP` is not an HTTP method, and `deprecated` is the documented way to retire a registration.
No lane could make that canonical, so the remedy the check prints was unreachable for it —
the #1202lr shape in a second reader: deprecation is the remedy the framework advertises, and
a gate ignores it.

★ How the ignoring was confirmed: a coarse scan of every `get_endpoints()` reader reported
this function as HANDLING deprecation. It does not — the word appears only in its comments.
The scan matched prose. Reading the filter chain settled it, which is why no bulk sweep was
shipped off that scan.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


class _RH:
    def __init__(self, eps):
        self._e = eps

    def get_endpoints(self):
        return self._e


class _Hubs:
    def __init__(self, eps):
        self.registryhub = _RH(eps)


R121_NOOP = {
    "NOOP /noop": {"id": "NOOP /noop", "method": "NOOP", "path": "/noop",
                   "status": "deprecated", "provider": "backend",
                   "metadata": {"response_key": "noop", "auth_required": True}},
}

LIVE_BAD = {
    "GET /api/videos": {"id": "GET /api/videos", "method": "GET", "path": "/api/videos",
                        "status": "implemented", "provider": "backend",
                        "metadata": {"response_key": "videos"}},
}


def _names(out):
    return sorted(str(x.get("endpoint")) for x in (out or []))


def test_r121s_own_blocker_is_gone():
    """★ The exact record that ended M3."""
    assert dg.noncanonical_business_response_keys(_Hubs(R121_NOOP)) == []


def test_a_live_endpoint_with_a_bad_key_still_blocks():
    """★ Non-vacuity: the check must keep its teeth for a real business endpoint."""
    assert _names(dg.noncanonical_business_response_keys(_Hubs(LIVE_BAD))) == ["GET /api/videos"]


def test_a_deprecated_http_endpoint_is_exempt():
    eps = {"GET /api/old": {"method": "GET", "path": "/api/old", "status": "deprecated",
                            "provider": "backend", "metadata": {"response_key": "old"}}}
    assert dg.noncanonical_business_response_keys(_Hubs(eps)) == []


@pytest.mark.parametrize("method", ["NOOP", "", None, "PROBE", "noop"])
def test_a_non_http_method_is_exempt_whatever_its_status(method):
    eps = {"X /x": {"method": method, "path": "/api/x", "status": "implemented",
                    "provider": "backend", "metadata": {"response_key": "x"}}}
    assert dg.noncanonical_business_response_keys(_Hubs(eps)) == []


@pytest.mark.parametrize("method", ["GET", "post", "Put", "PATCH", "delete"])
def test_every_real_verb_is_still_examined(method):
    """★ Case-insensitive, or the exemption swallows the check it guards."""
    eps = {"m /api/x": {"method": method, "path": "/api/x", "status": "implemented",
                        "provider": "backend", "metadata": {"response_key": "x"}}}
    assert len(dg.noncanonical_business_response_keys(_Hubs(eps))) == 1, method


def test_the_two_exemptions_are_general_not_a_path_match():
    """#251: an exemption must not depend on something a lane has to remember."""
    src = inspect.getsource(dg.noncanonical_business_response_keys)
    # Non-comment lines only: the fix's own comment QUOTES r121's record, which contains the
    # literal. Asserting on the whole source fails on the explanation of the fix — the third
    # time that trap has fired in this session, so it is worth naming here.
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("/noop" in ln for ln in code), (
        "a path-literal exemption is one more list to maintain (#251)")
    assert "_HTTP_METHODS_1202MC" in src
    assert 'status") or "").strip().lower() == "deprecated"' in src


def test_the_verb_set_is_the_real_set():
    assert dg._HTTP_METHODS_1202MC == frozenset(
        {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
