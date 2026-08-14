r"""#722: #715 had two warnings and no third, so silence meant three different things.

#715 checks that the frontend the browser is about to photograph was built from the current
source. It warns when the served bundle is missing routes (a stale build) and warns when nearly
all routes are missing (a suspect probe). It said nothing when everything matched — and nothing
is also what it says when it never ran, or when a guard above skipped it.

r148 is that ambiguity in the flesh. Neither warning appears, and grepping the log for "#715"
returns six hits that are all timestamp milliseconds (`10:44:42,715`). The one check built to
answer item 34's source-vs-served question told us nothing about the run it was built for.

That is the same shape as #691's silent skip, #696's invisible load failure and #712's dead
branch: a detector whose output is unobservable is indistinguishable from one that never
executed. It is the most-repeated finding of this session and it landed on a fix written to
address it.

INFO, not WARNING: a clean probe is not news, it is provenance. The point is only that "checked,
matched" and "never checked" stop looking identical.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _probe() -> str:
    src = inspect.getsource(vf)
    i = src.index("#715 probe inconclusive")
    return src[i:src.index("screens = map_reference_screens", i)]


# --- all three outcomes are now distinguishable -------------------------------------------------

def test_the_clean_path_logs():
    assert "#715 served build matches the source" in _probe()


def test_the_clean_path_is_info_not_warning():
    p = _probe()
    i = p.index("#715 served build matches the source")
    head = p[:i]
    assert head.rstrip().endswith("_LOG.info(") or "_LOG.info(" in head[-200:]


def test_the_two_warning_paths_survive():
    p = _probe()
    assert "#715 probe inconclusive" in p
    assert "#715 the SERVED frontend does not know" in p


def test_the_clean_path_is_the_else_of_the_stale_one():
    """It must not fire alongside a staleness report."""
    p = _probe()
    i = p.index("if _missing715:")
    j = p.index("#715 served build matches the source")
    assert i < j
    assert "else:" in p[i:j]


def test_it_reports_how_many_routes_were_checked():
    """'Clean' over zero routes is not the same claim as clean over fifteen."""
    p = _probe()
    assert "len(known_routes)" in p[p.index("#715 served build matches"):]


# --- the ambiguity it removes is recorded ----------------------------------------------------------

def test_the_three_states_are_named():
    b = " ".join(_probe().replace("#", " ").split())
    assert "the probe ran and found nothing" in b
    assert "the probe never ran" in b
    assert "skipped by a guard" in b


def test_r148s_ambiguity_is_the_evidence():
    b = " ".join(_probe().replace("#", " ").split())
    assert "r148" in b
    assert "timestamp milliseconds" in b


def test_it_names_the_family_it_belongs_to():
    b = " ".join(_probe().replace("#", " ").split())
    for ref in ("691", "696", "712"):
        assert ref in b


def test_why_info_and_not_warning_is_stated():
    b = " ".join(_probe().replace("#", " ").split())
    assert "not news, it is provenance" in b


# --- it cannot break the probe -----------------------------------------------------------------------

def test_the_whole_probe_is_still_guarded():
    p = _probe()
    assert "except Exception:" in p


def test_the_clean_branch_adds_no_control_flow():
    p = _probe()
    tail = p[p.index("#715 served build matches the source"):]
    stmts = [l.strip() for l in tail.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l.startswith(("return", "raise ")) or l == "raise"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
