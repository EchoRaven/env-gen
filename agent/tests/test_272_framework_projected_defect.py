"""#272 — a 500 from a framework-PROJECTED handler is a framework defect, not a lane bug.

Borrowed from Hatch's design principle #5 (notes/hatch_design_principles.md): the system
must structurally distinguish "my own framework code is broken" from "the app the lane
authored is broken", or the lane spends its whole convergence budget chasing a defect it
cannot fix and that does not exist in its code.

This session hit that exact trap repeatedly. #263 (a by-id path filled with a foreign id),
#270 (a non-id param compared to an integer PK), #271 (auth_required=None → wide open) were
all bugs in the framework's PROJECTED handlers — code the lane cannot touch — yet
business_chain recorded them as ``broken`` app endpoints, so the lanes were dispatched to
"fix" handlers they did not write. r58 logged
``500 ... backend traceback: main.py:772 in _projected_delete_api_users_username_follow``:
the traceback names a ``_projected_`` function, which is dispositive — that code came from
route_projector, not the lane.

classify_endpoint_failure() separates the two so the gate and the remediation dispatcher can
treat a framework defect as a FRAMEWORK signal (surface it, don't dispatch a lane to it)
rather than as an unconverged application. It is deliberately narrow: only a 5xx whose
traceback names a ``_projected_`` handler qualifies; a 4xx, or a 500 from a lane-authored
handler, stays a normal app failure the lane owns.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    classify_endpoint_failure,
)


def test_r58_regression_500_from_projected_handler_is_a_framework_defect():
    body = ('Internal Server Error | backend traceback: main.py:772 in '
            '_projected_delete_api_users_username_follow_19')
    assert classify_endpoint_failure(500, body) == "framework_defect"


def test_projected_get_and_post_also_qualify():
    for fn in ("_projected_get_api_users_username_16",
               "_projected_post_api_videos_id_like_3"):
        body = f"Internal Server Error | backend traceback: main.py:40 in {fn}"
        assert classify_endpoint_failure(500, body) == "framework_defect", fn


def test_any_5xx_from_a_projected_handler_qualifies():
    for status in (500, 502, 503):
        body = "err | backend traceback: main.py:1 in _projected_get_api_x_0"
        assert classify_endpoint_failure(status, body) == "framework_defect", status


def test_a_500_from_a_lane_handler_stays_a_normal_app_failure():
    """A traceback naming a lane-authored function is the lane's to fix."""
    body = "Internal Server Error | backend traceback: custom_routes.py:88 in create_video_comment"
    assert classify_endpoint_failure(500, body) == "broken"


def test_a_500_with_no_projected_marker_stays_broken():
    assert classify_endpoint_failure(500, "Internal Server Error") == "broken"


def test_a_4xx_is_never_a_framework_defect_even_on_a_projected_handler():
    """A 404/422 is a contract/data outcome, not a crash in framework-emitted code."""
    for status in (400, 401, 403, 404, 422):
        body = "not found | backend traceback: main.py:5 in _projected_get_api_users_username_16"
        assert classify_endpoint_failure(status, body) == "broken", status


def test_none_and_empty_bodies_are_safe():
    assert classify_endpoint_failure(500, None) == "broken"
    assert classify_endpoint_failure(500, "") == "broken"


def test_a_2xx_is_never_a_defect():
    assert classify_endpoint_failure(200, "backend traceback: _projected_x") == "ok"


# ---- gate-level separation ----------------------------------------------------
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (  # noqa: E402
    business_chain_blockers,
)


class _RH:
    def __init__(self, chains): self._c = chains
    def get_verification_chains(self): return self._c


class _Hubs:
    def __init__(self, chains): self.registryhub = _RH(chains)


def _chain(name, status, broken=None, fdefs=None, steps=1):
    return {"name": name, "status": status, "steps": [{"i": i} for i in range(steps)],
            "last_result": {"broken": broken or [], "framework_defects": fdefs or []}}


def test_gate_routes_framework_defect_to_its_own_reason():
    hubs = _Hubs({
        "auth_flow": _chain("auth_flow", "passing"),
        "follow_flow": _chain("follow_flow", "framework_blocked",
                              fdefs=["DELETE /api/users/{u}/follow → 500 (_projected_...)"]),
    })
    out = business_chain_blockers(hubs)
    assert out.get("reason") == "business_chain_framework_defect", out
    assert "follow_flow" in out.get("chains", [])


def test_a_real_broken_chain_still_fails_normally():
    hubs = _Hubs({
        "feed_flow": _chain("feed_flow", "failing", broken=["GET /api/feed → 404"]),
    })
    assert business_chain_blockers(hubs).get("reason") == "business_chain_failing"


def test_broken_wins_over_framework_defect_when_both_present():
    """A lane-owned break must not be masked by also having a framework defect."""
    hubs = _Hubs({
        "mix": _chain("mix", "failing", broken=["GET /api/x → 404"],
                      fdefs=["POST /api/y → 500 (_projected_)"]),
    })
    assert business_chain_blockers(hubs).get("reason") == "business_chain_failing"


def test_all_passing_is_clean():
    hubs = _Hubs({"a": _chain("a", "passing"), "b": _chain("b", "passing")})
    # may still return coverage/isolation reasons, but never a chain-failing/defect one
    r = business_chain_blockers(hubs).get("reason")
    assert r not in ("business_chain_failing", "business_chain_framework_defect")
