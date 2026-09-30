"""#1202fr -- when a critical UI flow fails, say whether the CONTRACT marks one of the
endpoints that page declares as auth_required.

#320 already names this class in backend_skeleton: an explicit `auth_required: false` is
"the lane's deliberate 'this read is public' declaration (r88/r89's PUBLIC-FEED WEDGE)".
The declaration exists; nothing said when the wedge had happened. tiktok-r96 set
auth_required: true on GET /api/videos — the only feed endpoint — and the logged-out
landing page could never render. 4 of that run's 12 failing flows, rediscovered by browser
walk each time and reported as "the page did not work", while the route is
framework-projected and only the contract could change.

Reports, never blocks: an app whose entry is a login screen legitimately serves an
authenticated feed, and deciding that from a route shape would be a guess.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.deliverability import _auth_wedge_note_1202fr  # noqa: E402

PAGES = {
    "feed": {"name": "fyp_feed_logged_out", "route": "/",
             "apis_used": ["GET /api/videos", "POST /api/videos/{id}/like"]},
    "explore": {"name": "explore_grid", "route": "/explore",
                "apis_used": ["GET /api/explore"]},
}
ENDPOINTS = {
    "GET /api/videos": {"method": "GET", "path": "/api/videos",
                        "schema": {"auth_required": True}},
    "GET /api/explore": {"method": "GET", "path": "/api/explore",
                         "schema": {"auth_required": False}},
    "POST /api/videos/{id}/like": {"method": "POST", "path": "/api/videos/{id}/like",
                                   "schema": {"auth_required": True}},
}


class _Reg:
    def __init__(self, pages=PAGES, eps=ENDPOINTS):
        self._p, self._e = pages, eps

    def list_ui_pages(self):
        return self._p

    def get_endpoints(self):
        return self._e


class _Hubs:
    def __init__(self, **kw):
        self.registryhub = _Reg(**kw)


def test_names_the_page_and_the_endpoint():
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"])
    assert "fyp_feed_logged_out" in note and "GET /api/videos" in note, note


def test_silent_when_the_failing_flow_uses_only_public_endpoints():
    assert _auth_wedge_note_1202fr(_Hubs(), ["explore_grid"]) == ""


def test_silent_when_nothing_failed():
    assert _auth_wedge_note_1202fr(_Hubs(), []) == ""
    assert _auth_wedge_note_1202fr(_Hubs(), None) == ""


def test_only_failing_flows_are_annotated():
    """It must not lecture about pages the run has no complaint about."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["explore_grid"])
    assert "fyp_feed_logged_out" not in note


def test_reports_a_condition_not_a_verdict():
    """#1114/#1023: a flow that authenticates first never sees the 401, so this must read
    as evidence, not as a diagnosis."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"]).lower()
    assert "anonymous visitor" in note
    for asserted in ("contract cause", "the cause is", "because the contract"):
        assert asserted not in note, f"states a verdict: {asserted!r}"


def test_carries_neither_gate_anchor_phrase():
    """The text is appended after the anchored blocker prefix that
    orchestrator._validate_delivery_gate canonicalises on."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"]).lower()
    assert "ui flow(s) failed" not in note and "ui flow(s) missing" not in note


def test_auth_required_read_from_any_of_the_three_spellings():
    for shape in ({"auth_required": True},
                  {"schema": {"auth_required": True}},
                  {"metadata": {"auth_required": True}}):
        eps = {"GET /api/videos": dict(shape, method="GET", path="/api/videos")}
        note = _auth_wedge_note_1202fr(_Hubs(eps=eps), ["fyp_feed_logged_out"])
        assert "GET /api/videos" in note, f"missed the {shape} spelling"


def test_registry_hiccup_degrades_to_empty_not_to_a_raise():
    class _Bad:
        def list_ui_pages(self):
            raise RuntimeError("hub down")

        def get_endpoints(self):
            return {}

    hubs = _Hubs()
    hubs.registryhub = _Bad()
    assert _auth_wedge_note_1202fr(hubs, ["fyp_feed_logged_out"]) == ""


