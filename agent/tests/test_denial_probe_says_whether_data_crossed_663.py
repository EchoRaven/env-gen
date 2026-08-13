r"""#663: "DENIAL-PROBE got success" could not tell a P0 leak from a wrong status code.

`registryhub_verification_chains.json` — 3533 chains over 133 runs — was the last big unmined
store, and it is the only artifact in the corpus that records FUNCTIONAL contract outcomes
rather than pixels. In the current era (r100+) it holds 44 failing chains across 13 runs, and
the largest single class of broken assertion is:

    DENIAL-PROBE got success — the request was NOT rejected    x20, in 8 runs
    (r117 r127 r130 r131 r133 r135 r141 r143)
    on GET /api/my-list x6, GET /api/continue-watching x5, POST /api/my-list x4,
    POST /api/titles/N/rating x3, POST /api/profiles x1, POST /api/continue-watching x1

#188 already made the note honest about the ambiguity — "an auth/isolation hole, OR a
mis-authored probe" — but left it unresolved, and the two readings are a P0 and a nit:

    the server STORED the id the caller named    -> a cross-user write. P0.
    the server SUBSTITUTED the caller's own id   -> no data crossed; but the request should
                                                    have been refused, not silently rebound.

The evidence was in hand and being discarded. The resolved request body carries the id the
prober sent; the response carries the id that was stored. Comparing them decides it.

Worked r127's `rating_upsert_and_isolation` by hand first: its step 5 is a correctly-authored
probe (`auth: tokenB`, body `profile_id: ${profileA_id}`) that got 201 instead of 403, and the
response shows `profile_id: 19` — but `last_result.steps` records only method/path/status/ok/
note, so `profileA_id` is unrecoverable and the class CANNOT be determined from the artifact.
That gap is the whole reason for this fix.

(Two of my own reading errors on the way: `last_result` is a string repr of a dict, not a dict,
so a first pass reported "no failure detail"; and my first dump of the chain steps omitted the
`auth` key, which briefly made a correctly-authored probe look mis-authored.)
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _denial_scope_verdict_663 as verdict,
)

_SENT = {"value": "love", "profile_id": 19}


# --- the two classes ---------------------------------------------------------------------------

def test_an_echoed_id_is_reported_as_a_boundary_crossing():
    out = verdict(_SENT, '{"item":{"id":18,"profile_id":19,"title_id":1}}')
    assert "BOUNDARY CROSSED" in out
    assert "profile_id=19" in out


def test_the_crossing_verdict_says_it_is_an_isolation_hole():
    out = verdict(_SENT, '{"item":{"id":18,"profile_id":19}}')
    assert "data-isolation hole" in out
    assert "not a status-code nit" in out


def test_a_substituted_id_is_reported_as_a_wrong_status_not_a_leak():
    out = verdict(_SENT, '{"item":{"id":18,"profile_id":42}}')
    assert "no data crossed" in out
    assert "SUBSTITUTED" in out
    assert "sent 19" in out and "stored 42" in out


def test_the_substitution_verdict_still_calls_it_a_defect():
    """A silent rebind is not a leak, but it is not acceptable either."""
    out = verdict(_SENT, '{"item":{"id":18,"profile_id":42}}')
    assert "must be refused, not silently rebound" in out


def test_crossing_wins_when_both_kinds_are_present():
    """One echoed id is a leak regardless of how many other fields were rewritten."""
    out = verdict({"profile_id": 19, "value": "love"},
                  '{"item":{"profile_id":19,"value":"LOVE"}}')
    assert "BOUNDARY CROSSED" in out


# --- it must never make the note worse -----------------------------------------------------------

@pytest.mark.parametrize("sent,body", [
    (None, '{"item":{}}'),
    ({"a": 1}, None),
    ({"a": 1}, ""),
    ({"a": 1}, "not json at all"),
    ({}, '{"item":{"a":1}}'),
    ({"a": 1}, '{"item":{"b":2}}'),      # no overlapping key
    ({"a": 1}, '[1,2,3]'),               # not an object
])
def test_it_returns_nothing_when_it_cannot_decide(sent, body):
    assert verdict(sent, body) == ""


def test_nested_containers_are_not_compared():
    """A list/dict field echoing back proves nothing about ownership."""
    assert verdict({"tags": [1, 2]}, '{"item":{"tags":[1,2]}}') == ""


def test_a_null_sent_value_is_ignored():
    assert verdict({"profile_id": None}, '{"item":{"profile_id":null}}') == ""


# --- the response envelope --------------------------------------------------------------------

@pytest.mark.parametrize("key", ["item", "data", "result", "record"])
def test_it_unwraps_the_common_envelopes(key):
    out = verdict(_SENT, '{"%s":{"profile_id":19}}' % key)
    assert "BOUNDARY CROSSED" in out


def test_a_bare_object_works_too():
    assert "BOUNDARY CROSSED" in verdict(_SENT, '{"profile_id":19}')


def test_string_and_int_ids_compare_equal():
    """Chains save ids out of JSON; the round trip can change the type."""
    assert "BOUNDARY CROSSED" in verdict({"profile_id": "19"}, '{"item":{"profile_id":19}}')


# --- wiring -------------------------------------------------------------------------------

def test_the_denial_note_calls_it():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce)
    i = src.index("DENIAL-PROBE got success — the request was NOT rejected")
    tail = src[i:src.index("FIX #188 causality", i)]
    assert "_denial_scope_verdict_663(body, res.get(\"body_text\"))" in tail


def test_it_precedes_the_raw_error_text():
    """The classification must lead; the raw body is context, not the headline."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce)
    i = src.index("DENIAL-PROBE got success — the request was NOT rejected")
    tail = src[i:src.index("FIX #188 causality", i)]
    assert tail.index("_denial_scope_verdict_663") < tail.rindex("+ note")


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    flat = " ".join(inspect.getsource(ce._denial_scope_verdict_663).replace("#", " ").split())
    assert "20 of the current era's broken assertions" in flat
    assert "r117/127/130/131/133/135/141/143" in flat


def test_the_unresolvable_case_that_motivated_it_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    flat = " ".join(inspect.getsource(ce._denial_scope_verdict_663).split())
    assert "rating_upsert_and_isolation" in flat
    assert "could not be determined" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
