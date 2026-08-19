"""#987: an error that says "at character 255" must show at least 255 characters.

#973 taught `_salient_error` to keep the postgres STATEMENT beside its ERROR. r160 proved it
works and then showed the next link in the chain:

    ERROR: syntax error at or near "?" at character 255 | … STATEMENT:  CREATE TABLE IF NOT
    EXISTS "titles" (

The statement is there and truncated at the 200-char cap. The offending token sits at
character 255 — beyond the cap BY CONSTRUCTION, because postgres reports the offset precisely
when the problem is deep inside a long statement. The diagnostic pointed at a location and
then withheld it.

Widen only when the error names an offset, only far enough to reach it, and never past 2000.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    _salient_error)

LONG_DDL = (
    'ERROR:  syntax error at or near "?" at character 255\n'
    'STATEMENT:  CREATE TABLE IF NOT EXISTS "titles" (' + ' "col_%d" TEXT,' * 1 % (0,)
    + ' "pad" TEXT,' * 20 + ' "broken" ? NOT NULL);\n'
)


def test_the_offending_token_is_reachable():
    out = _salient_error(LONG_DDL, cap=200)
    assert len(out) > 255, f"cap did not widen to the reported offset: {len(out)}"
    assert "broken" in out, "the column named at the offset must be visible"


def test_an_error_without_an_offset_keeps_the_caller_cap():
    plain = "ERROR:  relation \"titles\" does not exist\n" + "x" * 900
    assert len(_salient_error(plain, cap=200)) <= 200


def test_the_widening_is_bounded():
    huge = 'ERROR:  syntax error at character 99999\nSTATEMENT:  ' + "y" * 50_000
    assert len(_salient_error(huge, cap=200)) <= 2000


def test_a_smaller_offset_does_not_shrink_the_cap():
    """max(), not assignment — a caller asking for 600 must not be cut to 40."""
    src = 'ERROR:  syntax error at character 10\nSTATEMENT:  ' + "z" * 900
    assert len(_salient_error(src, cap=600)) == 600


def test_the_build_log_case_is_untouched():
    """#182's behaviour must survive: no offset, no widening."""
    build = ("Sending build context\n"
             "error: 'LoginPage' has already been declared\n")
    out = _salient_error(build, cap=400)
    assert "has already been declared" in out
    assert "Sending build context" not in out


def test_the_control_truncates_before_the_offset():
    """Planted control: the PRE-FIX behaviour — a flat cap — cuts before character 255,
    which is exactly what r160 printed."""
    flat = " | ".join(LONG_DDL.strip().split("\n"))[:200]
    assert "broken" not in flat, (
        "the control was supposed to hide the offending column; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
