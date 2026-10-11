"""#1203hr — the framework asked the filer to declare a recurrence it cannot see.

`parent_bug_id` has said "Set if this is a recurrence of an earlier bug" since this tool
existed. MEASURED over every `workhub_tasks.json` on disk, grouping by the (path, status)
a title names and excluding `registryhub_breaking_change`: 325 times a task was filed for a
symptom an earlier task had already been marked `completed` for. The field was set on 23 of
them and on **0 of the 6 in r170+**, where the new task carried neither the field nor any
mention in its title or body.

r178 is the cost. `GET /api/feed/foryou returns 500 during api_smoke and business_chain
validation` was completed by backend at 1791714717; `GET /api/feed/foryou returns 500
during api_smoke` was filed 3813s later, completed 57s after that, and the run aborted on
that same symptom after 33 ticks, $339.72, zero delivery. In the hour between, the backend
called `test_api` 80 times and made ONE write — to a different file than the traceback named.

Projected as it would actually run (each candidate sees only tasks created-and-completed
before it): r170+ 12 of 43 groupable tasks gain the note, r150-169 29 of 94.
"""

import types

import pytest

from env_generator.llm_generator.tools.bug_tools import (
    _symptom_key_1203hr,
    prior_fix_claim_1203hr,
)


class _Store:
    def __init__(self, d):
        self.d = d

    def value(self):
        return self.d


class _WH:
    def __init__(self, d):
        self.stores = types.SimpleNamespace(tasks=_Store(d))


def _task(title, status="completed", assignee="backend", when=100.0, source=None):
    t = {"title": title, "status": status, "assignee": assignee, "completed_at": when}
    if source:
        t["metadata"] = {"source": source}
    return t


# --- the key -------------------------------------------------------------------------

def test_the_key_is_path_and_status():
    assert _symptom_key_1203hr(
        "GET /api/feed/foryou returns 500 during api_smoke") == ("/api/feed/foryou", "500")


def test_a_numeric_path_segment_is_normalised():
    a = _symptom_key_1203hr("POST /api/videos/35/comments returns 404")
    b = _symptom_key_1203hr("POST /api/videos/2/comments returns 404")
    assert a == b == ("/api/videos/{}/comments", "404"), (a, b)


def test_a_title_with_no_endpoint_or_no_code_has_no_key():
    assert _symptom_key_1203hr("Frontend build fails: npm run build returns code 1") is None
    assert _symptom_key_1203hr("GET /api/feed/foryou is slow") is None
    assert _symptom_key_1203hr("") is None
    assert _symptom_key_1203hr(None) is None


# --- the lookup ----------------------------------------------------------------------

def test_r178s_symptom_finds_the_task_that_claimed_it_fixed():
    """The live pair, verbatim."""
    hub = _WH({
        "task_e1e04da9c2": _task(
            "GET /api/feed/foryou returns 500 during api_smoke and business_chain validation",
            when=1791714717.0),
    })
    got = prior_fix_claim_1203hr(hub, "GET /api/feed/foryou returns 500 during api_smoke")
    assert got is not None, "the earlier claim was not found"
    assert got[0] == "task_e1e04da9c2" and got[1] == "backend", got


def test_an_unfinished_earlier_task_is_not_a_fix_claim():
    """★ The point is that someone SAID it was fixed. A pending one has said nothing."""
    for status in ("pending", "in_progress", "cancelled", "failed"):
        hub = _WH({"t1": _task("GET /api/x returns 500", status=status)})
        assert prior_fix_claim_1203hr(hub, "GET /api/x returns 500") is None, status


def test_breaking_change_churn_is_excluded():
    """Those recur by construction from transient registry states — a separate, measured
    story — and they would otherwise drown the signal."""
    hub = _WH({"t1": _task("Fix breaking change in GET /api/x: removed a, b 500",
                           source="registryhub_breaking_change")})
    assert prior_fix_claim_1203hr(hub, "GET /api/x returns 500") is None


def test_a_different_symptom_is_not_matched():
    hub = _WH({"t1": _task("GET /api/other returns 500"),
               "t2": _task("GET /api/x returns 404")})
    assert prior_fix_claim_1203hr(hub, "GET /api/x returns 500") is None


def test_the_most_recent_claim_wins():
    hub = _WH({"old": _task("GET /api/x returns 500", assignee="verifier", when=10.0),
               "new": _task("GET /api/x returns 500", assignee="backend", when=900.0)})
    got = prior_fix_claim_1203hr(hub, "GET /api/x returns 500")
    assert got[0] == "new" and got[1] == "backend", got


def test_it_never_raises_and_never_blocks_a_filing():
    class _Boom:
        @property
        def stores(self):
            raise RuntimeError("hub unreadable")
    assert prior_fix_claim_1203hr(_Boom(), "GET /api/x returns 500") is None
    assert prior_fix_claim_1203hr(None, "GET /api/x returns 500") is None
    assert prior_fix_claim_1203hr(_WH({"_meta": {"version": 1}}),
                                  "GET /api/x returns 500") is None


# --- the note reaches the task body and the field --------------------------------------

