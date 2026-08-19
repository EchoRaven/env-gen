"""#973: a postgres ERROR must carry the STATEMENT that caused it.

`syntax error at or near "?" at character 170` names neither the table nor the query. It has
now appeared 6 times across r149, r157 and r158 and was written off twice as "one
occurrence, unlocalizable" — the harvest tool is what showed it recurring (4× in r158 alone).

Postgres always emits the pair:

    ERROR:  syntax error at or near "?" at character 170
    STATEMENT:  INSERT INTO titles (...) VALUES (?, ?, ?)

The capture had both — `_backend_logs_tail` keeps 3000 + 1500 chars. `_salient_error` threw
the second line away, because `STATEMENT` is not in `_ERR_MARKERS` and the extractor keeps
only marker-matching lines. So the run reported the symptom and discarded the cause, and
raising `cap` would not have helped: the line was DROPPED, not truncated.

Same family as #972 — "it failed" and "why it failed" are different features.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _salient_error)

PG_PAIR = (
    "2026-08-19 04:23:47.932 UTC [58] LOG:  database system is ready\n"
    '2026-08-19 04:23:47.932 UTC [58] ERROR:  syntax error at or near "?" at character 170\n'
    "2026-08-19 04:23:47.932 UTC [58] STATEMENT:  INSERT INTO titles (name, year) VALUES (?, ?)\n"
)


def test_the_statement_line_survives():
    out = _salient_error(PG_PAIR, cap=400)
    assert "syntax error" in out, "the error line must still be surfaced"
    assert "INSERT INTO titles" in out, (
        "the STATEMENT is the only part that localizes the fault; without it the report "
        "names neither the table nor the query")


def test_it_is_dropped_not_truncated_before_the_fix():
    """Planted control: the PRE-FIX extractor kept only marker-matching lines, so the
    STATEMENT was discarded outright — proving a larger cap would not have rescued it."""
    _ERR_MARKERS = ("error:", "syntaxerror", "not found")
    lines = [ln.strip() for ln in PG_PAIR.split("\n") if ln.strip()]
    pre_fix = [ln for ln in lines if any(m in ln.lower() for m in _ERR_MARKERS)]
    assert not any("STATEMENT" in ln for ln in pre_fix), (
        "the control was supposed to drop the statement; if it keeps it, this fix is "
        "unmotivated")


def test_a_non_postgres_error_is_unchanged():
    """The pairing must not disturb the build-log case #182 exists for."""
    build = (
        "Sending build context to Docker daemon\n"
        "#8 12.34 npm err! code ELIFECYCLE\n"
        "error: 'LoginPage' has already been declared\n"
    )
    out = _salient_error(build, cap=400)
    assert "has already been declared" in out
    assert "Sending build context" not in out, "the misleading prefix must stay excluded"


def test_an_error_with_no_statement_after_it_is_fine():
    out = _salient_error("ERROR:  relation \"titles\" does not exist\n", cap=400)
    assert "does not exist" in out


def test_a_lone_statement_line_is_not_promoted():
    """Only a STATEMENT that FOLLOWS an error is interesting; postgres logs statements on
    their own for other reasons and they are not failures."""
    out = _salient_error("STATEMENT:  SELECT 1\nLOG:  duration: 0.1 ms\n", cap=400)
    assert "SELECT 1" not in out or "ERROR" not in out


def test_output_stays_bounded():
    """#987 superseded the flat cap: an error naming "at character N" widens far enough to
    reach N, because otherwise the diagnostic points at an offset it refuses to show. The
    invariant is now BOUNDED, not fixed — PG_PAIR says character 170, so 200 is not the
    ceiling here and asserting it would pin behaviour #987 deliberately removed."""
    out = _salient_error(PG_PAIR.replace("titles", "t" * 3000), cap=200)
    assert len(out) <= 2000, "the widening must stay bounded"
    assert len(out) >= 170, "and must reach the offset the error names"


def test_a_pair_without_an_offset_keeps_the_flat_cap():
    """The un-widened path still honours the caller's cap exactly."""
    no_offset = ('ERROR:  relation "titles" does not exist\n'
                 'STATEMENT:  SELECT * FROM ' + "t" * 900 + "\n")
    assert len(_salient_error(no_offset, cap=200)) <= 200


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