# ── #1202zr: a WRITE is not "a read that is meant to be public" ───────────────────
#
# #1202qk already carved one hole in this advice for the same reason -- "tiktok-r127's note told
# the lanes to declare `/auth/me` auth_required=false: advice that would publish a 'who am I'
# endpoint". The METHOD is the other hole. r136 and r138 were told, verbatim, that
# `fyp_feed_logged_out -> POST /api/videos/{video_id}/like` is fixed by declaring
# `auth_required=false` "for a read that is meant to be public" -- and a lane that does that lets
# any anonymous visitor like and comment.
#
# MEASURED over every Contract note in the corpus: 390 named endpoints, 86 of them writes (78
# POST, 8 DELETE) across 6 runs including r136 and r138. By distinct note, 35 of 45 are read-only
# and keep their sentence byte for byte, 9 are write-only and 1 is mixed.

from multi_agent.runtime.deliverability import _hit_is_write_1202zr as _isw  # noqa: E402

_WRITE_PAGES = {
    "feed": {"name": "fyp_feed_logged_out", "route": "/",
             # the write FIRST, because the note reports `bad[0]` per page
             "apis_used": ["POST /api/videos/{id}/like", "GET /api/videos"]},
}
_READ_PAGES = {
    "feed": {"name": "fyp_feed_logged_out", "route": "/",
             "apis_used": ["GET /api/videos"]},
}


def _note(pages, failed=("fyp_feed_logged_out",)):
    return _auth_wedge_note_1202fr(_Hubs(pages=pages), list(failed))


def test_a_write_is_not_offered_as_a_public_read():
    """★ The whole point: the sentence that would open an anonymous write must not appear."""
    n = _note(_WRITE_PAGES)
    assert "POST /api/videos/{id}/like" in n, n
    assert "declare auth_required=false" not in n, n


def test_a_write_says_where_the_fix_actually_is():
    n = _note(_WRITE_PAGES)
    assert "name a WRITE" in n, n
    assert "sign in before" in n or "should not declare" in n, n
    assert "any anonymous visitor perform the action" in n, n


def _hubs_with_public_spec(tmp_path, pages):
    """★ The first version of the test below asserted `"PUBLIC content" not in note` against a
    registry with no `base_dir`, so `_root_spec_entities_1202gl` returned [] and the sentence
    could never have appeared for ANY input -- appending it unconditionally left the test green.
    #1202gl reads `<project>/design/reference_spec.json` through `base_dir`, which points at
    `<project>/shared`, so the fixture has to lay that out on disk."""
    import json as _json
    proj = tmp_path / "proj"
    (proj / "design").mkdir(parents=True)
    (proj / "shared").mkdir()
    (proj / "design" / "reference_spec.json").write_text(_json.dumps(
        {"entities": [{"name": "videos", "visibility": "public"},
                      {"name": "comments", "visibility": "public"}]}), encoding="utf-8")
    h = _Hubs(pages=pages)
    # `_root_spec_entities_1202gl(hub_registry)` reads `base_dir` off the OUTER object, not off
    # `.registryhub` -- the first draft set it on the inner one and the sentence stayed absent.
    h.base_dir = str(proj / "shared")
    return h


def test_the_materials_sentence_reaches_a_read(tmp_path):
    """Pins the fixture's own premise: with the spec on disk the sentence DOES appear, so its
    absence on a write below is a choice and not a missing file."""
    h = _hubs_with_public_spec(tmp_path, _READ_PAGES)
    n = _auth_wedge_note_1202fr(h, ["fyp_feed_logged_out"])
    assert "PUBLIC content" in n, n
    assert "videos" in n, n


def test_the_materials_sentence_is_withheld_from_a_write(tmp_path):
    """"the materials declare videos as PUBLIC content" is about who may READ those rows;
    appended to a write it argues for the change that must not be made."""
    h = _hubs_with_public_spec(tmp_path, _WRITE_PAGES)
    n = _auth_wedge_note_1202fr(h, ["fyp_feed_logged_out"])
    assert "name a WRITE" in n, n
    assert "PUBLIC content" not in n, n


