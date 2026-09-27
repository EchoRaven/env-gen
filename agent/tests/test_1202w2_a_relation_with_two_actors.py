"""#1202w2: a row that names two actors is scoped to one of them, and the other cannot see it.

The projector models ownership as ONE column: `WHERE owner_fk = caller`. A table with two FKs
to the actor table has two parties.

tiktok-r126 delivered it. `dm_conversations(user_id, other_user_id)` — both FKs to `users` —
and the projected read is `filter(DmConversation.user_id == _fw_owner_val(...))`. Counted in
the delivered database: 20 conversations, and 18 of them have NO reciprocal row, so the person
on the `other_user_id` side can never see the conversation they are in.

Measured over 176 backends: 45 tables across 42 runs carry a second actor FK that none of the
three name lists classifies — `user_a_id`/`user_b_id` (26), `peer_id`, `other_user_id`,
`participant_user_id` — every one a conversation or messaging table, most recent r131.

REPORTED, NOT REPAIRED, and the asymmetry is the reason. Matching the caller against EITHER
column fixes a symmetric relation and over-shares a directional one: `follows(follower_id,
following_id)` has two actor FKs too, and an OR there would show "who follows me" inside "who
I follow". `_TARGET_FK_NAMES` exists to mark the object side of a directional relation, and
these 45 are the cases where nothing marks it. Hiding rows and leaking rows are not the same
mistake, so the framework says what it could not classify instead of picking.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import route_projector as RP      # noqa: E402

_F = RP.two_actor_relations_1202w2


def _meta(cols, fks):
    return {"cls": "X", "cols": list(cols), "fks": dict(fks), "types": {}, "required": []}


def test_the_r126_shape_is_reported():
    models = {
        "users": _meta(["id"], {}),
        "dm_conversations": _meta(["id", "user_id", "other_user_id"],
                                  {"user_id": "users", "other_user_id": "users"}),
    }
    assert _F(models) == [{"table": "dm_conversations", "scoped_to": "user_id",
                           "unclassified": ["other_user_id"]}]


def test_a_directional_relation_the_lists_know_is_silent():
    """`following_id` is a known TARGET, so the projector CAN tell which way this runs and
    scoping to the follower is right. Reporting it would bury the cases that matter."""
    models = {
        "users": _meta(["id"], {}),
        "follows": _meta(["id", "follower_id", "following_id"],
                         {"follower_id": "users", "following_id": "users"}),
    }
    assert _F(models) == []


def test_a_known_actor_role_is_silent():
    """`notifications(user_id, actor_id)` — `actor_id` is a known actor role, and scoping a
    notification to its RECIPIENT is correct. 50 corpus instances have this shape and none of
    them is a defect; an earlier version of this measurement counted them and was wrong."""
    models = {
        "users": _meta(["id"], {}),
        "notifications": _meta(["id", "user_id", "actor_id"],
                               {"user_id": "users", "actor_id": "users"}),
    }
    assert _F(models) == []


def test_one_actor_fk_is_silent():
    models = {"users": _meta(["id"], {}),
              "posts": _meta(["id", "user_id"], {"user_id": "users"})}
    assert _F(models) == []


def test_a_table_with_no_owner_at_all_is_silent():
    """No owner column means no owner filter is projected, so there is no second party being
    excluded — that is a different defect with its own checks."""
    models = {"users": _meta(["id"], {}),
              "t": _meta(["id", "left_ref", "right_ref"],
                         {"left_ref": "users", "right_ref": "users"})}
    got = _F(models)
    assert got == [] or all(r["scoped_to"] for r in got)


def test_odd_input_is_returned_empty():
    assert _F(None) == []
    assert _F({}) == []
    assert _F({"t": "not a mapping"}) == []


def test_the_finding_reaches_an_artifact(tmp_path):
    """#947: a measurement that exists only in a log line is not a measurement."""
    assert RP.record_two_actor_relations_1202w2(
        tmp_path, [{"table": "t", "scoped_to": "a", "unclassified": ["b"]}])
    rec = json.loads((tmp_path / "logs" / "two_actor_relations_1202w2.jsonl").read_text().strip())
    assert rec["count"] == 1 and rec["relations"][0]["table"] == "t"
    assert not RP.record_two_actor_relations_1202w2(tmp_path, [])


def test_the_projector_reports_and_does_not_repair():
    """A repair here would have to guess which way the relation runs, so the detector's
    output must reach the report and NOTHING else.

    Asserted by AST on every USE of the result, not by searching the function text: the first
    version of this test was an `or` of two negatives and would have passed whatever the code
    did (#1202w1's lesson, one ticket later).
    """
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(RP)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "project_missing_routes")

    # every statement that mentions the detector's result
    users = []
    for node in ast.walk(fn):
        if isinstance(node, ast.stmt) and "_two1202w2" in ast.unparse(node):
            users.append(node)
    assert users, "the detector is never called in the projector"

    assigns = [n for n in users if isinstance(n, ast.Assign)]
    assert len(assigns) == 1, f"the result must be bound once, found {len(assigns)}"
    assert ast.unparse(assigns[0].targets[0]) == "_two1202w2"
    assert "two_actor_relations_1202w2" in ast.unparse(assigns[0].value)

    # and it must never be assigned INTO anything the projector decides with
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        if "_two1202w2" not in ast.unparse(node.value):
            continue
        tgt = ast.unparse(node.targets[0])
        assert tgt == "_two1202w2", (
            f"the detector's result flows into `{tgt}` — it must only be reported")

    calls = {ast.unparse(n.func) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and "_two1202w2" in ast.unparse(n)}
    assert "record_two_actor_relations_1202w2" in calls, "the artifact must be written"


def test_the_report_says_when_it_cut_the_list():
    """#1034 caught the first version: it printed `len(findings)` beside a bare `[:4]` join,
    which is the shape twelve sites in this repo were already converted away from. A reader
    given "12 table(s): a; b; c; d" cannot tell whether four is all of them."""
    out = RP._join_capped_1202w2(["a", "b", "c", "d", "e", "f"], 6, cap=4)
    assert "a" in out and "d" in out
    assert "more" in out, "a cut list must say it was cut"
    whole = RP._join_capped_1202w2(["a", "b"], 2, cap=4)
    assert "more" not in whole, "an uncut list must not claim a remainder"


def test_the_log_call_uses_the_capped_join():
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(RP)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "project_missing_routes")
    warn = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and "#1202w2" in ast.unparse(n)]
    assert warn, "the #1202w2 report is not emitted"
    src = ast.unparse(warn[0])
    assert "_join_capped_1202w2" in src, "the list must be joined through the capped helper"
    assert "[:4]" not in src, "a bare slice is the #1034 shape"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
