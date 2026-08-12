r"""#609: the same read, twice, in one tool batch.

Sixth finding on the cost axis. Over the arc's **133694** logged tool batches, **5562** issue the
same `(agent, path)` read more than once — **6234 redundant calls, half of all 12469 reads**. Two
identical reads in one batch cannot inform anything: the model receives both results in the same
turn, so the second is the first re-serialised at ~8.2k tokens.

DELIBERATELY NOT FIXED HERE, and the reason is recorded next to the code: the bigger number is
that **72% of reads (9015) re-read a file NOBODY changed since that agent last read it** — r134's
backend read `custom_routes.py` **135 times** with no intervening change. A cross-turn cache
cannot know whether the agent still HOLDS the earlier content after a context trim, and answering
"unchanged" to an agent that has lost it would wedge the lane. That needs a `force=` escape hatch
and a live run to validate the behaviour change.

METHOD NOTE — this fix was nearly built on a false number. A first pass counted duplicates from
the batch summary line, which logs only tool names and ARG KEY NAMES (`read(file_path)`), not
values: it reported 872 duplicates and would have flagged two reads of *different* files as one
repeat. Re-counted from the `READ: <path>` detail lines, the true figure is 6234.
"""
import inspect
import json

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import tooling as t


@pytest.fixture(scope="module")
def src():
    return inspect.getsource(t.AgentStepToolingMixin._process_tool_calls)


# --- the allowlist -----------------------------------------------------------------------------

def test_only_read_is_deduped():
    assert t._IDEMPOTENT_READ_TOOLS_609 == frozenset({"read"})


def test_queue_and_time_dependent_tools_are_excluded():
    """`check_inbox` can legitimately differ twice in a batch; `get_time` always does."""
    for name in ("check_inbox", "get_time", "write", "edit", "workhub_task", "test_api"):
        assert name not in t._IDEMPOTENT_READ_TOOLS_609, name


# --- the signature -------------------------------------------------------------------------------

def test_the_signature_uses_ARG_VALUES_not_just_names(src):
    """The bug the first measurement made: `read(file_path)` twice is not a duplicate unless
    the PATH matches. The runtime must key on the serialized args."""
    assert "json.dumps(tool_args, sort_keys=True, default=str)" in src


def test_the_signature_is_order_insensitive(src):
    assert "sort_keys=True" in src


def test_an_unserializable_arg_disables_the_dedupe_rather_than_crashing(src):
    i = src.index("_sig = (tool_name, json.dumps")
    window = src[i - 80:i + 260]
    assert "except Exception:" in window and "_sig = None" in window
    assert "if _sig is not None:" in window


# --- the substitute result -----------------------------------------------------------------------

def test_the_duplicate_still_gets_a_result_for_its_tool_call_id(src):
    """Every tool_call_id must be answered or the provider rejects the turn."""
    i = src.index("duplicate call in this same batch")
    window = src[i - 300:i + 300]
    assert "Message.assistant(tool_calls=[tool_call])" in window
    assert "Message.tool(" in window and "tool_call_id" in window


def test_the_substitute_points_at_the_call_that_carries_the_content(src):
    i = src.index("duplicate call in this same batch")
    assert "{_first}" in src[i:i + 200]


def test_the_first_call_of_a_batch_is_never_substituted(src):
    i = src.index("_batch_seen[_sig] = tool_call_id")
    assert src.index("_first = _batch_seen.get(_sig)") < i


def test_the_map_is_per_batch_not_per_agent(src):
    """A later batch must read the file again — the file may have changed."""
    assert "_batch_seen: Dict[tuple, str] = {}" in src
    assert src.index("_batch_seen: Dict[tuple, str] = {}") < src.index("for tool_call in calls:")


# --- the documented non-fix -------------------------------------------------------------------------

def test_the_cross_turn_case_is_documented_as_deliberately_untouched(src):
    assert "72% of reads" in src
    assert "context trim" in src and "force=" in src


def test_the_measurement_that_justifies_it_is_recorded(src):
    assert "6234" in src and "133694" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
