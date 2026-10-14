r"""#1203j2: the agent contract said every /api/ route needs a token. 24% of ours do not.

`_AGENT_NOTES` is what every lane reads first, and its auth line was absolute:

    Every /api/ route requires `Authorization: Bearer <token>`; missing/invalid -> 401.

Counted over the backends in `generated/`: the projector emits 3231 `/api/` handlers and 766
of them — 24%, across 142 runs — take no `user=Depends(get_current_user)`. They are
`/api/genres`, `/api/search`, `/api/browse`, `/api/feed/for-you`: reads a logged-OUT visitor
must see. `resolve_endpoint_auth` decides it from the contract — `auth_required: false` wins;
otherwise writes and personalised reads demand an actor, and only the token-minting prefixes
stay anonymous — so the framework's own rule has an exception its own notes denied.

A lane that believes the absolute version either puts a token behind a catalog no logged-out
visitor can then reach, or reads the gate accepting a public handler as the gate being wrong.
#1203ic is the same shape and it cost r183 its run.

This is a FALSEHOOD REMOVED, not an explanation added. #1203i9 measured what adding prose
buys — r184 received the `total` definition in this very block and shipped the violation
anyway — and that result is about persuasion. Stating something untrue is a different defect.
"""
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
if str(LLM) not in sys.path:
    sys.path.insert(0, str(LLM))

from multi_agent.runtime import reference_materials as rm  # noqa: E402
from multi_agent.runtime.route_projector import resolve_endpoint_auth  # noqa: E402

NOTES = rm._AGENT_NOTES
SRC = inspect.getsource(rm)


# --- the claim the notes now make -----------------------------------------------------------

def test_the_absolute_claim_is_gone_from_what_the_lane_reads():
    assert "Every /api/ route requires" not in NOTES, NOTES[:200]


def test_the_exception_is_stated():
    assert "auth_required: false" in NOTES
    assert "UNLESS" in NOTES


def test_the_401_rule_survives_for_the_routes_it_applies_to():
    """Removing a falsehood must not remove the true half with it."""
    assert "401" in NOTES
    assert "Authorization: Bearer <token>" in NOTES


# --- and the claim matches the framework's own behaviour -------------------------------------

def test_a_declared_public_read_really_is_public():
    """The exception the notes now state is the one `resolve_endpoint_auth` implements."""
    assert resolve_endpoint_auth("GET", "/api/genres", {"auth_required": False}, None) is False


def test_an_undeclared_write_really_does_demand_an_actor():
    """The notes say writes default to needing a token — so they must."""
    assert resolve_endpoint_auth("POST", "/api/videos", {}, None) is True


def test_a_token_minting_route_really_is_anonymous():
    assert resolve_endpoint_auth("POST", "/auth/login", {}, None) is False


def test_an_undeclared_plain_read_is_not_forced_to_carry_a_token():
    """★ The measurement, as a property: this is the 24%. If this ever returns True the notes
    become true again by accident and this test should be read, not deleted."""
    assert resolve_endpoint_auth("GET", "/api/genres", {}, None) is False


def test_a_personalised_read_still_demands_one():
    """The default is not 'public' — it is 'public unless the path is about the caller'."""
    assert resolve_endpoint_auth("GET", "/api/me", {}, None) is True


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded_beside_the_notes():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "3231" in flat and "766" in flat
    assert "142 runs" in flat


def test_the_precedent_that_makes_this_a_defect_is_named():
    """#1203ic is why a false sentence counts as a defect here, not a style note."""
    assert "#1203ic" in SRC
    assert "r183" in SRC


def test_it_says_why_this_is_not_the_thing_1203i9_tried():
    """Adding prose does not move a lane; removing a falsehood is a different claim."""
    flat = " ".join(SRC.split())
    assert "FALSEHOOD REMOVED, not an explanation added" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
