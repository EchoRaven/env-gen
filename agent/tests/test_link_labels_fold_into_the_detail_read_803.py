r"""#803 (item 109): fold a normalised many-to-many into the projected detail read.

The projected detail page renders a chip row from `cur.genres`. In **120 of 122** corpus runs the
payload carries no genre field at all — genres are a `title_genres` join and the handler is
`SELECT <cols> FROM titles WHERE id = :id`. #782 fixed the frontend accessor, and no accessor can
invent a field the response does not carry, so the block still rendered nothing. This is the
backend half.

It is not a genres feature: any normalised many-to-many a reference shows as chips — tags,
categories, skills, ingredients, topics — was invisible to every projected detail page for the
same reason.

**The safety rule is the design.** A pure link table (two FKs, nothing else) is *structurally
indistinguishable* from a per-user relation. The corpus holds 242, split exactly:

    139  title_genres (title_id, genre_id)     -> a label relation; folding it in is correct
    103  my_list      (profile_id, title_id)   -> folding it in attaches the NAMES OF THE
                                                  PROFILES WHO SAVED A TITLE to a public detail
                                                  response: a read-path owner-scoping leak, the
                                                  #569 class

Membership is therefore decided by **what the FK points at**, never by its name — #784 is why:
a name-based guard there missed `recipient_id` precisely because it was not on the list.

**Why this was parked, and what unparked it.** Item 112 concluded the only remaining risk was
"whether the emitted SQL is correct across schemas the corpus does not contain", and that emitting
bad SQL would 500 the detail read — far worse than a missing chip row. That is not a risk that
needs a generation run to retire: these tests **execute the emitted SQL against a real database**
(SQLite via SQLAlchemy), the same move that verified #782's accessors under node instead of
grepping for them.
"""
import pytest

sa = pytest.importorskip("sqlalchemy")

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp


# --- the models the projector would have parsed --------------------------------------------------

_NETFLIX = {
    "titles": {"cls": "Title", "cols": ["id", "name", "release_year"], "fks": {}},
    "genres": {"cls": "Genre", "cols": ["id", "name"], "fks": {}},
    "title_genres": {"cls": "TitleGenre", "cols": ["id", "title_id", "genre_id"],
                     "fks": {"title_id": "titles", "genre_id": "genres"}},
    "profiles": {"cls": "Profile", "cols": ["id", "name"], "fks": {}},
    "my_list": {"cls": "MyList", "cols": ["id", "profile_id", "title_id"],
                "fks": {"profile_id": "profiles", "title_id": "titles"}},
}


def test_the_label_relation_is_found():
    rels = rp._link_label_reads_803("titles", _NETFLIX)
    assert [r["field"] for r in rels] == ["genres"]
    r = rels[0]
    assert (r["link"], r["self_fk"], r["other_fk"], r["label"]) == \
        ("title_genres", "title_id", "genre_id", "name")


def test_the_per_user_relation_is_refused():
    """★ The whole point. `my_list` passes every structural test — two FKs, nothing else, and
    `profiles` even has a `name` column so the display-column check passes too."""
    assert not any(r["link"] == "my_list" for r in rp._link_label_reads_803("titles", _NETFLIX))


@pytest.mark.parametrize("actor", ["users", "profiles", "accounts", "members", "customers",
                                   "tenants", "user", "account"])
def test_every_actor_table_is_refused(actor):
    models = dict(_NETFLIX)
    models["shares"] = {"cls": "Share", "cols": ["id", "title_id", "who_id"],
                        "fks": {"title_id": "titles", "who_id": actor}}
    models[actor] = {"cls": "A", "cols": ["id", "name"], "fks": {}}
    assert not any(r["link"] == "shares" for r in rp._link_label_reads_803("titles", models))


def test_a_name_based_guard_would_have_missed_this_one():
    """#784's lesson, encoded: `curator_id` is on no owner-name list anywhere in the framework,
    and it points straight at `users`."""
    models = dict(_NETFLIX)
    models["curations"] = {"cls": "Curation", "cols": ["id", "title_id", "curator_id"],
                           "fks": {"title_id": "titles", "curator_id": "users"}}
    models["users"] = {"cls": "User", "cols": ["id", "name"], "fks": {}}
    from env_generator.llm_generator.multi_agent.runtime.route_projector import _OWNER_FK_NAMES
    assert "curator_id" not in _OWNER_FK_NAMES, "non-vacuity: a name list really would miss it"
    assert not any(r["link"] == "curations" for r in rp._link_label_reads_803("titles", models))


