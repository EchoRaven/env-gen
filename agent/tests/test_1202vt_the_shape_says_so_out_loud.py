"""#1202vt: when a table's SHAPE reverses an explicit public contract, say so.

`#1202kx` announces the demotion when the MATERIALS contradict an `auth_required=False`.
The sibling branch two lines below it demotes on the table's shape alone — which is the
branch that runs when the materials say nothing — and it said nothing.

Measured: `route_projector` contains no logging calls at all, and a precise search of every
run log in the corpus finds zero mentions of this decision, against 615 firings of #1202kx.
With the contract, the materials and the projected source aligned three ways, 23 endpoints
across the corpus are declared public, projected with an actor, and carry no materials
verdict — every one demoted here without a word.

r137 is the cost, and it is #1202kx's own r117 story through this door. The lane saw a 401
on a route its contract called public; #1202kx did not fire because the materials named no
verdict to disagree with; the lane went into `_FW_PUBLIC_API_1202KH` from custom_routes.py;
the run ended on `deliverability_guard_tampering` at 81 minutes and $190.49. #1202kx had
already written the conclusion: "a lane that knew WHY it was being refused had no reason to
build that."

The message's way out differs from #1202kx's on purpose: there is no materials verdict to
correct here, there is one to ADD.

★ #1202zn CHANGED THIS FIXTURE'S TABLE, and the reason is the point of that ticket.
The fixture was `feed_items`, and #1202zn stops the shape from reversing a DELIBERATE
`auth_required=False` on a table the framework's own `_FEED_SHAPED_TOKENS` calls a feed —
r140's `/api/feed` is exactly that case, and it is now released rather than announced.
So the announcer is exercised here on `saved_items`, which is #1202gd's named private
counterpart ("`videos(author_id, sound_id, ...)` and `saved_items(user_id, item_id)` are
the same shape") and still demotes. The last test below pins the other half: where the
reversal no longer happens, there must be NOTHING to announce.
"""
import ast
import inspect
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import backend_skeleton as BS      # noqa: E402

_COLS = [
    {"name": "id", "type": "integer primary_key"},
    {"name": "user_id", "type": "integer references users.id", "references": "users(id)"},
    {"name": "topic_id", "type": "integer references topics.id", "references": "topics(id)"},
    {"name": "body", "type": "string"},
]


def _tables(visibility=None):
    """A #598-shaped table: a users FK beside another entity's FK."""
    md = {"owner_scoped_reads": False}
    if visibility:
        md["visibility"] = visibility
    return {
        "saved_items": {"name": "saved_items", "schema": {"columns": _COLS}, "metadata": md},
        "users": {"name": "users", "schema": {"columns": [
            {"name": "id", "type": "integer primary_key"}]}, "metadata": {}},
        "topics": {"name": "topics", "schema": {"columns": [
            {"name": "id", "type": "integer primary_key"}]}, "metadata": {}},
    }


_ENDPOINT = [{"method": "GET", "path": "/api/saved_items", "auth_required": False,
              "metadata": {"auth_required": False}}]


def test_the_demotion_is_announced_when_the_materials_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=BS.__name__):
        BS.render_skeleton_main(_ENDPOINT, _tables())
    msgs = [r.getMessage() for r in caplog.records if "#1202vt" in r.getMessage()]
    assert msgs, "the shape reversed an explicit public contract and said nothing"
    m = msgs[0]
    assert "GET /api/saved_items" in m, "the endpoint must be named"
    assert "saved_items" in m, "the table whose shape decided must be named"
    assert "user_id->users" in m and "topic_id->topics" in m, (
        "the two FKs that triggered #598 must be named, or the lane cannot check the reasoning")
    assert "visibility" in m, "the one way out must be named"
    assert "not a way out" in m, "the tampering door must be closed explicitly (#1202kx/r117)"


def test_nothing_is_said_when_the_contract_did_not_claim_public(caplog):
    """Only a REVERSAL is news. An endpoint that never claimed public is projected with an
    actor as a matter of course, and announcing that would bury the case that matters."""
    ep = [{"method": "GET", "path": "/api/saved_items", "metadata": {"auth_required": True}}]
    with caplog.at_level(logging.WARNING, logger=BS.__name__):
        BS.render_skeleton_main(ep, _tables())
    assert not [r for r in caplog.records if "#1202vt" in r.getMessage()]


def test_nothing_is_said_when_the_materials_released_the_read(caplog):
    """A materials `public` verdict stops the shape deciding at all (#1202hh), so there is
    no reversal to report — and this is the state #1202vr restores."""
    with caplog.at_level(logging.WARNING, logger=BS.__name__):
        BS.render_skeleton_main(_ENDPOINT, _tables("public"))
    assert not [r for r in caplog.records if "#1202vt" in r.getMessage()]


def test_the_materials_contradiction_keeps_its_own_message(caplog):
    """#1202kx and #1202vt are different situations with different ways out; a table the
    materials call owner-private must still get #1202kx, not this one."""
    with caplog.at_level(logging.WARNING, logger=BS.__name__):
        BS.render_skeleton_main(_ENDPOINT, _tables("owner"))
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "#1202kx" in said
    assert "#1202vt" not in said


