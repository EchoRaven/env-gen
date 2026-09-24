r"""#1202tj: the temporal-synonym line builds an ATTRIBUTE, and only its argument was quoted.

`_temporal_synonyms` emits, beside each datetime column, an alias so `created_at` and
`created_time` both work. The line is

    <sib> = synonym("<nm>")

and `<sib>` is a Python ATTRIBUTE. It was interpolated raw, two lines away from the `Column`
call that has sanitised its own attribute since FIX #158:

    a_b_at   = Column('a-b_at', DateTime)      # safe — attribute sanitised, DB name quoted
    a-b_time = synonym("a-b_at")               # SyntaxError

so `import models` fails and the backend never boots — exactly the gmrun6 wedge
`safe_column_name` was written for, reached by the one line that did not call it.

IT ALSO FAILS SILENTLY FURTHER OUT. `route_projector._orm_models` parses `models.py` and
returns `{}` on SyntaxError, so the projector then projects NOTHING and says nothing about
why. That is how this was found: an unrelated fixture of mine used a `a-b_at` column and
`_orm_models` came back empty, which a non-vacuity assertion caught.

A SECOND, SUBTLER BUG in the same line: `synonym()` names a MAPPED ATTRIBUTE, not a DB column.
Pointing it at the raw name (`synonym("a-b_at")`) is wrong even where it parses, because the
mapped attribute is `a_b_at`; SQLAlchemy raises at mapper configuration. Both sides now go
through `safe_column_name`, which is idempotent, so ordinary columns are untouched.

HOW LIKELY: the corpus holds 3 non-identifier names in 2,009, all TABLE names — no hyphenated
column has appeared yet. Hardening, like its siblings, and the same reasoning: nothing upstream
constrains the name, and the cost is a backend that cannot import plus a projector that
silently does nothing.

BEHAVIOUR UNCHANGED, checked: all 39 real corpus schemas render BYTE-IDENTICALLY before and
after.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import render_models, safe_column_name  # noqa: E402
from multi_agent.runtime.route_projector import _orm_models  # noqa: E402

_ID = {"name": "id", "type": "integer", "primary_key": True}


def _models(col):
    return render_models({"videos": {"columns": [_ID, col]}})


@pytest.mark.parametrize("name", [
    "created_at", "updated_time", "posted_at",          # ordinary
    "a-b_at", "a-b_time", "2019_at", "from_at", "class_time",  # the ones that broke
])
def test_models_py_parses(name):
    ast.parse(_models({"name": name, "type": "datetime"}))


@pytest.mark.parametrize("name", ["a-b_at", "2019_at", "from_at"])
def test_the_synonym_attribute_is_an_identifier(name):
    src = _models({"name": name, "type": "datetime"})
    line = [l.strip() for l in src.split("\n") if "synonym(" in l and "import" not in l][-1]
    attr = line.split("=")[0].strip()
    assert attr.isidentifier(), line


@pytest.mark.parametrize("name", ["a-b_at", "2019_at"])
def test_the_synonym_points_at_the_mapped_attribute_not_the_db_column(name):
    """`synonym()` names a mapped attribute. Pointing it at the raw DB column name raises at
    mapper configuration even when the line parses."""
    src = _models({"name": name, "type": "datetime"})
    tree = ast.parse(src)
    targets = {n.targets[0].id for n in ast.walk(tree)
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None)}
    for call in ast.walk(tree):
        if (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "synonym"
                and call.args and isinstance(call.args[0], ast.Constant)):
            assert call.args[0].value in targets, (
                f"synonym({call.args[0].value!r}) names no mapped attribute; "
                f"attributes are {sorted(targets)}")


def test_the_projector_can_still_read_the_models():
    """The silent half: `_orm_models` returns {} on SyntaxError, so a broken models.py makes
    the projector do nothing quietly."""
    d = Path(tempfile.mkdtemp())
    (d / "models.py").write_text(_models({"name": "a-b_at", "type": "datetime"}),
                                 encoding="utf-8")
    parsed = _orm_models(d)
    assert "videos" in parsed, "the projector reads nothing from this models.py"
    assert all(str(c).isidentifier() for c in parsed["videos"]["cols"])


def test_ordinary_columns_are_untouched():
    """Non-vacuity, and what the corpus check confirmed at scale."""
    src = _models({"name": "created_at", "type": "datetime"})
    assert 'created_time = synonym("created_at")' in src


def test_the_sanitiser_is_idempotent():
    """`safe_column_name` documents this; the synonym line now calls it on both sides, and a
    second application must change nothing."""
    for n in ("created_at", "a-b_at", "2019_at", "from"):
        once = safe_column_name(n)
        assert safe_column_name(once) == once, n
