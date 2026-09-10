"""#1202hh — the materials' `visibility: public` must reach the PROJECTOR, not just the audit.

r103 is the whole argument. The reference spec declares `videos`/`comments` public and
`video_likes`/`follows`/`notifications` owner. The backend lane finally cleared
`owner_scoped_reads` on both public tables (14:56:38). `main.py` was re-projected 37s later
(15:02:53) and STILL emitted

    rows = db.query(Video).filter(Video.author_id == _fw_owner_val(...)).limit(100).all()

because `_structurally_private_resource_633` re-imposes the filter from the table's SHAPE
(`author_id` + `sound_id` -> `_is_user_content_relation`), overriding the contract by design.
So 39 seeded videos stayed invisible to every caller and the feed-backed flows kept failing.

`#1202gd` already settled this question ONCE, with a measured rationale over 116 backends:
the schema cannot separate `videos` from `saved_items`, so the MATERIALS have to say, and the
exemption needs both the spec declaration and the contract's agreement. But it settled it in
`backend_audit` alone -- the fact never reached the two emitters, which re-read nothing and
kept overriding. One fact, three readers, one of them informed.

These tests pin the fact travelling: kickoff stamps `visibility` onto the table record,
`_models_meta` carries it into the model meta both emitters already consume, and #633 stands
down for a declared-public table -- while the contract flag alone still owner-scopes, so the
r141 leak shape (a lane calling a per-user list public) is untouched.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import _models_meta, render_skeleton_main
from multi_agent.runtime.route_projector import _structurally_private_resource_633


def _col(name, type_="text", **kw):
    c = {"name": name, "type": type_}
    c.update(kw)
    return c


def _tables(videos_visibility=None, videos_owner_scoped=None):
    """r103's shape: a content table with an owner FK AND a second entity FK (what makes
    `_is_user_content_relation` fire), a genuine per-user relation table, and the referents."""
    vmeta = {}
    if videos_visibility is not None:
        vmeta["visibility"] = videos_visibility
    if videos_owner_scoped is not None:
        vmeta["owner_scoped_reads"] = videos_owner_scoped
    return {
        "users": {"name": "users", "schema": {"columns": [
            _col("id", "integer", primary_key=True), _col("email"), _col("name")]}},
        "sounds": {"name": "sounds", "schema": {"columns": [
            _col("id", "integer", primary_key=True), _col("title")]}},
        "videos": {"name": "videos", "schema": {"columns": [
            _col("id", "integer", primary_key=True),
            _col("author_id", "integer", references="users.id"),
            _col("sound_id", "integer", references="sounds.id"),
            _col("caption"), _col("video_url"), _col("view_count", "integer")]},
            "metadata": vmeta},
        "video_saves": {"name": "video_saves", "schema": {"columns": [
            _col("id", "integer", primary_key=True),
            _col("user_id", "integer", references="users.id"),
            _col("video_id", "integer", references="videos.id")]},
            "metadata": {"visibility": "owner"}},
    }


def test_models_meta_carries_the_declaration():
    """The emitters read `_models_meta`'s output and nothing else. If the declaration does
    not land here it cannot reach either of them -- which is exactly how it was lost."""
    meta = _models_meta(_tables(videos_visibility="public"))
    assert meta["videos"].get("visibility") == "public"
    assert meta["video_saves"].get("visibility") == "owner"


def test_declared_public_stands_down_the_structural_override():
    meta = _models_meta(_tables(videos_visibility="public"))
    assert _structurally_private_resource_633("GET", "/api/videos", meta) is False


def test_owner_declared_relation_is_still_private():
    """#633's whole reason to exist. `video_saves(user_id, video_id)` is the `my_list`
    shape #1202gd names as the one the corpus would have leaked."""
    meta = _models_meta(_tables(videos_visibility="public"))
    assert _structurally_private_resource_633("GET", "/api/video_saves", meta) is True


def test_undeclared_table_keeps_the_pre_1202hh_verdict():
    """Every spec in the corpus before r103 carries no `visibility`; those runs must not
    change verdict, the same opt-in property #1202gd argued for."""
    meta = _models_meta(_tables(videos_visibility=None))
    assert _structurally_private_resource_633("GET", "/api/videos", meta) is True


def _feed_handler(src):
    """The projected feed handler's own source.

    #1202kh re-anchor: this used to scan for the SUBSTRING `def _projected_get_api_videos` and
    keep every line until the next `@app.`, which matched a COMMENT in the auth middleware the
    moment one mentioned a handler signature, and returned that comment as "the handler". Read
    the function out of the parse tree instead (#923: no span locator over raw source), so no
    prose anywhere in main.py can be mistaken for code.
    """
    import ast as _ast
    tree = _ast.parse(src)
    for node in tree.body:
        if isinstance(node, _ast.FunctionDef) and node.name.startswith("_projected_get_api_videos"):
            return _ast.get_source_segment(src, node) or ""
    raise AssertionError("no projected /api/videos handler in the rendered main.py")


def _endpoints():
    return [{"id": "GET /api/videos", "method": "GET", "path": "/api/videos",
             "schema": {}, "metadata": {"auth_required": True}}]


def test_declared_public_feed_is_projected_unfiltered():
    """The r103 failure, end to end: the contract agrees the reads are not owner-scoped and
    the materials call the rows published, so the feed must serve every row."""
    src = render_skeleton_main(_endpoints(), _tables(videos_visibility="public",
                                                     videos_owner_scoped=False))
    handler = _feed_handler(src)
    assert handler, "the feed handler was not projected at all"
    assert "_fw_owner_val" not in handler, handler


def test_contract_flag_alone_still_owner_scopes_a_declared_public_table():
    """Both signals required -- a lane that marks the table private wins over the spec, so
    relaxing #633 cannot open a read the contract asked to keep scoped."""
    src = render_skeleton_main(_endpoints(), _tables(videos_visibility="public",
                                                     videos_owner_scoped=True))
    handler = _feed_handler(src)
    assert "_fw_owner_val" in handler, handler
