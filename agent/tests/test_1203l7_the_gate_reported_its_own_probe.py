r"""#1203l7: the gate reported its own probe as the app's contract drift, 96% of the time.

`#1202lz` reads the browser console for `/api` 404s and warns that "the browser called N /api
path(s) this app does NOT serve ... This is frontend-contract drift". Its own docstring
recorded the part it could not explain:

    `/api/profiles` appears NOWHERE in that run's frontend source, and `git log -S` finds it
    in none of the repo's 389 commits

The answer is in the same module. `_PROFILE_DISCOVER_JS` and `_PROFILE_COUNT_JS` fetch
`/api/profiles`, `/api/profile` and `/profiles` to find a profile gate, and proceed silently
on a miss -- the comment above them says so: "apps with no profile gate are unaffected". So
the 404 is the designed outcome of the gate's own request, and it lands in the same console
stream the warning reads. It is in no commit because no lane wrote it.

MEASURED over every run log on disk: 293 occurrences of the warning, of which **281 (96%)
name ONLY those three paths**, always "(on (startup))" -- before any screen. The 12 that
carry anything else are the signal the check exists for: `/api/users/1`,
`/api/users/1/videos`, `/api/creators/suggested`, `/api/videos/explore`, `/api/live`.

THE FILTER IS AT THE CAPTURE CHOKE POINT, not in that one warning, and the first version of
this ticket got that wrong. `#1202lz`'s warning is one of FOUR consumers of the same stream;
the one that reaches the frontend lane is `#740`, which folds every console error into each
screen's deviations -- which is the routing `#1202lz`'s own docstring complains about. Counted
separately: **618 of the 987 distinct #740 segments on disk (63%)** are the probe, diluting
the real crashes 2:1 under a display cap of four (`TypeError: replies.map is not a function`,
`Minified React error #31`, `name.split is not a function`).

Narrowed by SCREEN as well as path: a path cannot tell the gate's request from the app's. All
625 probe-path 404s on disk are on `(startup)` and none on a named screen, so this is
equivalent on the corpus and safer off it. NOT extended to the browser's companion line
("Failed to load resource ... 404", 313 of them, no URL): at startup the app's own bundle
requests run too, and dropping unattributable 404s there would hide a genuinely missing asset.
"""
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import visual_fidelity as VF  # noqa: E402


def _console(path, screen="(startup)"):
    return {screen: ["http: 404 GET http://localhost:8081%s" % path]}


def test_the_predicate_names_the_gates_own_probe():
    for p in VF._PROBE_PATHS_1203L7:
        assert VF.is_own_probe_404_1203l7(
            "(startup)", "http: 404 GET http://localhost:8081%s" % p) is True, p


def test_it_is_narrowed_by_screen_and_by_status():
    """A path alone cannot tell the gate's request from the app's."""
    msg = "http: 404 GET http://localhost:8081/api/profiles"
    assert VF.is_own_probe_404_1203l7("profile_own", msg) is False
    # a 500 on the same path at startup is not the probe's designed miss
    assert VF.is_own_probe_404_1203l7(
        "(startup)", "http: 500 GET http://localhost:8081/api/profiles") is False
    # and a longer path that merely starts the same is a different endpoint
    assert VF.is_own_probe_404_1203l7(
        "(startup)", "http: 404 GET http://localhost:8081/api/profiles/42/edit") is False


def test_the_real_crashes_and_the_unattributable_line_survive():
    """The teeth, and the residue this deliberately does not touch."""
    for t in ("uncaught: TypeError: replies.map is not a function",
              "console.error: Minified React error #31",
              "http: 404 GET http://localhost:8081/api/users/1/videos",
              "console.error: Failed to load resource: the server responded with a "
              "status of 404 (Not Found)"):
        assert VF.is_own_probe_404_1203l7("(startup)", t) is False, t


def test_the_capture_choke_point_consults_it():
    """Pinned at the call site: the predicate is useless unless `_rec740` asks it, and that
    is the one place all four consumers inherit from. By AST, so a comment quoting the name
    cannot satisfy it."""
    import ast
    src = inspect.getsource(VF)
    tree = ast.parse(src)
    rec = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_rec740"]
    assert len(rec) == 1, [n.name for n in ast.walk(tree)
                           if isinstance(n, ast.FunctionDef)][:20]
    called = {n.func.id for n in ast.walk(rec[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "is_own_probe_404_1203l7" in called, called
    # and it RETURNS on a hit rather than merely noting it
    guards = [n for n in ast.walk(rec[0]) if isinstance(n, ast.If)
              and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") ==
                      "is_own_probe_404_1203l7" for c in ast.walk(n.test))]
    assert guards and any(isinstance(b, ast.Return) for b in guards[0].body), ast.dump(
        guards[0]) if guards else "no guard"


def test_the_extractor_itself_is_unchanged():
    """#1032: ONE owner. `api_404s_from_console_1202lz` reports whatever stream it is handed
    -- the filtering belongs where the stream is built, not in each of its four readers."""
    assert VF.api_404s_from_console_1202lz(
        _console("/api/profiles")) == {"/api/profiles": ["(startup)"]}
    assert VF.api_404s_from_console_1202lz(
        _console("/api/users/1", "profile_own")) == {"/api/users/1": ["profile_own"]}


def test_the_probe_paths_have_one_owner():
    """#1032: the two scripts and the filter must read the same list, or the filter stops
    matching the first time a path is added to a script."""
    src = Path(inspect.getfile(VF)).read_text(encoding="utf-8")
    # no second hand-written list of them anywhere in the module
    assert src.count("'/api/profiles', '/api/profile', '/profiles'") == 0, (
        "a literal copy of the probe list survived")
    assert src.count("_PROBE_PATHS_1203L7 = (") == 1
    # both scripts take it from the owner, and the substitution really happened
    for name in ("_PROFILE_DISCOVER_JS", "_PROFILE_COUNT_JS"):
        js = getattr(VF, name)
        assert "__PROBE_PATHS_1203L7__" not in js, name
        for p in VF._PROBE_PATHS_1203L7:
            assert "'%s'" % p in js, (name, p)


def test_the_scripts_still_do_their_job():
    """Non-regression: the probe is unchanged apart from where its list comes from."""
    for name in ("_PROFILE_DISCOVER_JS", "_PROFILE_COUNT_JS"):
        js = getattr(VF, name)
        assert "await fetch(p, { headers })" in js, name
        assert "for (const p of paths)" in js, name
        assert js.lstrip().startswith("async (token)"), name


def test_the_corpus_warnings_were_mostly_the_probe():
    """The measurement in the docstring, recomputed from the run logs. Skipped when absent."""
    import pytest
    logs = sorted((ROOT.parent).glob("gm_*.log"))
    if len(logs) < 20:
        pytest.skip("too few run logs on this disk (%d)" % len(logs))
    probe = set(VF._PROBE_PATHS_1203L7)
    total = only = 0
    for f in logs:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(
                r"1202lz the browser called \d+ /api path\(s\) this app does NOT serve: "
                r"([^.]{0,400})\.", t):
            total += 1
            paths = set(re.findall(r"(/api/[A-Za-z0-9_\-/{}]+|/profiles)\s*\(on", m.group(1)))
            if paths and not (paths - probe):
                only += 1
    if total < 50:
        pytest.skip("too few warnings on this disk (%d)" % total)
    assert only / total > 0.8, (only, total)
