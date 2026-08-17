r"""#919: the page-level privacy axis — the last of the three the gates never looked for.

#908 was live in r153, the arc's best run:

    @app.get("/api/my-list")
    def _projected_get_api_my_list_7(db=Depends(get_db), user=Depends(get_current_user)):
        rows = db.query(MyList).limit(100).all()      # every account's rows

…beside a POST that 403s a foreign `profile_id`. It cleared every gate in the framework and was
found by reading the delivered backend by hand. This is the gate that would have caught it.

    corpus: 153 delivered backends
    ★ 159 findings across exactly TWO endpoints — /api/my-list (79), /api/continue-watching (80)
      both genuinely per-user; no other path fires, so the false-positive rate here is zero

★ It BLOCKS, like #173 (stub handler) and #175 (invented field) and unlike #909/#910/#918. The line
is not severity, it is category: those three report a CONTRACT that describes a different page,
which is not a broken app; this reports a functional defect in the artifact that ships.
`ENVGEN_OWNER_READ_GATE=0` disables it.

★ The decision is not re-derived. `_owner_fk` recognises the owner column and
`_is_per_user_sub_entity_fk` / `_is_user_content_relation` decide whether the read should be
scoped — the same functions `route_projector` consults when deciding whether to EMIT the filter.
#908 happened because two functions ten lines apart held different evidence standards for one
column; sharing them is how this gate cannot drift from the generator.
"""
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_audit as ba
from env_generator.llm_generator.multi_agent.runtime import deliverability as dv


_MODELS = """
from sqlalchemy import Column, Integer, Text
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(Text)

class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)

class MyList(Base):
    __tablename__ = "my_list"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer)
    title_id = Column(Integer)

class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    name = Column(Text)
"""


def _backend(main_body: str):
    d = Path(tempfile.mkdtemp()) / "app" / "backend"
    d.mkdir(parents=True)
    (d / "models.py").write_text(_MODELS, encoding="utf-8")
    (d / "main.py").write_text(main_body, encoding="utf-8")
    return d


_LEAK = '''
@app.get("/api/my-list")
def _projected_get_api_my_list(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(MyList).limit(100).all()
    return {"items": rows}
'''

_SCOPED = '''
@app.get("/api/my-list")
def _projected_get_api_my_list(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(MyList).filter(getattr(MyList, "profile_id") == _fw_owner_val(MyList, "profile_id", user)).all()
    return {"items": rows}
'''

_PUBLIC = '''
@app.get("/api/titles")
def _projected_get_api_titles(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(Title).limit(100).all()
    return {"items": rows}
'''


def test_the_r153_leak_is_caught():
    """★ #908's exact shape, verbatim."""
    found = ba.unscoped_owner_read_findings(_backend(_LEAK))
    assert len(found) == 1, found
    assert "/api/my-list" in found[0] and "my_list" in found[0]


def test_a_scoped_read_is_clean():
    assert ba.unscoped_owner_read_findings(_backend(_SCOPED)) == []


def test_a_public_catalog_read_is_clean():
    """`titles` has no owner column, so an unfiltered read is correct — the projector does not
    emit a filter there either, which is the point of sharing the decision."""
    assert ba.unscoped_owner_read_findings(_backend(_PUBLIC)) == []


def test_a_raw_sql_where_counts_as_scoping():
    """The lane's own handlers use `text("… WHERE … user_id = :uid")`; the gate must not demand
    an ORM `.filter(`."""
    body = ('\n@app.get("/api/my-list")\n'
            'def h(db=Depends(get_db), user=Depends(get_current_user)):\n'
            '    return db.execute(text("SELECT * FROM my_list WHERE profile_id = :p"), {"p": 1})\n')
    assert ba.unscoped_owner_read_findings(_backend(body)) == []


