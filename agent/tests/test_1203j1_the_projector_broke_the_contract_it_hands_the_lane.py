r"""#1203j1: the projector shipped `total: len(rows)` under its own `.limit(100)`.

`_AGENT_NOTES` hands every lane this contract:

    list -> {"items": [...], "total": N}; `N` is the size of the WHOLE COLLECTION the
    endpoint lists, after its filters

and the projector's own handlers answered

    rows = db.query(Cls).limit(100).all()
    return {"items": [...], "total": len(rows)}

`len(rows)` is capped by the limit on the line above, so for any collection over the page it
is the PAGE size. #1202os defined `total` as the collection size and implemented it with
`query.count()` — in ONE branch. Five sibling branches kept `len(rows)`: the nested
scope_fk collection, the many-to-many and plain nested collections, the owner-scoped private
list, and the ranked and plain public lists.

Why it is a defect even though every corpus table is small (the largest is 19 rows, so no
shipped app has reached the cap): the user's standing rule is that framework-projected code,
which a lane CANNOT edit, must be generically correct — "不是只在 tiktok 上对" — and that
rule says to audit rather than wait for a run to break. There is a second reason to care:
this is also the example a lane reads. #1203i9 put the definition of `total` into the lane's
contract and r184 shipped `{"items": items, "total": len(items), "next_cursor": ...}` anyway;
a lane copying the projector's own handlers would learn exactly that.

The `rows = ...` lines are left BYTE-IDENTICAL on purpose: #1202os's comment says keeping
them so "is what keeps the 69 corpus assertions about `db.query(Cls).limit(100).all()`
honest", and 24 test files assert that string. Only the `total` expression changed.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
if str(LLM) not in sys.path:
    sys.path.insert(0, str(LLM))

from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from db import Base


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    category = Column(String)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    body = Column(String)
'''


def _project(tmp_path, endpoints):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    (backend / "main.py").write_text(
        "from fastapi import Depends, FastAPI, Query\napp = FastAPI()\n")
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "videos", "visibility": "public"},
                      {"name": "comments", "visibility": "public"}]}))
    project_missing_routes(backend, endpoints)
    return (backend / "main.py").read_text()


class _Query:
    """`count()` is deliberately NOT `len(rows)` — that difference is the whole test."""

    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def filter(self, cond):
        self.log.append(("filter", cond))
        return self

    def join(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def offset(self, n):
        return self

    def limit(self, n):
        self.log.append(("limit", n))
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def count(self):
        return len(self.rows) + 7


def _run(src, path, rows_n=2):
    m = re.search(r'@app\.get\("%s"\)\ndef (\w+)\(' % re.escape(path), src)
    assert m, "no projected handler for %s" % path
    fn_name = m.group(1)
    log = []
    rows = [type("R", (), {"id": i + 1, "video_id": 5, "body": "x", "category": "c"})()
            for i in range(rows_n)]

    class _DB:
        def query(self, cls):
            log.append(("query", getattr(cls, "__name__", str(cls))))
            return _Query(rows, log)

    ns = {"Depends": lambda f=None: None, "Query": lambda default=None, **k: default,
          "get_db": None, "get_current_user": None, "HTTPException": Exception,
          "Comment": type("Comment", (), {"video_id": "COL_video_id", "id": "COL_id"}),
          "Video": type("Video", (), {"category": "COL_category", "id": "COL_id"}),
          "_fw_owner_val": lambda *a, **k: 1}
    body = re.search(r'(def %s\(.*?)(?=\n@app|\Z)' % fn_name, src, re.S).group(1)
    exec(compile(body, "<emitted>", "exec"), ns)
    sig = re.search(r'def %s\(([^\n]*)\):' % fn_name, src).group(1)
    kwargs = {}
    if "db" in sig:
        kwargs["db"] = _DB()
    if "user" in sig:
        kwargs["user"] = type("U", (), {"id": 1})()
    return ns[fn_name](**kwargs), log, rows


# --- the behaviour, on the code the projector actually emits -------------------------------------

def test_a_public_collection_counts_the_collection_not_the_page(tmp_path):
    """The fake's `count()` is `len(rows) + 7`, so a `total` of `len(rows)` cannot pass."""
    src = _project(tmp_path, [{"method": "GET", "path": "/api/videos"}])
    out, log, rows = _run(src, "/api/videos", rows_n=2)
    assert out["total"] == len(rows) + 7, (out, [l for l in log])
    assert len(out["items"]) == len(rows)


