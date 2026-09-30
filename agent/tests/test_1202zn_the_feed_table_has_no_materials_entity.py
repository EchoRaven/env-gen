r"""#1202zn: the lane invents a `feed` table, so the materials have no entity to release it.

#320 already states the policy this fixes: "a table can hold OWNED-but-PUBLIC content (TikTok
videos, IG posts, YT videos) -- rows have a creator yet the feed is public ... An EXPLICIT
auth_required=False is the lane's DELIBERATE 'this read is public' declaration -- honor it."
#1202hh is HOW that is meant to be honoured, and it reads `entities[].visibility` from the
materials -- keyed on a product entity NAME.

r140 traced end to end. The spec says `videos: public`, correctly. The ORM carries BOTH
`videos` and a `feed` table with the identical FK shape (`author_id -> users` beside
`sound_id -> sounds`). `GET /api/feed` resolves by segment to the table literally named
`feed`; the materials have no `feed` entity because no lane had written one when the spec was
compiled; `visibility` is None; #598 demotes it; the logged-out landing page got 401; the lane
appended to `_FW_PUBLIC_API_1202KH` from custom_routes.py; `deliverability_guard_tampering`
blocked the run 8 times across 90 minutes.

MEASURED. 43 runs are in the era where the spec carries visibility at all (every spec from
09-14 on has 7-12 verdicts; the 124 with none all predate the feature -- time-sliced, so this
is not a reporting artifact). In 8 endpoints across those 43 a DELIBERATE `auth_required=False`
is overridden because the resolved table has no materials entity, 6 of them on `feed`. Over all
182 run directories the release is 7 endpoints in 5 runs and the table is `feed` every time
(the 7th is r125's `GET /api/search`, whose search fallback resolves to `feed` as well); 107
demotions stand, including every genuinely-private one.

★ THE SIGNAL IS THE FRAMEWORK'S OWN. `_FEED_SHAPED_TOKENS` has been read against PATH segments
since #205. This asks the same question of the TABLE. Two predicates I invented first were
both too wide and are not here: an incoming-FK count separated `videos` but not `comments`
(149 of 174), and an author-named owner column released 97 endpoints on a name list of my own.

★ RELEASE NEEDS THREE AGREEING SIGNALS, each closing a different way to be wrong: the contract
said public DELIBERATELY, the materials do not say `owner` (so r141's shape -- a per-user list
declared public by mistake -- keeps its protection), and the table's own name is one the
framework already treats as a feed. #566y's sub-entity branch is not touched at all.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.route_projector as RP  # noqa: E402

_priv = RP._structurally_private_resource_633


def _models(table="feed", fks=None, cols=None, visibility=None):
    """r140's real shape: an author FK to users beside a second entity FK.

    ★ `cols` is DERIVED from `fks` unless given. The first draft kept a fixed column list, so
    `_owner_fk` picked the default `author_id` out of `cols` whatever `fks` said and two
    fixtures never reached the branch they were written for -- the same "an earlier branch
    excluded the fixture" miss that #1202zb's two fixtures made."""
    _fks = dict(fks if fks is not None else {"author_id": "users", "sound_id": "sounds"})
    meta = {
        "cls": table.title().replace("_", ""),
        "cols": cols or (["id"] + sorted(_fks) + ["caption", "created_at"]),
        "fks": _fks,
        "types": {}, "required": [],
    }
    if visibility:
        meta["visibility"] = visibility
    return {table: meta, "users": {"cls": "User", "cols": ["id"], "fks": {},
                                   "types": {}, "required": []}}


# ---------------------------------------------------------------- the name predicate

def test_the_framework_s_own_tokens_are_what_is_matched():
    """Not a list of my own: every token comes from `_FEED_SHAPED_TOKENS`."""
    for tok in RP._FEED_SHAPED_TOKENS:
        assert RP._feed_named_table_1202zn(tok), tok
        assert RP._feed_named_table_1202zn(tok + "s"), tok


def test_a_compound_name_matches_per_segment():
    assert RP._feed_named_table_1202zn("videos_feed")
    assert RP._feed_named_table_1202zn("feed_items")


def test_a_substring_is_not_a_match():
    """`feedback` is a support table, not a feed."""
    for n in ("feedback", "feeders", "streamlined", "discovery_settings"):
        assert not RP._feed_named_table_1202zn(n), n


def test_the_private_tables_are_not_feed_named():
    for n in ("my_list", "continue_watching", "notifications", "messages",
              "video_likes", "saved_videos", "videos", "comments"):
        assert not RP._feed_named_table_1202zn(n), n


