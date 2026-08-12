r"""#590: a re-registration must never DESTROY a table's known columns.

This is the ROOT CAUSE behind #568 (which only blocked the consequence). r133's event stream,
`table_registered` for `my_list`:

    03:17:05  cols=4  by=orchestrator     registered at kickoff, with columns
    04:37:21  cols=3  by=orchestrator
    04:57:03  cols=0  by=BACKEND          <- the lane re-registered without columns
    04:57:29  cols=0  by=orchestrator     <- the status flip propagated the empty schema

26s later the skeleton regenerated and baked in `class MyList(Base): id` — the PK-only model
behind #568's live cross-user leak. Its sibling `ratings` was never written again after 04:38
and kept all 4 columns; the only difference between them is who wrote LAST.

FIX #90 made an empty-columns registration legal for a table nobody has described yet. It must
not also license destroying a schema already on record: a table with zero columns cannot exist
(database_scaffold synthesises an `id` PK rather than raising), so empty carries no information
and has to behave exactly like `schema=None`.

Scanned over 56 runs: 2 wipes (r133 `my_list` 3->0, r119 `profiles` 5->0, both by the backend
lane). r119 survived only because a later registration restored the columns 63s on. Column
REDUCTIONS (45 seen) are deliberately left alone — real schema revisions — and the 23 spine
`users` 6->4 shrinks provably never reach the model (verified in r103/r113/r115).
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


_COLS = [{"name": "id", "type": "int", "primary_key": True},
         {"name": "profile_id", "type": "int", "references": "profiles.id"},
         {"name": "title_id", "type": "int", "references": "titles.id"}]


@pytest.fixture()
def hub(tmp_path):
    return RegistryHub(str(tmp_path))


def _cols(hub, name):
    return [c["name"] for c in ((hub.get_table(name) or {}).get("schema") or {}).get("columns") or []]


def _register(hub, **kw):
    kw.setdefault("agent", "backend")
    kw.setdefault("provider", "backend")
    return hub.register_table(**kw)


# --- the r133 sequence, replayed ------------------------------------------------------------

def test_the_r133_wipe_no_longer_lands(hub):
    _register(hub, name="my_list", schema={"columns": _COLS}, agent="orchestrator")
    assert _cols(hub, "my_list") == ["id", "profile_id", "title_id"]
    # 04:57:03 — the lane re-registers with no columns
    _register(hub, name="my_list", schema={"columns": []}, status="implemented")
    assert _cols(hub, "my_list") == ["id", "profile_id", "title_id"]


def test_an_empty_dict_schema_is_also_a_wipe_attempt(hub):
    """`{}` is what kickoff builds from a table entry carrying only a name."""
    _register(hub, name="my_list", schema={"columns": _COLS})
    _register(hub, name="my_list", schema={})
    assert _cols(hub, "my_list") == ["id", "profile_id", "title_id"]


def test_the_status_flip_that_propagated_it_is_harmless_too(hub):
    """04:57:29 — scaffolder marks the table implemented with `schema=None`."""
    _register(hub, name="my_list", schema={"columns": _COLS})
    hub.register_table("my_list", agent="orchestrator", status="implemented")
    assert _cols(hub, "my_list") == ["id", "profile_id", "title_id"]
    assert (hub.get_table("my_list") or {}).get("status") == "implemented"


def test_the_attempt_is_recorded_for_offline_diagnosis(hub):
    _register(hub, name="my_list", schema={"columns": _COLS})
    _register(hub, name="my_list", schema={"columns": []}, agent="backend")
    meta = (hub.get_table("my_list") or {}).get("metadata") or {}
    assert meta.get("schema_wipe_prevented_by") == "backend"


def test_a_clean_registration_leaves_no_breadcrumb(hub):
    _register(hub, name="ratings", schema={"columns": _COLS})
    assert "schema_wipe_prevented_by" not in ((hub.get_table("ratings") or {}).get("metadata") or {})


# --- what must still work ---------------------------------------------------------------------

def test_fix_90_still_holds_for_a_table_nobody_has_described(hub):
    """A name-first registration is legal — there is nothing to protect yet."""
    _register(hub, name="toggle", schema={"columns": []}, status="implemented")
    assert hub.get_table("toggle") is not None
    assert _cols(hub, "toggle") == []


def test_a_real_schema_revision_is_not_blocked(hub):
    """Adding, renaming and DROPPING columns all still land — only zero is refused."""
    _register(hub, name="profiles", schema={"columns": _COLS})
    _register(hub, name="profiles", schema={"columns": _COLS[:2]})
    assert _cols(hub, "profiles") == ["id", "profile_id"]          # a 3->2 shrink is honoured
    _register(hub, name="profiles", schema={"columns": _COLS + [{"name": "avatar", "type": "text"}]})
    assert _cols(hub, "profiles") == ["id", "profile_id", "title_id", "avatar"]


def test_the_flat_map_shape_still_normalizes(hub):
    """The other accepted shape must not be mistaken for empty."""
    _register(hub, name="genres", schema={"id": "int", "name": "text"})
    assert _cols(hub, "genres") == ["id", "name"]


def test_a_flat_map_cannot_be_wiped_either(hub):
    _register(hub, name="genres", schema={"id": "int", "name": "text"})
    _register(hub, name="genres", schema={})
    assert _cols(hub, "genres") == ["id", "name"]


def test_the_guard_is_documented_where_it_lives():
    import inspect
    src = inspect.getsource(RegistryHub.register_table)
    assert "#590" in src
    assert "FIX #90" in src            # the rule it narrows, kept adjacent


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
