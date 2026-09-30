"""#1202w0: a list endpoint that advertises a `total` its own pagination cannot reach.

Found by probing the stacks of DELIVERED runs that are still up. Two of the nine public list
endpoints across them break it, and both shipped:

    tiktok-r135  GET /api/feed/foryou         total=39  reachable=8   (the app's FRONT PAGE)
    tiktok-r126  GET /api/creators/suggested  total=92  reachable=20

Two different root causes — r135's handler INNER JOINs a table whose FK the dataset left NULL
(#1202vz), r126's `next_cursor` never advances and its `cursor`/`offset` params are ignored —
and ONE observable invariant. Neither app said a word about it.

REPORTED, NOT BLOCKED, on #1202uv's precedent: nine endpoints is a small sample, and a `total`
that legitimately counts a broader set than it pages would be a false positive. The log makes
the next runs the evidence for whether this earns a check.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import validation_runner as VR      # noqa: E402

_F = VR._list_total_unreachable_1202w0


def _pages(monkeypatch, pages):
    """Serve `pages` (a list of dicts) in order for every cursor GET."""
    seq = list(pages)

    def fake(method, url, **kw):
        body = seq.pop(0) if seq else {"items": []}
        return {"status": 200, "error": None, "body_text": json.dumps(body), "headers": {}}

    monkeypatch.setattr(VR, "_http", fake)


def test_a_cursor_that_never_advances_is_its_own_dead_end(monkeypatch):
    """r126's shape: 20 of 92, and `next_cursor` is None from the first page."""
    _pages(monkeypatch, [])
    got = _F("http://x", "/api/list", None,
             json.dumps({"items": list(range(20)), "total": 92, "next_cursor": None}))
    assert got == "/api/list total=92 reachable=20"


def test_a_walk_that_ends_short_is_reported(monkeypatch):
    """r135's shape: the cursor advances, then stops well before `total`."""
    _pages(monkeypatch, [{"items": list(range(3)), "total": 39, "next_cursor": None}])
    got = _F("http://x", "/api/feed", None,
             json.dumps({"items": list(range(5)), "total": 39, "next_cursor": "5"}))
    assert got == "/api/feed total=39 reachable=8"


def test_a_complete_walk_is_silent(monkeypatch):
    _pages(monkeypatch, [{"items": list(range(4)), "total": 9, "next_cursor": None}])
    assert _F("http://x", "/api/list", None,
              json.dumps({"items": list(range(5)), "total": 9, "next_cursor": "5"})) == ""


def test_a_single_full_page_is_silent(monkeypatch):
    _pages(monkeypatch, [])
    assert _F("http://x", "/api/list", None,
              json.dumps({"items": [1, 2], "total": 2})) == ""


def test_an_unfinished_walk_says_nothing(monkeypatch):
    """The cap exists to bound cost, so hitting it means the walk is INCONCLUSIVE. Reporting
    there would turn a large collection into a false accusation."""
    _pages(monkeypatch, [{"items": [1], "total": 10_000, "next_cursor": str(i)}
                         for i in range(VR._PAGE_WALK_CAP_1202W0 + 5)])
    assert _F("http://x", "/api/list", None,
              json.dumps({"items": [1], "total": 10_000, "next_cursor": "1"})) == ""


def test_a_body_that_is_not_a_counted_list_is_ignored(monkeypatch):
    _pages(monkeypatch, [])
    for body in ("not json", "[]", json.dumps({"items": [1]}), json.dumps({"total": 5})):
        assert _F("http://x", "/api/x", None, body) == "", body


def test_a_boolean_is_not_a_count(monkeypatch):
    """`True` is an int in Python. With zero items it would read as `total=1 reachable=0` and
    accuse an endpoint that never claimed a count."""
    _pages(monkeypatch, [])
    assert _F("http://x", "/api/x", None,
              json.dumps({"items": [], "total": True})) == ""


def test_a_cursor_that_repeats_itself_stops_the_walk(monkeypatch):
    """A handler that echoes the same cursor forever must not be walked forever. The page
    below always has rows and always the SAME cursor, so only the equality check ends it."""
    def fake(method, url, **kw):
        return {"status": 200, "error": None, "headers": {},
                "body_text": json.dumps({"items": [1], "total": 50, "next_cursor": "5"})}

    monkeypatch.setattr(VR, "_http", fake)
    got = _F("http://x", "/api/list", None,
             json.dumps({"items": [1], "total": 50, "next_cursor": "5"}))
    assert got == "/api/list total=50 reachable=2", (
        "the walk must stop at the repeated cursor and report what it reached")