def test_a_missing_backend_is_not_a_finding():
    """Best-effort: an absent or unparseable tree reports nothing rather than raising into the
    gate — #792's discipline, and the reason a broken audit cannot wedge a release."""
    assert ba.unscoped_owner_read_findings(Path("/nonexistent")) == []
    d = Path(tempfile.mkdtemp())
    (d / "main.py").write_text("this is not python (((", encoding="utf-8")
    assert ba.unscoped_owner_read_findings(d) == []


def test_the_message_names_the_fix():
    found = ba.unscoped_owner_read_findings(_backend(_LEAK))
    assert "Scope the read to the caller" in found[0]
    assert "profile_id" in found[0]


# --------------------------------------------------------------------------- the gate wiring

def test_it_reaches_the_delivery_blockers():
    app_root = _backend(_LEAK).parent
    assert dv._unscoped_owner_read_blockers(app_root), "the gate must surface the finding"


def test_the_env_switch_disables_it(monkeypatch):
    app_root = _backend(_LEAK).parent
    monkeypatch.setenv("ENVGEN_OWNER_READ_GATE", "0")
    assert dv._unscoped_owner_read_blockers(app_root) == []


def test_it_is_wired_into_the_blocker_list():
    """Non-vacuity for the tests above: a detector nobody calls is #903's shape."""
    import inspect
    src = inspect.getsource(dv)
    assert "blockers.extend(_unscoped_owner_read_blockers(app_root))" in src


def test_it_shares_the_projector_s_ownership_decision():
    """★ #908 existed because two functions ten lines apart disagreed about one column. If this
    gate ever grows its own copy, that is the regression."""
    import inspect
    src = inspect.getsource(ba)
    assert "_is_per_user_sub_entity_fk" in src and "_is_user_content_relation" in src
    assert "_owner_fk" in src

# --------------------------------------------------------------------------- generator vs gate

_PROJ_MODELS = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"], "fks": {}},
    "my_list": {"cls": "MyList", "cols": ["id", "profile_id", "title_id"], "fks": {}},
    "continue_watching": {"cls": "ContinueWatching",
                          "cols": ["id", "profile_id", "title_id"], "fks": {}},
    "titles": {"cls": "Title", "cols": ["id", "name"], "fks": {}},
}


def test_the_gate_is_silent_on_the_projector_s_own_output():
    """★ The invariant that makes BLOCKING safe, and the one #908 broke.

    This gate blocks, and the corpus holds 159 instances of the shape it blocks on. If the
    generator still emitted an unscoped read, #919 would wedge every run — so the two are run
    against each other here: project the handlers, feed them to the gate, require silence.

    ★ Precisely what it covers, because the obvious claim is wrong: this catches a ONE-SIDED
    drift — the projector stops emitting the filter while the gate still recognises the
    ownership, or the reverse. It does NOT catch a both-sided regression: disabling #908 makes
    both blind and this test stays green (verified). That direction is covered by
    `test_the_r153_leak_is_caught`, which uses a hand-written leak and never touches the
    projector — so the pair is complete only because the two tests fail on different things.
    """
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp

    d = Path(tempfile.mkdtemp()) / "app" / "backend"
    d.mkdir(parents=True)
    (d / "models.py").write_text(_MODELS + """
class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer)
    title_id = Column(Integer)
""", encoding="utf-8")
    (d / "main.py").write_text("\n".join(
        rp._generate_handler("GET", path, True, _PROJ_MODELS, i)
        for i, path in enumerate(["/api/my-list", "/api/continue-watching", "/api/titles"])
    ), encoding="utf-8")

    assert ba.unscoped_owner_read_findings(d) == [], (
        "the projector emitted a read this gate blocks on — blocking would wedge every run")


def test_the_projector_really_does_emit_the_filter():
    """Non-vacuity for the test above: silence must come from a SCOPED read, not from the gate
    failing to see the handler at all."""
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
    block = rp._generate_handler("GET", "/api/my-list", True, _PROJ_MODELS, 0)
    assert ".filter(" in block and "_fw_owner_val" in block, block[:300]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
