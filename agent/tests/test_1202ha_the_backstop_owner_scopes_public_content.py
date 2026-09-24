"""#1202ha — the framework's own backstop owner-scopes the tables the materials call public.

`run_kickoff`'s READ-VISIBILITY BACKSTOP sets `owner_scoped_reads = True` when the lane did
not decide, the table has an owner FK, and the GOAL text implies per-user privacy. TikTok's
description says "Each signed-in user sees only its own likes, saves and following list
(per-user private data)" — so the phrase matches, and the backstop then applies it to EVERY
owned table, including `videos` (author_id) and `comments` (user_id), which the goal never
called private and which the materials explicitly declare PUBLIC content.

That is the origin of the contradiction four runs died on. It surfaced three surfaces away
each time — an empty feed starving a chain capture (r100: 38 of 73 steps 404'd), an
unscoped-owner-read blocker (r99, r101), and a logged-out flow that cannot render (r98, and
r101's final blocker was `comments_page` for exactly this reason). #1202gv REPORTS the
disagreement; this stops the framework creating it.

The materials are available in time: r101 wrote `design/reference_spec.json` at 00:03:52 and
the tables ledger at 00:43:09, forty minutes later.

Narrow (#647): only a table the materials explicitly declare `public` is skipped. Absent a
declaration the backstop behaves exactly as before — that is #1202gd's rule for staying
strict, and it is what protects the per-user tables the backstop exists for.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.kickoff.run_kickoff import _build_contract  # noqa: E402

_PRIVACY_GOAL = ("Each signed-in user sees only its own likes, saves and following list "
                 "(per-user private data).")

# The real shape, from `_build_contract` itself: `data_model` is a MAPPING with a `tables`
# list. A bare list reads as empty and the backstop never runs — the first cut of this test
# asserted against that and would have passed anything.
_DRAFTS = {
    "backend": {"data_model": {"tables": [
        {"name": "videos", "columns": [{"name": "id", "type": "integer", "pk": True},
                                       {"name": "author_id", "type": "integer",
                                        "references": "users.id"}]},
        {"name": "video_saves", "columns": [{"name": "id", "type": "integer", "pk": True},
                                            {"name": "user_id", "type": "integer",
                                             "references": "users.id"}]},
    ]}, "endpoints": [{"method": "GET", "path": "/api/videos"}]},
    "frontend": {},
}


def _scoped(contract):
    dm = contract.get("data_model") or {}
    tables = dm.get("tables") if isinstance(dm, dict) else None
    return {t.get("name") for t in (tables or [])
            if isinstance(t, dict) and t.get("owner_scoped_reads") is True}


def test_the_backstop_still_protects_a_per_user_table():
    """The behaviour #1202h exists for must survive untouched."""
    got = _scoped(_build_contract(_DRAFTS, _PRIVACY_GOAL))
    assert "video_saves" in got, (
        "the per-user table lost its read scoping — this is the leak the backstop prevents")


def test_a_table_the_materials_declare_public_is_left_alone():
    got = _scoped(_build_contract(_DRAFTS, _PRIVACY_GOAL, public_tables=frozenset({"videos"})))
    assert "videos" not in got, (
        "the framework still owner-scopes content the materials call public")
    assert "video_saves" in got, "the narrowing leaked to a genuinely per-user table"


def test_no_declaration_changes_nothing():
    """Absent materials, the backstop is exactly what it was (#1202gd's strict default)."""
    assert _scoped(_build_contract(_DRAFTS, _PRIVACY_GOAL)) == _scoped(
        _build_contract(_DRAFTS, _PRIVACY_GOAL, public_tables=frozenset()))


def test_a_goal_without_the_privacy_phrase_scopes_nothing():
    got = _scoped(_build_contract(_DRAFTS, "Build a public video feed."))
    assert got == set(), got


def test_hostile_public_tables_never_raise():
    for bad in (None, "videos", 3, ["videos"]):
        assert isinstance(_build_contract(_DRAFTS, _PRIVACY_GOAL, public_tables=bad), dict)


def test_the_caller_reads_the_materials():
    """A parameter nobody fills is this codebase's most repeated failure.

    Observed on what `_build_contract` actually RECEIVES when the real kickoff path runs
    over a real spec file, rather than on two substrings in run_kickoff.py. #1202hh moved
    the spec reader into `backend_skeleton` (one reader, shared with the scaffolder's
    write-time backfill), so the filename no longer appears in this module while the
    parameter is filled exactly as before — a source check would have called that a
    regression, and would equally have passed on a caller that read the file and then
    passed the empty set.
    """
    import json
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_kickoff_run_kickoff import ATTENDEES, _all_clean_decisions, _mock_hubs

    from multi_agent.runtime.kickoff import run_kickoff as rk

    seen = {}
    real = rk._build_contract

    def _spy(drafts, description, public_tables=None, *a, **kw):
        seen["public_tables"] = public_tables
        return real(drafts, description, public_tables, *a, **kw)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared").mkdir(parents=True)
        (root / "design").mkdir(parents=True)
        (root / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": [{"name": "posts", "visibility": "public"},
                                     {"name": "saved_items", "visibility": "owner"}]}),
            encoding="utf-8")
        hubs = _mock_hubs(decisions=_all_clean_decisions())
        hubs.base_dir = str(root)          # production: HubRegistry(output_dir).base_dir IS the run root
        rk._build_contract = _spy
        try:
            rk.try_synthesize(hubs, {"meeting_id": "page_meeting_1", "milestone_index": 1,
                                     "expected_attendees": ATTENDEES,
                                     "description": _PRIVACY_GOAL})
        finally:
            rk._build_contract = real

    got = seen.get("public_tables")
    assert got is not None, "the parameter has no caller"
    assert "posts" in set(got), (
        "nothing reads the materials, so the parameter is always empty: %r" % (got,))
    assert "saved_items" not in set(got), (
        "a table the materials call owner-private must not be released: %r" % (got,))
