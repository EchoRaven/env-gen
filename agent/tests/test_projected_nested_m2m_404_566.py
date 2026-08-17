"""#566 (netflix r112, live): a projected nested COLLECTION under /<parent>/{id}/<child>
whose child has NO direct FK to the parent (MANY-TO-MANY via an association table) must
still 404 a missing parent and scope the list THROUGH the association table — NOT fall
through to the plain-collection branch that returns EVERY child row, 200.

r112 wedged exactly here: GET /api/genres/{genre_id}/titles. `titles` has no `genre_id`
column (the link lives in `title_genres`), so `_scope_fk` returned None, the nested-
collection branch was skipped, and the plain-collection branch served `db.query(Title)
.limit(100).all()` → 200 for a non-existent genre (should be 404) AND unscoped. The
verifier's business_chain kept failing `genre 404`, the deterministic delivery gate never
cut a release, and the run thrashed (dispatch queue full 1212x, 4x failed 6/6 validation
cycles) for ~50 min with no convergence.

The fix resolves the parent (404 if missing, incl. the #288/#77 owner filter) and, when an
association table links parent<->child, scopes the child list through it. Generalizes to any
m2m nested collection in any app — keyed purely off the contract FK graph, no product
literals. The direct-FK nested collection path (episodes under a title) is unchanged.
"""
import ast

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _assoc_table,
    _generate_handler,
)

# Netflix-shaped m2m: titles<->genres linked by title_genres; episodes has a DIRECT title FK.
_MODELS = {
    "genres":       {"cls": "Genre",      "cols": ["id", "name"], "fks": {}},
    "titles":       {"cls": "Title",      "cols": ["id", "name", "year"], "fks": {}},
    "title_genres": {"cls": "TitleGenre", "cols": ["id", "title_id", "genre_id"],
                     "fks": {"title_id": "titles", "genre_id": "genres"}},
    "episodes":     {"cls": "Episode",    "cols": ["id", "title_id", "name"],
                     "fks": {"title_id": "titles"}},
    "users":        {"cls": "User",       "cols": ["id", "email"], "fks": {}},
}


def _m2m():
    # /api/genres/{genre_id}/titles — m2m, child (titles) has no genre FK
    return _generate_handler("GET", "/api/genres/{genre_id}/titles", True, _MODELS, 8)


def _direct():
    # /api/titles/{title_id}/episodes — direct FK (episodes.title_id), scope_fk path
    return _generate_handler("GET", "/api/titles/{title_id}/episodes", True, _MODELS, 9)


# --- the m2m fix -----------------------------------------------------------------

def test_m2m_nested_collection_has_parent_404_guard():
    src = _m2m()
    assert "if parent is None:" in src, src
    assert 'raise HTTPException(status_code=404, detail="not found")' in src, src


def test_m2m_resolves_parent_by_its_field():
    src = _m2m()
    assert 'db.query(Genre).filter(getattr(Genre, "id") == genre_id)' in src, src


def test_m2m_scopes_list_through_association_table():
    src = _m2m()
    # joins the child to the association table and filters by the parent link col
    assert ".join(TitleGenre," in src, src
    assert 'getattr(TitleGenre, "title_id") == getattr(Title, "id")' in src, src
    assert 'getattr(TitleGenre, "genre_id") == parent.id' in src, src
    # must NOT fall through to the unscoped plain-collection list
    assert "rows = db.query(Title).limit(100).all()" not in src, src


def test_m2m_handler_is_valid_python():
    ast.parse(_m2m())


# --- direct-FK nested collection unchanged (byte-identical scope_fk path) ---------

def test_direct_fk_nested_collection_unchanged():
    src = _direct()
    # scope_fk branch: direct filter on the child's own FK, NO association join
    assert 'getattr(Episode, "title_id") == parent.id' in src, src
    assert ".join(" not in src, src
    assert "if parent is None:" in src, src


# --- fallback: parent recognized, no scope_fk, no association table ----------------

def test_no_assoc_no_scope_fk_still_404s_missing_parent():
    # widgets under genres, but nothing links them (no genre FK, no assoc table)
    models = {
        "genres":  {"cls": "Genre",  "cols": ["id", "name"], "fks": {}},
        "widgets": {"cls": "Widget", "cols": ["id", "label"], "fks": {}},
    }
    src = _generate_handler("GET", "/api/genres/{genre_id}/widgets", True, models, 3)
    assert "if parent is None:" in src, src
    assert 'raise HTTPException(status_code=404, detail="not found")' in src, src
    assert ".join(" not in src, src  # nothing to join through → best-effort list
    ast.parse(src)


# --- negatives --------------------------------------------------------------------

def test_plain_collection_unaffected():
    src = _generate_handler("GET", "/api/titles", True, _MODELS, 1)
    assert "parent" not in src, src
    assert ".join(" not in src, src


# --- the helper itself ------------------------------------------------------------

def test_assoc_table_finds_link():
    assert _assoc_table(_MODELS, "genres", "titles") == ("TitleGenre", "genre_id", "title_id")
    assert _assoc_table(_MODELS, "titles", "genres") == ("TitleGenre", "title_id", "genre_id")


def test_assoc_table_none_when_unlinked():
    assert _assoc_table(_MODELS, "genres", "users") is None
    assert _assoc_table(_MODELS, None, "titles") is None
    assert _assoc_table(_MODELS, "genres", None) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
