r"""#766: a parsed-but-empty judge response scored 0.00 and was believed.

`_parse_verdict` has three shapes to handle. Two were already right:

    no JSON in the reply        -> 0.0 + judge_error
    JSON that will not parse    -> 0.0 + judge_error

The third was missed: **valid JSON carrying neither `similarity` nor a usable `dimensions`
block**. `sim` falls to the dimension average, the dimension list is empty, and the expression
ends `else 0.0` — a zero with NO flag, indistinguishable from an honest "this page looks nothing
like the reference".

A 0.0 the framework believes is expensive. It drags the blocking average, it counts as a real
judgment for #138's plateau, and #500's high-water merge then hides it from `verdict.json`, so
nobody reading the persisted record afterwards can see it happened.

**Not claimed as r150's cause.** r150 shipped v1.0.0 with 9 of 12 screens at 0.00 on its final
round while the gating average sat at 0.6778; the zeros oscillate across rounds (7 → 4 → 6 → 9)
on 1.4MB content-rich captures, with no judge error logged and only ONE screen classified as a
blank capture. That points at the measurement rather than the app — but the raw judge responses
are not kept, so this is a hole found while investigating, not a proven diagnosis.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _parse_verdict


# --- the missed shape ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "{}",
    '{"deviations": ["something"]}',
    '{"summary": "could not see the image"}',
    '{"dimensions": {}}',
    '{"dimensions": {"layout": "not-a-mapping"}}',
])
def test_a_parsed_but_empty_verdict_is_a_judge_error(payload):
    v = _parse_verdict(payload)
    assert v["judge_error"] is True, payload
    assert v["similarity"] == 0.0


def test_it_says_what_happened():
    v = _parse_verdict("{}")
    assert any("NON-VERDICT" in d for d in v["deviations"]), v["deviations"]


# --- an honest zero must survive ------------------------------------------------------------------

def test_an_explicit_zero_is_NOT_an_error():
    """The whole risk of this fix: a real 'nothing like the reference' verdict must still land."""
    v = _parse_verdict('{"similarity": 0.0}')
    assert v["similarity"] == 0.0
    assert "judge_error" not in v


def test_dimensions_that_average_to_zero_are_NOT_an_error():
    v = _parse_verdict('{"dimensions": {"layout": {"score": 0.0}, "colour": {"score": 0.0}}}')
    assert v["similarity"] == 0.0
    assert "judge_error" not in v


@pytest.mark.parametrize("payload,expected", [
    ('{"similarity": 0.72}', 0.72),
    ('{"dimensions": {"layout": {"score": 0.5}}}', 0.5),
    ('{"similarity": 1.5}', 1.0),        # clamped
    ('{"similarity": -3}', 0.0),         # clamped, and an explicit value
])
def test_a_real_verdict_is_untouched(payload, expected):
    v = _parse_verdict(payload)
    assert v["similarity"] == expected
    assert "judge_error" not in v


# --- the two paths that were already right stay right -----------------------------------------------

def test_no_json_still_errors():
    v = _parse_verdict("I could not process that image.")
    assert v["judge_error"] is True
    assert "judge returned no JSON" in v["deviations"][0]


def test_unparseable_json_still_errors():
    v = _parse_verdict('{"similarity": 0.7, ')
    assert v["judge_error"] is True


# --- provenance ------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(_parse_verdict)
    i = src.index("#766: PARSED, BUT EMPTY")
    return " ".join(l.strip().lstrip("#").strip() for l in src[i:src.index("if not scores:", i)].split("\n"))


def test_it_records_why_a_believed_zero_is_expensive():
    p = _prov()
    assert "counts as a real judgment for #138's plateau" in p
    assert "500's high-water merge then hides it" in p


def test_it_does_NOT_claim_to_be_r150s_cause():
    """The evidence points at the measurement, but the raw responses are gone. Overclaiming
    here would be the same error as the r149 'killed' turn."""
    p = _prov()
    assert "NOT claimed as r150's cause" in p
    assert "not a proven diagnosis" in p


def test_the_r150_numbers_are_recorded():
    p = _prov()
    assert "9 of 12 screens at 0.00" in p
    assert "0.6778" in p and "7 -> 4 -> 6 -> 9" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