def test_the_demotion_itself_is_unchanged():
    """Announce only. The handler for the silent case must still take an actor — this fix
    must not become a release (#1202hh: releasing needs the materials AND the contract)."""
    src = BS.render_skeleton_main(_ENDPOINT, _tables())
    i = src.index('@app.get("/api/saved_items")')
    j = src.index("):", i)
    assert "get_current_user" in src[i:j], (
        "the by-construction privacy must still force an actor (#271/#1098)")


def test_the_swallowed_classifier_announces():
    """#1202ah: if this decision raises, the route is projected public, which reads exactly
    like 'the shape said public' — the one reading that must never be guessed."""
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(BS)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "render_skeleton_main")
    body = ast.unparse(fn)
    assert "_structurally_private_resource_633" in body
    assert "warn_once_1201" in body


# --- #1202vu: the OTHER emitter, and only one copy of the notice ------------------------

_MODELS_PY = (
    "from sqlalchemy import Column, Integer, String, ForeignKey\n"
    "from sqlalchemy.orm import declarative_base\n"
    "Base = declarative_base()\n"
    "class Saveditem(Base):\n"
    "    __tablename__ = 'saved_items'\n"
    "    id = Column(Integer, primary_key=True)\n"
    "    user_id = Column(Integer, ForeignKey('users.id'))\n"
    "    topic_id = Column(Integer, ForeignKey('topics.id'))\n"
    "    body = Column(String)\n"
    "class User(Base):\n"
    "    __tablename__ = 'users'\n"
    "    id = Column(Integer, primary_key=True)\n"
    "class Topic(Base):\n"
    "    __tablename__ = 'topics'\n"
    "    id = Column(Integer, primary_key=True)\n"
)


def _backend(tmp_path):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "models.py").write_text(_MODELS_PY, encoding="utf-8")
    (be / "main.py").write_text(
        "from fastapi import FastAPI, Depends, Query\n"
        "from auth_dependency import get_current_user\n"
        "app = FastAPI()\n", encoding="utf-8")
    return be


def test_the_delivery_time_projector_announces_too(tmp_path, caplog):
    """#1202vu. `render_skeleton_main` is the primary generator, but an endpoint registered
    after it ran is emitted HERE — and this emitter runs the identical release-then-override
    pair. Fixing one of two doors is the asymmetry #1032 exists to prevent."""
    from multi_agent.runtime import route_projector as RP

    be = _backend(tmp_path)
    with caplog.at_level(logging.WARNING, logger=RP.__name__):
        RP.project_missing_routes(
            be, [{"method": "GET", "path": "/api/saved_items", "auth_required": False,
                  "metadata": {"auth_required": False}}])
    assert [r for r in caplog.records if "#1202vt" in r.getMessage()], (
        "the delivery-time projector demoted an explicit public read and said nothing")


def test_the_notice_exists_once_in_the_runtime():
    """One copy, not two. Both emitters call the same function, so the wording cannot drift
    apart the way #1202my had to repair across these very two call sites."""
    runtime = pathlib.Path(BS.__file__).parent
    marker = "SHAPE OVERRODE AN EXPLICIT PUBLIC"
    owners = []
    for py in sorted(runtime.glob("*.py")):
        if marker in py.read_text(encoding="utf-8"):
            owners.append(py.name)
    assert owners == ["route_projector.py"], (
        f"the notice should live in exactly one module, found: {owners}")


def test_both_emitters_call_the_one_notice():
    """Structural, by AST: each emitter must reach the shared helper, so neither can be
    left silent by an edit to the other."""
    for mod, fn_name in ((BS, "render_skeleton_main"),
                         (__import__("multi_agent.runtime.route_projector",
                                     fromlist=["x"]), "project_missing_routes")):
        tree = ast.parse(inspect.getsource(mod))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == fn_name)
        body = ast.unparse(fn)
        assert "_structurally_private_resource_633" in body, fn_name
        assert "announce_shape_override_1202vt" in body, (
            f"{fn_name} overrides on shape without reaching the notice")


def test_the_notice_holds_its_tongue_when_nothing_was_reversed(tmp_path, caplog):
    from multi_agent.runtime import route_projector as RP

    be = _backend(tmp_path)
    models = RP._orm_models(be)
    with caplog.at_level(logging.WARNING, logger=RP.__name__):
        spoke = RP.announce_shape_override_1202vt("GET", "/api/saved_items", models, False)
    assert spoke is False
    assert not [r for r in caplog.records if "#1202vt" in r.getMessage()]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_released_feed_table_has_nothing_to_announce():
    """★ #1202zn's other half. The notice exists because a reversal happened silently; once
    the reversal does not happen, a notice would be describing a decision nobody made — which
    is how a log comes to disagree with the code that wrote it."""
    import multi_agent.runtime.route_projector as RP
    models = {
        "feed": {"cls": "Feed", "cols": ["id", "user_id", "topic_id", "body"],
                 "fks": {"user_id": "users", "topic_id": "topics"},
                 "types": {}, "required": []},
        "users": {"cls": "User", "cols": ["id"], "fks": {}, "types": {}, "required": []},
        "topics": {"cls": "Topic", "cols": ["id"], "fks": {}, "types": {}, "required": []},
    }
    assert RP._structurally_private_resource_633("GET", "/api/feed", models, True) is False
    assert RP._structurally_private_resource_633("GET", "/api/feed", models, False) is True
