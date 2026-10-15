r"""#1203l8: the verdict recorded which call failed, and the screen's deviation never said so.

`api_404s_from_console_1202lz` attributes each failing `/api` path to the screen that requested
it, and `run_visual_fidelity` persists the mapping on the verdict as `api_404s_1202lz`. The
per-screen `deviations` -- the text the lane acts on -- never carried it.

MEASURED across every verdict.json on disk: **11 of 11** real per-screen 404s (probe paths
excluded) are absent from their own screen's deviations, 9 of them modern:

    tiktok-web-r184  profile_own              /api/users/1                       sim 0.34
    tiktok-web-r187  fyp_feed_comments_panel  /api/videos/.../comments           sim 0.72
    tiktok-web-r155  live_discover            /api/live                          sim 0.63
    tiktok-web-r152  profile_own              /api/users/bts.records(/videos)    sim 0.70

r184 is a full-delivery run. Its `profile_own` scored 0.34 and the lane was told
"implementation shows only a small centered 'not found' message, while the reference shows the
full own-profile page" -- while the same document says `/api/users/1 -> profile_own`. The page
renders a not-found message BECAUSE the call 404s, and the file knew.

That is #740's own rule ("name the ACTUAL error ... without this the lane is told a symptom and
has to rediscover the cause") applied to the call instead of the console, and #1202kq's shape
in the same expression: the content complaint and its likely cause arrive together.
"""
import ast
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import visual_fidelity as VF  # noqa: E402

W = VF._with_api_404s_1203l8


def test_the_failing_call_is_named_beside_the_judges_complaint():
    base = ["main content: implementation shows only a small centered 'not found' message"]
    out = W(base, ["/api/users/1"])
    assert out[:1] == base, "the judge's own deviations come first and unchanged"
    assert len(out) == 2, out
    assert "/api/users/1" in out[1] and "404" in out[1], out[1]


def test_several_paths_are_listed_and_the_cut_is_declared():
    out = W([], ["/api/a", "/api/b", "/api/c", "/api/d", "/api/e", "/api/f"])
    assert len(out) == 1, out
    for p in ("/api/a", "/api/b", "/api/c", "/api/d"):
        assert p in out[0], out[0]
    # #1034: a shortened list says it was shortened, and says how many there were
    assert "6" in out[0] or "…" in out[0] or "more" in out[0], out[0]


def test_the_order_is_stable_whatever_order_the_browser_recorded_them_in():
    """The text lands in a persisted artifact, so the same failing set must read the same way
    every pass -- otherwise a re-run diffs against itself. Mutation found this: dropping
    `sorted` changed no assertion."""
    a = W([], ["/api/b", "/api/a", "/api/c"])
    b = W([], ["/api/c", "/api/b", "/api/a"])
    assert a == b, (a, b)


def test_a_screen_with_no_failing_call_is_untouched():
    base = ["left rail: implementation omits the reference's Shop item"]
    assert W(base, None) == base
    assert W(base, []) == base
    assert W(base, [""]) == base


def test_it_never_raises_and_never_drops_the_judges_list():
    """It runs inside the loop that builds every screen's record, so the contract is: always
    a list, never an exception, and whatever the judge said is still in it."""
    assert W(None, None) == []
    assert W(["a"], 3) == ["a"], "an unusable paths argument must leave the list alone"
    for dev, paths in ((["a", "b"], ["/api/y"]), (["a"], None), ([], ["/api/y"]),
                       (None, ["/api/y"]), ((x for x in ["a"]), ["/api/y"])):
        out = W(dev, paths)
        assert isinstance(out, list), (dev, paths, out)
    # the judge's entries survive verbatim and stay first
    out = W(["first", "second"], ["/api/y"])
    assert out[0] == "first" and out[1] == "second", out


def test_the_startup_bucket_is_not_attributed_to_any_screen():
    """`(startup)` is not a screen, so nothing can carry its errors -- and after #1203l7 what
    is left in that bucket is the app's own, not the gate's probe."""
    src = inspect.getsource(VF.run_visual_fidelity)
    i = src.index("_api404_by_screen_1203l8")
    block = src[i:src.index("for screen in judged_screens", i)]
    assert '"(startup)"' in block, block


def test_the_measurement_is_taken_once():
    """#1202mf: two calls would be two measurements taken moments apart. The later reader
    uses the same variable."""
    src = inspect.getsource(VF.run_visual_fidelity)
    assert src.count("api_404s_from_console_1202lz(") == 1, src.count(
        "api_404s_from_console_1202lz(")
    assert src.count("_api404_1202lz") >= 2


def test_the_call_site_wires_the_helper_into_the_rendered_screens_record():
    """Pinned by AST: the helper is useless unless the record for a RENDERED screen uses it,
    and the earlier branches (blank, picker) already name console errors their own way."""
    tree = ast.parse(inspect.getsource(VF.run_visual_fidelity))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_with_api_404s_1203l8"]
    assert len(calls) == 1, len(calls)
    # it wraps the deviations expression, and is keyed by this screen's name
    src = ast.dump(calls[0])
    assert "_unmatchable_route_rendered_1202kq" in src, src[:200]
    assert "_api404_by_screen_1203l8" in src, src[:200]


def test_the_corpus_screens_this_was_measured_on():
    """The 11 of 11, recomputed. Skipped when the corpus is absent."""
    import pytest
    PROBE = {"/api/profiles", "/api/profile", "/profiles"}
    pairs = []
    for p in sorted((ROOT.parent / "generated").glob("*/design/visual_gate/verdict.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        api = d.get("api_404s_1202lz") or {}
        if not isinstance(api, dict):
            continue
        screens = d.get("screens") or []
        if isinstance(screens, dict):
            screens = list(screens.values())
        by = {str(s.get("name")): s for s in screens if isinstance(s, dict)}
        for path, names in api.items():
            if path in PROBE:
                continue
            for n in (names or []):
                if str(n) == "(startup)" or str(n) not in by:
                    continue
                pairs.append((p.parts[-4], str(n), str(path),
                              str(path) in str(by[str(n)].get("deviations") or "")))
    if len(pairs) < 5:
        pytest.skip("too few per-screen 404s on this disk (%d)" % len(pairs))
    named = [x for x in pairs if x[3]]
    assert named == [], (
        "a verdict now names its own failing call -- if that is this fix reaching the corpus, "
        "update this assertion; these files predate it", named[:3])
    # and the modern ones are the majority of the population
    modern = [x for x in pairs if re.search(r"r(1[5-9]\d|[2-9]\d\d)$", x[0])]
    assert len(modern) >= len(pairs) / 2, (len(modern), len(pairs))
