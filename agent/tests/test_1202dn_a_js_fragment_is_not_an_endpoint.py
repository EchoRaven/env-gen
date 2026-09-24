r"""#1202dn: the frontend-call scanner hands the gate JavaScript, and the gate blocks on it.

#494 found this exact failure once already: an unstripped `?kind=movie` made `param_agnostic`
mangle `/api/titles` into `/api/:p`, which matched no declared key, and r65's delivery was
hard-blocked by a FALSE "Frontend calls unregistered endpoint" error for an endpoint that was
registered. It fixed the `?` case by stripping the query first.

netflix-r44 (2026-09-05 15:41:46) is the same bug through a different separator. The delivery
gate reported, verbatim:

    ERROR: Frontend calls unregistered endpoint(s) (register in RegistryHub):
      GET /api/continue-watching:qs({ profile_id: getProfileId() )},
      GET /api/genres/${requireId(id, ,
      GET /api/my-list:qs({ profile_id: getProfileId() )},
      GET /api/search:qs({ q: query, limit )},
      GET /api/titles:qs(params)

Those are not paths, they are source fragments — a call helper and a template literal that the
extractor read past the end of the path. Every one of the five base endpoints IS registered
(checked against the run's own registryhub_endpoints.json, 37 entries):

    GET /api/continue-watching   GET /api/genres   GET /api/my-list
    GET /api/search              GET /api/titles

So the gate blocked delivery on drift that does not exist, which is the failure class this
repo keeps paying for: a false blocker wedges a run (#566j), and here it sat alongside the
real failures in the same report, indistinguishable from them.

Stripping applies to the CALL side only. `param_agnostic` is also used on declared endpoints,
and `{}` is legitimate there (`GET /api/genres/{}/titles`) — cutting it on both sides would
turn a specific declared path into a prefix and start MASKING real drift, trading a false
positive for a false negative.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _strip_source_fragment_1202dn,
)


@pytest.mark.parametrize("raw,want", [
    # the five r44 reported, verbatim
    ("GET /api/continue-watching:qs({ profile_id: getProfileId() )}",
     "GET /api/continue-watching"),
    ("GET /api/my-list:qs({ profile_id: getProfileId() )}", "GET /api/my-list"),
    ("GET /api/search:qs({ q: query, limit )}", "GET /api/search"),
    ("GET /api/titles:qs(params)", "GET /api/titles"),
])
def test_the_call_helper_fragments_r44_blocked_on(raw, want):
    assert _strip_source_fragment_1202dn(raw) == want


@pytest.mark.parametrize("clean", [
    "GET /api/titles",
    "POST /api/my-list",
    "DELETE /api/my-list/{}",
    "GET /api/genres/{}/titles",
    "GET /health",
    "/api/titles",
])
def test_a_real_path_is_untouched(clean):
    """Including `{}` params — the declared form must survive verbatim."""
    assert _strip_source_fragment_1202dn(clean) == clean


def test_the_query_case_494_already_fixed_still_works():
    """`?` is handled downstream; this must not interfere with it."""
    assert _strip_source_fragment_1202dn("GET /api/titles?kind=movie") == \
        "GET /api/titles?kind=movie"


def test_a_well_formed_template_param_is_left_alone():
    """`${x}` is a PARAMETER. `param_agnostic` normalises it to the same `:p` that the
    declared `/api/posts/:id` becomes, and they match. An earlier, wider cut at `$` broke
    exactly that and manufactured a NEW false positive (test_contract_extract_stacks)."""
    assert _strip_source_fragment_1202dn("GET /api/posts/${x}") == "GET /api/posts/${x}"
    assert _strip_source_fragment_1202dn("GET /api/genres/${id}/titles") == \
        "GET /api/genres/${id}/titles"


def test_a_truncated_template_is_deliberately_not_guessed():
    """r44's fifth case. The scanner stopped mid-expression; reconstructing the path would
    be guessing, and that is how a false positive becomes a false negative that hides real
    drift. It stays reported — the defect belongs to the extractor."""
    raw = "GET /api/genres/${requireId(id, "
    assert _strip_source_fragment_1202dn(raw) == raw


def test_genuine_drift_is_still_reported():
    """The check must keep catching a real unregistered path."""
    assert _strip_source_fragment_1202dn("GET /api/not-registered") == "GET /api/not-registered"
