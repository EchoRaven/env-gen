r"""#1202zb: seeded content in a table no endpoint reads, beside an identically-shaped
table the API does serve.

r140 SHIPPED this in a released 1.0.0. `videos` and `feed` carry byte-identical columns;
`videos` held 35 rows and `feed` 8, their contents DISJOINT; the app's only collection read
is `GET /api/feed` and no GET anywhere resolves to `videos`. 35 authored videos -- the whole
point of the seed -- were unreachable through the delivered app. Verified by curl against
that run's own stack.

MEASURED over the 47 corpus runs that carry live row counts: six pairs in four runs match
the raw shape, and READING ALL SIX is what produced the exclusion the tests below pin:

    r140  videos(35)               no GET | feed(8)                   GET /api/feed
    r105  live_streams(3)          no GET | live(0)                   GET /api/live
    r105  creator_profiles(5)      no GET | suggested_creators(0)     GET /api/suggested-creators
    r99   conversations(7)         no GET | messages(6)               GET /api/messages
    r125  comments(295)            no GET | comment(8)                EXCLUDED
    r125  message_conversations(8) no GET | messages_conversations(6) EXCLUDED

★ r99 looked like a false positive on its names and is NOT one: both tables carry
`peer_id, last_message, unread` -- the lane modelled one conversation list twice. The
judgement that mattered went the other way: the r125 pairs are excluded because the finding
rests on `_resource_model` naming which table an endpoint reads, and for `comment` beside
`comments` that resolver can only pick one and its pick is not evidence.

★ A TASK, NOT A BLOCKER, on #1202w0's bargain for the same harm class -- and unlike #1202w0
it also reaches a lane, because today's #1202z0 and #1202z4 are both the same defect: a
finding computed correctly and delivered to a log nobody reads.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.backend_audit as BA      # noqa: E402
import multi_agent.runtime.heal_pipeline as HP      # noqa: E402
import multi_agent.runtime.seed_audit as SA         # noqa: E402

_VID = ["id", "author_id", "sound_id", "video_url", "caption", "like_count", "created_at"]


def _m(cols):
    return {"cols": list(cols), "fks": {}}


class _Reg:
    def __init__(self, eps):
        self._eps = {("e%d" % i): e for i, e in enumerate(eps)}

    def get_endpoints(self):
        return dict(self._eps)


class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "t1", **kw}


class _Orch:
    def __init__(self, wh):
        class _H:
            workhub = wh
        self.hubs = _H()


def _ep(method, path, status="implemented"):
    return {"method": method, "path": path, "status": status}


_R140_MODELS = {"videos": _m(_VID), "feed": _m(_VID), "users": _m(["id", "email", "name"])}
_R140_COUNTS_ORIG = {"videos": 35, "feed": 8, "users": 9}
_R140_EPS_ORIG = [_ep("GET", "/api/feed"), _ep("GET", "/api/feed/{video_id}"),
                  _ep("POST", "/api/videos/{video_id}/like"),
                  _ep("DELETE", "/api/videos/{video_id}/like")]


# #1203a9 moved the FEED-SHAPED half of this defect to the source: a feed-shaped route whose
# table is a column-identical copy of a data table now resolves to the data table, so the r140
# shape below can no longer arise and this detector correctly reports nothing for it.
#
# The detector keeps its purpose for the OTHER half, which #1203a9 deliberately does not touch:
# a column-identical pair whose route segment is NOT a feed word. r35 carries three of them —
# message/messages, notification/notifications, live_stream/live_streams. The behavioural tests
# below use that shape so they exercise the detector rather than the projector.
#
# The dict ORDER is load-bearing: `_match_model` returns the first match, so putting the lean
# singular first is what makes `/api/message` resolve to it deterministically.
# TWO exemptions had to be respected to build this, and each one cost a run of the suite:
#   * `_name_variants_1202zb` excludes singular/plural pairs (message/messages) BY DESIGN —
#     "the same concept spelled twice" is not hidden content. My first attempt used exactly
#     that pair and the detector correctly reported nothing.
#   * #1203a9 now redirects a FEED-SHAPED route away from a column-identical copy, so the
#     original `feed`/`videos` fixture no longer reproduces either.
# What remains, and what this fixture is: column-identical, NOT name variants, and reached by a
# route whose segment is not a feed word — so the projector stays out of it.
_TWIN_MODELS = {"archive": _m(_VID), "videos": _m(_VID),
                "users": _m(["id", "email", "name"])}
_TWIN_COUNTS = {"archive": 8, "videos": 35, "users": 9}
_TWIN_EPS = [_ep("GET", "/api/archive"), _ep("GET", "/api/archive/{video_id}"),
             _ep("POST", "/api/videos/{video_id}/like")]


def _run(monkeypatch, tmp_path, models, counts, eps):
    monkeypatch.setattr(BA, "_models_919", lambda *a, **k: (models, {}))
    monkeypatch.setattr(SA, "recent_live_counts_1202dj", lambda *a, **k: dict(counts))
    monkeypatch.setattr(SA, "_project_root_1202dj", lambda p: tmp_path)
    return HP._unreachable_twin_tables_1202zb(tmp_path, _Reg(eps))


def test_the_r140_feed_shape_is_now_rescued_at_the_source(monkeypatch, tmp_path):
    """★ WAS `test_the_r140_shape_is_reported`. Every number in `_R140_*` is that run's, and the
    detector used to report it. #1203a9 fixed it where it happens: `/api/feed` resolving to a
    column-identical copy of the content table now resolves to the content table, so `videos` IS
    read and there is nothing left to find. Reporting nothing here is the fix working — pinned so
    a regression in the projector shows up as this test going RED with a finding."""
    r = _run(monkeypatch, tmp_path, _R140_MODELS, _R140_COUNTS_ORIG, _R140_EPS_ORIG)
    assert r["measured"] is True, r
    assert r["findings"] == [], (
        "the feed-shaped twin reappeared — #1203a9's override stopped working: %r" % r["findings"])
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS)
    assert r["measured"] is True, r
    assert len(r["findings"]) == 1, r["findings"]
    f = r["findings"][0]
    assert f["unread"] == "videos" and f["unread_rows"] == 35, f
    assert f["served"] == "archive" and f["served_rows"] == 8, f
    assert f["via"] == "/api/archive", f


def test_a_twin_the_api_also_reads_is_not_reported(monkeypatch, tmp_path):
    """★ THE PRECISION TEST. r121 has the same two tables with the same lopsided split AND a
    `GET /api/videos`. Nothing is hidden there, so a check that reported it would be a false
    positive on the run immediately before the true one."""
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS,
             _TWIN_EPS + [_ep("GET", "/api/videos")])
    assert r["measured"] is True
    assert r["findings"] == [], r["findings"]


def test_a_route_that_is_not_implemented_does_not_count_as_a_read(monkeypatch, tmp_path):
    """A `defined` route serves nothing, so it cannot be the read that rescues the table."""
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS,
             _TWIN_EPS + [_ep("GET", "/api/videos", status="defined")])
    assert len(r["findings"]) == 1, r["findings"]


def test_a_name_variant_pair_is_excluded(monkeypatch, tmp_path):
    """r125: `comments`(295) beside `comment`(8), one served. Excluded because
    `_resource_model` cannot tell which of the two the handler queries."""
    cols = ["id", "video_id", "user_id", "body", "like_count", "created_at"]
    # ★ `comment` FIRST, because `_match_model` returns the first matching table in dict
    # order and that is how r125 really resolved: `/api/comments` -> `comment`, the 8-row
    # twin, while `comments` held 295. The first version of this fixture listed `comments`
    # first, the resolver picked the RICH twin, and the pair was then excluded by the
    # row-count comparison instead -- so removing the variant rule left the test green.
    models = {"comment": _m(cols), "comments": _m(cols)}
    r = _run(monkeypatch, tmp_path, models, {"comments": 295, "comment": 8},
             [_ep("GET", "/api/videos/{video_id}/comments")])
    assert r["findings"] == [], r["findings"]


def test_the_variant_rule_is_per_token(monkeypatch, tmp_path):
    """★ `message_conversations` vs `messages_conversations` differ in the FIRST token. A rule
    that strips only a trailing `s` calls them unrelated and reports r125's second pair --
    which is why every underscore token is singularised, not the name."""
    # Four columns AFTER `id` is dropped -- the first version had three and the column floor
    # excluded the pair before the variant rule was ever consulted.
    cols = ["id", "user_id", "peer_id", "last_message", "unread"]
    r = _run(monkeypatch, tmp_path,
             {"message_conversations": _m(cols), "messages_conversations": _m(cols)},
             {"message_conversations": 8, "messages_conversations": 6},
             [_ep("GET", "/api/messages/conversations")])
    assert r["findings"] == [], r["findings"]


def test_two_unrelated_names_with_one_shape_are_kept(monkeypatch, tmp_path):
    """★ r99, the case I first called a false positive and was wrong about: `conversations`
    and `messages` both carry `peer_id, last_message, unread`. Different names, one entity,
    7 rows with no route. Keeping it is the point of testing the exclusion by SPELLING rather
    than by whether the names look related."""
    cols = ["id", "user_id", "peer_id", "last_message", "unread"]
    r = _run(monkeypatch, tmp_path, {"conversations": _m(cols), "messages": _m(cols)},
             {"conversations": 7, "messages": 6}, [_ep("GET", "/api/messages")])
    assert len(r["findings"]) == 1, r["findings"]
    assert r["findings"][0]["unread"] == "conversations"


def test_an_empty_unread_table_is_not_reported(monkeypatch, tmp_path):
    """A table with no rows hides no content -- the harm is unreachable CONTENT. Carried by
    the row-count comparison rather than a guard of its own: `counts[served] >= 0` is always
    true, so an explicit `rows <= 0` guard could never change an answer and was removed."""
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, {"archive": 8, "videos": 0}, _TWIN_EPS)
    assert r["findings"] == [], r["findings"]


def test_the_unread_table_must_be_the_richer_one(monkeypatch, tmp_path):
    """Served-with-more is the ordinary case: the finding is about content the API cannot
    reach, not about duplication."""
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, {"archive": 30, "videos": 3}, _TWIN_EPS)
    assert r["findings"] == [], r["findings"]


def test_narrow_shapes_do_not_collide(monkeypatch, tmp_path):
    """`video_likes` and `video_saves` really do share `video_id, user_id` -- two join tables
    are not twins in any useful sense, and the column floor keeps the check off them."""
    cols = ["id", "video_id", "user_id", "created_at"]
    r = _run(monkeypatch, tmp_path, {"video_likes": _m(cols), "video_saves": _m(cols)},
             {"video_likes": 15, "video_saves": 2}, [_ep("GET", "/api/video_saves")])
    assert r["findings"] == [], r["findings"]


def test_an_audit_that_could_not_measure_says_so(monkeypatch, tmp_path):
    """★ #1202z5, the same lesson one module over: `count: 0` from an audit that inspected
    nothing must not read as clean."""
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, {}, _TWIN_EPS)
    assert r["measured"] is False
    assert "live row counts" in r["why"], r
    assert r["findings"] == []


def test_a_route_the_resolver_throws_on_is_announced(monkeypatch, tmp_path):
    """★ #883: an empty default born inside a handler is how a check goes quiet. A route the
    resolver could not read might have been the unread table's only GET."""
    import multi_agent.runtime.route_projector as RP

    def _boom(path, models):
        raise RuntimeError("unreadable path")
    monkeypatch.setattr(RP, "_resource_model", _boom)
    r = _run(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS)
    assert "did not resolve" in r["why"], r
    assert r["measured"] is True


