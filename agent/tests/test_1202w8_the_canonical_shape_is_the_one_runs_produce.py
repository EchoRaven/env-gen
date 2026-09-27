"""#1202w8: `_MEDIA_COL` must be populated from the shape a REAL RUN produces.

#1202uu gave media tables a demo-content floor of 1 instead of `_DEMO_FLOOR = 8`, so the
FIX #74 concentrator stops minting a byte-identical copy of someone else's video under a
different owner. The mechanism was wired end to end -- `_MEDIA_COL` is read at two places
in the generated loader -- but it was fed from `tables[t]["columns"]`, the FLATTENED shape.

A SchemaHub table record keeps its columns under `schema` (finalize_kickoff stores the
contract table minus `name` there). `_columns_of` is the shape-tolerant accessor that
exists precisely because both shapes circulate; reading the flat key directly sees nothing
in the canonical case. MEASURED: r136 and r137, both generated after #1202uu landed, ship
`_MEDIA_COL = {}` in seed_data.py while `_IMAGE_COL` on the SAME videos table is populated
(it goes through `_models_meta` -> `_columns_of`), and models.py declares `video_url`.

The #1202uu test built its fixture flattened, so it stayed green against a mechanism that
had never once fired in production. This test pins the OTHER TWO shapes `_columns_of`
accepts, so the pairing of predicate to real data is what is asserted -- not the presence
of an accessor's name in the source.
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "env_generator", "llm_generator"))

from multi_agent.runtime.backend_skeleton import render_seed_data  # noqa: E402

_VIDEO_COLS = [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "author_id", "type": "integer", "fk": "users.id"},
    {"name": "video_url", "type": "text"},
    {"name": "thumbnail_url", "type": "text"},
    {"name": "caption", "type": "text"},
]
_USER_COLS = [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "username", "type": "text"},
    {"name": "avatar_url", "type": "text"},
]

# The shape finalize_kickoff actually stores, and the one every generated app is built from.
CANONICAL = {
    "users": {"name": "users", "schema": {"columns": _USER_COLS}},
    "videos": {"name": "videos", "schema": {"columns": _VIDEO_COLS}},
}

# The raw flat-map schema `_columns_of` normalizes (defense in depth, same data).
FLAT_MAP = {
    "users": {"name": "users", "schema": {c["name"]: c["type"] for c in _USER_COLS}},
    "videos": {"name": "videos", "schema": {c["name"]: c["type"] for c in _VIDEO_COLS}},
}


def _media_col(tables):
    src = render_seed_data(tables)
    m = re.search(r"^_MEDIA_COL = (\{.*\})$", src, re.M)
    assert m, "_MEDIA_COL assignment not found in the generated loader"
    return ast.literal_eval(m.group(1)), src


def test_the_canonical_schema_nesting_reaches_the_media_floor():
    media, src = _media_col(CANONICAL)
    assert media.get("videos") == ["video_url"], (
        "a SchemaHub table record nests its columns under `schema`; _MEDIA_COL came back "
        f"{media!r}, so the #1202uu floor never applies on a real run"
    )
    # The decoration column must stay out of it: two rows may legitimately share a thumbnail.
    assert "thumbnail_url" not in (media.get("videos") or [])
    # And the same table's image backfill still sees its own columns, which is what proves
    # the two accessors now read the same data rather than one of them reading nothing.
    m_img = re.search(r"^_IMAGE_COL = (\{.*\})$", src, re.M)
    assert m_img, "_IMAGE_COL assignment not found"
    assert "thumbnail_url" in (ast.literal_eval(m_img.group(1)).get("videos") or [])


def test_the_flat_map_schema_reaches_the_media_floor():
    media, _src = _media_col(FLAT_MAP)
    assert media.get("videos") == ["video_url"], (
        f"a raw flat-map schema must normalize to the same columns; got {media!r}"
    )


def test_a_text_only_table_is_still_not_a_media_table():
    """The floor must not collapse to 1 for tables the concentrator is meant to top up."""
    text_only = {
        "users": {"name": "users", "schema": {"columns": _USER_COLS}},
        "messages": {"name": "messages", "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "user_id", "type": "integer", "fk": "users.id"},
            {"name": "body", "type": "text"},
        ]}},
    }
    media, _src = _media_col(text_only)
    assert "messages" not in media, (
        f"a message table carries no asset of its own; got {media!r}"
    )