def test_an_empty_name_is_not_a_feed():
    """#883: an empty input must not read as a meaningful value -- the mistake #908's own
    fix made three times in one session."""
    for n in (None, "", "   "):
        assert RP._feed_named_table_1202zn(n) is False, repr(n)


# ---------------------------------------------------------------- the decision

def test_r140_s_feed_is_released_when_the_contract_said_public():
    """★ The whole ticket. Same models, same path, the declaration is the only difference."""
    m = _models()
    assert _priv("GET", "/api/feed", m, True) is False


def test_the_old_behaviour_is_unchanged_without_the_declaration():
    """An UNSTATED read on this shape still demotes -- r58/#315's leak protection, which is
    what makes the release safe to have at all."""
    m = _models()
    assert _priv("GET", "/api/feed", m, False) is True


def test_the_default_keeps_the_old_answer():
    """Any caller not yet passing the flag behaves exactly as before the ticket."""
    assert _priv("GET", "/api/feed", _models()) is True


def test_the_materials_still_outrank_the_contract():
    """★ r141's shape: a per-user list the lane declared public by mistake. The materials say
    `owner`, so the release must not fire however the contract is spelled."""
    m = _models(visibility="owner")
    assert _priv("GET", "/api/feed", m, True) is True


def test_a_materials_public_verdict_releases_it_as_it_always_did():
    """#1202hh's own path, unaffected: no declaration needed."""
    m = _models(visibility="public")
    assert _priv("GET", "/api/feed", m, False) is False


def test_the_sub_entity_branch_is_untouched():
    """★ #566y decides a DIFFERENT question and #1202zn must not reach it: a feed-named table
    owned through a persona row stays private even with the declaration."""
    m = _models(fks={"profile_id": "profiles", "title_id": "titles"})
    m["profiles"] = {"cls": "Profile", "cols": ["id", "user_id"],
                     "fks": {"user_id": "users"}, "types": {}, "required": []}
    assert _priv("GET", "/api/feed", m, True) is True


def test_a_private_list_is_not_released_by_the_declaration():
    """The tables the corpus measurement shows must keep their demotion."""
    for t in ("my_list", "continue_watching", "saved_videos"):
        m = _models(table=t, fks={"user_id": "users", "title_id": "titles"})
        assert _priv("GET", "/api/" + t.replace("_", "-"), m, True) is True, t


def test_a_table_with_no_second_entity_fk_was_never_demoted():
    """#598's discriminator, restated: `posts(user_id, title, body)` is public by construction
    and neither the old nor the new predicate touches it."""
    m = _models(table="posts", fks={"user_id": "users"})
    assert _priv("GET", "/api/posts", m, True) is False
    assert _priv("GET", "/api/posts", m, False) is False


# ---------------------------------------------------------------- the callers

def _call_args(module, name):
    src = inspect.getsource(module)
    tree = ast.parse(src)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fn = getattr(n.func, "id", "") or getattr(n.func, "attr", "")
            if fn == name:
                out.append(n)
    return out


def test_the_projector_passes_its_own_declaration():
    """★ I have tested a helper and not its caller repeatedly. The flag must ARRIVE."""
    calls = _call_args(RP, "_structurally_private_resource_633")
    calls = [c for c in calls if len(c.args) >= 3]
    assert len(calls) == 1, "called %d times with models" % len(calls)
    assert len(calls[0].args) == 4, "the declaration is not passed: %d args" % len(calls[0].args)
    assert getattr(calls[0].args[3], "id", "") == "_explicit_public", ast.dump(calls[0].args[3])


def test_the_skeleton_passes_its_own_declaration():
    """The other emitter. #1032: two copies of this decision drifted once already (#1202my
    had to repair exactly these two sites)."""
    import multi_agent.runtime.backend_skeleton as BS
    calls = _call_args(BS, "_priv633")
    assert len(calls) == 1, "called %d times" % len(calls)
    assert len(calls[0].args) == 4, "the declaration is not passed"
    assert getattr(calls[0].args[3], "id", "") == "_explicit_public_1097", \
        ast.dump(calls[0].args[3])


def test_the_gate_asks_the_same_question():
    """`_shape_demoted_publics_1202y9` names the demoted routes for a blocked lane. If it
    keeps asking without the flag it names routes that were never demoted -- which is the
    failure its own docstring warns about ("recomputed here rather than carried ... keeps the
    gate and the generator from disagreeing about what is private")."""
    import multi_agent.runtime.deliverability as DV
    calls = _call_args(DV, "_priv1202y9")
    assert len(calls) == 1, "called %d times" % len(calls)
    assert len(calls[0].args) == 4, "the gate still asks the old question"
    assert getattr(calls[0].args[3], "value", None) is True, ast.dump(calls[0].args[3])
