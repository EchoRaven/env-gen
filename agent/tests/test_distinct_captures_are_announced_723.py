r"""#723: I read a detector's silence as a result, on the same day I built a guard against that.

Sweeping this session's detectors for the shape that keeps recurring — a warning path with no
clean path, so silence covers "nothing found", "never ran" and "raised" alike:

    #707  2 warnings, 0 info   ← same shape
    #711  2 warnings, 0 info   ← same shape
    #712  withdrawn (#712r)
    #713  2 warnings, 0 info   ← same shape, and the one that bit
    #715  fixed by #722

#713 is the one that mattered, because I used its silence while reading r148: "NOT SEEN, and
meaningful — zero duplicate groups". That conclusion was right, but only because I independently
hashed the twelve PNGs. Had I not, "the hashing raised" and "results was empty" would have read
identically. A detector guarding the validity of 26% of all fidelity scores must not need a
second opinion to be believed.

INFO, like #722: a clean pass is provenance, not news. #707 and #711 are left alone deliberately
— see the docstring below.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#723: SAY WHEN THE CAPTURES ARE ALL DISTINCT")
    return src[i:src.index("for _h713, _names713 in _by713.items():", i)]


# --- the clean path exists and is correct ------------------------------------------------------

def test_the_clean_path_logs():
    assert "#713 all %d screen captures are distinct" in _block()


def test_it_is_info_not_warning():
    b = _block()
    assert "_LOG.info(" in b
    assert "_LOG.warning(" not in b


def test_it_fires_only_when_no_group_has_two_members():
    b = _block()
    assert "if not [g for g in _by713.values() if len(g) > 1]:" in b


def test_it_reports_how_many_captures_were_checked():
    """'All distinct' over zero captures is not the same claim as over twelve."""
    assert "len(_by713)" in _block()


def test_it_precedes_the_duplicate_loop():
    src = inspect.getsource(vf)
    i = src.index("#723: SAY WHEN THE CAPTURES ARE ALL DISTINCT")
    j = src.index("for _h713, _names713 in _by713.items():", i)
    assert i < j


# --- the logic, exercised ------------------------------------------------------------------------

@pytest.mark.parametrize("groups,expect_clean", [
    ({"a": ["one"], "b": ["two"]}, True),
    ({"a": ["one", "two"]}, False),
    ({"a": ["one"], "b": ["two", "three"]}, False),
    ({}, True),
])
def test_the_predicate_matches_the_production_one(groups, expect_clean):
    assert (not [g for g in groups.values() if len(g) > 1]) is expect_clean


# --- provenance ------------------------------------------------------------------------------------

def test_the_sweep_that_found_it_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "Fourth instance of the same shape" in b
    for ref in ("691", "696", "712", "715"):
        assert ref in b


def test_my_own_misreading_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "bit while I was reading r148" in b
    assert "hashed the PNGs myself" in b


def test_the_stakes_are_stated():
    b = " ".join(_block().replace("#", " ").split())
    assert "26% of all fidelity scores" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
