r"""#1202: a table other rows are OWNED BY is per-user identity, whatever its shape.

#1200 learns the judgment from the lane's own read filter, so it cannot help a run where the
lane never wrote one — r1 and r27 ship `profiles` unscoped with no signal to learn from. This
is the third source, and it asks nothing of any agent.

#598 declined to scope a table carrying a user FK and nothing else, because
`profiles(user_id, name)` is shape-identical to a public `posts(user_id, title, body)` and
scoping by that shape would break every public feed. That is true, and it stays true. But a
SECOND shape separates them, and the framework already names it — `_NARROW_OWNER_FK_NAMES`,
the owner columns that attribute a row to a sub-entity rather than to a user:

    netflix    my_list.profile_id -> profiles     `profile_id` IS an owner name  -> private
    instagram  comments.post_id   -> posts        `post_id` is NOT               -> public
    tiktok     nothing is owned by video_id                                      -> public

Measured over the 94 generated backends carrying models: 14 ship an unscoped projected read on
a table with an owner column, and this rule separates them 9/9 — netflix's `profiles` in
r1/r2/r23/r27 private; instagram's `posts`/`comments` and tiktok's `videos`/`live_streams`
public, which is what those apps mean.

The extra condition — some OTHER table must actually carry that owner column — is what keeps a
public directory of profiles public: without it, nothing in the app treats the table as an
owner.

The vocabulary is imported, never re-listed. #908 wrote "a second hand-written copy of this
vocabulary is how one member goes missing from one of them" while deriving its own.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _sub_entity_owner_tables_1202, write_backend_skeleton,
)


def _t(*cols):
    return {"schema": {"columns": [{"name": c, "type": "integer"} for c in cols]}}


NETFLIX = {"users": _t("id", "email"),
           "profiles": _t("id", "user_id", "name"),
           "my_list": _t("id", "profile_id", "title_id"),
           "titles": _t("id", "name")}

INSTAGRAM = {"users": _t("id", "email"),
             "posts": _t("id", "user_id", "caption"),
             "comments": _t("id", "post_id", "user_id", "body")}


def test_a_table_other_rows_are_owned_by_is_private():
    assert _sub_entity_owner_tables_1202(NETFLIX) == {"profiles"}


def test_a_public_feed_stays_public():
    """`posts` carries a user FK and nothing owns rows BY a post — #598's case, untouched."""
    assert _sub_entity_owner_tables_1202(INSTAGRAM) == set()


def test_a_profiles_table_nothing_is_owned_by_stays_public():
    """A public directory of profiles: the name matches, but no table is owned by one."""
    directory = {"users": _t("id"), "profiles": _t("id", "user_id", "bio")}
    assert _sub_entity_owner_tables_1202(directory) == set()


def test_a_broken_tables_argument_never_raises():
    for bad in (None, {}, {"x": None}, {"x": {"schema": None}}, "nonsense"):
        assert isinstance(_sub_entity_owner_tables_1202(bad), set)


def test_the_vocabulary_is_the_frameworks_own():
    """A hand-written second copy is how one member goes missing (#908)."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py"
           ).read_text(encoding="utf-8")
    at = src.index("def _sub_entity_owner_tables_1202")
    # Landmark (#943): the body ends at whichever comes first — the next top-level def or
    # the next banner comment. Slicing only to "\ndef " ran past a module-level constant
    # into #1200's own vocabulary and read its "profile_id" as this function's.
    ends = [e for e in (src.find("\ndef ", at + 10), src.find("\n# ---", at + 10)) if e > 0]
    body = src[at:min(ends)]
    assert "from .route_projector import _NARROW_OWNER_FK_NAMES" in body
    assert '"profile_id"' not in body                 # not re-listed


def test_the_generated_read_becomes_scoped(tmp_path):
    """End to end on the deterministic projector, the way #1200 was validated."""
    endpoints = [{"method": "GET", "path": "/api/profiles",
                  "metadata": {"auth_required": True, "response_key": "items"}}]

    def render(tbls, tag):
        out = tmp_path / tag
        (out / "app" / "backend").mkdir(parents=True)
        write_backend_skeleton(out, endpoints, tbls)
        src = (out / "app" / "backend" / "main.py").read_text(encoding="utf-8")
        i = src.index("def _projected_get_api_profiles")
        return src[i:src.index("return", i)]

    assert "_fw_owner_val" not in render(NETFLIX, "before")

    scoped = dict(NETFLIX)
    for t in _sub_entity_owner_tables_1202(NETFLIX):
        rec = dict(scoped[t])
        rec["metadata"] = dict(rec.get("metadata") or {}, owner_scoped_reads=True)
        scoped[t] = rec
    assert "_fw_owner_val" in render(scoped, "after")


