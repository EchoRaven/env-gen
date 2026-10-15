r"""#1203mf: the chip row's query called `text(`, which the projected module never binds.

`#803` projects a label read for a link-table shape (netflix `title_genres` → `genres`;
equally a shop's `product_tags`): on the detail page, fetch the related names and merge them
into the item. The emitted SQL call used a BARE `text(` — and nothing in the projected module
binds `text`. The header imports it ALIASED, and the alias has drifted: `_text` in the
netflix-r11 era, `_sa_text` in the current skeleton. So the read raised NameError, the
`except Exception` two lines down turned that into `[]`, and the chip row was silently empty.

MEASURED: all 17 delivered `main.py` carrying a `_labels` block call the bare name, and in
netflix-local-r11 scripts/undefined_names.py confirms `text` is bound nowhere in the file
(only `_text`, inside two other functions). Dormant in the modern era — 0 of the 39 modern
runs have a `_labels` block, because no modern model graph has the link-table shape #803
detects — so this is a latent path made correct before it next fires.

The import is emitted HERE rather than taken from the header, so the projection does not
depend on another file's choice of alias. That coupling is what let the two names drift.
"""
from __future__ import annotations

import ast
import re
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _generate_handler, _link_label_reads_803)


def _meta(cls, cols, fks):
    return {"cls": cls, "cols": cols, "fks": fks}


MODELS = {
    "titles": _meta("Title", ["id", "name"], {}),
    "genres": _meta("Genre", ["id", "name"], {}),
    "title_genres": _meta("TitleGenre", ["id", "title_id", "genre_id"],
                          {"title_id": "titles", "genre_id": "genres"}),
}


def _emit():
    out = _generate_handler("GET", "/api/titles/{id}", False, MODELS, 0)
    return out if isinstance(out, str) else "\n".join(map(str, out))


def test_the_link_shape_still_projects_a_label_read():
    """Precondition: without this the rest of the file proves nothing."""
    assert _link_label_reads_803("titles", MODELS), "#803 no longer detects the link table"
    assert "_labels = {}" in _emit()


def test_no_bare_text_call_is_emitted():
    src = _emit()
    assert not re.search(r"db\.execute\(text\(", src), \
        "the label read calls a bare `text(` again; nothing in the projected module binds it"


def test_the_name_it_calls_is_bound_in_the_same_function():
    """★ The property: the SQL helper must be bound where it is used, not by the header."""
    src = _emit()
    fn = [n for n in ast.walk(ast.parse(textwrap.dedent(src)))
          if isinstance(n, ast.FunctionDef)][-1]
    called = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and isinstance(getattr(n, "args", [None])[0] if n.args else None, ast.Constant)
                and isinstance(n.args[0].value, str)
                and n.args[0].value.upper().startswith("SELECT")):
            called.add(n.func.id)
    assert called, "no SQL-text call was found in the projected handler"
    imported = {(a.asname or a.name) for x in ast.walk(fn)
                if isinstance(x, ast.ImportFrom) for a in x.names}
    assert called <= imported, (
        "the handler calls %s but imports %s — it is relying on the header's alias"
        % (sorted(called), sorted(imported)))


def test_the_import_precedes_its_use():
    src = _emit()
    imp = src.find("from sqlalchemy import text as ")
    use = src.find("SELECT")
    assert 0 <= imp < use, "the import lands after the query that needs it"


def test_the_read_still_degrades_rather_than_500ing():
    """#803's own rule: a label read must never turn a working detail page into a 500."""
    src = _emit()
    i = src.index("_labels = {}")
    block = src[i:]
    assert "except Exception:" in block and '_labels["genres"] = []' in block


@pytest.mark.parametrize("auth", [True, False])
def test_it_holds_for_both_auth_shapes(auth):
    out = _generate_handler("GET", "/api/titles/{id}", auth, MODELS, 0)
    src = out if isinstance(out, str) else "\n".join(map(str, out))
    assert not re.search(r"db\.execute\(text\(", src)
    assert "from sqlalchemy import text as " in src
