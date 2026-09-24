r"""#1200: the lane's own READ filter is evidence that a read is per-user.

r23 shipped a CROSS-USER LEAK and delivered with every gate green. Live, on the delivered
artifact (backend :8011):

    ava.chen        GET /api/profiles -> 33 profiles, user_ids 1,2,11,12,14,17,18,19...
    sofia.martinez  GET /api/profiles -> the same 33
    r26, same shape ->  1 profile each, correctly scoped

The chain, end to end:

  * `owner_scoped_reads` is set only for tables some verifier chain happens to probe for
    cross-user isolation. r23 had no such chain for `profiles`.
  * `_is_user_content_relation` (#598) deliberately does not cover it: a table with a user FK
    and NOTHING else is shape-identical to a public feed (`posts(user_id, title, body)`), and
    scoping by shape would break every such feed. That reasoning is sound.
  * So the projection shipped `db.query(Profile).limit(100).all()`.
  * And the lane's own correctly-scoped handler was DROPPED — "duplicate standard CRUD ...
    the framework's projected handler serves them, and it is schema-safe by construction",
    which is precisely false when the projection is unscoped:

        custom_routes.py:  db.query(Profile).filter(Profile.user_id == _user_id(user))
        main.py (won):     db.query(Profile).limit(100).all()

The fix takes the lane's filter as the judgment it is and scopes the PROJECTION with it.
Restoring the lane's route instead would be the r130 wedge in the other direction — a buggy
lane GET oscillating 403-own / 200-cross-user until the run died at 0 tags — so "projected
wins" is untouched.

#77's caution is honoured: only a READ handler counts. A write handler that checks ownership
proves write authz only, which is true of public resources too, and using it as a read signal
once scoped a world-readable feed to its caller.

Verified against the real corpus: r23 -> {'profiles'} (the leak closes), r22 -> {'profiles'}
(already opted in via a chain; the union is a no-op), r26 -> set() (its lane wrote no custom
read filter, and its chain-based opt-in still works).
"""

import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _lane_owner_scoped_read_tables_1200,
)

_TABLES = {"profiles": {}, "titles": {}, "my_list": {}}


def _backend(tmp_path, custom_routes: str):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    if custom_routes is not None:
        (be / "custom_routes.py").write_text(custom_routes, encoding="utf-8")
    return be


# r23's handler, as delivered.
_R23_READ = '''
@router.get("/api/profiles")
def list_profiles(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """List profiles owned by the authenticated user."""
    _resolve_profile_id(db, user)
    rows = db.query(Profile).filter(Profile.user_id == _user_id(user)).order_by(Profile.id.asc()).all()
    return {"items": [_profile_payload(p) for p in rows], "total": len(rows)}
'''


def test_a_lane_read_filter_is_detected(tmp_path):
    be = _backend(tmp_path, _R23_READ)
    assert _lane_owner_scoped_read_tables_1200(be, _TABLES) == {"profiles"}


def test_a_write_side_ownership_check_is_not_read_evidence(tmp_path):
    """#77: a cross-user WRITE denial proves write authz only — it is true of public
    resources too, and using it as a read signal scoped a world-readable feed to its caller."""
    be = _backend(tmp_path, '''
@router.post("/api/profiles")
def create_profile(body: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(Profile).filter(Profile.user_id == _user_id(user)).all()
    if len(rows) > 4:
        raise HTTPException(status_code=400, detail="too many profiles")
    return {"item": {}}
''')
    assert _lane_owner_scoped_read_tables_1200(be, _TABLES) == set()


def test_an_unfiltered_lane_read_is_not_evidence(tmp_path):
    """A public feed the lane serves to everyone must not be scoped."""
    be = _backend(tmp_path, '''
@router.get("/api/titles")
def list_titles(db: Session = Depends(get_db)):
    return {"items": db.query(Title).limit(100).all()}
''')
    assert _lane_owner_scoped_read_tables_1200(be, _TABLES) == set()


def test_the_handler_bodies_are_bounded_by_the_next_route(tmp_path):
    """#943 landmark, not a byte window: an unfiltered GET followed by a filtered one must
    not inherit its neighbour's filter."""
    be = _backend(tmp_path, '''
@router.get("/api/titles")
def list_titles(db: Session = Depends(get_db)):
    return {"items": db.query(Title).limit(100).all()}

@router.get("/api/profiles")
def list_profiles(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {"items": db.query(Profile).filter(Profile.user_id == _user_id(user)).all()}
''')
    assert _lane_owner_scoped_read_tables_1200(be, _TABLES) == {"profiles"}


