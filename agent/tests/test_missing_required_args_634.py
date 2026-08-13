r"""#634: the tool's own teaching error was unreachable exactly when it was needed.

Sweeping the 56 run logs by error CLASS rather than by hunch, the top entries are agents being
told things by Python instead of by the framework:

    submit_retro FAILED (0ms): SubmitRetroTool.execute() missing 3 required
    keyword-only arguments: 'systematic_failures', 'lessons' and ...

    124 such failures across 5 tools and 19+ runs
    submit_retro 106 · send_message 8 · broadcast 5 · ask_agent 1 · lint 1

`exec_fn(**tool_args)` raises before any of the tool's code runs. `SubmitRetroTool` already
validates that `plan_vs_reality` holds >= 2 dicts with named keys and returns a message saying
exactly that — unreachable, because the call never gets that far. The agent learns the parameter
NAMES, which it usually already knew, and nothing about the SHAPE, which is what it got wrong.
So it retries: 106 times on one tool.

This is #360's mirror. That fix drops an argument the callee cannot accept; this one answers for
an argument the callee requires, quoting the `PARAMETERS` schema the model was already shown.
"""
import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.tooling import (
    missing_args_message_634 as message,
    missing_required_args_634 as missing,
)


def _fn(*, title: str, body: str, tag: str = "x"):
    return None


def _positional(to_agent, content, urgent=False):
    return None


class _Tool:
    PARAMETERS = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "one line naming the retro"},
            "body": {"type": "array", "description": ">= 2 entries, each {plan, reality}"},
        },
    }


# --- what is missing -----------------------------------------------------------------------------

def test_it_names_the_omitted_keyword_only_args():
    assert missing(_fn, {}) == ["body", "title"]


def test_a_supplied_arg_is_not_reported():
    assert missing(_fn, {"title": "t"}) == ["body"]


def test_an_arg_with_a_default_is_never_required():
    assert "tag" not in missing(_fn, {})


def test_positional_parameters_count_too():
    """send_message/broadcast/ask_agent fail this way — 14 of the 124."""
    assert missing(_positional, {}) == ["content", "to_agent"]


def test_a_complete_call_reports_nothing():
    assert missing(_fn, {"title": "t", "body": []}) == []


def test_self_is_never_reported():
    class _C:
        def execute(self, *, a):
            return None
    assert missing(_C().execute, {}) == ["a"]
    assert missing(_C.execute, {"a": 1}) == []   # unbound: `self` must not be demanded


# --- never guess ------------------------------------------------------------------------------

def test_a_kwargs_signature_demands_nothing():
    def _any(**kw):
        return None
    assert missing(_any, {}) == []


def test_an_uninspectable_callable_demands_nothing():
    assert missing(object(), {}) == []


def test_non_dict_args_are_tolerated():
    assert missing(_fn, None) == ["body", "title"]


# --- what the agent is told ---------------------------------------------------------------------

def test_the_message_quotes_the_declared_type_and_description():
    msg = message("submit_retro", ["body"], _Tool())
    assert "body: array — >= 2 entries, each {plan, reality}" in msg


def test_every_missing_arg_appears():
    msg = message("submit_retro", ["title", "body"], _Tool())
    assert "title:" in msg and "body:" in msg


def test_it_says_what_to_do():
    assert "call again" in message("submit_retro", ["body"], _Tool())


def test_a_tool_without_a_schema_still_names_the_arg():
    msg = message("t", ["thing"], object())
    assert "thing" in msg and "missing required argument" in msg


# --- where it runs -------------------------------------------------------------------------------

def test_it_is_checked_before_the_call_and_after_the_360_drop():
    """#360 strips surplus args first; only then can 'what is still missing' be answered."""
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    src = inspect.getsource(tooling)
    i = src.index("_missing_634 = missing_required_args_634(exec_fn, tool_args)")
    assert src.index("drop_unaccepted_kwargs(exec_fn, tool_args)") < i
    assert i < src.index("if asyncio.iscoroutinefunction(exec_fn):")


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    flat = " ".join(inspect.getsource(tooling.missing_required_args_634).split())
    assert "124 such failures across 5 tools" in flat
    assert "submit_retro 106" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
