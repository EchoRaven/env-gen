r"""#674: a failed ToolResult dropped `data` — and `data` is where the reason lives.

Reviewing for WASTED TOKENS rather than for defects: per #257 a run's cost is prompt, re-sent
every step, so the metric is wasted STEPS and every doomed tool call is one. Ranking the 249 run
logs by failed tool call:

    25788 failed tool calls in total
    test_api                                 5248  (123 runs, median 22/run)
    registryhub_register_verification_chain  5004  -> #664
    write                                    2628  -> #666
    workhub_task                             2576  -> #668
    edit                                     1694
    submit_retro                             1348  (23 runs, median 40/run)

`test_api` is the largest single source and had never been examined. Its failures:

    1778  Request failed: Connection refused
    1750  HTTP Error: N                      <- a status code and NOTHING else
    1622  HTTP Error: N — this endpoint requires AUTH...   <- already has good guidance

The tool reads the response body, bounds it (#610) and stores it as `data["response"]`, then
reports `error_message="HTTP Error: 500"`. `ToolResult.__str__` was:

    if self.success:
        return str(self.data) if self.data is not None else "OK"
    return f"Error: {self.error_message}"

so on failure `data` was discarded and the agent saw the status code alone, then retried.

Not just test_api: 22 construction sites across 6 files build a failed ToolResult carrying data
the model never sees — code_tools has 10, including the #635 syntax check whose
`data={"errors": [...]}` held the line and column it had just computed. One change to `__str__`
covers all of them.

The ceiling is #610's already-justified agent-facing body limit, not a new number; producers that
bound their own payloads are already under it.
"""
import pytest

from utils.tool import ToolResult


# --- the reason now reaches the agent ---------------------------------------------------------

def test_a_failure_shows_the_data_beside_the_error():
    r = ToolResult(success=False, error_message="HTTP Error: 500",
                   data={"status": 500, "response": '{"detail":"null value in column title_id"}'})
    out = str(r)
    assert "HTTP Error: 500" in out
    assert "null value in column title_id" in out


def test_the_error_line_still_leads():
    r = ToolResult(success=False, error_message="HTTP Error: 500", data={"status": 500})
    assert str(r).startswith("Error: HTTP Error: 500")


def test_the_syntax_checkers_error_list_survives():
    """#635 computed line and column, then only reported that something was wrong."""
    r = ToolResult(success=False, error_message="SyntaxError at L12:5: invalid syntax",
                   data={"errors": [{"line": 12, "column": 5, "code": "SyntaxError"}]})
    assert "'line': 12" in str(r)


# --- nothing is added when there is nothing to add --------------------------------------------

@pytest.mark.parametrize("data", [None, {}, [], "None"])
def test_an_empty_payload_leaves_the_message_alone(data):
    r = ToolResult(success=False, error_message="plain", data=data)
    assert str(r) == "Error: plain"


def test_a_success_is_completely_unchanged():
    assert str(ToolResult(success=True, data={"ok": 1})) == "{'ok': 1}"
    assert str(ToolResult(success=True)) == "OK"


def test_a_success_with_no_data_still_says_OK():
    assert str(ToolResult(success=True, data=None)) == "OK"


# --- it must not become the token leak it is fixing -----------------------------------------------

def test_a_huge_payload_is_bounded():
    r = ToolResult(success=False, error_message="x", data="y" * 20000)
    out = str(r)
    assert len(out) < 8200
    assert "truncated" in out


def test_the_truncation_states_the_real_length():
    """Silent truncation reads as 'that was all there was'."""
    r = ToolResult(success=False, error_message="x", data="y" * 20000)
    assert "20000 chars total" in str(r)


def test_a_payload_at_the_ceiling_is_not_truncated():
    r = ToolResult(success=False, error_message="x", data="y" * 100)
    assert "truncated" not in str(r)


def test_the_ceiling_matches_the_existing_agent_facing_body_limit():
    """#610 justified 8000 for exactly this audience; #674 does not invent a second number."""
    from env_generator.llm_generator.tools.runtime_tools import _API_BODY_CHARS_610
    assert ToolResult._FAILED_DATA_CHARS_674 == _API_BODY_CHARS_610


# --- shape ------------------------------------------------------------------------------------

def test_the_detail_is_on_its_own_line():
    r = ToolResult(success=False, error_message="e", data={"a": 1})
    assert str(r).count("\n") >= 1


def test_a_non_dict_payload_works():
    assert "raw text" in str(ToolResult(success=False, error_message="e", data="raw text"))


def test_it_never_raises_on_an_odd_payload():
    class _Odd:
        def __str__(self):
            return "odd"

    str(ToolResult(success=False, error_message="e", data=_Odd()))


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    src = inspect.getsource(ToolResult)
    flat = " ".join(src.replace("#", " ").split())
    assert "25788 failed tool calls" in flat
    assert "1750 of those are a bare" in flat


def test_the_scope_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(ToolResult).split())
    assert "22 construction sites across 6 files" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
