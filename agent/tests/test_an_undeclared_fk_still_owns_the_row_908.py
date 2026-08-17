r"""#908: r153 ships GET /api/my-list returning every account's rows.

Found by auditing the delivered app after a green gate — the rule #569 left behind. r153 is the
arc's best run (multi-milestone validated, 2 tags, 146/146 business chains) and its backend serves:

    @app.get("/api/my-list")
    def _projected_get_api_my_list_7(db=Depends(get_db), user=Depends(get_current_user)):
        rows = db.query(MyList).limit(100).all()        # every profile's rows

    @app.post("/api/my-list", status_code=201)          # …beside a write that 403s a
                                                        #   profile_id the caller does not own

`GET /api/continue-watching` is the same shape in the same tree. The lane's OWN owner-scoped
handler — which checks `SELECT id FROM profiles WHERE id=:pid AND user_id=:uid` and 403s — was
DROPPED by `_custom_route_overrides_projected`, because #528 hands a registered resource's
collection GET to the projected handler on the premise that the projected read is owner-safe.

★ Two detectors exist to make that premise true and neither fires:

    _is_per_user_sub_entity_fk  (#566y)  profile_id -> profiles -> users
    _is_user_content_relation   (#598)   user_id + a content FK

both read `meta["fks"]`, which `_parse_models` fills from `Column(..., ForeignKey("users.id"))`.
r153's model is `profile_id = Column(Integer)` — no ForeignKey, no REFERENCES in the DDL, and
`metadata = {}` so no `owner_scoped_reads` flag either. Every gate was open at once.

★ The evidence standard was inconsistent between two functions ten lines apart. `_owner_fk` accepts
a column NAME as proof of ownership — that is the only reason `profile_id` counts as an owner at
all (`_OWNER_FK_NAMES`, N-P0-2) — while the function that decides what that column MEANS accepted
only a parsed FK. #908 resolves the parent by the same standard the owner was resolved by.

Era split of the corpus, because the raw count misleads: 162 projected reads ship unfiltered on a
table with a recognised owner column, but 157 predate the fix for their own shape. Still open were
r131 (#566y's own run), r141 (#598's), and r153 — the sub-entity shape with the FK undeclared.

Measured effect: exactly three (table, owner) pairs change verdict across all 143 parsed backends —
`my_list`, `ratings`, `continue_watching` in r153. Nothing else moves.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp


def _r153_models():
    """r153's real shapes: no ForeignKey anywhere on the business tables."""
    return {
        "users": {"cols": ["id", "email"], "fks": {}},
        "profiles": {"cols": ["id", "user_id", "name", "avatar", "is_kids"], "fks": {}},
        "titles": {"cols": ["id", "name", "year"], "fks": {}},
        "my_list": {"cols": ["id", "profile_id", "title_id"], "fks": {}},
        "continue_watching": {"cols": ["id", "profile_id", "title_id", "progress_seconds"],
                              "fks": {}},
        "title_genres": {"cols": ["id", "title_id", "genre_id"], "fks": {}},
        "posts": {"cols": ["id", "author_id", "body"], "fks": {}},
    }


def test_the_owner_column_is_recognised_at_all():
    """Non-vacuity and the premise: `_owner_fk` returns `profile_id` by NAME with no FK declared.
    Everything below is about the other end of that same edge being held to a stricter standard."""
    m = _r153_models()
    assert rp._owner_fk(m["my_list"]) == "profile_id"
    assert m["my_list"]["fks"] == {}, "the shape is: recognised owner, undeclared FK"


def test_an_undeclared_profile_fk_is_still_a_per_user_sub_entity():
    """The defect. Before #908 this was False and the projected read shipped unfiltered."""
    m = _r153_models()
    assert rp._is_per_user_sub_entity_fk(m["my_list"], "profile_id", m) is True
    assert rp._is_per_user_sub_entity_fk(m["continue_watching"], "profile_id", m) is True