def test_no_custom_routes_reproduces_the_previous_behaviour(tmp_path):
    assert _lane_owner_scoped_read_tables_1200(_backend(tmp_path, None), _TABLES) == set()


def test_an_unreadable_backend_never_raises(tmp_path):
    assert _lane_owner_scoped_read_tables_1200(tmp_path / "nope", _TABLES) == set()
    assert _lane_owner_scoped_read_tables_1200(None, _TABLES) == set()


# ------------------------------------- end to end, on the real generator (no LLM involved)

def test_the_generated_read_goes_from_unscoped_to_scoped(tmp_path):
    """The projection is deterministic, so the fix can be validated on the generation path
    itself rather than only on its inputs.

    Rendered twice from the same contract — once with r23's metadata as it actually was, once
    with the signal this fix derives from the lane's own handler:

        before:  rows = db.query(Profile).limit(100).all()
        after:   rows = db.query(Profile).filter(
                     getattr(Profile, "user_id") == _fw_owner_val(Profile, "user_id", user))

    The first line is the one that served every account's profiles to every account.
    """
    from multi_agent.runtime.backend_skeleton import write_backend_skeleton

    tables = {
        "users": {"schema": {"columns": [{"name": "id", "type": "serial primary key"},
                                         {"name": "email", "type": "text"}]}},
        "profiles": {"schema": {"columns": [{"name": "id", "type": "serial primary key"},
                                            {"name": "user_id", "type": "integer"},
                                            {"name": "name", "type": "text"}]},
                     "metadata": {}},
    }
    endpoints = [{"method": "GET", "path": "/api/profiles",
                  "metadata": {"auth_required": True, "response_key": "items"}}]
    lane = ('@router.get("/api/profiles")\n'
            'def list_profiles(db=Depends(get_db), user=Depends(get_current_user)):\n'
            '    rows = db.query(Profile).filter(Profile.user_id == _user_id(user)).all()\n'
            '    return {"items": rows}\n')

    def render(tbls, tag):
        out = tmp_path / tag
        (out / "app" / "backend").mkdir(parents=True)
        (out / "app" / "backend" / "custom_routes.py").write_text(lane, encoding="utf-8")
        write_backend_skeleton(out, endpoints, tbls)
        src = (out / "app" / "backend" / "main.py").read_text(encoding="utf-8")
        i = src.index("def _projected_get_api_profiles")
        return src[i:src.index("return", i)]          # landmark, not a byte window (#943)

    before = render(tables, "before")
    assert "_fw_owner_val" not in before              # r23, as delivered
    assert ".limit(" in before

    scoped = dict(tables)
    signal = _lane_owner_scoped_read_tables_1200(
        tmp_path / "before" / "app" / "backend", tables)
    assert signal == {"profiles"}
    for t in signal:
        rec = dict(scoped[t])
        rec["metadata"] = dict(rec.get("metadata") or {}, owner_scoped_reads=True)
        scoped[t] = rec

    after = render(scoped, "after")
    assert "_fw_owner_val" in after
    assert "user_id" in after


def test_the_two_signals_cannot_disable_each_other():
    """#1200's signal was first written INSIDE the try whose opening statement imports
    `_isolation_scoped_tables_from_chains` from heal_pipeline. A circular import or a raising
    hub there would have been swallowed by that block's `except Exception: pass` — taking the
    new signal down with it and leaving the leak exactly as it was, silently. That is the
    shape of most defects fixed this session, so the structure is pinned rather than trusted.
    """
    src = (Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
           ).read_text(encoding="utf-8")
    at = src.index("_lane_owner_scoped_read_tables_1200")
    # Landmark, not a byte window (#943): the try that encloses this call is the last one
    # opened before it.
    enclosing = src.rindex("try:", 0, at)
    assert "heal_pipeline" not in src[enclosing:at], (
        "the lane-read signal shares a try with the chain-probe signal; either failing "
        "would silently disable the other")
    # And the application of the union sits outside both, so a failure of either signal
    # still applies whatever the other found.
    # #782: match the CONSTRUCT, not its spelling — pinning `except Exception:` would have
    # made `except Exception as _e:` (which #1201 needs to report the failure) a violation.
    apply_at = src.index('_md["owner_scoped_reads"] = True', at)
    assert re.search(r"except\s+Exception", src[at:apply_at])
