r"""#566v (netflix r130): the #78 cross-user-denial re-verify only checked STATUS, so it false-flagged a
SECURE-override READ (a fresh intruder's owner-scoped GET returns their OWN empty view -> 2xx) as a leak,
which forced the lane to over-correct GET my-list to 403-on-own, oscillating and wedging M1. Fix: for a
GET denial probe, a fresh intruder's 2xx is a real leak ONLY if the response carries ROWS (the foreign
owner's data); an empty list = secure -> tolerate. Never masks a leak (a leak returns rows -> kept broken).
"""

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _response_has_rows,
)


def test_empty_list_envelopes_are_no_rows():
    assert _response_has_rows('{"items": [], "total": 0}') is False
    assert _response_has_rows('{"data": []}') is False
    assert _response_has_rows('{"results": []}') is False
    assert _response_has_rows('{"rows": []}') is False
    assert _response_has_rows("[]") is False


def test_nonempty_list_envelopes_have_rows():
    assert _response_has_rows('{"items": [{"id": 1}]}') is True
    assert _response_has_rows('{"data": [{"id": 9}, {"id": 10}]}') is True
    assert _response_has_rows('[{"id": 1}]') is True


def test_ambiguous_payloads_are_conservative_keep_leak_verdict():
    # unparseable / non-list / unrecognized envelope -> True (never mask a possible leak)
    assert _response_has_rows("not json") is True
    assert (
        _response_has_rows('{"id": 1, "name": "x"}') is True
    )  # single-object, no list envelope
    assert _response_has_rows("") is True
    assert _response_has_rows(None) is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