def test_a_broken_model_reader_does_not_crash_the_heal_cycle(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise RuntimeError("no orm")
    monkeypatch.setattr(BA, "_models_919", _boom)
    monkeypatch.setattr(SA, "_project_root_1202dj", lambda p: tmp_path)
    r = HP._unreachable_twin_tables_1202zb(tmp_path, _Reg(_TWIN_EPS))
    assert r["measured"] is False and r["findings"] == []


# ── the reporting half ────────────────────────────────────────────────────────────

def _report(monkeypatch, tmp_path, models, counts, eps, wh=None):
    monkeypatch.setattr(BA, "_models_919", lambda *a, **k: (models, {}))
    monkeypatch.setattr(SA, "recent_live_counts_1202dj", lambda *a, **k: dict(counts))
    monkeypatch.setattr(SA, "_project_root_1202dj", lambda p: tmp_path)
    wh = wh if wh is not None else _WH()
    HP._report_unreachable_twins_1202zb(_Orch(wh), tmp_path, _Reg(eps))
    return wh


def test_a_task_is_filed_for_the_backend(monkeypatch, tmp_path):
    wh = _report(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS)
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "backend"
    assert wh.created[0]["priority"] == "P1", "a task, not a blocker"


def test_the_task_names_the_instance(monkeypatch, tmp_path):
    """#983: a finding that reports only a count cannot be acted on."""
    d = _report(monkeypatch, tmp_path, _TWIN_MODELS,
                _TWIN_COUNTS, _TWIN_EPS).created[0]["description"]
    for piece in ("`videos`", "35", "`archive`", "8", "/api/archive"):
        assert piece in d, (piece, d)


def test_the_task_says_not_to_copy_rows(monkeypatch, tmp_path):
    """The obvious fix a lane reaches for is the wrong one -- #1202uu's demo top-up copied
    one creator's videos under another's name, and two sources of truth for the same content
    is how that happened."""
    d = _report(monkeypatch, tmp_path, _TWIN_MODELS,
                _TWIN_COUNTS, _TWIN_EPS).created[0]["description"]
    assert "Do NOT copy rows" in d, d


def test_the_artifact_carries_the_finding(monkeypatch, tmp_path):
    """#947: a measurement that exists only in a log line is not a measurement."""
    _report(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS)
    p = tmp_path / "logs" / "unreachable_twin_table_1202zb.jsonl"
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    assert rec["measured"] is True and rec["count"] == 1
    assert rec["findings"][0]["unread"] == "videos"


def test_nothing_is_filed_when_nothing_is_found(monkeypatch, tmp_path):
    wh = _report(monkeypatch, tmp_path, _TWIN_MODELS, {"videos": 3, "feed": 30}, _TWIN_EPS)
    assert wh.created == []
    assert not (tmp_path / "logs" / "unreachable_twin_table_1202zb.jsonl").exists()


def test_an_open_task_is_not_cloned(monkeypatch, tmp_path):
    """#794: a run has hundreds of heal cycles."""
    wh = _WH([{"title": "Seeded rows no endpoint reads, beside an identical table the API "
                        "serves (1)", "status": "in_progress"}])
    _report(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS, wh=wh)
    assert wh.created == [], wh.created


def test_a_completed_task_does_not_suppress_a_new_one(monkeypatch, tmp_path):
    wh = _WH([{"title": "Seeded rows no endpoint reads, beside an identical table the API "
                        "serves (1)", "status": "completed"}])
    _report(monkeypatch, tmp_path, _TWIN_MODELS, _TWIN_COUNTS, _TWIN_EPS, wh=wh)
    assert len(wh.created) == 1


def test_a_missing_workhub_is_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(BA, "_models_919", lambda *a, **k: (_TWIN_MODELS, {}))
    monkeypatch.setattr(SA, "recent_live_counts_1202dj", lambda *a, **k: dict(_TWIN_COUNTS))
    monkeypatch.setattr(SA, "_project_root_1202dj", lambda p: tmp_path)

    class _NoHub:
        hubs = None
    HP._report_unreachable_twins_1202zb(_NoHub(), tmp_path, _Reg(_TWIN_EPS))   # must not raise
    assert (tmp_path / "logs" / "unreachable_twin_table_1202zb.jsonl").exists(), \
        "the artifact must land even when no hub can take the task"


def test_the_unmeasured_case_is_announced_not_silent(monkeypatch, tmp_path):
    """It must not append a line per heal cycle (a run has hundreds) and it must not say
    nothing either -- `warn_once_1201` is the repo's answer to exactly that."""
    seen = []
    import multi_agent.runtime.message_format as MF
    monkeypatch.setattr(MF, "warn_once_1201",
                        lambda key, msg, exc=None: seen.append((key, msg)))
    wh = _report(monkeypatch, tmp_path, _TWIN_MODELS, {}, _TWIN_EPS)
    assert wh.created == []
    assert not (tmp_path / "logs" / "unreachable_twin_table_1202zb.jsonl").exists()
    assert any("1202zb" in k for k, _ in seen), seen


def test_the_caller_is_wired_and_fed_the_registry():
    """★ Three properties, because I have repeatedly tested a helper and not its caller: the
    reporter is called exactly once from `HealPipeline`, it is fed `out_dir` and
    `registryhub` (not the neighbouring `_ea` dict), and it does not sit behind a branch --
    a cycle whose only finding is a twin table would otherwise never reach it."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(HP.HealPipeline).lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_report_unreachable_twins_1202zb"]
    assert len(calls) == 1, "called %d times" % len(calls)
    names = [getattr(a, "id", "") for a in calls[0].args]
    assert "out_dir" in names and "registryhub" in names, ast.dump(calls[0])[:200]
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            raise AssertionError("the call sits behind a branch: %s"
                                 % ast.dump(node.test)[:140])
