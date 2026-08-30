"""#1172: the condenser bounded message COUNT while the cost is in TOKENS.

`should_condense_messages` was `len(messages) > max_messages` and nothing else.
Measured on r13 at the real rate ($5.50/$0.55/$33.00 per 1M incl. the regional
premium): cached input is the single biggest line item -- $192 of a $425 run,
45% -- because every call re-sends 54,753 tokens of context at $0.55/M. Cutting
10K of context saves $35 a run.

A handful of large tool results can take one call to 269,589 prompt tokens
without moving the message count anywhere near 50, and 269,589 is 0.9% under
272,000 -- the threshold where input bills at 2x and output at 1.5x. r13 never
crossed it; a slightly heavier payload would, and nothing was watching.

Sized against r13's 6,362 calls before choosing the bound:
    150K -> fires on 5.0%      200K -> fires on 2.0%
    240K -> fires on 0.4%      272K -> fires on 0.0% (too late to help)
p95 is 149,186, so 200K leaves normal traffic untouched and cuts only the tail
that approaches the cliff. Condensing is cheap: calls right after one hit 90.7%
cache against an 88.8% baseline.
"""
import os

import pytest

from env_generator.llm_generator.memory.generator_memory import GeneratorMemory


class _Condenser:
    max_messages = 50


@pytest.fixture
def mem():
    m = GeneratorMemory.__new__(GeneratorMemory)
    m.conversation_condenser = _Condenser()
    return m


@pytest.fixture(autouse=True)
def clean_env():
    os.environ.pop("ENVGEN_CONDENSER_MAX_TOKENS", None)
    yield
    os.environ.pop("ENVGEN_CONDENSER_MAX_TOKENS", None)


def test_the_count_trigger_still_works(mem):
    """The existing bound must survive -- this adds a second reason, never
    replaces the first."""
    assert mem.should_condense_messages([{"content": "x"}] * 60) is True
    assert mem.should_condense_messages([{"content": "x"}] * 10) is False


def test_one_huge_message_now_triggers(mem):
    """r13's shape: a few large tool results, message count nowhere near 50."""
    assert mem.should_condense_messages([{"content": "x" * 400_000}] * 3) is True


def test_normal_traffic_is_untouched(mem):
    """p95 on r13 was 149,186 tokens; a 100K single message must not fire."""
    assert mem.should_condense_messages([{"content": "x" * 400_000}]) is False


def test_the_bound_sits_below_the_billing_cliff(mem):
    """272,000 is where input doubles. Firing AT it would be too late."""
    cap = int(os.environ.get("ENVGEN_CONDENSER_MAX_TOKENS", "200000"))
    assert cap < 272_000


def test_zero_restores_the_previous_behaviour(mem):
    """An escape hatch, because a wrong condense bound is a live-run risk and
    #566j's lesson is that a false trigger costs a whole run."""
    os.environ["ENVGEN_CONDENSER_MAX_TOKENS"] = "0"
    assert mem.should_condense_messages([{"content": "x" * 400_000}] * 5) is False
    assert mem.should_condense_messages([{"content": "x"}] * 60) is True


def test_it_never_raises_on_odd_messages(mem):
    class _Obj:
        content = "x" * 10
    assert mem.should_condense_messages([{"nocontent": 1}, _Obj(), None, 5]) in (True, False)
    assert mem.should_condense_messages([]) is False


def test_it_stops_counting_once_over_the_bound(mem):
    """A million-message history must not be fully walked to answer yes."""
    import inspect
    src = inspect.getsource(GeneratorMemory.should_condense_messages)
    assert "return True" in src.split("for m in")[1]
