"""#1202kg: the lane said "public" four times and the ledger never heard it.

tiktok-r114, live, from the Backend Engineer Agent's own log:

    registryhub_register_table({'name': 'videos',
        'schema': {'columns': [...], 'owner_scoped_reads': False, 'visibility': 'public'},
        'status': 'implemented'})

called four times in eleven seconds, followed by a message to the orchestrator that diagnoses
it exactly:

    "RegistryHub retains legacy metadata.owner_scoped_reads=true for videos despite schema
     owner_scoped_reads=false"

`register_table` takes table-level policy as **metadata KWARGS. The tool advertises `schema`
as the table's shape, and a lane that reads it that way nests the policy inside it — where two
things go wrong at once:

  * the policy never reaches `metadata`, the only place #1202io, #633,
    `_apply_spec_visibility_1202hh` and `backend_audit` look;
  * in the flat-map dialect each policy key becomes a COLUMN.

The contrast is exact and is the counter-proof the corpus already ran: r111's lane passed
`visibility` as a kwarg, and #1202io fired on the very first registration —
`owner_scoped_reads_cleared_by_1202io: "backend"` is in the record. r114's first registration
carries `metadata: {}`. Same framework, same lane role, same table; only the dialect differed.

The cost in r114 is not hypothetical. With `visibility` absent, #1202io — which fires only when
the SAME record says `visibility: public` — could not see the contradiction; `videos` stayed
`owner_scoped_reads: true`; #633 re-imposed the owner filter on the FYP feed; and the run's
open blocker at the time of writing was

    deliverability_ui_flow_failed: fyp_feed_logged_out_page ...
    "unexpected unauthenticated GET /api/videos/feed 401"

i.e. the app's logged-out landing page.

The column half is in the ledger too: r110, r111 and r114 all carry a literal
`{"name": "owner_scoped_reads", "type": "false"}` column on `videos`, which becomes
`owner_scoped_reads = Column(String)` in models.py and is projected into every feed response.

WHAT IS VERIFIED: policy nested in `schema` now reaches `metadata` and reaches #1202io; it
never becomes a column in either dialect; an explicit kwarg still wins; and a schema with no
policy key is passed through unchanged.

WHAT IS NOT: that r114 would have delivered. #1202io still needs the materials to say `public`,
and a table the materials say nothing about is untouched — #1202gd's rule for staying strict.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator" / "multi_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                                          # noqa: E402

from runtime.database_scaffold import (                                # noqa: E402
    TABLE_POLICY_KEYS_1202KG,
    normalize_columns,
    normalize_table_schema,
    split_table_policy_1202kg,
)


# --- the split ------------------------------------------------------------------------------

def test_r114s_exact_schema_splits_into_shape_and_policy():
    sch = {"columns": [{"name": "id", "type": "integer primary key"}],
           "owner_scoped_reads": False, "visibility": "public"}
    clean, policy = split_table_policy_1202kg(sch)
    assert policy == {"owner_scoped_reads": False, "visibility": "public"}
    assert list(clean) == ["columns"]
    assert sch["visibility"] == "public", "the input must not be mutated"


def test_a_schema_with_no_policy_is_returned_unchanged():
    """★ The common path must be byte-identical — same object, not a rebuilt copy."""
    plain = {"columns": [{"name": "id", "type": "int"}]}
    clean, policy = split_table_policy_1202kg(plain)
    assert policy == {} and clean is plain
    assert normalize_table_schema(plain) is plain


# --- the column half ------------------------------------------------------------------------

def test_a_policy_key_never_becomes_a_column_in_the_flat_map():
    """★ r110/r111/r114 all carry `{"name": "owner_scoped_reads", "type": "false"}`."""
    flat = {"id": "integer primary key", "caption": "text",
            "owner_scoped_reads": False, "visibility": "public"}
    assert [c["name"] for c in normalize_columns(flat)] == ["id", "caption"]


def test_a_policy_key_beside_columns_is_dropped_from_the_stored_schema():
    sch = {"columns": [{"name": "id", "type": "int"}], "visibility": "public"}
    assert "visibility" not in normalize_table_schema(sch)


def test_a_real_column_that_merely_looks_policyish_survives():
    """`visibility_setting` and `is_public` are ordinary columns. An exact-key match, never a
    substring — the `art` matching `cart_token` trap."""
    flat = {"id": "int", "visibility_setting": "string", "is_public": "bool",
            "owner_scoped_reads_at": "datetime"}
    assert [c["name"] for c in normalize_columns(flat)] == [
        "id", "visibility_setting", "is_public", "owner_scoped_reads_at"]


# --- end to end through register_table ------------------------------------------------------

@pytest.fixture()
def hub(tmp_path):
    from runtime.hub_registry import HubRegistry
    return HubRegistry(str(tmp_path)).registryhub


def _meta(hub, name="videos"):
    return (hub.get_table(name) or {}).get("metadata") or {}


def _cols(hub, name="videos"):
    return [c.get("name") for c in
            (((hub.get_table(name) or {}).get("schema") or {}).get("columns") or [])]


def test_r114s_exact_call_now_reaches_the_metadata(hub):
    """★ The case, verbatim from the agent log."""
    hub.register_table(
        name="videos",
        schema={"columns": [{"name": "id", "type": "integer primary key"},
                            {"name": "caption", "type": "text"}],
                "owner_scoped_reads": False, "visibility": "public"},
        provider="backend", agent="backend", status="implemented")
    md = _meta(hub)
    assert md.get("visibility") == "public"
    assert md.get("owner_scoped_reads") is False
    assert _cols(hub) == ["id", "caption"]


def test_it_now_reaches_1202io_and_the_contradiction_is_refused(hub):
    """★ Reachability, not presence (the standing lesson): the lift is worthless unless the
    contradiction guard downstream can now SEE it. r114's ledger state was
    `owner_scoped_reads: true` with the materials saying public."""
    hub.register_table(
        name="videos",
        schema={"columns": [{"name": "id", "type": "int"}],
                "owner_scoped_reads": True, "visibility": "public"},
        provider="backend", agent="backend", status="implemented")
    md = _meta(hub)
    assert md.get("owner_scoped_reads") is False
    assert md.get("owner_scoped_reads_cleared_by_1202io") == "backend"


def test_an_explicit_kwarg_still_wins_over_the_nested_copy(hub):
    """Naming the argument is the more deliberate statement, so it must not be overwritten by
    a stale copy someone left in the schema."""
    hub.register_table(
        name="videos",
        schema={"columns": [{"name": "id", "type": "int"}], "visibility": "owner"},
        visibility="public",
        provider="backend", agent="backend", status="implemented")
    assert _meta(hub).get("visibility") == "public"


def test_the_kwarg_dialect_is_unchanged(hub):
    """Non-regression: r111's dialect is the one that always worked and must keep working."""
    hub.register_table(
        name="videos", schema={"columns": [{"name": "id", "type": "int"}]},
        visibility="public", owner_scoped_reads=True,
        provider="backend", agent="backend", status="implemented")
    md = _meta(hub)
    assert md.get("owner_scoped_reads") is False
    assert md.get("owner_scoped_reads_cleared_by_1202io") == "backend"


def test_a_table_the_materials_say_nothing_about_keeps_its_filter(hub):
    """★ Scope. #1202gd's rule: only an explicit `public` clears the flag."""
    hub.register_table(
        name="conversations",
        schema={"columns": [{"name": "id", "type": "int"}], "owner_scoped_reads": True},
        provider="backend", agent="backend", status="implemented")
    assert _meta(hub, "conversations").get("owner_scoped_reads") is True


def test_the_policy_key_set_is_named_once(hub):
    """Three readers use this set; a second hand-written copy is how #853 happened."""
    assert set(TABLE_POLICY_KEYS_1202KG) >= {"owner_scoped_reads", "visibility"}
