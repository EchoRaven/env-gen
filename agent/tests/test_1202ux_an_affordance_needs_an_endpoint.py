r"""#1202ux: the frontend mandate forbade stub PAGES and said nothing about stub CONTROLS.

Rule 1 of the frontend's non-negotiable mandate is "NO blank / mock / placeholder / 'coming
soon' / stub pages. EVERY declared page renders its REAL content wired to the REAL API", and
it goes on to forbid answering a failed request with mock data because "it hides the failure
from you and from every check".

A button whose endpoint does not exist is the same defect one level down, and the mandate did
not name it. MEASURED on the DELIVERED tiktok-r135, driven with a seeded login:

    setVideoLiked -> POST /api/videos/{id}/like  -> 404 with a valid token
    the contract has 25 endpoints and none is like, save, follow or share

`EngagementRail` fills the heart optimistically and its `catch` reverts it, so the click reads
to a user as "the app ignored me" -- precisely the hidden failure rule 1 exists to prevent.
#1202uv measured the shape across 155 runs: 29 (18%) call at least one endpoint nobody
implements.

The prompt already carries the remedy: rule 27's contract negotiation
(`eventhub.publish_api_request`). What was missing is the instruction to CHECK before wiring,
and the alternative when the endpoint is absent -- negotiate it, or do not render the control.

This test pins that the rule is present AND reaches the rendered prompt, because the mandate
lives inside a `{% macro %}`: a bare `render()` of this template returns 31 characters, so
"it is in the file" would not have proved it is in what an agent reads.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PROMPTS = LLM_DIR / "multi_agent" / "prompts"


def _rendered():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(PROMPTS)))
    return env.get_template("v4/frontend_agent.j2").module.frontend_system_prompt("/tmp/ws")


def test_the_rule_reaches_the_rendered_prompt():
    """★ Not "it is in the file": the mandate sits inside a macro, and a bare render of this
    template returns 31 characters."""
    out = _rendered()
    assert len(out) > 10000, len(out)
    assert "AN INTERACTIVE CONTROL WHOSE ENDPOINT IS NOT IN THE CONTRACT IS A STUB" in out


def test_it_names_both_ways_out():
    """A rule that only forbids leaves the lane stuck. It must say what to do instead --
    negotiate the endpoint, or do not render the control."""
    out = _rendered()
    # #943: LANDMARK ANCHORS, not a byte count. My first version read `out[i:i + 900]` and the
    # ratchet caught it -- a window sized in bytes breaks the moment the rule's own wording
    # grows. The block is bounded by the rules on either side of it, which is what "this
    # sentence belongs to rule 1b" actually means.
    i = out.find("AN INTERACTIVE CONTROL WHOSE ENDPOINT")
    assert i >= 0, "rule 1b is missing"
    j = out.find("2. A MAP screen uses a REAL map", i)
    assert j > i, "rule 2 no longer follows 1b; this assertion reads the wrong text"
    block = out[i:j]
    assert "publish_api_request" in block, block
    assert "DO NOT RENDER" in block, block
    assert "registryhub_list_endpoints" in block, block


def test_it_sits_with_the_rule_it_extends():
    """★ It is rule 1 one level down, so it must read beside rule 1 rather than as a
    disconnected twenty-eighth item nobody reaches."""
    out = _rendered()
    one = out.find("1. NO blank / mock / placeholder")
    onebee = out.find("1b. AN INTERACTIVE CONTROL")
    two = out.find("2. A MAP screen uses a REAL map")
    assert -1 < one < onebee < two, (one, onebee, two)


def test_rule_one_is_not_weakened():
    """★ The property this could most easily have cost: adding 1b must not disturb the rule it
    extends, including its ban on masking a failure with mock data."""
    out = _rendered()
    assert "NO blank / mock / placeholder / 'coming soon' / stub pages" in out
    assert "NEVER answer the failure with hardcoded or mock data" in out


def test_the_template_still_parses_for_every_macro():
    """A stray quote in a `mandate=(...)` implicit concatenation would break the whole file."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(PROMPTS)))
    mod = env.get_template("v4/frontend_agent.j2").module
    assert callable(getattr(mod, "frontend_system_prompt"))
