"""#1202ch — the knowledge lane is retired.

It spawned, registered 69 tools, woke once per milestone on `kickoff_complete`, matched
nothing in its own wake_contract table and emitted
`{"kind":"summarization_ack","action":"skipped","reason":"no matching trigger"}`. Measured
across six runs spanning 22 to 354 minutes its log volume was CONSTANT at 25-37 lines while
every working lane scaled with the run.

Its two intended jobs were already elsewhere or unreachable: `query_knowledge` is answered
directly by `store.search()` (32 calls in r35, none through this lane), and the
learning-capture loop was broken in three places at once — every lane's prompt says
"Default: skip" for submit_learning (0 calls across 18315 corpus tasks), this lane
subscribed only to `kickoff_complete` rather than the `learning_event` its contract names,
and no corpus task was ever assigned to it (0 of 18315).

Knowledge collection now lives OUTSIDE the pipeline. The store and its tools stay.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CONFIG = LLM / "multi_agent" / "agents" / "agents_config.yaml"


def _cfg():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_the_lane_is_not_spawned():
    assert "knowledge" not in _cfg()["resident_lanes"]


def test_the_five_working_lanes_remain():
    assert set(_cfg()["resident_lanes"]) == {
        "orchestrator", "backend", "frontend", "verifier", "debugger"}


def test_it_is_not_a_resident_lane_id():
    from multi_agent.agent_metadata import RESIDENT_LANE_IDS, ROLE_DESCRIPTIONS
    assert "knowledge" not in RESIDENT_LANE_IDS
    assert "knowledge" not in ROLE_DESCRIPTIONS


def test_it_is_not_a_task_domain():
    """0 of 18315 corpus tasks ever targeted it."""
    from multi_agent.agent_metadata import DEV_TASK_DOMAINS
    assert "knowledge" not in DEV_TASK_DOMAINS


def test_it_subscribes_to_no_events():
    from multi_agent.runtime.agent_subscriptions import DEFAULT_SUBSCRIPTIONS
    assert "knowledge" not in DEFAULT_SUBSCRIPTIONS


def test_no_prompt_offers_it_as_a_peer():
    """A lane told a peer exists will try to message one that cannot answer."""
    offenders = [str(f) for f in (LLM / "multi_agent" / "prompts").rglob("*.j2")
                 if '{"id": "knowledge"' in f.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_prompt_still_parses():
    """The peer entries were removed from ten templates; a broken macro arg list would only
    surface at render time, inside a run."""
    from jinja2 import Environment, FileSystemLoader
    base = LLM / "multi_agent" / "prompts"
    env = Environment(loader=FileSystemLoader(str(base)))
    for f in sorted(base.rglob("*.j2")):
        env.parse(f.read_text(encoding="utf-8"))


def test_the_knowledge_STORE_is_untouched():
    """THE thing that must not break: retrieval never went through the lane, and an
    external curator still needs the store and its tools."""
    from multi_agent.knowledge.tools import query_knowledge  # noqa: F401
    import multi_agent.tool_bundles as tb
    src = Path(tb.__file__).read_text(encoding="utf-8")
    assert "store_knowledge" in src and "submit_learning" in src


def test_lanes_are_still_told_where_a_lesson_goes():
    """submit_learning still exists, so the instruction must name the store rather than an
    agent that no longer runs."""
    d = (LLM / "multi_agent" / "prompts" / "agents" / "shared"
         / "agent_definition.j2").read_text(encoding="utf-8")
    line = next(l for l in d.splitlines() if "submit_learning" in l)
    assert "knowledge store" in line and "knowledge agent should classify" not in line
