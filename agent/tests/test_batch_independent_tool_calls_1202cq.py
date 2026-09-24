"""#1202cq — batch independent tool calls into one response.

The existing guidance parallelises WORK across agents (`create_agent_team`,
`parallel_execute`). Nothing told an agent to parallelise CALLS inside its own turn, and that
is the cheaper of the two: every extra round-trip re-sends the whole context.

Measured on r38, a delivered run: 3737 tool calls arrived in 2161 responses, and 1663 of
those responses (77%) carried exactly ONE call. Average 1.73 calls per response.

The billing makes the cost concrete. Over six days: 141,765 requests, 63,197 input tokens
each on average against 318 output — a 199:1 ratio — and cached input alone was $4,565 of
the $9,674 spent (47%), because a 1/10 price on 92.7% of the volume still dominates. The
lever is not the hit rate (92.7% is near its ceiling); it is the number of round-trips.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SHARED = (LLM / "multi_agent" / "prompts" / "agents" / "shared" / "agent_definition.j2")


def _text():
    return SHARED.read_text(encoding="utf-8")


def test_the_rule_is_present():
    assert "Batch INDEPENDENT tool calls into ONE response" in _text()


def test_it_says_why_it_costs():
    """A rule without its reason is a rule an agent argues itself out of."""
    t = _text()
    assert "re-sends your whole context" in t


def test_it_carries_the_measurement():
    """The number is what makes it credible: 77% of responses carried one call."""
    t = _text()
    assert "3737" in t and "2161" in t and "77%" in t


def test_it_names_which_calls_qualify():
    """'Batch when independent' is unactionable without examples of independence."""
    t = _text()
    for kind in ("reads", "greps", "independent writes"):
        assert kind in t, kind


def test_it_forbids_batching_dependent_calls():
    """THE guard. Batching a call that needs the previous result makes the agent guess at an
    input it has not read — worse than the round-trip it saves."""
    t = _text()
    assert "does need the result, do not" in t
    assert "guesses at an input you have not read" in t


def test_it_sits_with_the_other_parallelism_guidance():
    """So an agent reading about parallel work meets the cheaper lever in the same breath."""
    t = _text()
    assert t.index("parallel_execute` for one-shot fan-out") < t.index("Batch INDEPENDENT")


def test_every_prompt_still_parses():
    from jinja2 import Environment, FileSystemLoader
    base = LLM / "multi_agent" / "prompts"
    env = Environment(loader=FileSystemLoader(str(base)))
    for f in sorted(base.rglob("*.j2")):
        env.parse(f.read_text(encoding="utf-8"))
