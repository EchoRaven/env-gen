"""#1202w6: the guard read the file the framework writes, not the file the app serves.

r126 delivered a cross-user read leak that `unscoped_owner_read_findings` could not see.

    contract      dm_conversations: owner_scoped_reads=True, visibility="owner"
    main.py       filter(DmConversation.user_id == _fw_owner_val(...))     <- honours it
    custom_routes.py  db.query(DmConversation) ... no filter, no actor     <- REPLACES it

Verified against the running stack: logged in as `charlidamelio` (id 2), `GET
/api/dm_conversations` returns rows owned by users 10, 24 and 25. The database has 20 rows and
that user owns 1.

Two independent blind spots let it through:

  1. the scan read `main.py` only, and the lane's file overrides it -- that is what
     `_remove_projected_route` exists for;
  2. the ownership gate asked only the SHAPE predicates, and `_is_user_content_relation`
     requires a second FK to a NON-user table. `dm_conversations(user_id, other_user_id)` has
     none, so the contract's explicit `owner_scoped_reads: True` was never consulted.

The function's own closing note named the assumption that had expired -- "the handler is
framework-projected and the lane cannot add the filter itself". The lane did not add anything;
it replaced the handler.

The admission is bounded by two independent statements, mirroring `_declared_public_1202gd` at
the same evidence standard for the opposite decision. Measured: the contract alone would flag
13 more (`videos`, `titles`, `sounds` marked owner-scoped while the materials call them
published); requiring the materials too drops every one. Result: 2 findings in 1 run of 176.
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

from multi_agent.runtime import backend_audit as BA      # noqa: E402

_MODELS = (
    "from sqlalchemy import Column, Integer, String, ForeignKey\n"
    "from sqlalchemy.orm import declarative_base\n"
    "Base = declarative_base()\n"
    "class User(Base):\n"
    "    __tablename__ = 'users'\n"
    "    id = Column(Integer, primary_key=True)\n"
    "class Thread(Base):\n"
    "    __tablename__ = 'threads'\n"
    "    id = Column(Integer, primary_key=True)\n"
    "    user_id = Column(Integer, ForeignKey('users.id'))\n"
    "    other_user_id = Column(Integer, ForeignKey('users.id'))\n"
)

_SCOPED = '@app.get("/api/threads")\ndef a(db=None, user=None):\n    return db.query(Thread).filter(Thread.user_id == 1).all()\n'
_UNSCOPED = '@router.get("/api/threads")\ndef b(db=None):\n    return db.query(Thread).all()\n'


def _run(tmp_path, *, contract_owner=True, materials="owner", main_src=_SCOPED,
         lane_src=None, auth_required=True):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "models.py").write_text(_MODELS, encoding="utf-8")
    (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n" + main_src,
                                encoding="utf-8")
    if lane_src:
        (be / "custom_routes.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n" + lane_src, encoding="utf-8")
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    md = {"owner_scoped_reads": contract_owner}
    if materials:
        md["visibility"] = materials
    (hubs / "registryhub_tables.json").write_text(
        json.dumps({"threads": {"name": "threads", "metadata": md}}), encoding="utf-8")
    (hubs / "registryhub_endpoints.json").write_text(json.dumps(
        {"GET /api/threads": {"metadata": {"auth_required": auth_required}}}), encoding="utf-8")
    return be


def test_a_lane_override_that_drops_the_filter_is_found(tmp_path):
    """The r126 shape: the framework's projection is correct and the lane replaces it."""
    be = _run(tmp_path, lane_src=_UNSCOPED)
    found = BA.unscoped_owner_read_findings(be)
    assert len(found) == 1, found
    assert "/api/threads" in found[0] and "threads" in found[0]


def test_the_framework_projection_alone_stays_clean(tmp_path):
    """No lane file, and main.py filters — nothing to report. This is the pre-#1202w6
    behaviour and it must not change."""
    assert BA.unscoped_owner_read_findings(_run(tmp_path)) == []


def test_the_contract_alone_is_not_enough(tmp_path):
    """The bound that keeps this off a mislabelled table. 13 corpus tables are marked
    owner-scoped while the materials call them published content."""
    be = _run(tmp_path, lane_src=_UNSCOPED, materials="public")
    assert BA.unscoped_owner_read_findings(be) == []


def test_the_materials_alone_are_not_enough(tmp_path):
    be = _run(tmp_path, lane_src=_UNSCOPED, contract_owner=False)
    assert BA.unscoped_owner_read_findings(be) == []


