r"""#1202tq: #1200's owner-scoping signal greps for a class name models.py never emitted.

`_lane_owner_scoped_read_tables_1200` decides whether the LANE's own read handler already
filters a table by its owner column, and scopes the framework's PROJECTED read with that
judgment. When it says no, the projection ships

    db.query(Profile).limit(100).all()

which is r23's leak -- every account's private rows on the screen the product opens with. The
signal is the only thing standing between a lane that got it right and a projection that
throws the filter away.

It looks for `query(<Class>)` in `custom_routes.py`, and builds `<Class>` with `_class_name`.
But `_class_name` is NOT what models.py emits: #1096 replaced it with `_class_names_1096`
precisely because two tables can collapse onto one name, and the plural of a colliding pair
gets its PLURAL spelling (`messages` -> `Messages`, not `Message`). The lane imports from
models.py, so the lane writes `query(Messages)`; the signal greps `query(Message)`; the paren
makes the two non-overlapping; the signal finds nothing and the guard is silently off.

#1096's own docstring states the rule this violates: "Both emitters must agree ... They called
`_class_name` independently and collapsed identically, which is exactly why nothing caught it
-- so the mapping is computed ONCE from the whole table set and shared." A census of every
`_class_name` reference in backend_skeleton.py finds line 331 is the one reader still
computing it alone; the two emitters (866, 1239) already read the shared map.

MEASURED, and stated as what it is: 170 run directories, 5 carry a colliding pair (r35 three,
r125 seven, r99/r103 one, netflix-r11 one), and NONE of the five has a custom_routes.py that
queries the colliding class -- so this is a LATENT guard failure, not an observed leak. The
cost of the fix is one line and it removes the third independent computation of a name #1096
said must be computed once.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _class_name, _class_names_1096, _lane_owner_scoped_read_tables_1200, render_models,
)

COLS = {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                    {"name": "user_id", "type": "integer"}]}
# `message` collides with `messages`; #1096 gives the plural the plural spelling.
COLLIDING = {"messages": COLS, "message": COLS}


def _backend(routes_src: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "custom_routes.py").write_text(routes_src, encoding="utf-8")
    return d


def _routes_for(cls: str) -> str:
    return (
        "@router.get('/api/messages')\n"
        "def list_messages(db=Depends(get_db), user=Depends(cur)):\n"
        f"    return db.query({cls}).filter({cls}.user_id == _user_id(user)).all()\n"
    )


def test_the_class_the_lane_must_import_is_the_plural_one():
    """The premise: models.py emits `Messages`, so the lane cannot write `Message`."""
    assert _class_names_1096(set(COLLIDING) | {"tenants", "users"})["messages"] == "Messages"
    assert _class_name("messages") == "Message"          # what the signal used to grep
    assert "class Messages(Base):" in render_models(COLLIDING)


def test_the_signal_fires_for_a_colliding_table():
    """The bug: it greps `query(Message)`, the lane wrote `query(Messages)`, guard off."""
    found = _lane_owner_scoped_read_tables_1200(_backend(_routes_for("Messages")), COLLIDING)
    assert "messages" in found, found


def test_the_non_colliding_case_is_unchanged():
    """171 of 172 run dirs have no collision -- they must behave exactly as before."""
    tables = {"profiles": COLS}
    found = _lane_owner_scoped_read_tables_1200(_backend(_routes_for("Profile")), tables)
    assert found == {"profiles"}, found


def test_a_write_handler_is_still_not_read_evidence():
    """#77's caution must survive the fix -- it once scoped a world-readable feed."""
    src = _routes_for("Messages").replace("@router.get(", "@router.post(")
    assert _lane_owner_scoped_read_tables_1200(_backend(src), COLLIDING) == set()


def test_an_unfiltered_read_is_still_not_evidence():
    src = ("@router.get('/api/messages')\n"
           "def list_messages(db=Depends(get_db)):\n"
           "    return db.query(Messages).limit(100).all()\n")
    assert _lane_owner_scoped_read_tables_1200(_backend(src), COLLIDING) == set()


def test_no_reader_computes_the_name_alone():
    """The rule, not the instance: a fourth reader added tomorrow must share the map too.

    `_class_name` has exactly two legitimate uses: `_class_names_1096` builds the shared map
    from it, and the two emitters use it as the `or` fallback of a lookup in that map. Any
    other call is a reader computing the name alone, which is what #1096 forbade and what
    this ticket found still happening.
    """
    import ast
    src = (LLM_DIR / "multi_agent" / "runtime" / "backend_skeleton.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                owner[id(n)] = fn.name
    fallback = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            for v in n.values[1:]:
                fallback.add(id(v))          # `<map>.get(t) or _class_name(t)`
    lone = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_class_name"):
            continue
        if owner.get(id(n)) == "_class_names_1096" or id(n) in fallback:
            continue
        lone.append(f"backend_skeleton.py:{n.lineno} in {owner.get(id(n))}")
    assert lone == [], (
        "#1096: the class name is computed ONCE and shared; these compute it alone and so "
        "disagree with models.py for any colliding table: %s" % lone)
