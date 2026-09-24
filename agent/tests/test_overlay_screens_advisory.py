"""FIX #128 — overlay/flyout/modal reference screens are ADVISORY, not gate-blocking
(instagram-core-di visual-gate autopsy, 2026-07-10, run-47 SUCCESS artifacts).

The visual gate passes iff EVERY judged screen reaches min_similarity (0.65). But the
IG design-input reference set includes interaction-STATE shots that no URL route can
reproduce: `search_flyout.png` is literally the HOME FEED with a 'Turn on
Notifications' MODAL overlaid; `notifications_flyout` is the same class. Route capture
navigates to the base page (explore grid) → the judge compares unrelated images →
PERMANENT 0.00 → the gate is mathematically UNPASSABLE regardless of frontend quality,
so every final milestone ships via the 3600s below-threshold escape. Worse, the false
0.00 pollutes the frontend's remediation ('rebuild search_flyout, it's 0.00 unrelated'
— an un-fixable target). Overlay-named references (flyout/modal/popup/dropdown/overlay/
menu/dialog/drawer/popover/tooltip/sheet) are interaction states: still judged +
reported (advisory), but excluded from the BLOCKING pass criterion.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import map_reference_screens  # noqa: E402


def _mk(tmp_path, names):
    out = []
    for n in names:
        f = tmp_path / f"{n}.png"
        f.write_bytes(b"\x89PNG fake")
        out.append(str(f))
    return out


def test_overlay_names_flagged_advisory(tmp_path):
    refs = _mk(tmp_path, ["ig_search_flyout", "ig_notifications_flyout",
                          "ig_create_modal", "ig_home_feed", "ig_explore"])
    known = {"/", "/explore", "/search", "/notifications", "/create"}
    screens = {s["name"]: s for s in map_reference_screens(refs, known)}
    # overlay states → advisory (still mapped, still judged, but non-blocking)
    for ov in ("search_flyout", "notifications_flyout", "create_modal"):
        s = next((v for k, v in screens.items() if ov.split("_")[-1] in k or ov in k), None)
        assert s is not None, (ov, list(screens))
        assert s.get("advisory") is True, (ov, s)
    # real pages → NOT advisory
    for pg in screens.values():
        nm = pg["name"]
        if any(t in nm for t in ("flyout", "modal", "popup", "overlay", "dropdown",
                                 "menu", "dialog", "drawer", "popover", "tooltip", "sheet")):
            continue
        assert not pg.get("advisory"), pg


def _app_with_routes(tmp_path, routes):
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    body = "\n".join(f'<Route path="{r}" element={{<X/>}} />' for r in routes)
    (src / "App.jsx").write_text(body, encoding="utf-8")


def _run(tmp_path, refs, judge):
    import asyncio
    import multi_agent.runtime.visual_fidelity as vf

    async def _cap(screens):
        return {s["name"]: str(tmp_path / f"{s['name']}.png") for s in screens}
    return asyncio.new_event_loop().run_until_complete(
        vf.run_visual_fidelity(tmp_path, refs, object(),
                               capture_fn=_cap, judge_fn=judge))


def test_gate_passes_when_only_advisory_screens_fail(tmp_path):
    """the structural bug: a permanently-0.00 flyout must NOT block a gate whose real
    pages all clear the bar."""
    _app_with_routes(tmp_path, ["/", "/explore", "/search"])
    refs = _mk(tmp_path, ["ig_home_feed", "ig_explore", "ig_search_flyout"])

    async def _judge(llm, screen, shot):
        sim = 0.0 if screen["name"] == "ig_search_flyout" else 0.90
        return {"similarity": sim, "dimensions": {}, "deviations": [], "fixes": [],
                "summary": ""}

    res = _run(tmp_path, refs, _judge)
    assert res["passed"] is True, res.get("summary")          # flyout no longer blocks
    names = {r["name"]: r for r in res["screens"]}
    fly = names["ig_search_flyout"]
    assert fly.get("advisory") is True                        # still reported...
    assert fly["similarity"] == 0.0                           # ...honestly recorded


def test_real_page_failure_still_blocks(tmp_path):
    _app_with_routes(tmp_path, ["/", "/explore"])
    refs = _mk(tmp_path, ["ig_home_feed", "ig_explore"])

    async def _judge(llm, screen, shot):
        sim = 0.20 if screen["name"] == "ig_explore" else 0.90   # a REAL page is low
        return {"similarity": sim, "dimensions": {}, "deviations": [], "fixes": [],
                "summary": ""}

    res = _run(tmp_path, refs, _judge)
    assert res["passed"] is False                              # real low page still blocks
