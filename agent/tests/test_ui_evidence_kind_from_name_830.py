r"""#830: the UI-evidence detector could not see 645 records, and that rejected a gate.

`_ui_evidence_breadth_739` keys on `metadata.check`. #193/#236 recover that kind from `evidence`
when a writer nests it — but a writer that puts the kind ONLY in the record NAME
(`validation:ui_flow:landing`) leaves nothing to recover.

    UI records with the kind only in the name, invisible   645
    runs called "no UI evidence" that HAVE ui_flow records  36   (up to 13 records each)

★ A DETECTOR BUG, not a policy change: #752 blocks on "UI evidence that both passes and fails",
and the detector was not seeing all the evidence that policy refers to.

**It also rejected a gate on a wrong number.** #671 was turned down as "a halt, not a gate"
because 45% of runs had no UI evidence at all. Reading the kind from the name:

    runs with NO UI evidence   62 -> 26   (45% -> 17%)

17% is the order of #751's 13%, which WAS approved. Effect on #752's reach: r130+ 3 -> 4;
corpus-wide 10 -> 22. All three numbers were predicted before the change and matched after it.

This file is a RE-CREATION: the original was deleted from the working tree by a concurrent writer
before it was ever committed, leaving a shipped detector change with no test at all. The fix is in
HEAD; this restores its cover.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ui_evidence_breadth_739 as breadth)


def _rec(name, status, check=None):
    return {"name": name, "status": status,
            "metadata": ({"check": check} if check else {}), "updated_at": 1}


def test_the_kind_is_read_from_metadata_when_present():
    """Non-regression: the existing path must be untouched."""
    assert breadth([_rec("validation:ui_smoke:login", "passed", check="ui_smoke")])[
        "passed_records"] == 1


def test_the_kind_is_recovered_from_the_name():
    """★ The 645 records. r5 has 13 of these; the detector counted zero."""
    assert breadth([_rec("validation:ui_flow:landing", "passed")])["passed_records"] == 1


def test_a_failing_name_only_record_counts_too():
    """#752 blocks on failed_records; under-counting them means under-blocking."""
    assert breadth([_rec("validation:ui_flow:browse", "failed")])["failed_records"] == 1


@pytest.mark.parametrize("kind", ["ui_smoke", "ui_flow", "ui_page_reachable"])
def test_every_ui_kind_is_recovered(kind):
    assert breadth([_rec(f"validation:{kind}:x", "passed")])["passed_records"] == 1


def test_metadata_wins_over_the_name():
    """The name is a FALLBACK. A record that declares its kind keeps it — otherwise a misleading
    name would silently reclassify a record that was already correct."""
    assert breadth([_rec("validation:ui_flow:x", "passed", check="api_smoke")])[
        "passed_records"] == 0


def test_a_non_ui_record_is_not_dragged_in():
    """Non-vacuity: the fallback must not turn every named record into UI evidence."""
    assert breadth([_rec("validation:api_smoke:x", "passed")])["passed_records"] == 0
    assert breadth([_rec("build:frontend", "passed")])["passed_records"] == 0


def test_a_bare_kind_at_the_end_of_a_name_is_recovered():
    assert breadth([_rec("validation:ui_smoke", "passed")])["passed_records"] == 1


def test_a_substring_is_not_a_match():
    """`my_ui_flowchart` is not a ui_flow record; the boundaries have to hold."""
    assert breadth([_rec("validation:my_ui_flowchart:x", "passed")])["passed_records"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
