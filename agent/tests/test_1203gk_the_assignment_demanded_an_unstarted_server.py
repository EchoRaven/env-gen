"""#1203gk: the mcp_parity assignment told the test-user to connect to a server the
framework knows is not running.

`mcp_server/<env>/start.sh` opens with "agentsuite-red pool runs this as a subprocess", and
`runhub.service._list_registryhub_mcp_servers` states the consequence outright: the MCP
server is NOT SUPPOSED TO BE RUNNING during a run, 0 of 191 generated composes declare an
mcp service, and no MCP container has ever existed. The old goal — "Connect to the env's MCP
server with a token" — was therefore unachievable, and in tiktok-web-r166 its failure became
a P0 that told the lane to "make the MCP service available through compose", which broke
docker_up for the whole stack (9 tasks, 4 cancelled, release validation blocked).

Everything here is asserted on the BRIEFING the agent actually receives, rendered by
`build_briefing`, not on the source of the goal dict: the briefing is what lands in the task
prompt, and a step list that never reaches it would prove nothing.
"""
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.test_user_squad import (
    build_briefing, plan_test_user_goals,
)

API_BASE = "http://localhost:8029"
UI_BASE = "http://localhost:3029"


def _mcp_goal(**kw):
    """The mcp_parity goal as the squad builder emits it, or None."""
    eps = [{"method": "GET", "path": "/api/videos/feed", "response_key": "items"},
           {"method": "POST", "path": "/api/videos", "response_key": "item"}]
    goals = plan_test_user_goals(
        business_eps=eps, tables={"videos": {"schema": {"columns": ["id", "caption"]}}},
        ui_pages=[], feature_inventory={}, mcp_present=True, max_goals=24, **kw)
    return next((g for g in goals if g.get("kind") == "mcp_parity"), None)


def _briefing():
    g = _mcp_goal()
    assert g is not None, "the squad no longer builds an mcp_parity goal"
    return build_briefing(g, ui_base=UI_BASE, api_base=API_BASE)


def test_the_goal_is_still_built_when_mcp_is_present():
    assert _mcp_goal() is not None


def test_the_briefing_says_nothing_is_listening_yet():
    b = _briefing()
    assert re.search(r"NOTHING IS LISTENING", b), b
    assert "downstream" in b.lower() or "DOWNSTREAM" in b


def test_the_briefing_no_longer_opens_by_demanding_a_connection():
    g = _mcp_goal()
    assert "Connect to the env's MCP server with a token" not in g["goal"], (
        "the unachievable instruction is back")


def test_the_briefing_tells_it_how_to_start_the_server():
    b = _briefing()
    assert "start.sh" in b, b
    assert "mcp_server/" in b
    # #1203h3: the literal port was pinned here and that turned out to be the defect.
    # r174 10:45:34: the copy said `PORT=8890`, the agent did exactly that, and got
    # `Port 8890 is already in use` -- twice over, because two MCP servers r173 left running
    # still held 8890 and 8891. What this test should require is that the briefing makes the
    # agent ACQUIRE a port, not that it names one.
    assert "find_free_port" in b, b
    assert "PORT=" in b, b                      # it still shows how to pass the port
    import re as _re
    assert not _re.search(r"PORT=\d", b), (
        "the briefing hardcodes a port again; r174 measured what that costs")
    assert "API_BASE_URL" in b


def test_the_start_instruction_warns_about_the_default_api_base():
    """start.sh defaults API_BASE_URL to 127.0.0.1:8080, which is never the assigned base —
    r166's was http://localhost:8029. An instruction that omits this starts a server wired to
    the wrong app."""
    b = _briefing()
    assert "127.0.0.1:8080" in b, b
    assert API_BASE in b, "the briefing must carry the assigned API base for the agent to pass"


def test_the_briefing_forbids_adding_a_compose_service():
    """The one prohibition, and the one that broke the stack in r166."""
    b = _briefing()
    assert "docker-compose" in b
    assert re.search(r"NEVER edit docker-compose", b), b


def test_a_refusal_before_starting_is_declared_expected_and_not_a_lane_defect():
    b = _briefing()
    assert "EXPECTED" in b
    assert "not a defect in any lane" in b, b


def test_a_server_that_fails_to_start_is_still_reportable():
    """Removing a false blocker must not mask a true one: if start.sh itself fails, that is a
    real defect and the briefing must still ask for it."""
    b = _briefing()
    # anchored on the AFFIRMATIVE clause: a mutation that negates it ("that is NOT a real
    # defect") leaves the substring "real defect" in place, so the loose form proved nothing.
    assert re.search(r"start\.sh ITSELF fails, that is a real defect", b), b
    assert "what start.sh printed" in b, b
    assert "NOT EXERCISED" in b, b


def test_completeness_parity_and_auth_rejection_survived():
    b = _briefing()
    # "parity" alone is not falsifiable — it also sits in the step list and in the goal `kind`.
    # The CLAUSE is what carries the check.
    assert "one per business endpoint (completeness)" in b, b
    assert "MIRRORS the equivalent HTTP API call" in b, b
    assert "reject-on-no-auth" in b, b


def test_the_steps_reach_the_briefing_as_step_hints():
    """A `steps` list the renderer drops would leave the procedure invisible."""
    g = _mcp_goal()
    assert g.get("steps"), "the goal carries no steps"
    b = build_briefing(g, ui_base=UI_BASE, api_base=API_BASE)
    assert "STEP HINTS:" in b
    for i, _s in enumerate(g["steps"], 1):
        assert re.search(r"^\s+%d\. " % i, b, re.M), (i, b)


def test_no_mcp_goal_when_the_env_has_no_mcp_surface():
    """Unchanged behaviour: the goal is gated on mcp_present."""
    eps = [{"method": "GET", "path": "/api/videos/feed", "response_key": "items"}]
    goals = plan_test_user_goals(business_eps=eps, tables={}, ui_pages=[],
                                 feature_inventory={}, mcp_present=False, max_goals=24)
    assert not [g for g in goals if g.get("kind") == "mcp_parity"]