def test_the_page_is_still_limited(tmp_path):
    """The fix must not remove the page cap — only stop reporting it as the total."""
    src = _project(tmp_path, [{"method": "GET", "path": "/api/videos"}])
    _out, log, _rows = _run(src, "/api/videos")
    assert ("limit", 100) in log, log


def test_the_rows_line_is_byte_identical(tmp_path):
    """#1202os kept it so, and 24 test files assert that exact string."""
    src = _project(tmp_path, [{"method": "GET", "path": "/api/videos"}])
    line = [l.strip() for l in src.splitlines()
            if l.strip().startswith("rows = db.query(Video)")]
    assert line == ["rows = db.query(Video).limit(100).all()"], line


# --- no branch left behind -----------------------------------------------------------------------

def test_no_emitted_handler_still_reports_the_page_as_the_total():
    """The generator is the subject: every `total` it writes must come from a count."""
    import inspect

    from multi_agent.runtime import route_projector
    src = inspect.getsource(route_projector)
    assert '"total": len(rows)' not in src
    assert "\\\"total\\\": len(rows)" not in src


def test_every_total_the_projector_emits_is_a_count():
    """Counted over the generator's own emissions, so a sixth branch cannot appear quietly.

    Line-based rather than a paired `items`/`total` regex: several of these returns are
    f-strings split across two source lines, and the paired version silently saw only two of
    them — a predicate that under-counts is how a new `len(rows)` would slip back in.
    """
    import inspect

    from multi_agent.runtime import route_projector
    src = inspect.getsource(route_projector)
    counted = len(re.findall(r'count\(\)\}\}', src)) + len(re.findall(r'_total1203j1\}\}', src))
    assert counted >= 7, "only %d total-emitting sites use a count" % counted
    # and the shape this ticket removed must not come back, in any spelling
    assert not re.search(r'"total\\?": ?len\(rows\)', src), "a page size is being reported again"


def _total_emissions():
    """Each emitted `total`, with the text that produces it (the f-strings are split)."""
    import inspect

    from multi_agent.runtime import route_projector
    src = inspect.getsource(route_projector)
    out = []
    lines = src.splitlines()
    for k, line in enumerate(lines):
        if '"total' not in line and '\\"total' not in line:
            continue
        out.append(" ".join(lines[k:k + 3]))
    return out


def test_every_filtered_branch_counts_THROUGH_its_own_filter():
    """★ The failure this fix could have shipped instead of the one it removes.

    A count that drops the filter answers with the whole table — right shape, wrong number,
    and on the owner-scoped list it is a disclosure: `total` would tell a caller how many
    rows OTHER principals hold. A first version of this test counted a marker over the whole
    module, and `_fw_owner_val` appears nine times there, so dropping it from the count still
    left the marker above the threshold — the mutation survived. The filter has to be found
    in the SAME emission as the total it belongs to.
    """
    emissions = _total_emissions()
    assert emissions, "no `total` emitted at all — the projector changed shape"
    wanted = {
        "scope_fk": 'getattr({cls}, "{scope_fk}") == parent.id',
        "owner-scoped": "_fw_owner_val({cls}, ",
        "ranked": "isnot(None)",
    }
    for label, marker in wanted.items():
        hits = [e for e in emissions if marker in e and "count()" in e]
        assert hits, "the %s branch emits a total that does not carry %r" % (label, marker)


def test_no_counted_total_is_filterless_where_its_page_is_filtered():
    """The same rule from the other side: an emission that counts must not be bare when the
    branch it sits in filters. Bare counts are legitimate only for unfiltered collections."""
    emissions = _total_emissions()
    bare = [e for e in emissions
            if "count()" in e and "filter(" not in e and "join(" not in e]
    # the plain public list and the plain nested list are genuinely unfiltered
    assert len(bare) <= 3, [b[:100] for b in bare]


# --- provenance -------------------------------------------------------------------------------

def test_the_rule_it_is_fixed_under_is_recorded():
    import inspect

    from multi_agent.runtime import route_projector
    flat = " ".join(inspect.getsource(route_projector).replace("#", " ").split())
    assert "WHOLE COLLECTION" in flat
    assert "#1202os" in inspect.getsource(route_projector)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
