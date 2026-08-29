"""#1156: routes whose handler BODIES are identical answer the same rows.

netflix-local-r13 delivered /api/titles, /api/titles/trending and
/api/titles/top10 all answering the same 60 rows.  r14, with #1155, shipped
top10 correctly (`.filter(top10_rank.isnot(None)).order_by(...).limit(10)`)
and still shipped `trending` as a copy of `/api/titles` -- it has no backing
column, so there is nothing to project and inventing an ordering would be a
guess.  The CONTRACT is what is incomplete, and only the lane can close it.

Read from the FINAL main.py, not from one generator's bookkeeping: r14's
handlers came from `backend_skeleton`, not `project_missing_routes`, and the
first version of this check lived inside the latter and stayed silent through
a whole run that had the defect.  The file is what ships.
"""
import textwrap
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    identical_projected_bodies_1156 as dupes)


def _backend(tmp_path, body: str, custom: str = ""):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(textwrap.dedent(body), encoding="utf-8")
    if custom:
        (be / "custom_routes.py").write_text(textwrap.dedent(custom), encoding="utf-8")
    return be


def test_two_routes_with_the_same_body_are_named(tmp_path):
    be = _backend(tmp_path, '''
        @app.get("/api/titles")
        def a(db=None):
            rows = db.query(Title).limit(100).all()
            return {"items": rows}

        @app.get("/api/titles/trending")
        def b(db=None):
            rows = db.query(Title).limit(100).all()
            return {"items": rows}
        ''')
    assert dupes(be) == [("GET /api/titles", "GET /api/titles/trending")]


def test_a_ranked_route_is_no_longer_a_duplicate(tmp_path):
    """#1155's shape, taken verbatim from r14's delivered main.py."""
    be = _backend(tmp_path, '''
        @app.get("/api/titles")
        def a(db=None):
            rows = db.query(Title).limit(100).all()
            return {"items": rows}

        @app.get("/api/titles/top10")
        def b(db=None):
            rows = db.query(Title).filter(getattr(Title, "top10_rank").isnot(None)).order_by(getattr(Title, "top10_rank")).limit(10).all()
            return {"items": rows}
        ''')
    assert dupes(be) == []


def test_the_decorator_and_name_are_not_compared(tmp_path):
    """Both encode the path, so comparing whole functions would find nothing."""
    be = _backend(tmp_path, '''
        @app.get("/api/a")
        def handler_one(db=None):
            rows = db.query(T).limit(100).all()
            return {"items": rows}

        @app.get("/api/b")
        def handler_two(db=None):
            rows = db.query(T).limit(100).all()
            return {"items": rows}
        ''')
    assert dupes(be) == [("GET /api/a", "GET /api/b")]


def test_non_db_handlers_are_not_a_contract_gap(tmp_path):
    """Two identical health probes or stubs are not the defect."""
    be = _backend(tmp_path, '''
        @app.get("/healthz")
        def a():
            return {"ok": True}

        @app.get("/readyz")
        def b():
            return {"ok": True}
        ''')
    assert dupes(be) == []


def test_a_missing_or_unparseable_main_never_raises(tmp_path):
    assert dupes(tmp_path / "nope") == []
    be = tmp_path / "broken"
    be.mkdir()
    (be / "main.py").write_text("def (: syntax error\n", encoding="utf-8")
    assert dupes(be) == []


def test_it_uses_no_word_list():
    src = Path(dupes.__module__ and
               __import__("env_generator.llm_generator.multi_agent.runtime."
                          "route_projector", fromlist=["x"]).__file__
               ).read_text(encoding="utf-8")
    i = src.index("def identical_projected_bodies_1156")
    body = src[i:src.index("\ndef ", i + 1)]
    for word in ("popular", "featured", "recommended"):
        assert ('"%s"' % word) not in body


def test_the_caller_makes_it_visible_without_blocking():
    h = Path(hp.__file__).read_text(encoding="utf-8")
    i = h.index("#1156: name the endpoints")
    seg = h[i:h.index("except Exception", i)]
    assert "identical_projected_bodies_1156" in seg
    assert "_logger.warning" in seg
    assert "failed_checks" not in seg


DUP_MAIN = '''
    @app.get("/api/titles")
    def a(db=None):
        rows = db.query(Title).limit(100).all()
        return {"items": rows}

    @app.get("/api/titles/trending")
    def b(db=None):
        rows = db.query(Title).limit(100).all()
        return {"items": rows}
    '''


def test_a_route_the_lane_serves_is_not_a_duplicate(tmp_path):
    """r14's real shape. The projected body IS identical to /api/titles, and it is
    DEAD: include_router(_custom_router) runs at main.py:948, hundreds of lines
    before the projected route, so the lane's handler wins. Probed on the live
    stack: ?limit=5 -> 5 rows, ?limit=37 -> 37. Reporting it would send a lane to
    fix an endpoint it had already implemented correctly."""
    be = _backend(tmp_path, DUP_MAIN, custom='''
        @router.get("/api/titles/trending")
        def trending_titles(limit: int = Query(default=20), db=None):
            return {"items": db.query(Title).limit(limit).all()}
        ''')
    assert dupes(be) == []


def test_without_a_lane_override_it_still_reports(tmp_path):
    """r13's real shape: no custom_routes entry, and the delivered API answered 60
    rows for /api/titles and /api/titles/trending alike."""
    assert dupes(_backend(tmp_path, DUP_MAIN)) == [
        ("GET /api/titles", "GET /api/titles/trending")]


def test_a_lane_override_on_a_DIFFERENT_verb_does_not_excuse_the_route(tmp_path):
    """POST /x does not make GET /x lane-served."""
    be = _backend(tmp_path, DUP_MAIN, custom='''
        @router.post("/api/titles/trending")
        def make(db=None):
            return {}
        ''')
    assert dupes(be) == [("GET /api/titles", "GET /api/titles/trending")]
