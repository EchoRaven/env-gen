"""#1202db — 'schema-safe by construction' overstated what the projected handler covers.

When a lane route duplicates standard CRUD it is dropped and the projected handler serves
the path. The notice told the lane that handler "is schema-safe by construction", full
stop, and told it not to patch the route table.

Probed on netflix-r42's DELIVERED artifact: `POST /api/profiles {}` returns 201 and
inserts name=null, avatar=null, is_kids=null — while the lane's own custom_routes.py:298
rejects exactly that with `name is required` and was dropped here.

The promise holds for what the projector can see: route_projector refuses a body naming
no subject FK (that is why /api/continue-watching and /api/my-list return 400 on the same
probe), and a NOT NULL column is caught at INSERT. `profiles.name` is a plain nullable
string — no schema constraint to be safe about — so the lane's knowledge had nowhere to
go. A nameless profile is what the who's-watching picker renders.

'Projected wins' is a decision and is untouched; #1166 already carved out the unserved
case. Only the notice changes.
"""
from pathlib import Path

import pytest

SRC = Path("env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py").read_text()


def _notice() -> str:
    i = SRC.index("custom_routes: %d route(s) NOT registered")
    return SRC[i:SRC.index("len(_dropped_cr)", i)]


def test_the_unqualified_promise_is_gone():
    """'schema-safe by construction.' with no qualifier is the sentence that misled."""
    assert "is schema-safe by construction. This is expected" not in SRC


def test_it_names_what_is_actually_enforced():
    """A guarantee the reader cannot scope is worse than none: they trust it everywhere."""
    body = _notice()
    assert "OWNER and SUBJECT foreign keys" in body
    assert "NOT NULL" in body


def test_it_names_what_is_not():
    """The r42 case in one clause — a nullable column the lane validated and the contract
    never declared."""
    body = _notice()
    assert "does NOT know a constraint the contract" in body
    assert "unvalidated" in body


def test_it_still_forbids_patching_the_route_table():
    """tiktok-r58 shipped a delivered milestone whose /health, /docs and /api/videos were
    all 404 because a lane patched the route table. That warning must survive."""
    body = _notice()
    assert "do NOT patch the" in body


def test_it_gives_the_lane_both_exits():
    """Naming the gap without naming the way out just relocates the frustration."""
    body = _notice()
    assert "declare it in the contract" in body
    assert "action" in body and "segment" in body
