"""#1203ko: the cause line said "MCP surface INCOMPLETE" twice in one sentence.

    MCP surface INCOMPLETE (9/23 tools; MCP surface INCOMPLETE: 9 tool(s) for 23 endpoint(s))

`describe_non_pass_1038` formats its own prefix and then appends `mcp["note"]`, which opens
with the same words. #1203kg then made that note longer — it now carries WHY the count is
short — so the duplicate prefix pushes the part a reader needs further back.

Honest about the harm: the consumer is a `logger.warning` with no cap, so nothing was being
truncated. The cost is readability, and it is paid on every incomplete-MCP report — 17 of the
36 modern ones.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_validation import (  # noqa: E402
    describe_non_pass_1038 as DESCRIBE)

_SUMM = {"broken": [], "missing": [], "api_steps": 1, "mcp_complete": False}
_PRE = "MCP surface INCOMPLETE"


def _msg(note):
    return DESCRIBE(_SUMM, {"tools_found": 9, "tools_expected": 23, "note": note})


def test_the_prefix_is_not_repeated_1203ko():
    m = _msg("MCP surface INCOMPLETE: 9 tool(s) for 23 endpoint(s)")
    assert m.count(_PRE) == 1, m


def test_the_rest_of_the_note_survives_1203ko():
    """#1203kg's cause clause is the part a reader needs; only the opening is redundant."""
    m = _msg("MCP surface INCOMPLETE: 9 tool(s) for 23 endpoint(s) — but 14 of those "
             "endpoint(s) were registered AFTER this server file was written")
    assert m.count(_PRE) == 1, m
    assert "registered AFTER this server file was written" in m, m
    assert "9 tool(s) for 23 endpoint(s)" in m, "the note's own counts are not dropped either"


def test_the_structured_counts_stay_in_front_1203ko():
    """The note is free text; an older or error-path shape may not carry counts at all."""
    assert _msg("mcp check error: NameError: x").startswith("%s (9/23 tools;" % _PRE)
    assert _msg("").startswith("%s (9/23 tools)" % _PRE)
    assert _msg(None).startswith("%s (9/23 tools)" % _PRE)


def test_an_unrelated_note_is_untouched_1203ko():
    m = _msg("mcp check error: NameError: x")
    assert "mcp check error: NameError: x" in m, m


def test_a_note_that_only_repeats_the_prefix_leaves_no_dangling_separator_1203ko():
    for note in (_PRE, _PRE + ":", _PRE + ": "):
        m = _msg(note)
        assert m.startswith("%s (9/23 tools)" % _PRE), (note, m)
        assert ";" not in m.split("--")[0], ("no empty tail after the semicolon", note, m)


def test_a_complete_surface_says_nothing_here_1203ko():
    """The branch is gated on `mcp_complete` being present AND false."""
    assert _PRE not in DESCRIBE({"broken": [], "missing": [], "api_steps": 1,
                                 "mcp_complete": True}, {"note": "9 tools for 9 endpoints"})
    assert _PRE not in DESCRIBE({"broken": [], "missing": [], "api_steps": 1}, {})


def test_the_other_causes_are_unaffected_1203ko():
    m = DESCRIBE({"broken": ["GET /api/x -> 500"], "missing": ["POST /api/y -> 404"],
                  "api_steps": 0, "mcp_complete": False},
                 {"tools_found": 1, "tools_expected": 2,
                  "note": "MCP surface INCOMPLETE: 1 tool(s) for 2 endpoint(s)"})
    assert "BROKEN" in m and "MISSING" in m and "NOT WALKED" in m, m
    assert m.count(_PRE) == 1, m
