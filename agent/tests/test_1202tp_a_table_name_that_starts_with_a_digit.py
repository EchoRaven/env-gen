r"""#1202tp: a table whose name starts with a digit emits a models.py that cannot be imported.

`_class_name` builds the ORM class name by PascalCasing the table name. It never checks that
the result is a valid Python identifier, so a table named `2fa_tokens` -- an ordinary name for
any app with two-factor auth -- emits

    class 2faToken(Base):

and `models.py` is a SyntaxError: *invalid decimal literal*. Nothing imports, so the backend
crashes on every boot, which is the same total failure `safe_column_name` in this very file
has guarded against for COLUMNS since #158 (gmrun6's backend_health wedge), and `_pascal_case`
for frontend COMPONENTS since #1202th. Table class names were the one identifier of the three
left unguarded.

MEASURED: 172 run directories, 112 distinct table names, NONE starting with a digit -- so this
is hardening, not a live break, exactly as #1202th recorded for its own case. Three real names
carry a digit (`top10`, `titles_top10`, `design_analyst_1`) and none leads with one.

The guard goes in the two places that MINT a class name -- `_class_name` and #1096's
alternate-spelling branch -- rather than at the emission site, because #1096's whole lesson was
that two emitters computing the name independently is how the last collision escaped. Both
`render_models` and `_models_meta` read the one shared map, so they cannot disagree.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _class_name, _class_names_1096, _models_meta, render_models,
)

COLS = {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                    {"name": "user_id", "type": "integer"}]}


def test_the_digit_leading_table_still_parses():
    """The bug: models.py was a SyntaxError, so the backend never booted."""
    src = render_models({"2fa_tokens": COLS})
    ast.parse(src)          # was: SyntaxError: invalid decimal literal
    assert "class Model2faToken(Base):" in src, [
        l for l in src.split("\n") if l.startswith("class ")]


def test_every_digit_leading_name_is_a_valid_identifier():
    for t in ("2fa_tokens", "2019_stats", "3d_models", "404_pages", "2", "1st_place"):
        cls = _class_name(t)
        assert cls.isidentifier(), (t, cls)
        assert _class_names_1096({t})[t].isidentifier(), t
        ast.parse(render_models({t: COLS}))


def test_both_emitters_agree_on_the_name():
    """#1096's lesson: render_models and _models_meta must never compute it separately."""
    tables = {"2fa_tokens": COLS, "messages": COLS, "message": COLS}
    src = render_models(tables)
    emitted = {l.split("(")[0].split()[1] for l in src.split("\n") if l.startswith("class ")}
    for t, m in _models_meta(tables).items():
        if t in ("tenants", "users") and t not in tables:
            continue
        assert m["cls"] in emitted, (t, m["cls"], sorted(emitted))


def test_collisions_are_still_resolved():
    """The guard must not weaken #1096 -- two tables may never share a class."""
    m = _class_names_1096({"message", "messages", "2fa_token", "2fa_tokens"})
    assert len(set(m.values())) == len(m), m
    assert all(v.isidentifier() for v in m.values()), m


def test_it_is_idempotent():
    """Applying the guard to its own output changes nothing."""
    for t in ("2fa_tokens", "posts", "model2fa_token"):
        assert _class_name(_class_name(t)) == _class_name(t), t


def test_no_real_table_name_changes():
    """172 run dirs: the guard is a no-op on every name the corpus actually contains."""
    seen = set()
    for f in glob.glob(str(ROOT.parent / "generated" / "*" / "shared" / "hubs"
                           / "registryhub_tables.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        v = d.get("value", d) if isinstance(d, dict) else d
        if isinstance(v, dict):
            seen.update(str(t) for t in v)
    assert len(seen) > 100, f"corpus not found ({len(seen)} names) -- this test proved nothing"
    changed = [t for t in seen if not _class_name(t).isidentifier()
               or _class_name(t).startswith("Model") and not t.lower().startswith("model")]
    assert changed == [], changed