def test_a_read_only_note_is_unchanged():
    """★ Regression guard for the 78% of notes this must not touch."""
    n = _note(_READ_PAGES)
    assert "declare auth_required=false for a read that is meant to be public (#320)" in n, n
    assert "name a WRITE" not in n, n


def test_a_mixed_set_carries_both_sentences():
    """Two flows, one bad read and one bad write: the reader needs both instructions, and
    neither may be dropped because the other applies."""
    pages = {
        "feed": {"name": "fyp_feed_logged_out", "route": "/",
                 "apis_used": ["POST /api/videos/{id}/like"]},
        "explore": {"name": "explore_grid", "route": "/explore",
                    "apis_used": ["GET /api/videos"]},
    }
    n = _auth_wedge_note_1202fr(_Hubs(pages=pages),
                                ["fyp_feed_logged_out", "explore_grid"])
    assert "declare auth_required=false" in n, n
    assert "name a WRITE" in n, n


def test_the_condition_still_lists_every_hit():
    """#1114/#1023: the note reports the CONDITION. Both halves are still named up front,
    whatever advice follows."""
    n = _note(_WRITE_PAGES)
    head = n.split("declare auth_required")[0].split("name a WRITE")[0]
    assert "returns 401 to an anonymous visitor" in head, head
    assert "POST /api/videos/{id}/like" in head, head


# ── the method parser ─────────────────────────────────────────────────────────────

def test_every_write_method_counts():
    for m in ("POST", "PUT", "PATCH", "DELETE", "post", "Delete"):
        assert _isw("flow -> %s /api/x" % m), m


def test_a_get_is_not_a_write():
    assert not _isw("flow -> GET /api/x")


def test_a_bare_path_keeps_todays_advice():
    """`apis_used` carries both `"POST /api/x"` and a bare `"/api/x"` in the corpus. With no
    method the note has always assumed a read; guessing otherwise would put the new sentence on
    an entry nobody can classify."""
    assert not _isw("flow -> /api/x")
    assert not _isw("flow -> ")
    assert not _isw("")
    assert not _isw(None)


# ── #1202zr: the OTHER channel that gives a lane this advice ──────────────────────
#
# A lane reads two things about a 401 it cannot clear: the blocker prose above, and the
# remediation task body `remediation_dispatcher` files for it. Only ONE of them was fixed first,
# and #1202zr's whole point is that the advice was wrong -- so leaving the second reader saying
# "to make an endpoint public, change its CONTRACT" unqualified is worse than fixing neither:
# the two channels would disagree about what is safe, and the lane would have a citation for the
# change that must not be made. Of the 38 `_GATE_OWNER` bodies, exactly one carries this advice.


def _guard_tampering_body():
    import ast
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
         / "multi_agent" / "runtime" / "remediation_dispatcher.py")
    src = p.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if getattr(t, "id", None) != "_GATE_OWNER":
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for k, v in zip(node.value.keys, node.value.values):
                if getattr(k, "value", None) == "deliverability_guard_tampering":
                    return " ".join(str(x) for x in ast.literal_eval(v))
    raise AssertionError("the guard_tampering owner row is gone")


def test_the_task_body_still_says_to_fix_the_contract():
    """Pins the premise: the advice IS there, so the caveat below is guarding something."""
    b = _guard_tampering_body()
    assert "change its CONTRACT" in b, b[-300:]
    assert "never edit the guard" in b, b[-300:]


def test_the_task_body_carries_the_write_caveat():
    b = _guard_tampering_body()
    assert "POST/PUT/PATCH/DELETE" in b, b[-300:]
    assert "anonymous visitor perform the action" in b, b[-300:]


def test_both_channels_say_the_same_thing():
    """★ #1032: one evidence store read by two consumers that each implemented half the rules is
    the shape this codebase keeps finding. The shared phrase is asserted in BOTH so a future edit
    to either cannot quietly drop it from one."""
    note = _note(_WRITE_PAGES)
    body = _guard_tampering_body()
    phrase = "anonymous visitor perform the action"
    assert phrase in note, note
    assert phrase in body, body[-300:]