def test_the_reach_is_reported_from_the_contract_not_the_handler(tmp_path):
    """#1202gc puts the reach in the message because understating it is dangerous. The lane's
    handler takes no actor, and the blanket middleware still refuses a tokenless caller — so
    "ANY caller" would overstate it in the other direction and send the lane after the wrong
    fix. Verified against r126: a tokenless request gets 401."""
    be = _run(tmp_path, lane_src=_UNSCOPED, auth_required=True)
    msg = BA.unscoped_owner_read_findings(be)[0]
    assert "any authenticated caller" in msg
    assert "UNAUTHENTICATED" not in msg


def test_a_contract_public_route_is_still_called_unauthenticated(tmp_path):
    """And the louder reading survives where it is true: an explicitly public contract does
    open the route, so the exposure really is everyone."""
    be = _run(tmp_path, lane_src=_UNSCOPED, auth_required=False)
    msg = BA.unscoped_owner_read_findings(be)[0]
    assert "UNAUTHENTICATED" in msg


def test_both_served_files_are_read():
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(BA)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "unscoped_owner_read_findings")
    body = ast.unparse(fn)
    assert "'main.py', 'custom_routes.py'" in body.replace('"', "'"), (
        "the scan must read the file the app serves, not only the one the framework writes")


def test_the_reach_probe_says_when_it_could_not_read_the_contract():
    """#1202be caught this: the probe returns True on a crash, which is the LOUDER reading and
    the safe direction — but a reader comparing two findings still cannot tell "the contract
    opens this route" from "the contract could not be read". The ratchet's own rule is
    "announce it, or return a value the caller can tell apart", and the ceiling was not
    raised to admit it."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(BA)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_reachable_unauthenticated_1202w6")
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    assert handlers, "the probe must stay total"
    assert any("warn_once_1201" in ast.unparse(h) for h in handlers), (
        "a crash that widens a security finding has to announce itself")


def test_a_missing_contract_keeps_the_louder_reading(tmp_path):
    """Absent a contract there is nothing to say the route is closed, so the finding must not
    quietly narrow — the direction that would understate an exposure."""
    be = _run(tmp_path, lane_src=_UNSCOPED)
    (be.parents[1] / "shared" / "hubs" / "registryhub_endpoints.json").unlink()
    msg = BA.unscoped_owner_read_findings(be)[0]
    assert "UNAUTHENTICATED" in msg


def test_a_single_principal_table_is_left_to_the_projected_read(tmp_path):
    """#1202w6's false positive, found by probing the running app rather than reading source.

    `backend_skeleton` keeps a SINGLE-principal table inside `_OWNER_SCOPED_RESOURCES`, so the
    projected scoped read wins and the lane's unscoped handler never serves. r126 has exactly
    that in `user_settings`: the lane's `db.query(UserSetting).all()` sits in custom_routes.py
    and the endpoint still returns ONE row per caller, verified against the stack. Flagging it
    would send a lane after a handler that is not running."""
    models_one = _MODELS.replace(
        "    other_user_id = Column(Integer, ForeignKey('users.id'))\n", "")
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "models.py").write_text(models_one, encoding="utf-8")
    (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n" + _SCOPED,
                                encoding="utf-8")
    (be / "custom_routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n" + _UNSCOPED, encoding="utf-8")
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    import json as _j
    (hubs / "registryhub_tables.json").write_text(_j.dumps(
        {"threads": {"name": "threads",
                     "metadata": {"owner_scoped_reads": True, "visibility": "owner"}}}),
        encoding="utf-8")
    (hubs / "registryhub_endpoints.json").write_text(_j.dumps(
        {"GET /api/threads": {"metadata": {"auth_required": True}}}), encoding="utf-8")
    assert BA.unscoped_owner_read_findings(be) == [], (
        "a single-principal table keeps its projected read; the lane handler does not serve")


def test_the_handover_predicate_matches_the_skeleton_rule():
    """The rule is `len(principals) > 1`, and it must stay the same rule the skeleton applies
    when it builds `_OWNER_SCOPED_RESOURCES` — two copies of one decision is #1032."""
    one = {"cols": ["id", "user_id"], "fks": {"user_id": "users"}}
    two = {"cols": ["id", "user_id", "other_user_id"],
           "fks": {"user_id": "users", "other_user_id": "users"}}
    assert BA._handed_to_the_lane_1202w6(one) is False
    assert BA._handed_to_the_lane_1202w6(two) is True
    assert BA._handed_to_the_lane_1202w6(None) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
