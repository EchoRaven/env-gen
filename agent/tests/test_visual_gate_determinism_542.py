"""#542 — VISUAL-GATE DETERMINISM: transient interaction-state screens are ADVISORY, and the
judged BLOCKING set is deterministic run-to-run.

ROOT CONTEXT (netflix): Part-A avg swung ~+-0.10 run-to-run partly because (a) the SET of
judged screens was non-deterministic (r99 judged 13 incl. title_detail/browse_home_rows; r100
judged 12, dropped those, added card_hover_preview) and (b) transient interaction-state screens
were judged as BLOCKING even though a static projector can't render them — card_hover_preview.png
is BYTE-IDENTICAL to browse_home.png (same route /browse) yet scored 0.35 as a blocking screen,
mechanically lowering the mean.

#542a — a transient interaction state (hover/preview/ad/modal/dialog/…) OR a screen that
DUPLICATES another's capture route (same route -> same static screenshot) is marked ADVISORY:
still judged + reported, but EXCLUDED from the BLOCKING pass/average that gates delivery.
#542b — the judged BLOCKING set is derived from the measured page screens in a STABLE, sorted
order (deterministic), and a canonical page that FAILS to capture still COUNTS in the denominator
(counts as its 0.0 — it does not silently vanish).

Neither the 0.65 bar nor any per-screen score is changed — only WHICH screens are in the
blocking average, and the determinism of that set.

Isolation harness (mirrors tests/test_visual_fidelity_coverage.py): visual_fidelity's only
sibling import is `from .validation_runner import _service_host_port` — stub it, then exec the
module source under a synthetic package (importing by package path would pull the engine graph).

Run:
  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_visual_gate_determinism_542.py -q
"""
import asyncio
import json
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["vf_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()


def _run_async(coro):
    """Run a coroutine WITHOUT polluting the process-global event loop for later tests.
    asyncio.run() sets the current loop to None on exit (py3.10), which would break the
    alphabetically-adjacent test_visual_gate_wiring_precondition (it uses the deprecated
    asyncio.get_event_loop()). Save + restore a usable current loop instead."""
    prev = None
    try:
        prev = asyncio.get_event_loop()
        if prev.is_closed():
            prev = None
    except Exception:
        prev = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(prev or asyncio.new_event_loop())


def _mk(name, route, advisory=False, similarity=None, **kw):
    d = {"name": name, "path": f"/x/{name}.png", "route": route, "auth": True,
         "advisory": advisory}
    if similarity is not None:
        d["similarity"] = similarity
    d.update(kw)
    return d


# ── (a) transient / duplicate-route screens are marked advisory; a normal page is not ──────────

def test_transient_name_is_advisory_even_when_mislabeled_page(tmp_path):
    """hover/preview/ad NAME tokens force ADVISORY even when the pixel-only analyst mislabeled
    the screen kind='page' (#389: kind comes back INVERTED for screens that share a route). A
    plain page stays BLOCKING."""
    proj = tmp_path
    (proj / "design").mkdir(parents=True, exist_ok=True)
    screens_cls = [
        {"name": "browse_home", "kind": "page", "route": "/browse"},
        {"name": "card_hover_preview", "kind": "page", "route": "/browse"},   # mislabeled page
        {"name": "card_preview", "kind": "page", "route": "/browse"},         # mislabeled page
        {"name": "home_ad", "kind": "page", "route": "/shows"},               # mislabeled page
        {"name": "login", "kind": "page", "route": "/login"},
    ]
    (proj / "design" / "design_system.json").write_text(
        json.dumps({"screens": screens_cls}), encoding="utf-8")
    refs = []
    for s in screens_cls:
        f = proj / f"{s['name']}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))
    known = {"/browse", "/shows", "/login"}
    cls = VF.load_screen_classifications(proj)
    by = {s["name"]: s for s in VF.map_reference_screens(refs, known, classifications=cls)}
    # transient interaction-state names -> advisory despite kind='page'
    assert by["card_hover_preview"]["advisory"] is True, by["card_hover_preview"]
    assert by["card_preview"]["advisory"] is True, by["card_preview"]
    assert by["home_ad"]["advisory"] is True, by["home_ad"]
    # a plain page stays blocking
    assert by["browse_home"]["advisory"] is False, by["browse_home"]
    assert by["login"]["advisory"] is False, by["login"]


def test_duplicate_route_demotes_the_non_canonical_even_without_a_transient_name():
    """Two screens that resolve to the SAME capture route -> a static capture is byte-identical,
    so only ONE can be the canonical blocking page; the other is demoted ADVISORY. Works purely
    from the route (no transient name needed) and picks the canonical DETERMINISTICALLY."""
    # transient duplicate: browse_home is the page, card_hover_preview duplicates /browse
    scr = [_mk("browse_home", "/browse"), _mk("card_hover_preview", "/browse"),
           _mk("login", "/login")]
    VF._demote_duplicate_route_screens(scr)
    by = {s["name"]: s for s in scr}
    assert by["browse_home"]["advisory"] is False   # canonical page kept blocking
    assert by["card_hover_preview"]["advisory"] is True  # transient duplicate demoted
    assert by["login"]["advisory"] is False         # lone route untouched

    # NON-transient duplicate: neither name is a transient token -> earliest name is canonical
    scr2 = [_mk("beta", "/x"), _mk("alpha", "/x")]
    VF._demote_duplicate_route_screens(scr2)
    by2 = {s["name"]: s for s in scr2}
    assert by2["alpha"]["advisory"] is False
    assert by2["beta"]["advisory"] is True

    # param routes are duplicates once the :id is filled the same way (#418)
    scr3 = [_mk("title_detail", "/title/:id"), _mk("rate_dialog", "/title/:id")]
    VF._demote_duplicate_route_screens(scr3)
    by3 = {s["name"]: s for s in scr3}
    assert by3["title_detail"]["advisory"] is False
    assert by3["rate_dialog"]["advisory"] is True


def test_no_duplicate_no_transient_is_byte_identical_no_demotion():
    """When no two screens share a route and none are transient, demotion is a no-op —
    every screen keeps its incoming advisory flag (byte-identical gating)."""
    scr = [_mk("a", "/a"), _mk("b", "/b"), _mk("c", "/c", advisory=True)]
    before = [(s["name"], s["advisory"]) for s in scr]
    VF._demote_duplicate_route_screens(scr)
    after = [(s["name"], s["advisory"]) for s in scr]
    assert before == after


# ── (b) the blocking average equals the average over just the non-transient screens ────────────

def test_blocking_average_excludes_advisory_and_equals_nontransient_mean():
    results = [
        _mk("page_a", "/a", advisory=False, similarity=0.80, blank=False),
        _mk("page_b", "/b", advisory=False, similarity=0.70, blank=False),
        _mk("card_hover_preview", "/a", advisory=True, similarity=0.20, blank=False),  # transient
        _mk("rate_dialog", "/b", advisory=True, similarity=0.10, blank=False),         # transient
    ]
    avg = VF._blocking_similarity_average(results)
    # the average over just the BLOCKING (non-transient) screens
    non_transient = [r for r in results if not r["advisory"]]
    expected = round(sum(r["similarity"] for r in non_transient) / len(non_transient), 4)
    assert avg == expected == 0.75, avg
    # a transient present must NOT change the blocking average vs the same set without them
    avg_without = VF._blocking_similarity_average(non_transient)
    assert avg == avg_without


def test_blocking_average_blank_excluded_but_real_capture_failure_counts():
    # a BLANK mid-rebuild capture (#75a) is a transient env glitch -> excluded from the mean;
    # a REAL capture failure (blank=False, similarity 0.0) COUNTS as a 0.0 (a real miss).
    with_blank = [
        _mk("good", "/g", advisory=False, similarity=0.90, blank=False),
        _mk("blank", "/b", advisory=False, similarity=0.00, blank=True),   # excluded
    ]
    assert VF._blocking_similarity_average(with_blank) == 0.90
    with_real_fail = [
        _mk("good", "/g", advisory=False, similarity=0.90, blank=False),
        _mk("failed", "/f", advisory=False, similarity=0.00, blank=False),  # counts as 0.0
    ]
    assert VF._blocking_similarity_average(with_real_fail) == 0.45


# ── (c) determinism: same measured input -> same judged / blocking set + order across calls ────

def test_selection_is_order_independent_and_sorted():
    a = [_mk("z", "/z"), _mk("a", "/a"), _mk("m", "/m", advisory=True), _mk("b", "/b")]
    b = list(reversed(a))
    order_a = [s["name"] for s in VF._select_judged_screens(a, max_screens=8)]
    order_b = [s["name"] for s in VF._select_judged_screens(b, max_screens=8)]
    # identical order regardless of input order: blocking sorted, then advisory sorted
    assert order_a == order_b == ["a", "b", "z", "m"], (order_a, order_b)


def test_full_pipeline_same_input_same_blocking_set_twice(tmp_path):
    """map -> demote -> select is reproducible: the same measured references (even shuffled)
    yield the same judged/blocking set AND order every run."""
    names = ["browse_home", "card_hover_preview", "login", "shows", "rate_dialog"]
    refs = []
    for n in names:
        f = tmp_path / f"{n}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))
    known = {"/browse", "/login", "/shows", "/title/:id"}
    # classification so card_hover_preview & rate_dialog carry parent (duplicate) routes
    cls = {"card_hover_preview": {"kind": "overlay", "route": "/browse"},
           "rate_dialog": {"kind": "overlay", "route": "/shows"}}

    def _run(order):
        scr = VF.map_reference_screens(order, known, classifications=cls)
        scr = VF._demote_duplicate_route_screens(scr)
        judged = VF._select_judged_screens(scr, max_screens=8)
        blocking = [s["name"] for s in judged if not s["advisory"]]
        return [s["name"] for s in judged], blocking

    j1, b1 = _run(list(refs))
    j2, b2 = _run(list(reversed(refs)))
    assert j1 == j2, (j1, j2)                 # same judged order
    assert b1 == b2, (b1, b2)                 # same blocking set + order
    # the transient/duplicate screens are NOT in the blocking set
    assert "card_hover_preview" not in b1
    assert "rate_dialog" not in b1
    assert "browse_home" in b1 and "login" in b1


# ── (d) a canonical page that FAILS to capture still counts in the denominator (0.0) ──────────

def test_failed_capture_canonical_page_counts_in_blocking_denominator(tmp_path):
    """End-to-end run_visual_fidelity: a canonical page that fails capture is NOT silently
    dropped — it is recorded (similarity 0.0, blocking) and its 0.0 counts in the blocking
    average, while a transient duplicate-route screen is judged but EXCLUDED."""
    proj = tmp_path
    (proj / "app" / "frontend" / "src").mkdir(parents=True, exist_ok=True)
    (proj / "design").mkdir(parents=True, exist_ok=True)
    (proj / "app" / "frontend" / "src" / "App.jsx").write_text(
        '<Route path="/browse" element={<div/>} />'
        '<Route path="/login" element={<div/>} />', encoding="utf-8")
    cls_screens = [
        {"name": "browse_home", "kind": "page", "route": "/browse"},
        {"name": "login", "kind": "page", "route": "/login"},
        {"name": "card_hover_preview", "kind": "page", "route": "/browse"},  # mislabeled + dup
    ]
    (proj / "design" / "design_system.json").write_text(
        json.dumps({"screens": cls_screens}), encoding="utf-8")
    refs = []
    for s in cls_screens:
        f = proj / f"{s['name']}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))

    async def _capture(screens):
        out = {}
        for s in screens:
            if s["name"] == "browse_home":
                continue   # the canonical page FAILS to capture this run
            p = proj / f"shot_{s['name']}.png"
            p.write_bytes(b"\x89PNG\r\n" + s["name"].encode())
            out[s["name"]] = str(p)
        return out

    async def _judge(llm, screen, shot):
        return {"similarity": 0.90, "dimensions": {}, "deviations": [],
                "fixes": [], "summary": "ok", "empty_state": False}

    result = _run_async(VF.run_visual_fidelity(
        proj, refs, llm=object(), capture_fn=_capture, judge_fn=_judge))

    by = {r["name"]: r for r in result["screens"]}
    # the failed canonical page is present (not dropped) and BLOCKING at 0.0
    assert "browse_home" in by, "canonical page silently vanished from the denominator"
    assert by["browse_home"]["advisory"] is False
    assert by["browse_home"]["similarity"] == 0.0
    assert by["browse_home"].get("blank") in (False, None)   # a real capture failure, not blank
    # the transient duplicate is judged but ADVISORY (excluded from the blocking average)
    assert by["card_hover_preview"]["advisory"] is True
    # blocking average = (browse_home 0.0 + login 0.90) / 2 = 0.45 (card_hover_preview excluded)
    assert result["blocking_average"] == 0.45, result["blocking_average"]
    # the app didn't pass (a blocking page at 0.0), and the bar is the shared default (#1202nv)
    assert result["passed"] is False
    assert result["min_similarity"] == VF.VISUAL_MIN_DEFAULT_1202NV
    # the recorded verdict.json carries the blocking_average too
    vj = json.loads((proj / "design" / "visual_gate" / "verdict.json").read_text())
    assert vj["blocking_average"] == 0.45, vj["blocking_average"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
