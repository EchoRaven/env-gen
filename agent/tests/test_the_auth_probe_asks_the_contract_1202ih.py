r"""#1202ih: `auth_enforced_401` demanded a denial from whatever GET came first.

The check took the FIRST GET in `business_endpoints` and asserted 401, whatever the
contract said about it. When the lane declares that endpoint PUBLIC — which it may, and
which the projector then honours by emitting a handler with no guard — the framework is
demanding a denial from a route it built itself to answer 200. No lane can satisfy both
halves, and the only move that looks like progress is to flip the endpoint back to
auth-required, which collides with the public-feed requirement and flips again.

tiktok-r107 resume2, live: this wedged the run for four post-cap validation cycles and
then ended it. The debugger lane — awake since #1202dr — filed it as a P0 and named it
exactly:

    "run_validation auth_enforced_401 uses stale metadata for public GET /api/videos ...
     schema.auth_required=false but metadata.auth_required=true ... Registered
     public_video_metadata_drift_guard chain and diagnostic contract test passed, but
     run_validation still fails auth_enforced_401."

The lane did everything right and could not clear a check that reads a copy it cannot
reach.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR
from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _stated_auth_1202hi as stated,
)


# THE PRODUCTION SELECTION, not a copy of it. The first draft of this file
# re-implemented it inline, and reverting the production code to the blind first-GET left
# every case green — two of three counter-proofs passed on the stand-in.
_pick_new = VR.pick_auth_probe_endpoint_1202ih


PUBLIC_FEED = {"method": "GET", "path": "/api/videos",
               "schema": {"auth_required": False},
               "metadata": {"auth_required": True}}
GUARDED = {"method": "GET", "path": "/api/messages", "schema": {"auth_required": True}}
UNSTATED = {"method": "GET", "path": "/api/explore", "schema": {}}


def test_a_contract_public_first_get_is_not_probed_for_a_denial():
    """The r107 wedge: the first GET is the one the lane declared public."""
    gets = [PUBLIC_FEED, GUARDED, UNSTATED]
    assert gets[0] is PUBLIC_FEED, "premise: the public one really is first"
    assert _pick_new(gets) is GUARDED


def test_an_unstated_endpoint_is_not_treated_as_auth_required():
    """`_stated_auth_1202hi` returns None when nothing states it; demanding a denial from
    a default would invent the same unsatisfiable assertion in a new place."""
    assert _pick_new([UNSTATED]) is None


def test_no_declared_denial_means_nothing_to_verify():
    """An app whose reads are all public is a legitimate contract — the logged-out
    surface #320 exists to keep open."""
    assert _pick_new([PUBLIC_FEED, UNSTATED]) is None


def test_a_guarded_endpoint_is_still_probed():
    """The check keeps its teeth where the contract actually promises a denial."""
    assert _pick_new([GUARDED]) is GUARDED


# --- the wiring, over the AST ---------------------------------------------------------

def _probe_src() -> str:
    src = inspect.getsource(VR)
    i = src.index('_add("auth_enforced_401"')
    return src[src.rindex("# 5. Auth enforced", 0, i):src.index("# 5.5", i)]


def test_the_selection_asks_the_single_auth_reader():
    """One predicate: the probe and the generated handler must agree about the contract."""
    tree = ast.parse(inspect.getsource(VR.pick_auth_probe_endpoint_1202ih).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_stated_auth_1202hi" in called, (
        "auth is re-decided here; that is how two readers of one fact drift apart")


def test_the_probe_delegates_instead_of_indexing():
    """The blind `gets[0]` is the defect; the probe must go through the selection."""
    seg = _probe_src()
    tree = ast.parse("if True:\n" + "\n".join("    " + l for l in seg.splitlines()))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "pick_auth_probe_endpoint_1202ih" in called
    assert "_gets_1202ih[0]" not in seg, "the blind first-GET selection is back"


def test_skipping_is_announced_not_silent():
    """A check that quietly stops running is its own kind of lie."""
    seg = _probe_src()
    assert "#1202ih auth_enforced_401 skipped" in seg
    assert "_LOG.info" in seg


# --- against r107's own records --------------------------------------------------------

def _r107_business_gets():
    root = Path(__file__).resolve().parents[2]
    p = root / "generated/tiktok-web-r107/shared/hubs/registryhub_endpoints.json"
    if not p.is_file():
        return None
    from env_generator.llm_generator.multi_agent.runtime.lifecycle import business_endpoints
    raw = json.loads(p.read_text())
    d = {k: v for k, v in raw.items() if k != "_meta"}
    return [e for e in business_endpoints(d)
            if str(e.get("method", "GET")).upper() == "GET"]


def test_the_r107_wedge_state_selects_a_different_endpoint():
    gets = _r107_business_gets()
    if not gets:
        pytest.skip("r107 corpus not on this machine")
    wedged = copy.deepcopy(gets)
    for e in wedged:                      # the state the debugger reported at 05:20
        if e.get("path") == "/api/videos":
            e.setdefault("schema", {})["auth_required"] = False
            e["auth_required"] = None
            e.setdefault("metadata", {})["auth_required"] = True
    assert wedged[0].get("path") == "/api/videos", "premise: it is still first"
    picked = _pick_new(wedged)
    assert picked is not None and picked.get("path") != "/api/videos", (
        "the probe still demands a denial from the endpoint the lane declared public")