def test_a_table_with_payload_columns_is_not_a_link_table():
    """`ratings (user_id, title_id, value)` carries data of its own — it is an entity, not a join."""
    models = dict(_NETFLIX)
    models["episodes"] = {"cls": "Episode", "cols": ["id", "title_id", "genre_id", "runtime"],
                          "fks": {"title_id": "titles", "genre_id": "genres"}}
    assert not any(r["link"] == "episodes" for r in rp._link_label_reads_803("titles", models))


def test_a_child_with_no_display_column_is_skipped():
    """A chip row of bare ids is noise, not a feature."""
    models = dict(_NETFLIX)
    models["genres"] = {"cls": "Genre", "cols": ["id", "created_at"], "fks": {}}
    assert rp._link_label_reads_803("titles", models) == []


def test_housekeeping_columns_do_not_disqualify_a_link_table():
    models = dict(_NETFLIX)
    models["title_genres"] = {"cls": "TitleGenre",
                              "cols": ["id", "title_id", "genre_id", "created_at", "updated_at"],
                              "fks": {"title_id": "titles", "genre_id": "genres"}}
    assert [r["field"] for r in rp._link_label_reads_803("titles", models)] == ["genres"]


def test_no_models_is_not_a_crash():
    for bad in ({}, None, {"x": None}, {"x": {"cols": None, "fks": None}}):
        assert rp._link_label_reads_803("titles", bad) == []


# --- the emitted SQL, executed against a real database --------------------------------------------

def _db():
    eng = sa.create_engine("sqlite+pysqlite:///:memory:")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE titles (id INTEGER PRIMARY KEY, name TEXT)"))
        c.execute(sa.text("CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT)"))
        c.execute(sa.text("CREATE TABLE title_genres "
                          "(id INTEGER PRIMARY KEY, title_id INTEGER, genre_id INTEGER)"))
        c.execute(sa.text("INSERT INTO titles VALUES (1,'Disclosure Day'),(2,'Other')"))
        c.execute(sa.text("INSERT INTO genres VALUES (10,'Thriller'),(11,'Drama'),(12,'Kids')"))
        c.execute(sa.text("INSERT INTO title_genres VALUES (1,1,11),(2,1,10),(3,2,12)"))
    return eng


def test_the_emitted_sql_runs_and_returns_the_right_labels():
    """This is the assertion item 112 said needed a generation run. It does not."""
    rel = rp._link_label_reads_803("titles", _NETFLIX)[0]
    sql = rp._link_label_sql_803(rel)
    with _db().begin() as c:
        rows = c.execute(sa.text(sql), {"_lid": 1}).fetchall()
    assert [r[0] for r in rows] == ["Drama", "Thriller"], "sorted by label, scoped to title 1"


def test_it_does_not_leak_another_rows_labels():
    rel = rp._link_label_reads_803("titles", _NETFLIX)[0]
    with _db().begin() as c:
        rows = c.execute(sa.text(rp._link_label_sql_803(rel)), {"_lid": 2}).fetchall()
    assert [r[0] for r in rows] == ["Kids"]


def test_an_unrelated_id_returns_empty_not_an_error():
    rel = rp._link_label_reads_803("titles", _NETFLIX)[0]
    with _db().begin() as c:
        assert c.execute(sa.text(rp._link_label_sql_803(rel)), {"_lid": 999}).fetchall() == []


def test_the_id_is_bound_not_interpolated():
    """The only runtime value in this SQL must be a bind parameter."""
    sql = rp._link_label_sql_803(rp._link_label_reads_803("titles", _NETFLIX)[0])
    assert ":_lid" in sql
    assert "%" not in sql and "format(" not in sql


# --- the generated handler ------------------------------------------------------------------------

def _handler(models):
    return rp._generate_handler("GET", "/api/titles/{id}", False, models, 0)


def test_the_handler_folds_the_labels_in():
    src = _handler(_NETFLIX)
    assert "_labels" in src
    assert "title_genres" in src
    assert '**_labels' in src


def test_a_label_read_failure_cannot_500_the_page():
    """A chip row is worth strictly less than the page it sits on."""
    src = _handler(_NETFLIX)
    i = src.index("_labels")
    assert "except Exception:" in src[i:]
    assert '_labels["genres"] = []' in src


def test_no_relation_leaves_the_handler_byte_identical():
    """Non-regression for every app without a link table — the overwhelming majority of routes."""
    plain = {"titles": _NETFLIX["titles"]}
    src = _handler(plain)
    assert "_labels" not in src
    assert 'return {"item":' in src


def test_the_per_user_relation_is_absent_from_the_generated_source():
    """End-to-end version of the safety rule: not merely unselected, but not emitted."""
    src = _handler(_NETFLIX)
    assert "my_list" not in src
    assert "profile" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
