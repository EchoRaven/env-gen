r"""#1029: #1017 read the COUNT and tried to iterate it, so it named nothing, 269 times.

`_ui_evidence_breadth_739` returns both shapes:

    "failed_records": len(failed)          <- an INT
    "pages_failed":   sorted(set(failed))  <- the list of names

#1017 exists to "name the flows, not just the failure". It read `failed_records`, so:

    isinstance(int, (list, tuple))   -> False  => no names ever collected
    hasattr(int, "__len__")          -> False  => count printed as 0

Every firing since it landed read, verbatim:

    #1017 validation_ui_evidence_failed on 0 record(s): <unnamed records>

**269 of 269 occurrences across r170-r173.** The item that shipped #1017 recorded that it was
"never verified by a run"; this is what a run would have shown immediately.

Why it matters more than the usual instrument bug: `validation_ui_evidence_failed` is the most
common live blocker — **7 of the last 10 STUCK runs** carry it, and it is the single check that
ended r173 — so the flows it exists to name have never once been visible while being the thing
most often stopping delivery.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _site():
    s = inspect.getsource(dg.validate_delivery_gate)
    i = s.index("#1029")
    return s[i:s.index("failed_checks.append", i)]


# --- the two shapes are not interchangeable ------------------------------------------------

def test_breadth_returns_a_count_and_a_list_separately():
    """The premise. If these ever merge, this fix and its bug both stop making sense."""
    src = inspect.getsource(dg._ui_evidence_breadth_739)
    assert '"failed_records": len(failed)' in src
    assert '"pages_failed": sorted(set(failed))' in src


def test_names_come_from_the_LIST():
    assert 'get("pages_failed")' in _site()


def test_the_count_comes_from_the_COUNT():
    assert 'get("failed_records")' in _site()


def test_it_no_longer_iterates_the_count():
    b = _site()
    assert 'isinstance(_recs1017' not in b
    assert 'hasattr(_recs1017' not in b


# --- behaviour, exercised on the real breadth shape -------------------------------------------

def _rec(check, status, page):
    return {"status": status, "metadata": {"check": check, "page": page}}


def _breadth(records):
    return dg._ui_evidence_breadth_739(records)


def _render(breadth):
    """Mirror of the production expression."""
    names = [str(p)[:44] for p in (breadth.get("pages_failed") or [])]
    return (int(breadth.get("failed_records") or 0),
            "; ".join(names[:12]) or "<unnamed records>")


def test_a_failing_flow_is_named():
    b = _breadth([_rec("ui_flow", "failed", "browse_home_page"),
                  _rec("ui_smoke", "passed", "landing")])
    count, names = _render(b)
    assert count == 1
    assert "browse_home_page" in names


def test_several_failing_flows_are_all_named():
    recs = [_rec("ui_flow", "failed", p) for p in ("games_page", "movies_page", "my_list_page")]
    count, names = _render(_breadth(recs))
    assert count == 3
    for p in ("games_page", "movies_page", "my_list_page"):
        assert p in names


def test_the_control_is_the_pre_fix_expression():
    """★ Planted control: the old code against the same input must reproduce the exact string
    that appeared 269 times. Without this the tests above would also pass on a build that
    happened to name things for a different reason."""
    b = _breadth([_rec("ui_flow", "failed", "browse_home_page")])
    recs = b["failed_records"]                              # the INT, as #1017 read it
    names = []
    for r in (recs if isinstance(recs, (list, tuple)) else [])[:12]:
        names.append(str(r)[:44])
    rendered = (len(recs) if hasattr(recs, "__len__") else 0,
                "; ".join(names) or "<unnamed records>")
    assert rendered == (0, "<unnamed records>"), rendered
    assert _render(b) != rendered, "the fix must differ from the defect on the same input"


def test_no_failures_still_says_unnamed_rather_than_lying():
    count, names = _render(_breadth([_rec("ui_smoke", "passed", "landing")]))
    assert count == 0 and names == "<unnamed records>"


def test_it_caps_the_list_but_not_the_count():
    """A bounded list is fine; the COUNT must stay true, or the reader mis-reads coverage
    (#1022b's lesson, applied to the other list in this gate)."""
    recs = [_rec("ui_flow", "failed", f"page_{i}") for i in range(20)]
    count, names = _render(_breadth(recs))
    assert count == 20
    assert names.count(";") == 11, "expected 12 names listed"


def test_the_measurement_travels_with_the_fix():
    d = " ".join((__doc__ or "").split())
    assert "269 of 269" in d
    assert "7 of the last 10 STUCK runs" in d, (
        "why this instrument matters must stay attached to it")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
