"""#1202lz — the browser proved a contract gap no source scan can find.

GROUND TRUTH (tiktok-web-r121 resume #3, recorded twice — 11:47:45 and 12:07:38):

    #740 the browser reported 3 distinct uncaught/console error(s) during this capture:
      http: 404 GET http://localhost:8081/api/profiles (on 1 screen(s): (startup));
      console.error: Failed to load resource: ... 404 (Not Found) (on 1 screen(s): (startup));
      http: 404 GET http://localhost:8081/api/profile (on 1 screen(s): (startup))

while the same run's delivery gate reported

    frontend_calls: 11 | frontend_call_unregistered: 0

and its endpoint registry holds NO endpoint with "profile" in it.

`/api/profiles` appears in no frontend source file in that run, and `git log -S "api/profiles"`
finds it in none of the repo's 389 commits.

★ #1203l5-era correction, landed as #1203l7: THE GATE ITSELF ISSUED THAT REQUEST. The same
module's `_PROFILE_DISCOVER_JS` and `_PROFILE_COUNT_JS` fetch `/api/profiles`, `/api/profile`
and `/profiles` to find a profile gate and proceed silently on a miss — "apps with no profile
gate are unaffected" — so the 404 is the designed outcome of the framework's own probe, and it
lands in the console stream this reads. It is in no commit because no lane wrote it. Measured
over every run log on disk: 281 of the 293 warnings this produced named ONLY those three paths
(96%), always "(on (startup))". They are skipped now.

The ground truth above is still the ground truth — it is simply not evidence of contract drift.
What IS: the 12 remaining warnings, `/api/users/1`, `/api/users/1/videos`,
`/api/creators/suggested`, `/api/videos/explore`, `/api/live`. The running BUNDLE calls them;
the SOURCE does not spell them.

The contract-alignment check scans source literals and states one of its blind spots itself
("its extractor recognises `request(...)` and `fetch(...)` only"). This is the other one, and
it cannot state it: no source scan can see a path only the built bundle contains. The live
browser can, and already had — #740 recorded it and then folded it into the screens' visual
DEVIATIONS, which sends the contract question to the frontend lane as a rendering defect.

Reports, never blocks: an /api 404 can be legitimate, and this codebase has paid repeatedly
for turning a best-effort signal into a refusal (#504, r81).
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

_f = vf.api_404s_from_console_1202lz


def test_r121s_own_console_stream():
    """★ The exact messages, verbatim from the run — and #1203l7 moved what they prove.

    This asserted that r121's two paths ARE reported, because they were read as the app's
    drift. They are the GATE's own probe (`_PROFILE_DISCOVER_JS`), so the stream is still the
    ground truth and the verdict on it is now the opposite: skipped, not reported. The
    extractor's actual subject — pulling `/api` paths out of this stream shape — is unchanged,
    because the exclusion lives at the capture choke point where all four consumers inherit it,
    not in this one reader.
    """
    stream = {"(startup)": [
        "http: 404 GET http://localhost:8081/api/profiles",
        "console.error: Failed to load resource: the server responded with a status of 404 (Not Found)",
        "http: 404 GET http://localhost:8081/api/profile",
    ]}
    # The extractor still reports what it is HANDED -- #1032, it has one job. What changed is
    # that in production it is never handed these: `_rec740` drops the gate's own probe 404s
    # at capture, so all four consumers of that stream inherit the exclusion. That behaviour
    # is pinned in test_1203l7_the_gate_reported_its_own_probe.py.
    assert set(_f(stream)) == {"/api/profiles", "/api/profile"}, _f(stream)
    assert _f(stream)["/api/profiles"] == ["(startup)"]

    # the same stream shape with a path the app really failed to serve (r173's) -- this one
    # does survive capture, and is what the check exists for
    real = {"(startup)": ["http: 404 GET http://localhost:8081/api/users/1/videos"]}
    assert _f(real) == {"/api/users/1/videos": ["(startup)"]}


def test_auth_and_oauth_paths_count_too():
    out = _f({"login": ["http: 404 GET http://localhost:8081/auth/logout",
                        "http: 404 POST http://localhost:9000/oauth/token"]})
    assert set(out) == {"/auth/logout", "/oauth/token"}


def test_a_query_string_is_not_a_different_endpoint():
    out = _f({"s": ["http: 404 GET http://localhost:8081/api/videos?limit=12"]})
    assert set(out) == {"/api/videos"}


def test_a_trailing_slash_is_not_a_different_endpoint():
    out = _f({"s": ["http: 404 GET http://localhost:8081/api/videos/"]})
    assert set(out) == {"/api/videos"}


def test_the_same_path_on_several_screens_is_one_entry():
    out = _f({"a": ["http: 404 GET http://localhost:8081/api/feed"],
              "b": ["http: 404 GET http://localhost:8081/api/feed"]})
    assert set(out) == {"/api/feed"}
    assert sorted(out["/api/feed"]) == ["a", "b"]


@pytest.mark.parametrize("msg", [
    "http: 500 GET http://localhost:8081/api/feed",          # not a 404
    "http: 404 GET http://localhost:8081/assets/logo.png",   # not an /api path
    "console.error: Failed to load resource: 404 (Not Found)",  # no URL to attribute
    "TypeError: (void 0) is not a function",
])
def test_what_must_not_be_reported_as_contract_drift(msg):
    assert _f({"s": [msg]}) == {}, msg


@pytest.mark.parametrize("junk", [None, "", 42, [], {"s": None}, {"s": [None]}])
def test_it_never_raises(junk):
    assert isinstance(_f(junk), dict)


# ------------------------------------------------------------------ the wiring

def test_it_is_named_as_contract_drift_not_a_rendering_defect():
    src = inspect.getsource(vf)
    i = src.index("#1202lz the browser called")
    msg = src[i:src.index('",', i)]
    assert "frontend↔contract drift" in msg
    assert "not a rendering defect" in msg
    assert "cannot see it" in msg


def test_it_reaches_the_artifact():
    """★ CORRECTED (#1202mf): asserting the source line that sets the key on the RETURNED dict
    proved nothing — `_persist_verdict` builds verdict.json separately and never saw it."""
    import ast
    src = inspect.getsource(vf.run_visual_fidelity)
    calls = [ast.unparse(n) for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_persist_verdict"]
    assert calls, "the persist call moved"
    assert "api_404s_1202lz=" in calls[0], (
        "the static extractor cannot produce this list — the WRITER must be handed it")


def test_it_is_computed_before_740_folds_the_stream():
    """#740 routes every console error into the screens' visual deviations; the /api 404s
    must be named as themselves first."""
    src = inspect.getsource(vf)
    assert src.index("_api404_1202lz = api_404s_from_console_1202lz") < src.index(
        "_by740 = _group_console_errors_740")


def test_it_does_not_block():
    """★ #504/r81: a best-effort signal turned into a refusal is a false blocker."""
    src = inspect.getsource(vf)
    i = src.index("#1202lz the browser called")
    window = src[i:src.index("_by740 = _group_console_errors_740")]
    assert "passed" not in window.replace("passed, not blocked", "")
    assert "Reported, not blocked" in window