def test_the_three_signals_are_independent():
    """#1201: one failing must not switch the others off."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
           ).read_text(encoding="utf-8")
    at = src.index("_sub_entity_owner_tables_1202")
    enclosing = src.rindex("try:", 0, at)
    assert "heal_pipeline" not in src[enclosing:at]
    assert "_lane_owner_scoped_read_tables_1200" not in src[enclosing:at]


def test_the_same_signal_also_restores_authentication(tmp_path):
    """One signal, two defects. netflix-r5 shipped `GET /api/profiles` with NO auth at all —
    anonymous access to every account's profiles, which is worse than #1200's
    authenticated leak. It is the only case in 114 generated backends.

    No new mechanism was needed: #1098 already forces an actor on an owner-scoped resource
    "whatever the contract omits", so marking the table private authenticates it too.
    Rendered from r5's own contract:

        before  def _projected_get_api_profiles_14(db=Depends(get_db)):
        after   def _projected_get_api_profiles_14(db=Depends(get_db), user=Depends(get_current_user)):

    Pinned because the two rules meet by consequence rather than by design: if #1098's
    `or _owner_scoped` were ever narrowed, this guarantee would go quietly.
    """
    endpoints = [{"method": "GET", "path": "/api/profiles",
                  "metadata": {"response_key": "items"}}]      # note: no auth_required

    def render(tbls, tag):
        out = tmp_path / tag
        (out / "app" / "backend").mkdir(parents=True)
        write_backend_skeleton(out, endpoints, tbls)
        src = (out / "app" / "backend" / "main.py").read_text(encoding="utf-8")
        i = src.index("def _projected_get_api_profiles")
        return src[i:src.index("\n", i)]

    assert "get_current_user" not in render(NETFLIX, "auth_before")

    scoped = dict(NETFLIX)
    for t in _sub_entity_owner_tables_1202(NETFLIX):
        rec = dict(scoped[t])
        rec["metadata"] = dict(rec.get("metadata") or {}, owner_scoped_reads=True)
        scoped[t] = rec
    assert "get_current_user" in render(scoped, "auth_after")


def test_either_signal_alone_closes_the_leak(tmp_path):
    """Replayed over every leaking run in the corpus, at no LLM cost, both signals were
    exercised and each proved sufficient on its own:

        r23   #1200 ✓  #1202 ✓   db.query(Profile).limit(100).all()  ->  owner-filtered
        r1    #1200 –  #1202 ✓   ditto
        r5    #1200 –  #1202 ✓   ditto (and regains auth, via #1098)
        r26   #1200 –  #1202 ✓   already scoped, stays scoped

    r1 and r5 are exactly the runs #1200 cannot reach — their lanes never wrote a scoped read
    to learn from — so this pins that neither signal is load-bearing alone.
    """
    from multi_agent.runtime.backend_skeleton import _lane_owner_scoped_read_tables_1200

    endpoints = [{"method": "GET", "path": "/api/profiles",
                  "metadata": {"auth_required": True, "response_key": "items"}}]
    lane_with_filter = (
        '@router.get("/api/profiles")\n'
        'def list_profiles(db=Depends(get_db), user=Depends(get_current_user)):\n'
        '    return {"items": db.query(Profile).filter(Profile.user_id == _user_id(user)).all()}\n')

    def render(tbls, tag, lane_src):
        out = tmp_path / tag
        (out / "app" / "backend").mkdir(parents=True)
        if lane_src:
            (out / "app" / "backend" / "custom_routes.py").write_text(lane_src, encoding="utf-8")
        write_backend_skeleton(out, endpoints, tbls)
        src = (out / "app" / "backend" / "main.py").read_text(encoding="utf-8")
        i = src.index("def _projected_get_api_profiles")
        return out, src[i:src.index("return", i)]

    def scoped_with(signals, tag, lane_src):
        tbls = dict(NETFLIX)
        for t in signals:
            rec = dict(tbls[t])
            rec["metadata"] = dict(rec.get("metadata") or {}, owner_scoped_reads=True)
            tbls[t] = rec
        return render(tbls, tag, lane_src)[1]

    # r23's shape: the lane wrote a scoped read, so #1200 alone is enough.
    be, before = render(NETFLIX, "r23_before", lane_with_filter)
    assert "_fw_owner_val" not in before
    s1200 = _lane_owner_scoped_read_tables_1200(be / "app" / "backend", NETFLIX)
    assert s1200 == {"profiles"}
    assert "_fw_owner_val" in scoped_with(s1200, "r23_after", lane_with_filter)

    # r1/r5's shape: no lane filter to learn from, so #1202 alone has to carry it.
    be2, before2 = render(NETFLIX, "r1_before", None)
    assert "_fw_owner_val" not in before2
    assert _lane_owner_scoped_read_tables_1200(be2 / "app" / "backend", NETFLIX) == set()
    s1202 = _sub_entity_owner_tables_1202(NETFLIX)
    assert s1202 == {"profiles"}
    assert "_fw_owner_val" in scoped_with(s1202, "r1_after", None)
