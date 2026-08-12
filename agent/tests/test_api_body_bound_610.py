r"""#610: an API test result was unbounded, and pretty-printed on top.

Seventh finding on the cost axis. `test_api` returned the whole response body, re-serialised with
`indent=2`. Over the arc's run logs it returned a **median of 44,783 chars and a max of 274,327**
— 2.34M tokens over 209 calls — for a call whose question is "did this endpoint answer
correctly".

Two separate costs, fixed separately:
  * `indent=2` is pure inflation for a machine reader. Modelled over 346 real seeded collection
    responses, pretty-printing costs **34% more** than compact JSON for identical information.
  * the body is unbounded. Truncating raw text would hide the very field the agent is checking
    and leave invalid JSON, so a LIST-shaped envelope keeps its SHAPE: the first 5 items survive
    intact and the rest become a count. The agent still sees the envelope, a representative
    sample, and the true total.
"""
import json

import pytest

from env_generator.llm_generator.tools.runtime_tools import (
    _API_BODY_CHARS_610 as CAP,
    _API_BODY_ITEMS_610 as K,
    _bound_api_body_610 as bound,
)


# --- the shape is preserved ---------------------------------------------------------------

def test_a_collection_keeps_its_envelope_a_sample_and_the_true_total():
    body = json.dumps({"items": [{"id": i} for i in range(60)], "total": 60})
    out = json.loads(bound(body))
    assert out["total"] == 60                      # the envelope's own field is untouched
    assert out["items"][:K] == [{"id": i} for i in range(K)]
    assert "55 more items omitted; 60 total" in out["items"][-1]


def test_the_result_is_still_valid_json():
    body = json.dumps({"items": [{"id": i} for i in range(60)]})
    json.loads(bound(body))                        # would raise on a raw truncation


def test_a_bare_list_body_is_handled_too():
    out = json.loads(bound(json.dumps([{"id": i} for i in range(30)])))
    assert len(out) == K + 1 and "25 more items omitted; 30 total" in out[-1]


def test_a_short_collection_is_untouched():
    body = {"items": [{"id": 1}, {"id": 2}], "total": 2}
    assert json.loads(bound(json.dumps(body))) == body


def test_every_list_field_in_the_envelope_is_bounded():
    body = json.dumps({"items": list(range(40)), "errors": list(range(40))})
    out = json.loads(bound(body))
    for f in ("items", "errors"):
        assert len(out[f]) == K + 1, f


# --- compaction -------------------------------------------------------------------------------

def test_pretty_printing_is_dropped():
    body = json.dumps({"a": {"b": 1}}, indent=2)
    out = bound(body)
    assert "\n" not in out and out == '{"a": {"b": 1}}'


def test_an_error_detail_is_never_clipped_away():
    """The single most actionable body there is — a 4xx/5xx detail — must survive whole."""
    body = json.dumps({"detail": "user_id does not belong to the caller"})
    assert json.loads(bound(body)) == {"detail": "user_id does not belong to the caller"}


# --- non-JSON and extremes -----------------------------------------------------------------------

def test_non_json_short_text_passes_through_verbatim():
    assert bound("plain OK") == "plain OK"


def test_non_json_long_text_is_truncated_and_says_the_real_length():
    raw = "y" * (CAP + 500)
    out = bound(raw)
    assert out.startswith("y" * 100)
    assert f"{CAP + 500} chars total" in out


def test_a_still_huge_json_body_is_capped_and_says_the_real_length():
    body = json.dumps({"blob": "z" * (CAP * 2)})     # one long scalar, no list to trim
    out = bound(body)
    assert len(out) <= CAP + 80 and "chars total" in out


def test_junk_input_cannot_raise():
    for v in ("", "{", None, 7):
        bound(v)


# --- wiring ---------------------------------------------------------------------------------------

def test_both_the_success_and_the_HTTPError_path_are_bounded():
    import inspect
    from env_generator.llm_generator.tools import runtime_tools as rt
    src = inspect.getsource(rt)
    i = src.index('NAME = "test_api"')
    blk = src[i:src.index("\nclass ", i)]
    assert blk.count("_bound_api_body_610(") == 2
    assert "indent=2" not in blk


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