def test_it_runs_on_the_probe_that_already_has_the_response():
    """AST (#943): the check must ride the existing 2xx, not add a probe pass of its own."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(VR)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "_shape_violation" in ast.unparse(n)
              and "business_endpoints_reachable" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "_list_total_unreachable_1202w0" in body
    assert "#1202w0" in inspect.getsource(VR)


def test_the_finding_reaches_an_artifact_not_only_a_log(tmp_path):
    """#947's rule, which caught the first version of this fix: "a measurement that exists
    only in a log line is not a measurement." It lands the same way its sibling #1202uv does
    — its own jsonl under the run's `logs/` — so holding the artifacts means holding the
    finding, without it becoming a blocker on nine endpoints of evidence."""
    import json as _j

    assert VR.record_list_total_unreachable_1202w0(tmp_path, ["/api/x total=9 reachable=2"])
    f = tmp_path / "logs" / "list_total_unreachable_1202w0.jsonl"
    rec = _j.loads(f.read_text().strip())
    assert rec["count"] == 1 and rec["endpoints"] == ["/api/x total=9 reachable=2"]
    # nothing found -> no file, the same guard #1202uv uses
    assert not VR.record_list_total_unreachable_1202w0(tmp_path, [])


def test_the_reporting_path_writes_the_artifact():
    """AST (#943): the warning and the artifact must be written from the same branch, or the
    log keeps saying something the files never show."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(VR)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "_unreachable_totals_1202w0" in ast.unparse(n)
              and "business_endpoints_reachable" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "record_list_total_unreachable_1202w0(project_dir, _unreachable_totals_1202w0)" in body


def test_it_reports_and_does_not_block():
    """#1202uv's precedent. A check would block delivery on nine endpoints of evidence; this
    logs instead, and the next runs decide whether it earns one."""
    import ast
    import inspect

    src = inspect.getsource(VR)
    tree = ast.parse(src)
    emitted = {n.args[0].value
               for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_add" and n.args
               and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    assert not any("1202w0" in e for e in emitted), (
        "this must not emit a gate check yet — see the note on the helper")
    assert "#1202w0 %d list endpoint(s)" in src, "it must still SAY what it found"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── #1202zp: the other direction — a `total` that UNDER-reports ───────────────────
#
# The early return `if total <= len(items)` could not see it, so an endpoint whose `total` is
# really its PAGE SIZE passed as clean. Probed live against the delivered stacks still up
# (2026-09-29), both of which shipped:
#
#   r139 GET /api/videos/feed  total=5 items=5 next_cursor=5      -> the walk reaches 35
#        distinct ids and `videos` holds 35. A UI trusting `total` renders "5".
#   r132 GET /api/videos/feed  total=5 items=5 next_cursor=<ts>   -> page 2 comes back EMPTY
#        while `videos` holds 78. BOTH numbers are wrong, so the old total-vs-reachable
#        comparison agreed with itself and said nothing.
#
# ★ WHY NOT COMPARE `total` TO THE TABLE'S ROW COUNT, which is where I started: a per-user or
# published-only collection legitimately counts fewer rows than its table, so that predicate
# lands squarely in the false-positive class. "You have seen the total" beside "here is the
# next page" is incoherent whatever the collection filters, and costs no request.


def _no_http(monkeypatch):
    """The new direction must decide from the response already in hand."""
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        return {"status": 200, "error": None, "body_text": '{"items": []}', "headers": {}}

    monkeypatch.setattr(VR, "_http", fake)
    return calls


def test_r139_s_shape_total_equals_the_page_while_a_next_page_is_offered(monkeypatch):
    calls = _no_http(monkeypatch)
    got = _F("http://x", "/api/videos/feed", None,
             json.dumps({"items": list(range(5)), "total": 5, "next_cursor": 5}))
    assert "total=5 is not the collection size" in got, got
    assert "next_cursor=5" in got, got
    assert calls == [], "the check must cost no request: %r" % calls


def test_r132_s_shape_a_timestamp_cursor_counts_too(monkeypatch):
    _no_http(monkeypatch)
    got = _F("http://x", "/api/videos/feed", None,
             json.dumps({"items": list(range(5)), "total": 5,
                         "next_cursor": "2026-02-26T22:16:19+00:00|31"}))
    assert "is not the collection size" in got, got
    assert "2026-02-26T22:16:19" in got, got


def test_a_total_below_the_page_is_caught_too(monkeypatch):
    """Stronger than equal: `total` smaller than what this very page carries."""
    _no_http(monkeypatch)
    got = _F("http://x", "/api/list", None,
             json.dumps({"items": list(range(9)), "total": 2, "next_cursor": "9"}))
    assert "total=2 is not the collection size" in got, got


def test_a_full_page_with_no_next_page_stays_silent(monkeypatch):
    """★ The legitimate reading of the same numbers, and the reason the cursor is the whole
    signal: total == items and nothing on offer means the caller really has seen everything."""
    _no_http(monkeypatch)
    for cur in (None, "", 0, False):
        body = {"items": [1, 2], "total": 2}
        if cur is not None:
            body["next_cursor"] = cur
        assert _F("http://x", "/api/list", None, json.dumps(body)) == "", repr(cur)


def test_a_boolean_cursor_is_not_a_next_page(monkeypatch):
    """`True` is not a cursor anyone can follow; treating it as one would report an endpoint
    that only carries a has_more flag it spelled oddly."""
    _no_http(monkeypatch)
    assert _F("http://x", "/api/list", None,
              json.dumps({"items": [1, 2], "total": 2, "next_cursor": True})) == ""


def test_the_over_reporting_direction_is_untouched(monkeypatch):
    """★ Regression guard: r135's shape must still take the walk, not the new branch."""
    _pages(monkeypatch, [{"items": list(range(3)), "total": 39, "next_cursor": None}])
    got = _F("http://x", "/api/feed/foryou", None,
             json.dumps({"items": list(range(5)), "total": 39, "next_cursor": "5"}))
    assert got == "/api/feed/foryou total=39 reachable=8", got