def test_the_create_path_attaches_the_note_and_fills_the_slot():
    """Structural: the helper must be called on the filing path, its result must reach
    `description`, and `parent_bug_id` must be set when the filer left it empty."""
    import ast
    import inspect
    from env_generator.llm_generator.tools import bug_tools as _bt
    tree = ast.parse(inspect.getsource(_bt))
    runs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_run"]
    hit = [n for n in runs if "prior_fix_claim_1203hr" in ast.unparse(n)]
    assert len(hit) == 1, [n.name for n in runs]
    body = ast.unparse(hit[0])
    assert "ALREADY MARKED FIXED ONCE IN THIS RUN" in body, body[-800:]
    assert "parent_bug_id = _pid" in body, body[-800:]
    # the note must be appended to the description, not replace it
    assert "str(description or '').rstrip()" in body or \
           'str(description or "").rstrip()' in body, body[-800:]


def test_the_note_says_what_to_check_not_just_that_it_recurred():
    import inspect
    from env_generator.llm_generator.tools import bug_tools as _bt
    src = inspect.getsource(_bt)
    i = src.index("ALREADY MARKED FIXED ONCE IN THIS RUN")
    note = src[i:src.index("#1203hr\"", i)]
    assert "read" in note and "edited" in note, note


# ------------- #1203hs: the same key, reachable 4x more often --------------------------
#
# #1203hr keys on the (path, status) a TITLE names. MEASURED over the 1980 bug tasks in every
# `workhub_tasks.json` since r150: that shape is in 121 of them (6%), while
# `bug_artifacts.affected_endpoint` -- handed straight to `bug_create`, and PARSED by the
# framework per its own schema -- is set on 966 (49%), with 848 carrying the endpoint and no
# title key at all. 538 of the 966 also yield a status code. Projected: 80 recurrences the
# title key cannot see, e.g. `POST /api/posts registered implemented …` ->
# `business_chain fails because POST /api/posts …`.

from env_generator.llm_generator.tools.bug_tools import _symptom_key_1203hs


def test_a_title_key_still_wins_when_there_is_one():
    k = _symptom_key_1203hs("GET /api/feed/foryou returns 500 during api_smoke",
                            {"affected_endpoint": "GET /api/other"})
    assert k == ("/api/feed/foryou", "500"), k


def test_the_endpoint_supplies_the_path_when_the_title_does_not():
    k = _symptom_key_1203hs("Tenant initialization endpoint returns 404 despite registration",
                            {"affected_endpoint": "POST /api/v1/admin/init-tenant"})
    assert k == ("POST /api/v1/admin/init-tenant", "404"), k


def test_actual_supplies_the_code_when_the_title_does_not():
    k = _symptom_key_1203hs("Home feed calls a protected endpoint while logged out",
                            {"affected_endpoint": "GET /api/feed", "actual": "401 Unauthorized"})
    assert k == ("GET /api/feed", "401"), k


def test_expected_is_never_a_code_source():
    """★ `expected: 401` means "it should 401 and does not" — the code is the DEMAND, not
    the symptom. Mixing it with an `actual` code would group "returns 401" with "should
    return 401", which are opposite problems."""
    k = _symptom_key_1203hs("GET /api/me allows unauthenticated access",
                            {"affected_endpoint": "GET /api/me", "expected": "401"})
    assert k is None, k


def test_a_numeric_segment_in_the_endpoint_is_normalised():
    a = _symptom_key_1203hs("broken", {"affected_endpoint": "GET /api/videos/35", "actual": "404"})
    b = _symptom_key_1203hs("broken", {"affected_endpoint": "GET /api/videos/2", "actual": "404"})
    assert a == b == ("GET /api/videos/{}", "404"), (a, b)


def test_no_endpoint_and_no_title_key_is_still_no_key():
    assert _symptom_key_1203hs("Frontend build fails", {}) is None
    assert _symptom_key_1203hs("Frontend build fails", None) is None
    assert _symptom_key_1203hs("Frontend build fails",
                               {"affected_endpoint": "GET /api/x"}) is None


def test_a_code_without_an_endpoint_is_not_a_key():
    """★ Found by mutation: a fixture with no code at all cannot tell a missing endpoint
    from a substituted one — both paths return None for want of a code. The discriminating
    case has a CODE and no endpoint, where a stand-in endpoint would invent a key that
    groups unrelated bugs."""
    assert _symptom_key_1203hs("npm run build exits 500 lines of output", {}) is None
    assert _symptom_key_1203hs("worker crashed, 503 restarts queued",
                               {"affected_files": ["app/worker.py"]}) is None
    assert _symptom_key_1203hs("build fails", {"actual": "500"}) is None


def test_the_lookup_compares_stored_artifacts_too():
    """A stored task's key must be computed the same way, from its own artifacts."""
    hub = _WH({"t1": {"title": "Tenant init endpoint returns 404", "status": "completed",
                      "assignee": "backend", "completed_at": 100.0,
                      "metadata": {"bug_artifacts":
                                   {"affected_endpoint": "POST /api/v1/admin/init-tenant"}}}})
    got = prior_fix_claim_1203hr(
        hub, "Declared tenant init endpoint still 404s",
        {"affected_endpoint": "POST /api/v1/admin/init-tenant", "actual": "404"})
    assert got is not None and got[0] == "t1", got


def test_the_create_path_passes_the_artifacts():
    import ast
    import inspect
    from env_generator.llm_generator.tools import bug_tools as _bt
    tree = ast.parse(inspect.getsource(_bt))
    runs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_run"]
    hit = [n for n in runs if "prior_fix_claim_1203hr" in ast.unparse(n)]
    assert len(hit) == 1
    body = ast.unparse(hit[0])
    assert "prior_fix_claim_1203hr(getattr(self._hubs, 'workhub', None), title, bug_artifacts)" \
        in body.replace("\n", " ").replace("  ", " ") or "bug_artifacts)" in body, body[-400:]
