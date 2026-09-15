"""#1202nw: a 401/403 expectation on a projected create whose body names no owner column is rejected.

#1202jd exempts POST ("a cross-actor create denial is about the payload, not row ownership"). A
FRAMEWORK-PROJECTED create enforces one payload rule: #566s refuses a body OWNER column naming
another user. tiktok-r126 M1: `deny_a_claiming_b_comment_actor` POSTed /api/notifications as user A
with user B's `comment_id`, expecting 403. The lane's own handler did refuse that, but main.py
serves a bare collection from the projected handler; the projected create answered 201. The
verifier kept the step through six re-registrations and the milestone died on the no-convergence
abort, that step its only blocker.

Replayed on every run in the corpus: the rule flags exactly those three r126 steps (all broken, 201)
and no step that ever passed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import unenforceable_create_denials_1202nw  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402

TABLES = {"notifications": {"name": "notifications", "schema": {"columns": [
    {"name": "id"}, {"name": "user_id"}, {"name": "actor_id"}, {"name": "type"},
    {"name": "comment_id"}]}}}
PROJ = {("POST", "/api/notifications")}
R126 = {"action": "deny_a_claiming_b_comment_actor", "method": "POST",
        "path": "/api/notifications", "auth": "tokenA", "expect": [403],
        "body": {"type": "comment", "title": "x", "comment_id": "${commentIdB}"}}


def _flag(step, projected=PROJ, lane=frozenset()):
    return unenforceable_create_denials_1202nw([step], TABLES, projected, lane)


def test_r126_the_step_is_flagged():
    assert _flag(R126) == [(0, "POST /api/notifications", "notifications", ["user_id", "actor_id"])]


def test_a_lane_route_for_a_bare_collection_does_not_exempt_it():
    """r126's lane declared POST /api/notifications; main.py still served the projected create."""
    assert _flag(R126, lane={("POST", "/api/notifications")})


def test_a_real_idor_probe_naming_another_owner_is_left_alone():
    assert _flag(dict(R126, body=dict(R126["body"], actor_id="${userB}"))) == []


def test_other_shapes_are_left_alone():
    assert _flag(dict(R126, expect=[404])) == []                 # not a denial code
    assert _flag(dict(R126, expect=[201, 403])) == []            # #591's business, not this one
    assert _flag(dict(R126, auth=None)) == []                    # unauthenticated 401 is enforced
    assert _flag(dict(R126, path="/api/videos/{videoId}/comments")) == []   # nested create
    assert _flag(R126, projected=set()) == []                    # not a projected route
    assert _flag(dict(R126, expect=403)) != []                   # scalar expect is read too


def test_registration_rejects_it_with_the_repair(tmp_path):
    (tmp_path / "shared").mkdir()
    main = tmp_path / "app" / "backend" / "main.py"
    main.parent.mkdir(parents=True)
    main.write_text('@app.post("/api/notifications", status_code=201)\n'
                    'def _projected_post_api_notifications_1(body: dict = None):\n    pass\n',
                    encoding="utf-8")
    reg = HubRegistry(tmp_path)
    # The shape a real run stores (r126's registry: schema.columns); `columns=` lands in
    # metadata and would test a table no run has.
    reg.registryhub.register_table(
        "notifications", schema={"columns": [{"name": "id"}, {"name": "user_id"},
                                             {"name": "actor_id"}, {"name": "comment_id"}]},
        agent="backend")
    res = reg.registryhub.register_verification_chain(
        name="core_social_actions", steps=[R126], agent="verifier")
    err = str(res.get("error") or "")
    assert "unenforceable create denial" in err, res
    assert "owner column" in err and "user_id" in err
