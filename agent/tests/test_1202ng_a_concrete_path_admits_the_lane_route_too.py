"""#1202ng: the "lane cannot edit it" tag must ask about the lane's route for a CONCRETE path too.

#1202hs stopped `_projected_owner_note` from claiming sole framework ownership of a path the
lane's router also declares — but only when the step names the template itself. Chain steps name
concrete paths (`/api/users/67/follow`), which take the by-id branch, and that branch never asked.

tiktok-r125's release was held on

    POST /api/users/67/follow -> 400 {"detail":"cannot follow yourself"}
        [FRAMEWORK-PROJECTED route — ... the lane cannot edit it, fix the projector/contract]

while "cannot follow yourself" exists only in the lane's custom_routes.py. Across the corpus's
chain records, 306 of the 443 such tags on a concrete path (23 runs) named a template the lane's
router also declares.
"""
from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import _projected_owner_note  # noqa: E402

PROJ = {("POST", "/api/users/{user_id}/follow"), ("GET", "/api/videos/{id}")}


def test_r125_a_concrete_follow_path_the_lane_declares_is_not_sole_framework():
    note = _projected_owner_note(PROJ, "POST", "/api/users/67/follow",
                                 lane={("POST", "/api/users/{user_id}/follow")})
    assert "BOTH" in note and "lane cannot edit it" not in note, note


def test_a_different_parameter_name_is_the_same_route():
    note = _projected_owner_note(PROJ, "POST", "/api/users/67/follow",
                                 lane={("POST", "/api/users/{id}/follow")})
    assert "BOTH" in note, note
    note = _projected_owner_note(PROJ, "POST", "/api/users/{user_id}/follow",
                                 lane={("POST", "/api/users/{id}/follow")})
    assert "BOTH" in note, note


def test_without_a_lane_route_the_projected_tag_stands():
    note = _projected_owner_note(PROJ, "GET", "/api/videos/12", lane=set())
    assert "FRAMEWORK-PROJECTED" in note
    note = _projected_owner_note(PROJ, "GET", "/api/videos/12",
                                 lane={("POST", "/api/videos/{id}")})    # other method
    assert "FRAMEWORK-PROJECTED" in note


def test_an_unrelated_path_gets_no_tag():
    assert _projected_owner_note(PROJ, "GET", "/api/sounds/3", lane=set()) == ""