def test_a_declared_fk_still_works():
    """Non-regression: #566y's original path is untouched — the explicit FK is consulted first."""
    m = _r153_models()
    m["my_list"]["fks"] = {"profile_id": "profiles"}
    m["profiles"]["fks"] = {"user_id": "users"}
    assert rp._is_per_user_sub_entity_fk(m["my_list"], "profile_id", m) is True


def test_a_direct_user_owner_is_not_a_sub_entity():
    """★ The line #566y deliberately drew: a row owned DIRECTLY by a user is ambiguous (a public
    feed is a list of rows each owned by someone), so it keeps the opt-in. Widening the parent
    lookup must not erase that."""
    m = _r153_models()
    assert rp._is_per_user_sub_entity_fk(m["posts"], "author_id", m) is False
    assert rp._is_per_user_sub_entity_fk(m["profiles"], "user_id", m) is False


def test_a_parent_with_no_user_principal_is_not_a_sub_entity():
    """`title_genres.title_id → titles` is a content edge, not an ownership one. (It is never
    reached in practice — `title_id` is not an owner name — but the second hop must still say no.)"""
    m = _r153_models()
    assert rp._is_per_user_sub_entity_fk(m["title_genres"], "title_id", m) is False


def test_an_owner_column_naming_no_table_resolves_to_nothing():
    """`created_by` names no entity; inference must return None rather than guess."""
    m = _r153_models()
    assert rp._fk_target_by_name_908("created_by", m) is None
    assert rp._fk_target_by_name_908("profile_id", m) == "profiles"
    assert rp._fk_target_by_name_908("id", m) is None
    assert rp._fk_target_by_name_908("", m) is None


def test_the_direct_owner_vocabulary_is_derived_not_recopied():
    """★ A second hand-written copy of an owner-name list is how one member goes missing from one
    of them — this session already found a set literal with six copies under five names."""
    assert "profile_id" in rp._OWNER_FK_NAMES
    assert "profile_id" not in rp._DIRECT_OWNER_FK_NAMES
    assert set(rp._DIRECT_OWNER_FK_NAMES) == set(rp._OWNER_FK_NAMES) - set(rp._NARROW_OWNER_FK_NAMES)


def test_the_verdict_reaches_the_emitted_filter():
    """★ The half that matters and the one this session keeps finding broken: a correct verdict
    nobody acts on. `read_scoped` must still be what gates the emitted `.filter(...)`."""
    import inspect
    src = inspect.getsource(rp._generate_handler)
    assert "owner_sub_entity = bool(owner_fk) and _is_per_user_sub_entity_fk(" in src
    assert "read_scoped = bool(owner_fk) and (bool(owner_scoped_reads) or owner_sub_entity" in src
    assert src.count("if read_scoped:") >= 3
    assert "_fw_owner_val" in src



def test_an_unknown_child_table_is_not_a_sub_entity():
    """★ Caught by #566y's own test, not by mine. The first #908 resolved the parent from
    `models` alone, without checking that the CHILD declares the column — so `{}` ("I know
    nothing about this table") came back True.

    Third time in one session that an empty input was read as a meaningful value: #902's blank
    route as the site root, #907's empty cache as an empty source tree, and now this — inside the
    fix for the other two. An empty container is not a fact about the world."""
    m = _r153_models()
    assert rp._is_per_user_sub_entity_fk({}, "profile_id", m) is False
    assert rp._is_per_user_sub_entity_fk({"cols": [], "fks": {}}, "profile_id", m) is False
    assert rp._is_per_user_sub_entity_fk({"cols": ["id", "title_id"]}, "profile_id", m) is False


def test_the_inference_requires_the_child_to_declare_the_column():
    """The positive half of the same rule, so the guard cannot be satisfied by weakening it."""
    m = _r153_models()
    assert rp._is_per_user_sub_entity_fk({"cols": ["id", "profile_id"], "fks": {}},
                                         "profile_id", m) is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
